#!/usr/bin/env python3
"""Try backend/app/ai.py the way the backend calls it, without starting the backend.

    backend/.venv/bin/python tools/try_ai.py                  # tests backend/app/ai.py
    backend/.venv/bin/python tools/try_ai.py --file draft.py  # tests another file with the same functions

Each function is called once with sample data, under the backend's time limit, and the
shape of what comes back is checked. Exit code 0 means the backend can use the module.
Environment variables (AI_BASE_URL, AI_TOKEN, AI_MODEL) are read by your module as usual;
to load them from .env first:  set -a; . ./.env; set +a
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import inspect
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.kb import CATEGORIES  # noqa: E402

TIMEOUT = 10.0   # the backend's backstop; the contract says your own limit is 8 s
PROMISED = 8.0

DOMAINS = ["api.puzzle-garden-game.example", "telemetry.puzzle-garden-game.example", "cdn.puzzle-garden-game.example",
           "metrics.shop-example.io", "ads-track.example.net"]
STATS = {"device": "Test iPhone A", "label": "Demo Game", "seconds": 95,
         "by_category": {"advertising": 41, "analytics": 12, "social": 3, "content": 5, "vendor": 16, "unknown": 6},
         "top_companies": [["Google", 21], ["AppLovin", 15], ["Unity", 9], ["Meta", 6], ["AppsFlyer", 5]],
         "blocked": 4, "hidden_attempts": 2}
LABEL = {"app": "Demo Game", "source_url": "https://apps.apple.com/app/id0000000000", "checked": "2026-10-10",
         "data_used_to_track_you": [], "data_linked_to_you": ["Identifiers", "Usage Data"],
         "data_not_linked_to_you": ["Diagnostics"], "data_not_collected": False}

failures = 0


def say(ok: bool | None, text: str) -> None:
    global failures
    failures += ok is False
    print({True: "  ok    ", False: "  FAIL  ", None: "  note  "}[ok] + text)


def load(file: str | None):
    if file:
        spec = importlib.util.spec_from_file_location("ai_under_test", file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    if not (ROOT / "backend" / "app" / "ai.py").exists():
        sys.exit("backend/app/ai.py does not exist yet. Write it (docs/AI-QUICKSTART.md), or pass --file <your draft>.")
    return importlib.import_module("app.ai")


BROKEN = object()  # the call itself failed, and that was already reported


async def call(module, name: str, *args):
    """What the function returned, or BROKEN if the call itself failed."""
    function = getattr(module, name)
    if not inspect.iscoroutinefunction(function):
        say(False, f"{name} must be declared with 'async def': the backend awaits it")
        return BROKEN
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(function(*args), TIMEOUT)
    except TimeoutError:
        say(False, f"{name} did not answer within {TIMEOUT:.0f} s: the backend gives up and uses its fallback")
        return BROKEN
    except Exception as error:
        say(False, f"{name} raised {type(error).__name__}: {error} (the contract says: return None on any failure)")
        return BROKEN
    seconds = time.monotonic() - started
    say(None, f"answered in {seconds:.1f} s" + (f"; the contract promises {PROMISED:.0f} s" if seconds > PROMISED else ""))
    return result


def check_classified(result: object) -> None:
    if not isinstance(result, dict):
        say(False, f"classify_domains returned {type(result).__name__}, not a dict: the backend treats this as a failed call")
        return
    for name in DOMAINS:
        answer = result.get(name)
        if answer is None:
            say(None, f"{name}: no answer (allowed; it stays 'unknown' and is not asked again until a wipe)")
            continue
        problems = []
        if not isinstance(answer, dict):
            problems.append("the answer is not a dict")
        else:
            if answer.get("category") not in CATEGORIES:
                problems.append(f"category {answer.get('category')!r} is not one of {', '.join(CATEGORIES)}")
            if not (answer.get("company") is None or isinstance(answer.get("company"), str)):
                problems.append("company must be a string or null")
            if not isinstance(answer.get("confidence"), (int, float)) or not 0 <= answer["confidence"] <= 1:
                problems.append("confidence must be a number from 0 to 1")
        say(not problems, f"{name}: " + ("; ".join(problems) if problems else
                                          f"{answer['company']} / {answer['category']} / {answer['confidence']}"))
    extra = sorted(set(result) - set(DOMAINS))
    if extra:
        say(None, f"answers for names that were not asked are ignored: {', '.join(extra[:5])}")


def check_text(name: str, result: object) -> None:
    if isinstance(result, str) and result.strip():
        say(True, f"{name}: {result.strip()!r}")
        if "sent" in result.lower():
            say(None, f"{name} says \"sent\": we see lookups, not content. Prefer \"contacted\".")
    else:
        say(False, f"{name} returned {result!r}: the backend needs a non-empty string and otherwise keeps its own sentence")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", help="test this file instead of backend/app/ai.py")
    args = parser.parse_args()
    try:
        module = load(args.file)
    except Exception as error:
        sys.exit(f"the module failed to import ({type(error).__name__}: {error}). The backend would run without AI.")

    print(f"classify_domains({len(DOMAINS)} names)")
    if not hasattr(module, "classify_domains"):
        say(False, "classify_domains is missing")
    elif (result := await call(module, "classify_domains", list(DOMAINS))) is None:
        say(False, "classify_domains returned None: the backend marks health.ai false and retries in 15 s")
    elif result is not BROKEN:
        check_classified(result)

    print("summarize(stats)")
    if not hasattr(module, "summarize"):
        say(False, "summarize is missing")
    elif (result := await call(module, "summarize", dict(STATS))) is not BROKEN:
        check_text("summarize", result)

    print("label_check(label, stats)   [optional]")
    if not hasattr(module, "label_check"):
        say(None, "label_check is not there, which is fine")
    elif (result := await call(module, "label_check", dict(LABEL), dict(STATS))) is not BROKEN:
        check_text("label_check", result)

    print("RESULT: " + ("the backend can use this module" if not failures else f"{failures} problem(s) to fix"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
