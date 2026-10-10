#!/usr/bin/env python3
"""Tattle sensor: the DNS resolver the hotspot's phones talk to.

Answers every lookup (NXDOMAIN for blocked and guard-list names, otherwise the
upstream's answer) and reports each name to the backend. Query names stay in
RAM: nothing is printed or written unless --debug or --record is given.
Phones are reported by address only; their DHCP names are read only with --names.
"""
from __future__ import annotations

import argparse
import collections
import http.client
import itertools
import json
import os
import re
import socket
import socketserver
import struct
import sys
import threading
import time
import urllib.error
import urllib.request

from dnslib import QTYPE, RCODE, DNSRecord

# Always NXDOMAIN, so phones fall back to plain DNS that we can see.
GUARD = frozenset({
    "mask.icloud.com", "mask-h2.icloud.com", "mask.apple-dns.net",  # iCloud Private Relay opt-out
    "_dns.resolver.arpa",  # the phone asking this resolver for an encrypted upgrade
    "dns.google", "cloudflare-dns.com", "one.one.one.one", "dns.quad9.net",  # well-known DoH hosts
    "doh.opendns.com", "use-application-dns.net",
})

# Phones choose the names they look up, and DNS allows any bytes in them. Only plain host names
# (letters, digits, "-", "_", dots; at most 253 characters) are resolved and reported. Anything
# else is refused and counted: a name we cannot show must not become a way around us.
VALID_NAME = re.compile(r"(?=.{1,253}$)[a-z0-9_-]{1,63}(\.[a-z0-9_-]{1,63})*")

# NetworkManager's lease file for the hotspot interface box-up.sh creates.
DEFAULT_LEASES = "/var/lib/NetworkManager/dnsmasq-tattle0.leases"

UPSTREAM_TIMEOUT = 3.0  # seconds
SEND_INTERVAL = 0.25    # seconds between event batches
POLL_INTERVAL = 1.0     # seconds between blocklist polls
QUEUE_MAX = 5000        # events kept while the backend is down
BATCH_MAX = 500

# Talk to the backend directly, even if the shell has proxy variables set.
_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def suffix_match(name: str, suffixes: frozenset[str]) -> bool:
    """True if name or any parent domain of it is in suffixes."""
    while name:
        if name in suffixes:
            return True
        name = name.partition(".")[2]
    return False


def host_port(value: str, default_port: int) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    return (host, int(port)) if host else (value, default_port)


