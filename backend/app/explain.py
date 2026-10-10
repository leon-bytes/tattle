"""Who is this company? The sentence the show screen's detail panel opens with, built from the
tracker list alone, and the facts handed to the AI for a better one."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

MAX_NAMES = 20  # server names handed to the AI for one company, most looked up first

# "<company>: <this>, according to our tracker list." The show screen builds the same sentence
# (KINDS in frontend/app.js) so that its panel can open before this backend has answered.
KINDS = {
    "advertising": "an advertising company",
    "analytics": "an analytics company: it measures how an app is used",
    "social": "a social network",
    "fingerprinting": "a company known for fingerprinting: telling devices apart by their technical traits",
    "content": "a content delivery company: it serves files such as images and video for other companies",
    "vendor": "the phone maker's or the app's own servers",
    "unknown": "a company we have no category for",
}


def seen(hits: Iterable[dict], company: str, device_id: str | None, since: float, until: float | None) -> tuple[str, list[str]]:
    """What the lookups on record say about a company: the category it was mostly contacted for, and
    its server names, most looked up first. Guard-list lookups are not contacts to a company."""
    names: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    for hit in hits:
        if hit["company"] != company or hit["block_reason"] == "guard" or hit["ts"] < since:
            continue
        if (device_id and hit["device_id"] != device_id) or (until is not None and hit["ts"] > until):
            continue
        names[hit["domain"]] += 1
        categories[hit["category"]] += 1
    category = categories.most_common(1)[0][0] if categories else "unknown"
    return category, [name for name, _ in names.most_common(MAX_NAMES)]


def fallback(company: str, category: str, listed: bool) -> str:
    """The plain sentence, with no model involved. `listed`: the tracker list knows this company;
    otherwise its name is itself an AI guess, and the sentence says so."""
    kind = KINDS.get(category, KINDS["unknown"])
    if listed:
        return f"{company}: {kind}, according to our tracker list."
    return f"{company}: {kind}, according to the AI's guess. It is not on our tracker list."
