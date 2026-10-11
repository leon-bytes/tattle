"""AI module for Tattle (owner: AI). Contract: docs/AI-QUICKSTART.md and docs/TEAM.md.

Four async functions, all following the same rules:
  * a hard 8 s wall-clock limit per call, and None on ANY failure (never raises)
  * model settings come from the environment: AI_BASE_URL, AI_TOKEN, AI_MODEL
    (OpenAI-compatible /chat/completions; Ollama's /v1 works; the token may be a placeholder).
    This file does not read .env: backend/start.sh does that, as for every other setting.
  * we only see server-name lookups, never content: outputs must say "contacted", never
    "sent your data". Sentences that claim data was sent are cut out (-> None if nothing is left).
  * no in-process cache: Wipe must forget everything. The backend caches in Postgres itself.
    Only the seed file is read (precomputed answers for the demo apps).

The model server answers one request at a time, at about 40 tokens a second (measured on
qwen2.5-14b), so a long answer holds up every call queued behind it. The prompts and
max_tokens below keep each answer to about 2 to 4 s.

No third-party packages: only the standard library, so the backend's import cannot fail
on a missing dependency.
"""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger("tattle.ai")

TIMEOUT_S = 8.0
MAX_DOMAINS_PER_CALL = 10          # the backend asks for at most 10 names at a time
MAX_EXPLAIN_HOSTS = 20             # the backend sends up to 20 server names
DEFAULT_MODEL = "qwen2.5-14b:latest"   # the name the server lists at /v1/models; AI_MODEL in .env overrides it
# Ollama unloads a model nobody used for 5 minutes, and loading it again takes about 5 s:
# most of our time limit. Every call asks it to stay loaded ("keep_alive" is Ollama's own
# field in an otherwise OpenAI-style request).
KEEP_ALIVE = "12h"
CATEGORIES = {"advertising", "analytics", "social", "fingerprinting",
              "content", "vendor", "unknown"}
ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------- config / health
def _cfg():
    return (os.getenv("AI_BASE_URL", "").rstrip("/"),
            os.getenv("AI_TOKEN", ""),
            os.getenv("AI_MODEL", "").strip() or DEFAULT_MODEL)


def model_name() -> str:
    return _cfg()[2]


def configured() -> bool:
    return bool(_cfg()[0])


_state = {"last_ok": None, "last_error": None}


def status() -> dict:
    return {"configured": configured(),
            "ok": configured() and _state["last_error"] is None,
            "last_ok": _state["last_ok"], "last_error": _state["last_error"]}


# ----------------------------------------------------------------- seed file (read-only)
_seed: Optional[dict] = None
_SEED_SECTIONS = {"classify": "domains", "summary": "summaries",
                  "label": "label_checks", "explain": "explanations"}


def _load_seed() -> dict:
    global _seed
    if _seed is None:
        try:  # the same file the backend reads; a relative path counts from the repo root
            path = ROOT / (os.getenv("AI_CACHE_SEED_PATH") or "data/ai_cache_seed.json")
            _seed = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _seed = {}
    return _seed


def _seeded(kind: str, name: str) -> Optional[dict]:
    value = _load_seed().get(_SEED_SECTIONS[kind], {}).get(name)
    if value is None:
        return None
    return value if isinstance(value, dict) else {"text": value}


def _stats_key(kind: str, stats: dict, extra: str = "") -> str:
    """Key ignores device name and elapsed seconds so a replay hits the same entry."""
    basis = {"label": stats.get("label"), "by_category": stats.get("by_category"),
             "top_companies": stats.get("top_companies"), "extra": extra}
    h = hashlib.sha1(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:16]
    return f"{kind}:{h}"


# ----------------------------------------------------------------- model call
_idle: list[http.client.HTTPConnection] = []  # connections into the tunnel, kept open between calls
_idle_lock = threading.Lock()
MAX_IDLE = 4