def recv_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class Leases:
    """IP -> hostname from a dnsmasq lease file. Best effort: any problem means no names."""

    def __init__(self, path: str | None) -> None:
        self.path = path
        self.names: dict[str, str] = {}
        self.mtime = 0.0
        self.checked = 0.0

    def name(self, ip: str) -> str | None:
        if not self.path:
            return None
        now = time.monotonic()
        if now - self.checked > 2:
            self.checked = now
            self._reload()
        return self.names.get(ip)

    def _reload(self) -> None:
        try:
            mtime = os.stat(self.path).st_mtime
            if mtime == self.mtime:
                return
            names = {}
            with open(self.path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.split()  # expiry, mac, ip, hostname, client-id
                    if len(parts) >= 4 and parts[3] != "*":
                        names[parts[2]] = parts[3]
            self.names, self.mtime = names, mtime
        except OSError:
            self.names = {}


class Sensor:
    def __init__(self, upstream: tuple[str, int], backend: str, leases: str | None,
                 debug: bool = False, record: str | None = None) -> None:
        self.upstream = upstream
        self.backend = backend.rstrip("/")
        self.leases = Leases(leases)
        self.debug = debug
        self.record = record
        self.record_names: dict[str, str] = {}
        self.blocklist: frozenset[str] = frozenset()
        self.queue: collections.deque[tuple[int, dict]] = collections.deque(maxlen=QUEUE_MAX)
        self.seq = 0
        self.malformed = 0  # names refused since the backend last heard about them
        self.lock = threading.Lock()
        self.backend_ok: bool | None = None

    # --- answering ---

    def handle(self, data: bytes, client_ip: str, tcp: bool) -> bytes | None:
        try:
            request = DNSRecord.parse(data)
            question = request.q
            name = str(question.qname).rstrip(".").lower()
        except Exception:
            return None  # not a DNS query we can read: drop it
        if request.header.qr:
            return None  # an answer, not a question: nothing to resolve
        if not name:
            return self.resolve(data, request, tcp)  # a lookup of the root: nothing to report
        if not VALID_NAME.fullmatch(name):
            with self.lock:
                self.malformed += 1
            if self.debug:
                print(f"{client_ip} malformed name refused", flush=True)  # the name itself is never printed
            return self.reply(request, RCODE.REFUSED)
        if suffix_match(name, GUARD):
            reason = "guard"
        elif suffix_match(name, self.blocklist):
            reason = "user"
        else:
            reason = None
        qtype = QTYPE.forward.get(question.qtype, f"TYPE{question.qtype}")
        self.report(client_ip, name, qtype, reason)
        if self.debug:
            print(f"{client_ip} {qtype} {name} -> {reason or 'forward'}", flush=True)
        if reason:
            return self.reply(request, RCODE.NXDOMAIN)
        return self.resolve(data, request, tcp)

    def resolve(self, data: bytes, request: DNSRecord, tcp: bool) -> bytes:
        try:
            return self.forward_tcp(data) if tcp else self.forward_udp(data)
        except OSError:
            return self.reply(request, RCODE.SERVFAIL)

    @staticmethod
    def reply(request: DNSRecord, rcode: int) -> bytes:
        answer = request.reply()
        answer.header.rcode = rcode
        return answer.pack()

    def forward_udp(self, data: bytes) -> bytes:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(UPSTREAM_TIMEOUT)
            s.connect(self.upstream)  # connected: only the upstream's replies arrive
            s.send(data)
            while True:
                answer = s.recv(65535)
                if answer[:2] == data[:2]:  # same query id
                    return answer

    def forward_tcp(self, data: bytes) -> bytes:
        with socket.create_connection(self.upstream, timeout=UPSTREAM_TIMEOUT) as s:
            s.sendall(struct.pack("!H", len(data)) + data)
            head = recv_exact(s, 2)
            answer = recv_exact(s, struct.unpack("!H", head)[0]) if head else None
            if answer is None:
                raise OSError("upstream closed the connection")
            return answer

    # --- events ---

    def report(self, client_ip: str, name: str, qtype: str, reason: str | None) -> None:
        event = {"ts": time.time(), "client_ip": client_ip, "client_name": self.leases.name(client_ip),
                 "qname": name, "qtype": qtype, "blocked": reason is not None, "block_reason": reason}
        with self.lock:
            self.seq += 1
            self.queue.append((self.seq, event))  # a full deque drops its oldest entry
            if self.record:
                self._record(event)

    def _record(self, event: dict) -> None:
        # Replays end up in the team repo: never store the phone's real name.
        ip = event["client_ip"]
        if ip not in self.record_names:
            self.record_names[ip] = f"Test iPhone {chr(ord('A') + len(self.record_names) % 26)}"
        try:
            with open(self.record, "a", encoding="utf-8") as f:
                f.write(json.dumps({**event, "client_name": self.record_names[ip]}) + "\n")
        except OSError as error:  # recording must never cost a DNS answer
            print(f"sensor: recording stopped ({error.strerror})", file=sys.stderr, flush=True)
            self.record = None

    def send_loop(self) -> None:
        while True:
            time.sleep(SEND_INTERVAL)
            with self.lock:
                batch = list(itertools.islice(self.queue, BATCH_MAX))
                malformed = self.malformed
            if not batch and not malformed:
                continue
            body = json.dumps({"events": [event for _, event in batch], "malformed": malformed}).encode()
            request = urllib.request.Request(f"{self.backend}/api/events", data=body,
                                             headers={"Content-Type": "application/json"})
            try:
                _http.open(request, timeout=2).close()
            except urllib.error.HTTPError as error:
                # The backend is there but refused this batch. Sending it again would block the queue for good: drop it.
                print(f"backend: refused a batch (HTTP {error.code}), dropped", file=sys.stderr, flush=True)
            except (OSError, http.client.HTTPException):
                self.set_backend_ok(False)
                continue  # the batch stays queued for the next round
            self.set_backend_ok(True)
            with self.lock:
                self.malformed -= malformed
                while batch and self.queue and self.queue[0][0] <= batch[-1][0]:
                    self.queue.popleft()

    def poll_loop(self) -> None:
        while True:
            try:
                with _http.open(f"{self.backend}/api/blocklist", timeout=2) as response:
                    domains = json.load(response)["domains"]
                self.blocklist = frozenset(d.lower().rstrip(".") for d in domains)
            except (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException):
                pass  # keep the last good list
            time.sleep(POLL_INTERVAL)

    def set_backend_ok(self, ok: bool) -> None:
        if ok != self.backend_ok:
            self.backend_ok = ok
            print("backend: " + ("connected" if ok else "unreachable, queueing events"),
                  file=sys.stderr, flush=True)

    def start_background(self) -> None:
        for loop in (self.send_loop, self.poll_loop):
            threading.Thread(target=loop, daemon=True).start()


class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data, sock = self.request
        answer = self.server.sensor.handle(data, self.client_address[0], tcp=False)
        if answer:
            sock.sendto(answer, self.client_address)


class TCPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(5)
        try:
            while head := recv_exact(self.request, 2):
                data = recv_exact(self.request, struct.unpack("!H", head)[0])
                if data is None:
                    return
                answer = self.server.sensor.handle(data, self.client_address[0], tcp=True)
                if answer is None:
                    return
                self.request.sendall(struct.pack("!H", len(answer)) + answer)
        except OSError:
            pass  # client went away or idled out


class UDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True
    daemon_threads = True


class TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(sensor: Sensor, listen: tuple[str, int]) -> tuple[UDPServer, TCPServer]:
    """Start the UDP and TCP listeners in background threads."""
    servers = (UDPServer(listen, UDPHandler), TCPServer(listen, TCPHandler))
    for server in servers:
        server.sensor = sensor
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return servers


def main() -> None:
    env = os.environ
    parser = argparse.ArgumentParser(description="Tattle DNS sensor")
    parser.add_argument("--listen", default=env.get("SENSOR_LISTEN", "0.0.0.0:5300"), help="host:port for UDP and TCP")
    parser.add_argument("--upstream", default=env.get("UPSTREAM_DNS", "9.9.9.9"), help="upstream resolver, host or host:port")
    parser.add_argument("--backend", default=env.get("BACKEND_URL", "http://127.0.0.1:8000"), help="backend base URL")
    parser.add_argument("--names", action="store_true", help="send each phone's DHCP hostname (off: phones stay unnamed)")
    parser.add_argument("--leases", default=env.get("LEASES_FILE") or DEFAULT_LEASES,
                        help="dnsmasq lease file, read only with --names")
    parser.add_argument("--debug", action="store_true", help="print every query (development only)")
    parser.add_argument("--record", metavar="FILE", help="append events to a JSONL replay file (our own phones only)")
    args = parser.parse_args()

    leases = args.leases if args.names else None
    sensor = Sensor(host_port(args.upstream, 53), args.backend, leases, args.debug, args.record)
    sensor.start_background()
    serve(sensor, host_port(args.listen, 5300))
    print(f"sensor: listening on {args.listen} (udp+tcp), upstream {args.upstream}, backend {args.backend}",
          file=sys.stderr, flush=True)
    print("sensor: device names " + (f"from {leases}" if leases else "off"), file=sys.stderr, flush=True)
    if args.record:
        print(f"sensor: RECORDING events to {args.record}", file=sys.stderr, flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
