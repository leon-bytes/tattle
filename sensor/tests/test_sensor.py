"""Sensor tests: a real sensor on a loopback port, with a fake upstream resolver and a fake backend."""
import json
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from dnslib import QTYPE, RCODE, RR, A, DNSLabel, DNSQuestion, DNSRecord
from dnslib.server import BaseResolver, DNSServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tattle_sensor  # noqa: E402

ANSWER_IP = "192.0.2.1"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class Upstream(BaseResolver):
    """Answers every A query with ANSWER_IP and remembers what it was asked."""

    def __init__(self):
        self.seen = []

    def resolve(self, request, handler):
        self.seen.append(str(request.q.qname).rstrip("."))
        reply = request.reply()
        reply.add_answer(RR(request.q.qname, QTYPE.A, rdata=A(ANSWER_IP), ttl=60))
        return reply


class Backend:
    """Collects POSTed event batches and serves a blocklist."""

    def __init__(self):
        self.batches = []
        self.blocklist = {"version": 1, "domains": []}
        self.post_status = 200
        self.malformed = 0
        self.port = free_port()
        self.server = None

    @property
    def events(self):
        return [event for batch in self.batches for event in batch]

    def start(self):
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if backend.post_status != 200:
                    self.send_error(backend.post_status)
                    return
                backend.malformed += body["malformed"]
                if body["events"]:
                    backend.batches.append(body["events"])
                self._send({"accepted": len(body["events"])})

            def do_GET(self):
                self._send(backend.blocklist)

            def _send(self, payload):
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(tattle_sensor, "SEND_INTERVAL", 0.05)
    monkeypatch.setattr(tattle_sensor, "POLL_INTERVAL", 0.05)
    upstream = Upstream()
    upstream_port = free_port()
    upstream_servers = [DNSServer(upstream, port=upstream_port, address="127.0.0.1", tcp=tcp) for tcp in (False, True)]
    for server in upstream_servers:
        server.start_thread()
    backend = Backend()
    backend.start()
    sensor = tattle_sensor.Sensor(("127.0.0.1", upstream_port), f"http://127.0.0.1:{backend.port}", None)
    sensor.start_background()
    port = free_port()
    servers = tattle_sensor.serve(sensor, ("127.0.0.1", port))

    class Rig:
        pass

    rig = Rig()
    rig.upstream, rig.backend, rig.sensor, rig.port = upstream, backend, sensor, port
    yield rig
    for server in servers:
        server.shutdown()
        server.server_close()
    for server in upstream_servers:
        server.stop()
    backend.stop()


def ask(port, name, qtype="A", tcp=False):
    answer = DNSRecord.question(name, qtype).send("127.0.0.1", port, tcp=tcp, timeout=3)
    return DNSRecord.parse(answer)


def test_forwards_over_udp_and_reports(rig):
    answer = ask(rig.port, "example.com")
    assert answer.header.rcode == RCODE.NOERROR
    assert str(answer.rr[0].rdata) == ANSWER_IP
    assert wait_for(lambda: rig.backend.events)
    event = rig.backend.events[0]
    assert event["qname"] == "example.com" and event["qtype"] == "A"
    assert event["client_ip"] == "127.0.0.1" and event["client_name"] is None
    assert event["blocked"] is False and event["block_reason"] is None
    assert abs(event["ts"] - time.time()) < 5


def test_forwards_over_tcp(rig):
    answer = ask(rig.port, "example.com", tcp=True)
    assert str(answer.rr[0].rdata) == ANSWER_IP


def test_two_queries_on_one_tcp_connection(rig):
    with socket.create_connection(("127.0.0.1", rig.port), timeout=3) as s:
        for name in ("a.example.com", "b.example.com"):
            query = DNSRecord.question(name).pack()
            s.sendall(struct.pack("!H", len(query)) + query)
            length = struct.unpack("!H", tattle_sensor.recv_exact(s, 2))[0]
            assert str(DNSRecord.parse(tattle_sensor.recv_exact(s, length)).rr[0].rdata) == ANSWER_IP


@pytest.mark.parametrize("name,qtype", [
    ("mask.icloud.com", "A"), ("mask-h2.icloud.com", "AAAA"), ("mask.apple-dns.net", "A"),
    ("_dns.resolver.arpa", "SVCB"), ("dns.google", "A"), ("mozilla.cloudflare-dns.com", "HTTPS"),
    ("one.one.one.one", "A"), ("dns.quad9.net", "A"), ("doh.opendns.com", "A"), ("use-application-dns.net", "A"),
])
def test_guard_list_is_nxdomain_and_never_forwarded(rig, name, qtype):
    answer = ask(rig.port, name, qtype)
    assert answer.header.rcode == RCODE.NXDOMAIN
    assert rig.upstream.seen == []
    assert wait_for(lambda: rig.backend.events)
    event = rig.backend.events[0]
    assert event["qname"] == name and event["qtype"] == qtype
    assert event["blocked"] is True and event["block_reason"] == "guard"