def _post_tunnel(host: str, port: int, path: str, headers: dict, payload: bytes, timeout: float) -> bytes:
    """POST over a connection that stays open between calls. Opening one through the SSH tunnel
    cost 0.9 to 1.8 s on the demo's uplink (measured), a call on an open one 0.45 s. A kept
    connection that the other side has closed meanwhile gets one more try on a new one."""
    for fresh in (False, True):
        with _idle_lock:
            conn = None if fresh or not _idle else _idle.pop()
        kept = conn is not None
        if not kept:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            if kept and conn.sock is not None:
                conn.sock.settimeout(timeout)
            conn.request("POST", path, body=payload, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except TimeoutError:  # the time is used up: no second try
            conn.close()
            raise
        except (http.client.HTTPException, OSError):
            conn.close()
            if kept:
                continue
            raise
        with _idle_lock:
            keep = not resp.will_close and len(_idle) < MAX_IDLE
            if keep:
                _idle.append(conn)
        if not keep:
            conn.close()
        if resp.status != 200:
            raise RuntimeError(f"HTTP Error {resp.status}: {resp.reason}")
        return data
    raise RuntimeError("unreachable")


def _post_sync(url: str, headers: dict, body: dict, timeout: float) -> dict:
    payload = json.dumps(body).encode("utf-8")
    target = urlparse(url)
    host = target.hostname or ""
    if host in ("127.0.0.1", "localhost", "::1") and target.scheme == "http":
        # the SSH tunnel is local: never through an HTTP proxy from the environment
        return json.loads(_post_tunnel(host, target.port or 80, target.path or "/", headers, payload, timeout).decode("utf-8"))
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    if host in ("127.0.0.1", "localhost", "::1"):
        resp = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)
    else:
        resp = urllib.request.urlopen(req, timeout=timeout)
    with resp:
        return json.loads(resp.read().decode("utf-8"))


async def _chat(messages: list[dict], max_tokens: int, timeout: float) -> str:
    base, token, model = _cfg()
    if not base:
        raise RuntimeError("AI_BASE_URL not set")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens,
            "keep_alive": KEEP_ALIVE}
    data = await asyncio.to_thread(_post_sync, f"{base}/chat/completions",
                                   headers, body, timeout)
    choice = data["choices"][0]
    text = choice["message"]["content"] or ""
    if choice.get("finish_reason") == "length":  # cut off by max_tokens: drop the unfinished sentence or line
        text = text[:max(text.rfind(". "), text.rfind("\n")) + 1]
    return text


async def _call(messages: list[dict], max_tokens: int, timeout: float = TIMEOUT_S) -> Optional[str]:
    """Hard wall-clock cap (8 s unless less is left); records health; never raises."""
    try:
        out = await asyncio.wait_for(_chat(messages, max_tokens, max(timeout, 0.1)), timeout)
        _state.update(last_ok=time.time(), last_error=None)
        return out
    except Exception as e:  # timeout, network, HTTP error, bad JSON, not configured
        error = f"{type(e).__name__}: {e}"[:200]  # a timeout has no text of its own
        if configured():
            _state["last_error"] = error
        log.warning("AI call failed: %s", error)
        return None


# ----------------------------------------------------------------- output checks
_SEND_VERBS = r"(?:sent|sends|sending|leak\w*|stole\w*|steal\w*|exfiltrat\w*|transmit\w*)"
_BANNED = re.compile(
    # "sends your location", "collects the user's data", "shares users' information"
    r"\b(?:" + _SEND_VERBS + r"|upload\w*|collect\w*|shar(?:e|es|ed|ing))\W+(?:\w+\W+){0,4}?"
    r"(?:your|the user'?s?|users')\s+(?:data|information|info|messages|photos|location|contacts|activity)\b"
    # "sent data to", "leaks location"
    r"|\b" + _SEND_VERBS + r"\W+(?:\w+\W+){0,3}?(?:data|information|location)\b"
    r"|\byour data (?:was|is|has been|were)\b"
    # "where usage data are sent", "information is shared with"
    r"|\b(?:data|information)\s+(?:\w+\s+)?(?:is|are|was|were|gets?|being)\s+(?:sent|shared|uploaded|transmitted)\b"
    # "tracks you", "tracking your activity", "your personal information"
    r"|\btrack(?:s|ed|ing)?\s+(?:you|your)\b"
    r"|\byour\s+(?:\w+\s+)?(?:data|information|info|location|contacts|photos|messages|identity|behaviou?r|habits)\b",
    re.I)


def _wording_ok(text: str) -> bool:
    # "Data Used to Track You" is the title of a section of the App Store label, not a claim
    return not _BANNED.search(re.sub(r"data used to track you", "", text, flags=re.I))


def _english(text: str) -> bool:
    """False if a letter from another script slipped in: this model can drift into Chinese
    in the middle of an English sentence, and the screen's font has Latin letters only."""
    return not any(ch.isalpha() and ord(ch) > 0x24F for ch in text)


