#!/usr/bin/env python3
"""Replay a JSONL file of sensor events into the backend, with the original timing.

Standard library only, so it runs anywhere Python does. It behaves like the real sensor:
batches every 250 ms, timestamps rewritten to "now", and names on the backend's blocklist
are sent as blocked, so blocking from the UI works in replay mode too.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
import urllib.request

BATCH_SECONDS = 0.25
LOOP_PAUSE = 2.0  # seconds between passes with --loop

# Talk to the backend directly, even if the shell has proxy variables set.
_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
    if not events:
        sys.exit(f"{path}: no events")
    return sorted(events, key=lambda event: event["ts"])


def suffix_match(name: str, suffixes: frozenset[str]) -> bool:
    while name:
        if name in suffixes:
            return True
        name = name.partition(".")[2]
    return False


class Backend:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self.blocklist: frozenset[str] = frozenset()
        self.ok: bool | None = None

    def poll_blocklist(self) -> None:
        try:
            with _http.open(f"{self.url}/api/blocklist", timeout=2) as response:
                self.blocklist = frozenset(json.load(response)["domains"])
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            pass  # keep the last good list, like the sensor

    def send(self, events: list[dict]) -> None:
        request = urllib.request.Request(f"{self.url}/api/events", data=json.dumps({"events": events}).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            _http.open(request, timeout=2).close()
            ok = True
        except (OSError, http.client.HTTPException):
            ok = False  # drop the batch and carry on: the replay must not stop mid-demo
        if ok != self.ok:
            self.ok = ok
            print("backend: " + ("connected" if ok else f"unreachable at {self.url}, dropping events"), file=sys.stderr)


def replay(events: list[dict], backend: Backend, speed: float) -> None:
    first = events[0]["ts"]
    wall_start, start = time.time(), time.monotonic()
    i = 0
    while i < len(events):
        time.sleep(BATCH_SECONDS)
        position = (time.monotonic() - start) * speed  # seconds into the recording
        batch = []
        backend.poll_blocklist()
        while i < len(events) and events[i]["ts"] - first <= position:
            event = dict(events[i], ts=wall_start + (events[i]["ts"] - first) / speed)
            if not event.get("blocked") and suffix_match(event["qname"], backend.blocklist):
                event.update(blocked=True, block_reason="user")
            batch.append(event)
            i += 1
        if batch:
            backend.send(batch)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay recorded sensor events into the Tattle backend")
    parser.add_argument("file", help="JSONL replay, e.g. data/replays/demo-synthetic.jsonl")
    parser.add_argument("--backend", default=os.environ.get("BACKEND_URL", "http://127.0.0.1:8000"), help="backend base URL")
    parser.add_argument("--speed", type=float, default=1.0, help="2 = twice as fast (default 1)")
    parser.add_argument("--loop", action="store_true", help="start over when the file ends")
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("--speed must be above 0")

    events = load(args.file)
    backend = Backend(args.backend)
    seconds = (events[-1]["ts"] - events[0]["ts"]) / args.speed
    try:
        while True:
            print(f"replaying {len(events)} events over {seconds:.0f} s", file=sys.stderr)
            replay(events, backend, args.speed)
            if not args.loop:
                break
            time.sleep(LOOP_PAUSE)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