def test_blocklist_from_backend_is_nxdomain(rig):
    rig.backend.blocklist = {"version": 2, "domains": ["doubleclick.net"]}
    assert wait_for(lambda: "doubleclick.net" in rig.sensor.blocklist)
    assert ask(rig.port, "ad.doubleclick.net").header.rcode == RCODE.NXDOMAIN
    assert ask(rig.port, "doubleclick.net", tcp=True).header.rcode == RCODE.NXDOMAIN
    assert ask(rig.port, "notdoubleclick.net").header.rcode == RCODE.NOERROR  # suffix match is per label
    assert rig.upstream.seen == ["notdoubleclick.net"]
    assert wait_for(lambda: len(rig.backend.events) == 3)
    assert [e["block_reason"] for e in rig.backend.events] == ["user", "user", None]


def test_unblock_takes_effect(rig):
    rig.backend.blocklist = {"version": 2, "domains": ["doubleclick.net"]}
    assert wait_for(lambda: rig.sensor.blocklist)
    rig.backend.blocklist = {"version": 3, "domains": []}
    assert wait_for(lambda: not rig.sensor.blocklist)
    assert ask(rig.port, "ad.doubleclick.net").header.rcode == RCODE.NOERROR


def test_mixed_case_names_are_matched_and_reported_lowercase(rig):
    assert ask(rig.port, "MaSk.iCloud.COM").header.rcode == RCODE.NXDOMAIN
    assert wait_for(lambda: rig.backend.events)
    assert rig.backend.events[0]["qname"] == "mask.icloud.com"


def test_events_are_batched(rig):
    for i in range(30):
        ask(rig.port, f"host{i}.example.com")
    assert wait_for(lambda: len(rig.backend.events) == 30)
    assert len(rig.backend.batches) < 30
    assert [e["qname"] for e in rig.backend.events] == [f"host{i}.example.com" for i in range(30)]


def test_backend_down_keeps_resolving_and_delivers_later(rig, monkeypatch):
    rig.backend.blocklist = {"version": 2, "domains": ["doubleclick.net"]}
    assert wait_for(lambda: rig.sensor.blocklist)
    rig.backend.stop()
    assert ask(rig.port, "example.com").header.rcode == RCODE.NOERROR
    assert ask(rig.port, "ad.doubleclick.net").header.rcode == RCODE.NXDOMAIN  # last good blocklist kept
    time.sleep(0.3)
    assert len(rig.sensor.queue) == 2
    rig.backend.start()
    assert wait_for(lambda: len(rig.backend.events) == 2)
    assert wait_for(lambda: not rig.sensor.queue)


def test_a_batch_the_backend_refuses_is_dropped_not_resent_forever(rig):
    rig.backend.post_status = 422
    ask(rig.port, "refused.example.com")
    assert wait_for(lambda: not rig.sensor.queue and rig.sensor.seq == 1)
    rig.backend.post_status = 200
    ask(rig.port, "example.com")
    assert wait_for(lambda: rig.backend.events)
    assert [e["qname"] for e in rig.backend.events] == ["example.com"]


def test_dns_answers_sent_to_the_sensor_are_ignored(rig):
    answer = DNSRecord.question("example.com").reply().pack()  # QR bit set: not a question
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(0.3)
        s.sendto(answer, ("127.0.0.1", rig.port))
        with pytest.raises(TimeoutError):
            s.recv(512)
    assert rig.upstream.seen == [] and rig.sensor.seq == 0


@pytest.mark.parametrize("labels", [
    [b"x<script>alert(1)</script>", b"example", b"com"],  # markup
    [b"a b", b"example", b"com"],                          # a space
    [b"caf\xc3\xa9", b"example", b"com"],                  # raw non-ASCII bytes
    [b"\x1b[31mred", b"example", b"com"],                  # a terminal escape sequence
    [b"evil\x00null", b"example", b"com"],                 # a NUL byte
    [b"*", b"example", b"com"],
])
def test_names_that_are_not_plain_host_names_are_refused_and_counted(rig, labels):
    query = DNSRecord(q=DNSQuestion(DNSLabel(labels))).pack()
    for tcp in (False, True):
        answer = DNSRecord.parse(DNSRecord.parse(query).send("127.0.0.1", rig.port, tcp=tcp, timeout=3))
        assert answer.header.rcode == RCODE.REFUSED
    assert ask(rig.port, "example.com").header.rcode == RCODE.NOERROR  # the sensor carries on
    assert wait_for(lambda: rig.backend.malformed == 2 and rig.backend.events)
    assert rig.upstream.seen == ["example.com"]  # the odd name never left the box
    assert [e["qname"] for e in rig.backend.events] == ["example.com"]  # and never reached the backend
    assert rig.sensor.malformed == 0


