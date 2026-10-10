#!/usr/bin/env python3
"""End-to-end self-check of the loop, with no Wi-Fi involved.

Starts a private backend (test kb fixture) and a sensor on loopback, then checks:
  1. fake_sensor replay -> backend -> /ws: hits arrive with company and category
  2. real DNS queries -> sensor -> backend -> /ws, including guard and user blocking

Run it with the backend venv's Python (it needs the "websockets" package):
    backend/.venv/bin/python tools/selfcheck.py
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "backend" / "tests" / "fixtures"
REPLAY = ROOT / "data" / "replays" / "demo-synthetic.jsonl"
_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
failures = 0


def check(ok: bool, what: str) -> None:
    global failures
    failures += not ok
    print(("  ok    " if ok else "  FAIL  ") + what)


def system_resolver() -> str:
    for line in Path("/etc/resolv.conf").read_text().splitlines():
        if line.startswith("nameserver"):
            return line.split()[1]
    return "9.9.9.9"


def wait_port(port: int, kind: int = socket.SOCK_STREAM) -> None:
    for _ in range(100):
        with socket.socket(socket.AF_INET, kind) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    sys.exit(f"nothing started listening on port {port}")


def post(base: str, path: str, body: dict) -> None:
    request = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    _http.open(request, timeout=5).close()


def dns_query(port: int, name: str, tcp: bool = False) -> tuple[int, int]:
    """Send one hand-built A query to the sensor. Returns (rcode, number of answers)."""
    labels = b"".join(bytes([len(part)]) + part.encode() for part in name.split("."))
    query = struct.pack("!HHHHHH", 0x7A77, 0x0100, 1, 0, 0, 0) + labels + b"\x00" + struct.pack("!HH", 1, 1)
    if tcp:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(struct.pack("!H", len(query)) + query)
            answer = s.recv(65535)[2:]
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(5)
            s.sendto(query, ("127.0.0.1", port))
            answer = s.recv(65535)
    _, flags, _, answers = struct.unpack("!HHHH", answer[:8])
    return flags & 0xF, answers


def collect(ws, seconds: float, stop=None) -> list[dict]:
    """Messages from the WebSocket for up to `seconds`, or until stop(message) is true."""
    messages, deadline = [], time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = json.loads(ws.recv(timeout=left))
        except TimeoutError:
            break
        messages.append(message)
        if stop and stop(message):
            break
    return messages


def hit_for(ws, domain: str) -> dict | None:
    found = collect(ws, 5, lambda m: m["type"] == "hit" and m["domain"] == domain)
    return found[-1] if found and found[-1].get("domain") == domain else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend-port", type=int, default=8099, help="port for the private backend (default 8099)")
    parser.add_argument("--sensor-port", type=int, default=5300, help="loopback port for the sensor (default 5300)")
    parser.add_argument("--upstream", default=system_resolver(), help="resolver the sensor forwards to (default: this machine's)")
    parser.add_argument("--sensor-python", default=str(ROOT / "sensor" / ".venv" / "bin" / "python"),
                        help="Python that has dnslib (default: sensor/.venv)")
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.backend_port}"
    env = {**os.environ, "KB_PATH": str(FIXTURES / "kb.json"), "KB_OVERRIDES_PATH": str(FIXTURES / "kb_overrides.json")}
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}

    processes = [subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(args.backend_port)],
                                  cwd=ROOT / "backend", env=env, **quiet)]
    try:
        wait_port(args.backend_port)
        with connect(f"ws://127.0.0.1:{args.backend_port}/ws") as ws:
            print("1. fake_sensor replay -> backend -> /ws")
            snapshot = json.loads(ws.recv(timeout=5))
            check(snapshot["type"] == "snapshot" and snapshot["hits"] == [], "first message is an empty snapshot")
            replay = subprocess.Popen([sys.executable, str(ROOT / "tools" / "fake_sensor.py"), str(REPLAY),
                                       "--backend", base, "--speed", "20"], **quiet)
            messages = collect(ws, 30, lambda m: replay.poll() is not None and m["type"] == "health")
            replay.wait(timeout=30)
            hits = [m for m in messages if m["type"] == "hit"]
            named = [h for h in hits if h["company"] and h["category"] != "unknown"]
            check(len(hits) >= 50, f"{len(hits)} hits arrived")
            check(len(named) >= 40, f"{len(named)} of them carry a company and a category")
            check({"advertising", "analytics", "vendor"} <= {h["category"] for h in hits},
                  "categories seen: " + ", ".join(sorted({h["category"] for h in hits})))
            check(any(h["domain"] == "googleads.g.doubleclick.net" and h["company"] == "Google"
                      and h["category"] == "advertising" and h["source"] == "list" for h in hits),
                  "googleads.g.doubleclick.net -> Google / advertising / list")
            check(any(h["source"] == "override" and h["category"] == "vendor" for h in hits), "overrides apply (Apple -> vendor)")
            hidden = {h["domain"] for h in hits if h["block_reason"] == "guard"}
            check({"_dns.resolver.arpa", "mask.icloud.com"} <= hidden,
                  f"guard-list lookups arrive as hidden-traffic attempts ({len(hidden)} names)")
            check(any(m["type"] == "device" and m["name"] == "Test iPhone A" for m in messages), 'device "Test iPhone A" announced')

            print(f"2. real DNS -> sensor (127.0.0.1:{args.sensor_port}, upstream {args.upstream}) -> backend -> /ws")
            processes.append(subprocess.Popen([args.sensor_python, str(ROOT / "sensor" / "tattle_sensor.py"),
                                               "--listen", f"127.0.0.1:{args.sensor_port}", "--upstream", args.upstream,
                                               "--backend", base], **quiet))
            wait_port(args.sensor_port)

            rcode, answers = dns_query(args.sensor_port, "example.com")
            check(rcode == 0 and answers > 0, f"example.com forwarded over UDP: rcode {rcode}, {answers} answers")
            hit = hit_for(ws, "example.com")
            check(bool(hit) and hit["device_id"] == "127.0.0.1" and not hit["blocked"], "its hit reached /ws, not blocked")
            with _http.open(base + "/api/state", timeout=5) as response:
                names = {d["device_id"]: d["name"] for d in json.load(response)["devices"]}
            check(names.get("127.0.0.1") == "box self-test", f"lookups from this machine itself are shown as \"{names.get('127.0.0.1')}\", not as a phone")

            rcode, answers = dns_query(args.sensor_port, "example.net", tcp=True)
            check(rcode == 0 and answers > 0, f"example.net forwarded over TCP: rcode {rcode}, {answers} answers")

            rcode, _ = dns_query(args.sensor_port, "mask.icloud.com")
            check(rcode == 3, f"guard list: mask.icloud.com -> rcode {rcode} (3 = NXDOMAIN)")
            hit = hit_for(ws, "mask.icloud.com")
            check(bool(hit) and hit["blocked"] and hit["block_reason"] == "guard" and hit["company"] == "Apple",
                  "its hit reached /ws as blocked by the guard, company Apple")

            post(base, "/api/block", {"company": "Google"})
            time.sleep(2.5)  # the sensor polls the blocklist every second
            rcode, _ = dns_query(args.sensor_port, "stats.g.doubleclick.net")
            check(rcode == 3, f"after blocking Google: stats.g.doubleclick.net -> rcode {rcode} (3 = NXDOMAIN)")
            hit = hit_for(ws, "stats.g.doubleclick.net")
            check(bool(hit) and hit["blocked"] and hit["block_reason"] == "user" and hit["company"] == "Google",
                  "its hit reached /ws as blocked by the user, company Google")

            # Unblocking is checked with a neutral name: some networks' resolvers drop tracker names themselves.
            post(base, "/api/block", {"domain": "example.org"})
            time.sleep(2.5)
            rcode, _ = dns_query(args.sensor_port, "www.example.org")
            check(rcode == 3, f"after blocking the domain example.org: www.example.org -> rcode {rcode} (3 = NXDOMAIN)")
            post(base, "/api/unblock", {"domain": "example.org"})
            time.sleep(2.5)
            rcode, answers = dns_query(args.sensor_port, "www.example.org")
            check(rcode == 0 and answers > 0, f"after unblocking it: www.example.org -> rcode {rcode}, {answers} answers")

            post(base, "/api/wipe", {})
            check(any(m["type"] == "wiped" for m in collect(ws, 5, lambda m: m["type"] == "wiped")), "wipe is broadcast")
            with _http.open(base + "/api/state", timeout=5) as response:
                state = json.load(response)
            check(state["hits"] == [] and state["devices"] == [], "state is empty after the wipe")
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)

    print("SELF-CHECK " + ("PASSED" if not failures else f"FAILED ({failures} checks)"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
