"""Tracker knowledge base: domain -> company and category, with suffix lookup."""
from __future__ import annotations

import json
import sys
from pathlib import Path

CATEGORIES = ("advertising", "analytics", "social", "fingerprinting", "content", "vendor", "unknown")


def clean(name: str) -> str:
    return name.strip().strip(".").lower()


def _read(path: Path) -> dict[str, dict]:
    """The "domains" map of a kb file. A missing or broken file means an empty kb, not a crash."""
    try:
        domains = json.loads(path.read_text(encoding="utf-8"))["domains"]
        return {clean(name): entry for name, entry in domains.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"kb: ignoring {path.name}: {type(error).__name__}", file=sys.stderr)
        return {}


class Kb:
    def __init__(self, domains: dict[str, dict], overrides: dict[str, dict]) -> None:
        self.domains = domains
        self.overrides = overrides
        self._by_company: dict[str, set[str]] = {}
        for name, company, _, _ in self.entries():
            if company:
                self._by_company.setdefault(company, set()).add(name)

    @classmethod
    def load(cls, kb_path: Path, overrides_path: Path) -> Kb:
        return cls(_read(kb_path), _read(overrides_path))

    def __len__(self) -> int:
        return len(self.domains.keys() | self.overrides.keys())

    def lookup(self, name: str) -> dict | None:
        """Walk up the name. Overrides are tried first, all the way up: an override wins over the kb
        for its own name and for everything under it."""
        for table, source in ((self.overrides, "override"), (self.domains, "list")):
            walk = name
            while walk:
                entry = table.get(walk)
                if entry:
                    category = entry.get("category")
                    return {"company": entry.get("company"),
                            "category": category if category in CATEGORIES else "unknown",
                            "source": source}
                walk = walk.partition(".")[2]
        return None

    def entries(self) -> list[tuple[str, str | None, str, str]]:
        """Every known name as (domain, company, category, source), as lookup() would answer for it."""
        return [(name, match["company"], match["category"], match["source"])
                for name in sorted(self.domains.keys() | self.overrides.keys())
                if (match := self.lookup(name))]

    def company_domains(self, company: str) -> set[str]:
        return self._by_company.get(company, set())