def test_ordinary_unusual_names_still_resolve(rig):
    for name in ("_dns-sd._udp.example.com", "r1---sn-abc.example.com", "xn--bcher-kva.example", "a" * 63 + ".example.com"):
        assert ask(rig.port, name).header.rcode == RCODE.NOERROR
    assert DNSRecord.parse(DNSRecord(q=DNSQuestion(".")).send("127.0.0.1", rig.port, timeout=3)).header.rcode == RCODE.NOERROR
    assert wait_for(lambda: len(rig.backend.events) == 4)  # the root lookup is answered but not reported
    assert rig.backend.malformed == 0


def test_full_queue_drops_the_oldest(monkeypatch):
    monkeypatch.setattr(tattle_sensor, "QUEUE_MAX", 3)
    sensor = tattle_sensor.Sensor(("127.0.0.1", 9), "http://127.0.0.1:9", None)
    for i in range(5):
        sensor.report("10.42.0.23", f"host{i}.example.com", "A", None)
    assert [event["qname"] for _, event in sensor.queue] == [f"host{i}.example.com" for i in (2, 3, 4)]


def test_dead_upstream_gives_servfail(rig, monkeypatch):
    monkeypatch.setattr(tattle_sensor, "UPSTREAM_TIMEOUT", 0.3)
    rig.sensor.upstream = ("127.0.0.1", free_port())
    assert ask(rig.port, "example.com").header.rcode == RCODE.SERVFAIL
    assert ask(rig.port, "example.com", tcp=True).header.rcode == RCODE.SERVFAIL
    assert ask(rig.port, "mask.icloud.com").header.rcode == RCODE.NXDOMAIN  # blocking needs no upstream


def test_garbage_is_ignored(rig):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(b"\x00not dns", ("127.0.0.1", rig.port))
    assert ask(rig.port, "example.com").header.rcode == RCODE.NOERROR


def test_lease_file_gives_device_names(tmp_path):
    leases = tmp_path / "dnsmasq.leases"
    leases.write_text("1760070000 aa:bb:cc:dd:ee:01 10.42.0.23 Test-iPhone 01:aa:bb:cc:dd:ee:01\n"
                      "1760070000 aa:bb:cc:dd:ee:02 10.42.0.24 * 01:aa:bb:cc:dd:ee:02\n")
    sensor = tattle_sensor.Sensor(("127.0.0.1", 9), "http://127.0.0.1:9", str(leases))
    sensor.report("10.42.0.23", "example.com", "A", None)
    sensor.report("10.42.0.24", "example.com", "A", None)
    assert [event["client_name"] for _, event in sensor.queue] == ["Test-iPhone", None]
    assert tattle_sensor.Leases(str(tmp_path / "missing")).name("10.42.0.23") is None


def test_script_sends_names_only_with_the_names_flag(tmp_path):
    """Runs the real script, so the command-line default is what gets tested."""
    leases = tmp_path / "dnsmasq.leases"
    leases.write_text("1760070000 aa:bb:cc:dd:ee:01 127.0.0.1 Phone-Name *\n")
    for flags, expected in (([], None), (["--names"], "Phone-Name")):
        backend = Backend()
        backend.start()
        port = free_port()
        process = subprocess.Popen(
            [sys.executable, tattle_sensor.__file__, "--listen", f"127.0.0.1:{port}", "--upstream", "127.0.0.1:9",
             "--backend", f"http://127.0.0.1:{backend.port}", "--leases", str(leases), *flags],
            stderr=subprocess.PIPE, text=True)
        try:
            process.stderr.readline()  # "listening on ...": the sockets are open
            assert ("device names off" if expected is None else f"device names from {leases}") in process.stderr.readline()
            assert ask(port, "mask.icloud.com").header.rcode == RCODE.NXDOMAIN  # a guard name needs no upstream
            assert wait_for(lambda: backend.events)
            assert backend.events[0]["client_name"] == expected
        finally:
            process.terminate()
            process.wait(timeout=5)
            backend.stop()


def test_record_writes_anonymized_jsonl(tmp_path):
    leases = tmp_path / "dnsmasq.leases"
    leases.write_text("1760070000 aa:bb:cc:dd:ee:01 10.42.0.23 Real-Phone-Name *\n")
    replay = tmp_path / "replay.jsonl"
    sensor = tattle_sensor.Sensor(("127.0.0.1", 9), "http://127.0.0.1:9", str(leases), record=str(replay))
    sensor.report("10.42.0.23", "example.com", "A", None)
    sensor.report("10.42.0.24", "example.org", "AAAA", None)
    sensor.report("10.42.0.23", "mask.icloud.com", "A", "guard")
    rows = [json.loads(line) for line in replay.read_text().splitlines()]
    assert [row["client_name"] for row in rows] == ["Test iPhone A", "Test iPhone B", "Test iPhone A"]
    assert "Real-Phone-Name" not in replay.read_text()
    assert rows[2]["blocked"] is True and rows[2]["block_reason"] == "guard"