def _numbers_ok(text: str, facts: str) -> bool:
    """Every number in the model's sentence must be one it was given: it has been seen to
    write 39 of 42 (93%) where the facts said 40 of 42 (95%)."""
    return set(re.findall(r"\d+", text)) <= set(re.findall(r"\d+", facts))


def _trim_sentences(text: str, limit: int) -> str:
    """Cut at the last full sentence that fits in `limit` characters ("" if none fits)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("."))
    return cut[:end + 1].strip() if end > 40 else ""


def _safe(sentence: str) -> str:
    """The sentence if it may be shown, else what can be saved of it ("" if nothing). A sentence
    like "The app contacted a.example.com, most likely its server for sending usage data" keeps
    its fact and loses its guess."""
    if not _english(sentence):
        return ""
    if _wording_ok(sentence):
        return sentence
    head = re.split(r",?\s+(?:most likely|probably|likely|possibly|which)\b", sentence, maxsplit=1)[0]
    return head.rstrip(" ,;:") + "." if head != sentence and "contacted" in head and _wording_ok(head) else ""


def _finish_text(out: Optional[str], limit: int) -> Optional[str]:
    """The model's text as we are willing to show it: whole sentences, in English, saying
    "contacted" and never that data was sent, within `limit` characters. None if nothing is left."""
    first = re.split(r"\n\s*\n|\s-{3,}\s", (out or "").strip(), maxsplit=1)[0]  # no afterthoughts ("--- This sentence is ...")
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", first).strip().strip('"').strip())
    if len(sentences) > 1 and not sentences[-1].endswith((".", "!", "?")):
        sentences.pop()  # max_tokens cut the answer in mid-sentence
    text = _trim_sentences(" ".join(filter(None, map(_safe, sentences))), limit)
    return text if "contact" in text.lower() else None


# ----------------------------------------------------------------- classify_domains
_CLASSIFY_SYS = (
    "You label internet hostnames that a phone looked up. You get only the hostnames. For each "
    "one, name the company or service behind it and choose a category. The category is exactly "
    "one of these seven words:\n"
    "advertising: ad networks, ad exchanges, ad measurement and install attribution\n"
    "analytics: usage analytics, crash and performance reporting\n"
    "social: the own servers of a social network or messenger\n"
    "fingerprinting: device fingerprinting, bot and fraud detection\n"
    "content: content delivery networks, cloud and file hosting, and services apps are built "
    "on (payments, sign-in, maps, chat, push messages)\n"
    "vendor: the phone maker's system servers, or the own backend of one app, game or shop "
    "(names like api., config., telemetry. under that app's own domain)\n"
    "unknown: you cannot tell\n"
    "Company: the short name people know, such as Spotify or TikTok. For servers of Google, "
    "Apple, Meta (Facebook, Instagram), Amazon or Microsoft write exactly Google, Apple, Meta, "
    "Amazon or Microsoft. If you do not recognise a hostname, look at its domain: when it "
    "spells out an app or brand, use that as the company with category vendor; when it does "
    "not, answer - for the company. Never invent a company. A hostname under an app's or "
    "service's own domain is vendor, and one you cannot place is unknown, unless the name "
    "itself clearly says advertising or analytics (ads., adserver., analytics., metrics.).\n"
    "Confidence: 0.9 for a hostname you know, 0.6 when you read it off the name, 0.3 or less "
    "for unknown.\n"
    "Answer in English with one line per hostname and nothing else: "
    "number|company|category|confidence\n"
    "Example. Input:\n1. e.crashlytics.com\n2. api.word-safari-game.example\n"
    "3. d1k2xj3.cdn77.org\n4. qq-7f3a.net\n"
    "Output:\n1|Google|analytics|0.9\n2|Word Safari Game|vendor|0.6\n"
    "3|CDN77|content|0.9\n4|-|unknown|0.2"
)
_LINE = re.compile(r"\s*(\d+)\s*\|\s*(.*?)\s*\|\s*([A-Za-z -]+?)\s*\|\s*([0-9.]+)")
_NO_COMPANY = {"", "-", "null", "none", "unknown", "n/a"}


def _clean_entry(v) -> Optional[dict]:
    if not isinstance(v, dict):
        return None
    cat = str(v.get("category", "unknown")).lower().strip()
    if cat not in CATEGORIES:  # "ad networks", "cdn": the model put its own words for one of ours
        first = cat.split(" ")[0]
        cat = "advertising" if first in ("ad", "ads") else "content" if first == "cdn" else "unknown"
    company = v.get("company")
    company = company.strip()[:80] if isinstance(company, str) and company.strip() else None
    if company and (company.lower() in _NO_COMPANY or not _english(company)):
        company = None
    try:
        conf = float(v.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    if cat == "unknown":
        conf = min(conf, 0.3)
    return {"company": company, "category": cat, "confidence": round(conf, 2)}


def _parse_lines(text: str, chunk: list[str]) -> dict[str, dict]:
    """"3|Example Ads|advertising|0.9" lines back onto the names that were asked, by number.
    One line per name instead of a JSON object: under half the tokens (measured: about 4 s
    instead of 7 s for ten names), and a cut-off answer still yields every complete line."""
    found: dict[str, dict] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        index = int(m.group(1)) - 1 if m else -1
        if 0 <= index < len(chunk) and chunk[index] not in found:
            entry = _clean_entry({"company": m.group(2), "category": m.group(3), "confidence": m.group(4)})
            if entry:
                found[chunk[index]] = entry
    return found


async def classify_domains(domains: list[str]) -> dict[str, dict] | None:
    """-> {"odd.example.io": {"company": str | None, "category": str, "confidence": float}}
    Names the model leaves out stay unknown. None if nothing could be answered."""
    try:
        deadline = time.monotonic() + TIMEOUT_S  # for the whole call, however many chunks it takes
        wanted = []
        for d in domains or []:
            d = d.strip().lower().rstrip(".") if isinstance(d, str) else ""
            if d and d not in wanted:
                wanted.append(d)
        result: dict[str, dict] = {}
        todo: list[str] = []
        for d in wanted:
            hit = _seeded("classify", d)
            if hit:
                result[d] = hit
            else:
                todo.append(d)

        for i in range(0, len(todo), MAX_DOMAINS_PER_CALL):
            chunk = todo[i:i + MAX_DOMAINS_PER_CALL]
            out = await _call(
                [{"role": "system", "content": _CLASSIFY_SYS},
                 {"role": "user", "content": "\n".join(f"{n}. {d}" for n, d in enumerate(chunk, 1))}],
                max_tokens=18 * len(chunk) + 20, timeout=deadline - time.monotonic())
            if out:
                result.update(_parse_lines(out, chunk))
        return result or None
    except Exception as e:
        log.warning("classify_domains failed: %s", e)
        return None


# ----------------------------------------------------------------- summarize
_KINDS = {"advertising": "advertising", "analytics": "analytics", "social": "social networks",
          "fingerprinting": "fingerprinting", "content": "content delivery and hosting",
          "vendor": "the phone maker's or the app's own servers", "unknown": "not identified"}
_WORDING = (
    "We see which servers were looked up, never what was sent: say 'contacted'. Never say or "
    "imply that data was sent, shared, collected, leaked or tracked, and never mention the "
    "user's data. English only, plain text: no lists, no markdown, no emojis."
)
_SUMMARY_SYS = (
    "You write the summary a presenter reads aloud in a live privacy demo, after someone used "
    "one app on an iPhone for a short while. You get what the phone contacted: lookups by kind "
    "of server, with shares already worked out, and the most contacted companies.\n"
    "Write 1 or 2 plain sentences, 40 words at most, starting with the app's name. Say which "
    "kind of company the app contacted most and how large that share is, and name the two or "
    "three companies that lead it. Apple's servers are the phone's own: do not count Apple "
    "among advertising or analytics companies. Say 'the app's own servers', never 'vendor'. "
    "'Not identified' are servers no list knows: if that is the largest share, say that most "
    "servers could not be identified. "
    "Mention blocked lookups only if there are any. Copy names and numbers exactly as given; "
    "never work out a number yourself.\n" + _WORDING + "\n"
    "Example: \"Word Safari contacted mostly advertising companies: 31 of its 52 lookups (60%) "
    "went to ad servers, led by Google and Unity.\""
)


def _facts(stats: dict) -> str:
    """The stats as plain lines. Shares are worked out here, so the model does no arithmetic."""
    counts = {str(c): int(n) for c, n in (stats.get("by_category") or {}).items() if int(n) > 0}
    total = sum(counts.values())
    kinds = ", ".join(f"{_KINDS.get(c, c)} {n} ({round(100 * n / total)}%)"
                      for c, n in sorted(counts.items(), key=lambda item: -item[1]))
    top = ", ".join(f"{name} {count}" for name, count in (stats.get("top_companies") or [])[:5])
    seconds = int(stats.get("seconds") or 0)
    return "\n".join([
        f"App: {stats.get('label') or 'no name given, say: this phone'}",
        f"Time: {seconds} seconds" + (f" (about {round(seconds / 60)} minutes)" if seconds >= 90 else ""),
        f"Lookups: {total}",
        f"Lookups by kind of server: {kinds}",
        f"Most contacted companies, with their lookups: {top}",
        f"Lookups blocked by the user: {int(stats.get('blocked') or 0)}"])


async def summarize(stats: dict) -> str | None:
    try:
        seeded = _seeded("summary", _stats_key("summary", stats).split(":", 1)[1])
        if seeded and seeded.get("text"):
            return seeded["text"]
        if not stats.get("top_companies"):
            return None  # nothing to name: the backend's own sentence says so, and a model would pad
        facts = _facts(stats)
        out = await _call([{"role": "system", "content": _SUMMARY_SYS},
                           {"role": "user", "content": facts}], max_tokens=110)
        text = _finish_text(out, 400)
        return text if text and _numbers_ok(text, facts) else None
    except Exception as e:
        log.warning("summarize failed: %s", e)
        return None


# ----------------------------------------------------------------- label_check (optional)
_TRACKING = ("advertising", "analytics", "social", "fingerprinting")
_LABEL_SYS = (
    "You write the verdict line of a privacy-label check in a live privacy demo: an app's "
    "App Store privacy label next to the companies the app was seen contacting during a short "
    "test. You are given what the label says and the finding. Write ONE plain sentence, 35 "
    "words at most: first what the label says, then one to three of the advertising or "
    "analytics companies the app contacted (if there are any), then the finding. Do not name "
    "Apple: its servers are the phone's own. Never say the app lied, and never say the label "
    "is accurate or true: we only compare. Use only facts you are given. Give the sentence "
    "only.\n" + _WORDING + "\n"
    "Example 1: \"The label lists nothing under \"Data Used to Track You\", yet the app "
    "contacted advertising companies such as Google and Unity: worth a closer look.\"\n"
    "Example 2: \"The label lists Identifiers under \"Data Used to Track You\", and the app "
    "contacted advertising companies such as Google and Unity: consistent with the label.\""
)


def _label_facts(label: dict, stats: dict) -> str:
    """What the label says and whether it matches, decided here by the backend's own rules
    (docs/TEAM.md, "The rules"), so the model's sentence cannot contradict the verdict on screen."""
    counts = stats.get("by_category") or {}
    declared = [str(item) for item in label.get("data_used_to_track_you") or []]
    if label.get("data_not_collected"):
        says, mismatch = "says that no data is collected", any(counts.get(c) for c in _TRACKING)
    elif not declared:
        says, mismatch = 'lists nothing under "Data Used to Track You"', bool(counts.get("advertising"))
    else:
        says, mismatch = f'lists {", ".join(declared[:3])} under "Data Used to Track You"', False
    finding = "the label does not match what we saw: worth a closer look" if mismatch else "what we saw is consistent with the label"
    return f"The label {says}.\nFinding: {finding}.\nWhat we saw:\n{_facts(stats)}"


