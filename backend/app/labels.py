"""Privacy-label fact-check: an app's App Store label next to what a session contacted.

Rule-based and careful with words: we see which servers a phone looks up, never what is
sent to them, so every sentence says "contacted".
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .summary import is_hidden_attempt, session_hits

TRACKING = ("advertising", "analytics", "social", "fingerprinting")
NOTE = "Tattle sees which servers a phone looks up, not what is sent to them."
MAX_COMPANIES = 20


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def find_label(directory: Path, app: str) -> dict | None:
    """The label whose file name or "app" field matches the given app name. Files are read on
    every call, so a label added during the day shows up without a restart."""
    wanted = slug(app)
    for path in sorted(directory.glob("*.json")):
        try:
            label = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(label, dict) and wanted and wanted in (path.stem, slug(str(label.get("app", "")))):
            return label
    return None


def observed(hits, session: dict, now: float) -> dict:
    """What the session's phone contacted. Hidden-traffic attempts are counted apart."""
    mine = session_hits(hits, session)
    seen = [h for h in mine if not is_hidden_attempt(h)]
    by_category = Counter(h["category"] for h in seen)
    per_company: dict[str, Counter] = {}
    for hit in seen:
        if hit["company"]:
            per_company.setdefault(hit["company"], Counter())[hit["category"]] += 1
    companies = sorted(({"company": company, "category": counts.most_common(1)[0][0], "hits": sum(counts.values())}
                        for company, counts in per_company.items()), key=lambda c: (-c["hits"], c["company"]))
    return {
        "seconds": max(0, int((session.get("stopped") or now) - session["started"])),
        "lookups": len(seen),
        "blocked": sum(1 for h in seen if h["blocked"]),
        "hidden_attempts": len(mine) - len(seen),
        "by_category": dict(by_category.most_common()),
        "companies": companies[:MAX_COMPANIES],
        "advertising_companies": sum(1 for counts in per_company.values() if counts["advertising"]),
        "tracking_companies": sum(1 for counts in per_company.values() if any(counts[c] for c in TRACKING)),
    }


def companies(count: int, kind: str) -> str:
    return f"{count} {kind} compan" + ("y" if count == 1 else "ies")


def verdict(label: dict, seen: dict) -> tuple[str, str]:
    """("mismatch" or "consistent", one sentence)."""
    ads = companies(seen["advertising_companies"], "advertising")
    trackers = companies(seen["tracking_companies"], "tracking")
    declared = [str(item) for item in label.get("data_used_to_track_you") or []]
    if label.get("data_not_collected"):
        if seen["tracking_companies"]:
            return "mismatch", f"The label says no data is collected, but this session contacted {trackers}."
        return "consistent", "The label says no data is collected, and this session contacted no known tracking companies."
    if not declared:
        if seen["advertising_companies"]:
            return "mismatch", f'The label lists nothing under "Data Used to Track You", but this session contacted {ads}.'
        return "consistent", ('The label lists nothing under "Data Used to Track You", and this session contacted '
                              "no known advertising companies.")
    listed = ", ".join(declared[:3]) + (" and more" if len(declared) > 3 else "")
    if seen["advertising_companies"]:
        return "consistent", f"The label declares tracking ({listed}), and this session contacted {ads}."
    return "consistent", f"The label declares tracking ({listed}); this session contacted no known advertising companies so far."
