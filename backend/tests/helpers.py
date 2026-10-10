"""Shared by the API and database tests."""
import time
from types import SimpleNamespace

from app import main

PHONE = "10.42.0.23"


def event(qname, ts=None, **extra):
    return {"ts": ts or time.time(), "client_ip": PHONE, "client_name": "Test iPhone A", "qname": qname,
            "qtype": "A", "blocked": False, "block_reason": None, **extra}


def post_events(client, *events):
    response = client.post("/api/events", json={"events": list(events)})
    assert response.status_code == 200
    return response.json()


def until(ws, kind):
    """The next message of the given type (health and summary messages may be interleaved)."""
    while True:
        message = ws.receive_json()
        if message["type"] == kind:
            return message


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def fake_ai(monkeypatch, classify=None, summarize=None, label_check=None):
    """Stand in for backend/app/ai.py, which belongs to the AI owner."""
    calls = SimpleNamespace(classify=[], summarize=[], label_check=[])

    async def classify_domains(domains):
        calls.classify.append(domains)
        return await classify(domains) if classify else None

    async def summarize_stats(stats):
        calls.summarize.append(stats)
        return await summarize(stats) if summarize else None

    module = SimpleNamespace(classify_domains=classify_domains, summarize=summarize_stats)
    if label_check:  # optional in the contract: only there when a test asks for it
        async def check(label, stats):
            calls.label_check.append((label, stats))
            return await label_check(label, stats)
        module.label_check = check
    monkeypatch.setattr(main, "ai", module)
    monkeypatch.setattr(main, "AI_POLL", 0.01)
    monkeypatch.setattr(main, "AI_RETRY", 0.01)
    return calls
