#!/usr/bin/env python3
"""Build data/kb.json, the tracker knowledge base, from Disconnect's tracking-protection list.

    python3 tools/build_kb.py              # download the list and rewrite data/kb.json
    python3 tools/build_kb.py --source services.json --out /tmp/kb.json

Standard library only. The list is CC BY-NC-SA 4.0; data/kb.json is derived from it and
carries the same license (credit is in the README).

NOTE FOR THE AI OWNER. This is a first version, written by BOX so the demo has real data.
The file, data/kb.json and data/kb_overrides.json are yours from here on. Worth improving:

- Precedence. A domain listed under several Disconnect categories gets the first one in
  CATEGORIES below. Today: advertising, analytics, social, fingerprinting, content. About
  140 advertising domains are also on the "invasive fingerprinting" list and show as
  advertising. Decide whether fingerprinting should win.
- Categories we have no slot for. "Cryptomining" is dropped. "Anti-fraud" (captchas, bot
  detection) and "ConsentManagers" are filed under content. "Email" trackers are filed
  under analytics, last in line. Check that this reads right on screen.
- Company names are Disconnect's (legal owners, often CamelCase): "Unity" for ironSource
  hosts, "AppLovin" for adjust.com, "LoopMe" for chartboost.com. display_name() below
  tidies them for the screen: names written all in lowercase get capitals ("reddit" ->
  "Reddit"), stray spaces go, and RENAME holds the few hand-picked ones. Names styled on
  purpose ("eBay", "comScore") and names that are domains are left alone. CamelCase
  names such as "HumanSecurity" are not split into words yet.
- The list is built for the web. Phone-only hosts (ad mediation SDKs, Firebase, Apple)
  are thin or missing. data/kb_overrides.json fills in the ones the synthetic replay
  uses; real recordings from our phones will show what else is missing.
- Overrides win over this file for a name and everything under it. So the override
  "cloudfront.net -> content" also covers any single cloudfront host Disconnect lists as
  a tracker.
- Entries with a path ("google.com/pagead/...") are skipped: DNS only sees host names.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://raw.githubusercontent.com/disconnectme/disconnect-tracking-protection/master/services.json"
LICENSE = ("Derived from Disconnect's tracking-protection list (https://github.com/disconnectme/disconnect-tracking-protection), "
           "Copyright Disconnect, Inc., licensed CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/). "
           "This file is shared under the same license. Non-commercial use only.")

# Disconnect category -> ours. Order is precedence: the first category that lists a domain wins.
CATEGORIES = [
    ("Advertising", "advertising"),
    ("Analytics", "analytics"),
    ("Social", "social"),
    ("FingerprintingInvasive", "fingerprinting"),
    ("FingerprintingGeneral", "fingerprinting"),
    ("Content", "content"),
    ("Anti-fraud", "content"),
    ("ConsentManagers", "content"),
    ("Email", "analytics"),
    ("EmailAggressive", "analytics"),
]

RENAME = {"FunctionalSoftware": "Sentry"}  # Disconnect's company name -> the name shown on screen


def display_name(company: str) -> str:
    """Disconnect's company name, tidied for the screen. The same rule for every entry, so nothing is fixed by hand."""
    company = " ".join(company.split())  # stray and doubled spaces
    if company in RENAME:
        return RENAME[company]
    if company == company.lower() and "." not in company:  # all lowercase and not a domain: "reddit" -> "Reddit"
        return " ".join(word[:1].upper() + word[1:] for word in company.split(" "))
    return company


def load(source: str) -> dict:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as response:
            return json.load(response)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def build(services: dict) -> dict[str, dict]:
    """domain -> {"company", "category", "source"}, one entry per host name."""
    domains: dict[str, dict] = {}
    for theirs, ours in CATEGORIES:
        for entity in services["categories"].get(theirs, []):
            for company, properties in entity.items():
                for value in properties.values():
                    if not isinstance(value, list):
                        continue  # flags such as "session-replay": "true"
                    for name in value:
                        name = name.strip().strip(".").lower()
                        if "." in name and "/" not in name and " " not in name:
                            domains.setdefault(name, {"company": display_name(company), "category": ours,
                                                      "source": "disconnect"})
    return domains


def write(domains: dict[str, dict], out: Path) -> None:
    """One domain per line, sorted, so a rebuild gives a small diff."""
    lines = [f"    {json.dumps(name)}: {json.dumps(domains[name], ensure_ascii=False)}" for name in sorted(domains)]
    out.write_text("{\n"
                   f"  \"license\": {json.dumps(LICENSE)},\n"
                   "  \"domains\": {\n" + ",\n".join(lines) + "\n  }\n}\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build data/kb.json from Disconnect's services.json")
    parser.add_argument("--source", default=SOURCE, help="URL or local path of services.json (default: Disconnect's GitHub)")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "kb.json", help="where to write (default: data/kb.json)")
    args = parser.parse_args()
    try:
        services = load(args.source)
    except (OSError, ValueError) as error:
        sys.exit(f"could not read {args.source}: {error}")
    domains = build(services)
    write(domains, args.out)
    counts: dict[str, int] = {}
    for entry in domains.values():
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    print(f"{args.out}: {len(domains)} domains, {len({e['company'] for e in domains.values()})} companies")
    print("  " + ", ".join(f"{count} {category}" for category, count in sorted(counts.items(), key=lambda item: -item[1])))


if __name__ == "__main__":
    main()