async def label_check(label: dict, stats: dict) -> str | None:
    try:
        seeded = _seeded("label", _stats_key("label", stats, json.dumps(label, sort_keys=True)).split(":", 1)[1])
        if seeded and seeded.get("text"):
            return seeded["text"]
        facts = _label_facts(label, stats)
        out = await _call([{"role": "system", "content": _LABEL_SYS},
                           {"role": "user", "content": facts}], max_tokens=110)
        text = _finish_text(out, 380)
        return text if text and _numbers_ok(text, facts) else None
    except Exception as e:
        log.warning("label_check failed: %s", e)
        return None


# ----------------------------------------------------------------- explain_company
_EXPLAIN_SYS = (
    "You write the text shown on a big screen when someone taps a company in a live privacy "
    "demo. Someone used an app on an iPhone, and the phone looked up server names of that "
    "company; the names are all we know. A phone looks a name up just before it connects, so "
    "each name is a server the app reached out to; what was exchanged, we never see.\n"
    "Write one short plain paragraph that leaves a general reader understanding this "
    "company's part in the app. Most companies take three sentences, some four or five: you "
    "judge how much this one needs, and stop there. Aim for about 60 words and never pass 75, "
    "because the screen has room for no more. No filler: every sentence tells the reader "
    "something.\n"
    "- Say who the company is, in everyday words, and what apps use it for. If you do not "
    "know it, say only what its server names show.\n"
    "- Begin one sentence with 'The app contacted', give two of the server names (three at "
    "most, they are long), and say what kind of server each most likely is, going by its "
    "name. Kinds you may "
    "recognise: an ad auction (advertisers bid for the next ad slot), an ad server (delivers "
    "the ad itself), a measurement or attribution server (counts which ads were shown, "
    "clicked, or led to an install), a settings server (an SDK fetches its configuration at "
    "start), an events, logs or crash server (receives usage or error reports), a sign-in "
    "server, a content delivery network (images, video and other files), an app's own API "
    "(its content and accounts).\n"
    "- Say what the app most likely uses these servers for, as far as that follows from the "
    "names: showing ads and being paid for them, measuring how the app is used, finding "
    "crashes, loading its pictures and videos, signing people in.\n"
    "That the servers were contacted is a fact. What a server is for is your reading of its "
    "name: say 'most likely' or 'probably' there. Describe a server by what it does, never by "
    "what the app sends to it. Do not invent facts about the company.\n"
    + _WORDING + "\n"
    "Example for Bugsnag (analytics; sessions.bugsnag.com, notify.bugsnag.com): \"Bugsnag is "
    "a crash-reporting service: app makers build it into their apps to learn when and why "
    "the app fails. The app contacted sessions.bugsnag.com and notify.bugsnag.com, most "
    "likely the server that counts app starts and the one that receives crash reports. "
    "Counting starts shows the maker what share of sessions end in a crash. So this app "
    "probably uses Bugsnag to watch its own stability.\""
)


