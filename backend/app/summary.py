"""Session statistics, and the sentence that describes a session when no AI answer is available."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from .kb import CATEGORIES

SPOKEN = ("advertising", "analytics", "social", "fingerprinting")  # read out by name, in this order


def is_hidden_attempt(hit: dict) -> bool:
    """A guard-list lookup: the phone tried encrypted DNS or Private Relay and was told no.
    Counted on its own, never as a blocked tracker and never towards a company."""
    return hit["block_reason"] == "guard"


def session_hits(hits: Iterable[dict], session: dict) -> list[dict]:
    """The session's hits: its device, from its start to its stop (if it has stopped)."""
    stopped = session.get("stopped") or float("inf")
    return [h for h in hits if h["device_id"] == session["device_id"] and session["started"] <= h["ts"] <= stopped]


def session_stats(hits: Iterable[dict], session: dict, device_name: str | None, now: float) -> dict:
    """The stats dict from docs/TEAM.md, counted over the session's hits. This is what the AI module gets."""
    mine = session_hits(hits, session)
    seen = [h for h in mine if not is_hidden_attempt(h)]
    by_category = Counter(h["category"] for h in seen)
    companies = Counter(h["company"] for h in seen if h["company"])
    return {
        "device": device_name or session["device_id"],
        "label": session["label"],
        "seconds": max(0, int((session.get("stopped") or now) - session["started"])),
        "by_category": {c: by_category[c] for c in CATEGORIES if by_category[c]},
        "top_companies": [[company, count] for company, count in companies.most_common(5)],
        "blocked": sum(1 for h in seen if h["blocked"]),
        "hidden_attempts": len(mine) - len(seen),
    }


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else many or one + 's'}"


def listing(names: list[str]) -> str:
    """Up to three names, then "and N more"."""
    return ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")


def describe(hits: Iterable[dict], session: dict, now: float) -> str:
    """The session in a few short sentences, written to be read aloud. Says "contacted", never "sent":
    we see which servers were looked up, not what went to them."""
    mine = session_hits(hits, session)
    seen = [h for h in mine if not is_hidden_attempt(h)]
    seconds = max(0, int((session.get("stopped") or now) - session["started"]))
    took = plural(seconds, "second") if seconds < 90 else f"about {plural(round(seconds / 60), 'minute')}"
    who = session["label"] or "this phone"

    per_company: dict[str, Counter] = {}
    for hit in seen:
        if hit["company"]:
            per_company.setdefault(hit["company"], Counter())[hit["category"]] += 1
    groups: dict[str, list[tuple[int, str]]] = {}  # a company counts once, under the category it was mostly contacted for
    for company, counts in per_company.items():
        groups.setdefault(counts.most_common(1)[0][0], []).append((-sum(counts.values()), company))

    total = plural(len(per_company), "company", "companies")
    parts = [f"{len(groups[c])} {c} ({listing([name for _, name in sorted(groups[c])])})" for c in SPOKEN if c in groups]
    others = len(per_company) - sum(len(groups[c]) for c in SPOKEN if c in groups)
    if not seen:
        text = f"No lookups from {who} in {took}."
    elif not per_company:
        text = f"In {took}, {who} contacted no company we know."
    elif not parts:
        text = f"In {took}, {who} contacted {total}, none of them known for advertising or tracking."
    else:
        text = f"In {took}, {who} contacted {total}: {', '.join(parts)}" + (f", and {plural(others, 'other')}." if others else ".")

    unknown = len({h["domain"] for h in seen if not h["company"]})
    blocked = sum(1 for h in seen if h["blocked"])
    hidden = len(mine) - len(seen)
    if unknown:
        text += f" {plural(unknown, 'server')} could not be identified."
    if blocked:
        text += f" {plural(blocked, 'lookup')} {'was' if blocked == 1 else 'were'} blocked."
    if hidden:
        text += f" {plural(hidden, 'hidden-traffic attempt')} {'was' if hidden == 1 else 'were'} refused."
    return text
