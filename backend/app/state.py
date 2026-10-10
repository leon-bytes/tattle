"""In-memory state. Everything captured lives here, in RAM, and nowhere else.

Methods are plain synchronous code and return the WebSocket messages to broadcast.
"""
from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

from .kb import CATEGORIES, Kb, clean
from .summary import describe, session_stats
from .validate import is_hostname, is_ip, is_loopback, plain

MAX_HITS = 5000        # hits kept for the snapshot
MAX_PENDING = 500      # unknown names waiting for the AI
MAX_AI_RESULTS = 5000  # AI answers remembered; the oldest go first
MAX_DEVICES = 256      # more phones than a hotspot can hold; later ones are ignored
SELF_TEST = "box self-test"  # name of the "device" behind lookups the box makes through its own sensor
DEDUPE_SECONDS = 2.0   # iPhones ask A, AAAA and HTTPS for one name at once: count that as one hit


UNANSWERED = {"company": None, "category": "unknown", "confidence": 0.0}


def is_noise(name: str) -> bool:
    """Network plumbing, not companies: reverse lookups, mDNS, single-label names."""
    return "." not in name or name.endswith((".arpa", ".local"))


def clean_answer(raw: object) -> dict:
    """An AI answer (from the module, the seed file or the database) in the one shape used here."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        confidence = float(raw.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {"company": plain(raw.get("company"), 80),  # a model wrote this: text only, bounded
            "category": raw.get("category") if raw.get("category") in CATEGORIES else "unknown",
            "confidence": confidence}


def read_ai_seed(path: Path) -> dict[str, dict]:
    """Precomputed AI answers, {"domains": {name: answer}}. A missing or broken file means none."""
    try:
        domains = json.loads(path.read_text(encoding="utf-8"))["domains"]
        answers = {clean(name): clean_answer(answer) for name, answer in domains.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"ai seed: ignoring {path.name}: {type(error).__name__}", file=sys.stderr)
        return {}
    return {name: answer for name, answer in answers.items() if answer["category"] != "unknown"}


class State:
    def __init__(self, kb: Kb) -> None:
        self.kb = kb
        self.health: dict = {"db": False, "db_error": None, "ai": False, "sensor_seen": None, "kb": len(kb),
                             "malformed": 0,       # names refused by the sensor or here; counted, never kept
                             "ai_endpoint": None}  # does the model server answer? None: no AI_BASE_URL set
        self.blocklist_version = 1
        self.generation = 0  # bumped by wipe, so late AI answers for wiped data are dropped
        self.ai_seed: dict[str, dict] = {}  # answers from the seed file and the database's ai_cache; survives wipe
        self._clear()

    def _clear(self) -> None:
        self.devices: dict[str, dict] = {}
        self.device_count = 0
        self.auto_named: set[str] = set()  # devices still carrying their "Device N" label
        self.hits: deque[dict] = deque(maxlen=MAX_HITS)
        self.hit_count = 0
        self.last_counted: dict[tuple[str, str], float] = {}
        self.blocked_companies: set[str] = set()
        self.blocked_domains: set[str] = set()
        self.session: dict | None = None
        self.last_session: dict | None = None  # the session that just stopped, kept for the label check
        self.summary: dict | None = None
        self.summarized_at = 0
        self.label_ai: dict | None = None  # the AI's sentence for the label check of one session and label
        self.explained: dict[tuple, dict] = {}  # the AI's explanation of a company, per (company, phone, session start)
        self.ai_results: dict[str, dict] = dict(self.ai_seed)  # every name the AI was asked about, with its answer
        self.pending: dict[str, None] = {}     # insertion-ordered set of names to ask about

    # --- events ---

    def ingest(self, events: list[dict], now: float | None = None) -> list[dict]:
        """Turn sensor events into hits. With `now`, the batch is moved onto this machine's clock:
        the sensor runs on another one, and sessions are timed here. Spacing inside the batch is kept."""
        messages: list[dict] = []
        shift = now - max(event["ts"] for event in events) if now is not None and events else 0.0
        for event in events:
            name = clean(event["qname"])
            if not name:
                continue  # a lookup of the root: nothing to show
            if not is_hostname(name) or not is_ip(event["client_ip"]):
                self.health["malformed"] += 1  # untrusted input that is not a plain host name: counted, dropped
                continue
            reason = event.get("block_reason") if event.get("block_reason") in ("user", "guard") else None
            guard = reason == "guard"  # a hidden-traffic attempt: always shown, never sent to the AI
            if is_noise(name) and not guard:
                continue
            device_id, ts = event["client_ip"], round(event["ts"] + shift, 3)
            if device_id not in self.devices and len(self.devices) >= MAX_DEVICES:
                continue
            messages += self._see_device(device_id, plain(event.get("client_name"), 64))
            last = self.last_counted.get((device_id, name))
            if last is not None and abs(ts - last) < DEDUPE_SECONDS:
                continue
            self.last_counted[device_id, name] = ts
            hit = {"type": "hit", "device_id": device_id, "domain": name, **self._classify(name, ask_ai=not guard),
                   "blocked": bool(event.get("blocked")), "block_reason": reason, "ts": ts}
            self.hits.append(hit)
            self.hit_count += 1
            messages.append(hit)
        if len(self.last_counted) > 4 * MAX_HITS:
            newest = max(self.last_counted.values())
            self.last_counted = {k: t for k, t in self.last_counted.items() if newest - t < DEDUPE_SECONDS}
        return messages

    def _classify(self, name: str, ask_ai: bool) -> dict:
        match = self.kb.lookup(name)
        if match:
            return match
        answer = self.ai_results.get(name)
        if answer is None and ask_ai and len(self.pending) < MAX_PENDING:
            self.pending[name] = None
        if answer and answer["category"] != "unknown":
            return {"company": answer["company"], "category": answer["category"], "source": "ai"}
        return {"company": None, "category": "unknown", "source": "unknown"}

    def _new_device(self, device_id: str, name: str | None) -> dict:
        """Phones are "Device 1", "Device 2", ... unless a name is given: their own names stay private.
        A loopback address is the box asking its own sensor (the checklist's self-test): not a phone, not numbered."""
        if not name and is_loopback(device_id):
            name = SELF_TEST
        elif not name:
            self.device_count += 1
            name = f"Device {self.device_count}"
            self.auto_named.add(device_id)
        else:
            self.device_count += 1
        device = self.devices[device_id] = {"device_id": device_id, "name": name, "persist": False}
        return device

    def _see_device(self, device_id: str, client_name: str | None) -> list[dict]:
        device = self.devices.get(device_id)
        if device is None:
            device = self._new_device(device_id, client_name)
        elif client_name and device_id in self.auto_named:  # sensor started with --names; never replaces a rename
            device["name"] = client_name
            self.auto_named.discard(device_id)
        else:
            return []
        return [{"type": "device", **device}]

    def set_device(self, device_id: str, name: str | None, persist: bool | None) -> dict:
        device = self.devices.get(device_id) or self._new_device(device_id, None)
        if name:
            device["name"] = name
            self.auto_named.discard(device_id)
        if persist is not None:
            device["persist"] = persist
        return {"type": "device", **device}

    # --- AI classification of unknown names ---

    def seed_ai(self, answers: dict[str, dict]) -> None:
        """Answers we already have (seed file, database cache): known from the start, and again after a wipe."""
        self.ai_seed.update(answers)
        self.ai_results.update(answers)

    def seen_by_persist_device(self, name: str) -> bool:
        return any(hit["domain"] == name and self.devices[hit["device_id"]]["persist"] for hit in self.hits)

    def take_pending(self, limit: int) -> list[str]:
        names = list(self.pending)[:limit]
        for name in names:
            del self.pending[name]
            self.ai_results[name] = UNANSWERED  # asked: don't queue it again while the AI is thinking
        for name in list(self.ai_results)[:max(0, len(self.ai_results) - MAX_AI_RESULTS)]:
            if name not in self.ai_seed:
                del self.ai_results[name]
        return names

    def requeue(self, names: list[str]) -> None:
        """Put names back after a failed AI call."""
        for name in names:
            self.ai_results.pop(name, None)
        self.pending = {**dict.fromkeys(names), **self.pending}

    def apply_classified(self, names: list[str], results: dict) -> list[dict]:
        messages = []
        for name in names:
            answer = self.ai_results[name] = clean_answer(results.get(name))
            company, category, confidence = answer["company"], answer["category"], answer["confidence"]
            if category == "unknown":
                continue
            for hit in self.hits:
                if hit["domain"] == name and hit["source"] == "unknown":
                    hit.update(company=company, category=category, source="ai")
            if company in self.blocked_companies:
                self.blocklist_version += 1
            messages.append({"type": "classified", "domain": name, "company": company, "category": category,
                             "source": "ai", "confidence": confidence})
        return messages

    # --- blocking ---

    def set_blocked(self, company: str | None, domain: str | None, on: bool) -> dict:
        for target, value in ((self.blocked_companies, company), (self.blocked_domains, domain and clean(domain))):
            if value and on:
                target.add(value)
            elif value:
                target.discard(value)
        self.blocklist_version += 1
        return self.blocked_message()

    def company_names(self, company: str) -> list[str]:
        """Every name a block on this company covers: its kb domains, and names the AI assigned to it."""
        names = self.kb.company_domains(company) | {n for n, answer in self.ai_results.items() if answer["company"] == company}
        return sorted(names)

    def blocked(self) -> dict:
        """What is blocked, and for each blocked company what that covers. A name also covers everything under it."""
        return {"companies": sorted(self.blocked_companies), "domains": sorted(self.blocked_domains),
                "covers": {company: self.company_names(company) for company in sorted(self.blocked_companies)}}

    def blocked_message(self) -> dict:
        return {"type": "blocked", **self.blocked()}

    def blocklist(self) -> dict:
        """What the sensor polls: blocked domains plus every known domain of each blocked company."""
        domains = set(self.blocked_domains)
        for company in self.blocked_companies:
            domains.update(self.company_names(company))
        return {"version": self.blocklist_version, "domains": sorted(domains)}

    # --- sessions and summaries ---

    def start_session(self, device_id: str, label: str | None, now: float) -> dict:
        self.session = {"device_id": device_id, "label": label, "started": now}
        self.last_session = None
        self.summary = None
        self.summarized_at = self.hit_count
        return {"type": "session", "session": self.session}

    def stats(self, now: float) -> dict:
        device = self.devices.get(self.session["device_id"], {})
        return session_stats(self.hits, self.session, device.get("name"), now)

    def set_summary(self, text: str, by: str, device_id: str) -> dict:
        self.summary = {"type": "summary", "device_id": device_id, "text": text, "by": by}
        self.summarized_at = self.hit_count
        return self.summary

    def refresh_summary(self, now: float) -> dict | None:
        """A fresh template summary if a session is running and saw new hits since the last one."""
        if not self.session or self.hit_count == self.summarized_at:
            return None
        return self.set_summary(describe(self.hits, self.session, now), "template", self.session["device_id"])

    def stop_session(self, now: float) -> tuple[list[dict], dict | None]:
        """Messages to broadcast, and the final stats (None if no session was running)."""
        if not self.session:
            return [], None
        stats = self.stats(now)
        self.last_session, self.session = {**self.session, "stopped": now}, None
        summary = self.set_summary(describe(self.hits, self.last_session, now), "template", self.last_session["device_id"])
        return [{"type": "session", "session": None}, summary], stats

    # --- everything ---

    def wipe(self) -> list[dict]:
        self._clear()
        self.generation += 1
        self.blocklist_version += 1
        return [{"type": "wiped"}, self.blocked_message(), {"type": "session", "session": None}]

    def snapshot(self) -> dict:
        return {"type": "snapshot", "devices": list(self.devices.values()), "hits": list(self.hits),
                "blocked": self.blocked(),
                "session": self.session, "last_session": self.last_session,
                "summary": self.summary, "health": self.health}