async def explain_company(company: str, category: str, domains: list[str]) -> str | None:
    """A short paragraph: who the company is, what kinds of servers the app contacted, and what
    the app most likely uses them for. The model judges the length; 500 characters at most."""
    try:
        company = (company or "").strip()[:80]
        if not company:
            return None
        category = category if category in CATEGORIES else "unknown"
        hosts = []
        for d in domains or []:
            d = str(d).strip().lower().rstrip(".")
            if d and d not in hosts:
                hosts.append(d)
        hosts = hosts[:MAX_EXPLAIN_HOSTS]

        seeded = _seeded("explain", company.lower())
        if seeded and seeded.get("text"):
            return seeded["text"]
        kind, note = _KINDS[category], ""
        if category == "vendor" and company.lower() == "apple":  # a phone talks to its maker all the time: that is not the app
            kind = "the iPhone maker's own servers"
            note = ("\nApple makes the iPhone: most of these lookups are the phone's own housekeeping, not "
                    "the app's. Write 'The phone contacted' instead of 'The app contacted', and say so.")
        elif category == "vendor":
            kind = "the own servers of an app or service"
        out = await _call(
            [{"role": "system", "content": _EXPLAIN_SYS},
             {"role": "user", "content": f"Company: {company}\nKind: {kind}\n"
                                         "Server names contacted, most often first:\n" + "\n".join(hosts) + note}],
            max_tokens=140)
        return _finish_text(out, 500)
    except Exception as e:
        log.warning("explain_company failed: %s", e)
        return None


# ----------------------------------------------------------------- template fallback (used by tools/build_seed.py)
def template_summary(stats: dict) -> str:
    who = stats.get("label") or "This app"
    device = stats.get("device")
    secs = int(stats.get("seconds") or 0)
    span = f"{secs} seconds" if secs < 90 else f"{round(secs / 60)} minutes"
    top = stats.get("top_companies") or []
    cats = stats.get("by_category") or {}
    where = f" on {device}" if device else ""
    if not top:
        return f"{who}{where} contacted no known companies in {span}."
    n = len(top)
    top_cat = max(cats, key=cats.get) if cats else None
    s = f"In {span}, {who}{where} contacted {n} {'company' if n == 1 else 'companies'}"
    if top_cat and top_cat != "unknown":
        s += f", mostly {top_cat} ({cats[top_cat]} lookups)"
    s += f". Busiest: {top[0][0]} ({top[0][1]} lookups)."
    return s
