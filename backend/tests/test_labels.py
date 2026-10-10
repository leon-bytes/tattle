"""Privacy-label fact-check: the rules, and the endpoint."""
import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import PHONE, event, fake_ai, post_events, wait_for

from app import labels, main

LABELS = Path(__file__).parent / "fixtures" / "labels"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "ai", None)
    with TestClient(main.app) as client:
        yield client


def seen(advertising=0, tracking=0):
    return {"advertising_companies": advertising, "tracking_companies": tracking}


def test_labels_are_found_by_app_name_or_file_name():
    assert labels.find_label(LABELS, "Demo Game")["app"] == "Demo Game"
    assert labels.find_label(LABELS, "  demo GAME!")["app"] == "Demo Game"
    assert labels.find_label(LABELS, "quiet-notes")["app"] == "Quiet Notes"
    assert labels.find_label(LABELS, "broken") is None  # unreadable files are skipped
    assert labels.find_label(LABELS, "Nothing Like It") is None
    assert labels.find_label(LABELS, "") is None
    assert labels.find_label(LABELS / "missing-folder", "Demo Game") is None


@pytest.mark.parametrize("label, observed, level, text", [
    ({"data_not_collected": True}, seen(0, 2), "mismatch",
     "The label says no data is collected, but this session contacted 2 tracking companies."),
    ({"data_not_collected": True}, seen(0, 0), "consistent",
     "The label says no data is collected, and this session contacted no known tracking companies."),
    ({"data_used_to_track_you": []}, seen(1, 3), "mismatch",
     'The label lists nothing under "Data Used to Track You", but this session contacted 1 advertising company.'),
    ({"data_used_to_track_you": []}, seen(0, 3), "consistent",
     'The label lists nothing under "Data Used to Track You", and this session contacted no known advertising companies.'),
    ({"data_used_to_track_you": ["Identifiers", "Usage Data"]}, seen(4, 6), "consistent",
     "The label declares tracking (Identifiers, Usage Data), and this session contacted 4 advertising companies."),
    ({"data_used_to_track_you": ["A", "B", "C", "D"]}, seen(0, 0), "consistent",
     "The label declares tracking (A, B, C and more); this session contacted no known advertising companies so far."),
])
def test_verdict_rules(label, observed, level, text):
    assert labels.verdict(label, observed) == (level, text)
    assert "sent" not in text and "contacted" in text


def test_no_session_yet(client):
    body = client.get("/api/label-check").json()
    assert (body["session"], body["label"], body["observed"], body["level"]) == (None, None, None, "no-session")


def test_label_next_to_what_the_session_contacted(client):
    post_events(client, event("before.doubleclick.net"))  # before the session: not counted
    time.sleep(0.05)
    client.post("/api/session/start", json={"device_id": PHONE, "label": "Demo Game"})
    post_events(client,
                event("googleads.g.doubleclick.net"), event("pagead2.googlesyndication.com"), event("app-measurement.com"),
                event("ms.applovin.com", blocked=True, block_reason="user"), event("graph.facebook.com"),
                event("gateway.icloud.com"), event("odd.example.io"),
                event("mask.icloud.com", blocked=True, block_reason="guard"),
                event("ms.applovin.com", client_ip="10.42.0.99", client_name=None))  # another phone
    body = client.get("/api/label-check").json()
    assert body["label"]["app"] == "Demo Game" and body["label"]["data_linked_to_you"] == ["Identifiers", "Usage Data"]
    assert body["session"]["label"] == "Demo Game" and body["session"]["stopped"] is None
    assert body["observed"] == {
        "seconds": body["observed"]["seconds"], "lookups": 7, "blocked": 1, "hidden_attempts": 1,
        "by_category": {"advertising": 3, "analytics": 1, "social": 1, "vendor": 1, "unknown": 1},
        "companies": [{"company": "Google", "category": "advertising", "hits": 3},
                      {"company": "AppLovin", "category": "advertising", "hits": 1},
                      {"company": "Apple", "category": "vendor", "hits": 1},
                      {"company": "Meta", "category": "social", "hits": 1}],
        "advertising_companies": 2, "tracking_companies": 3}
    assert (body["level"], body["verdict"]) == (
        "mismatch", 'The label lists nothing under "Data Used to Track You", but this session contacted 2 advertising companies.')
    assert body["note"] == "Tattle sees which servers a phone looks up, not what is sent to them."
    assert (body["verdict_by"], body["rule_verdict"]) == ("rules", body["verdict"])  # no AI: the rules speak

    client.post("/api/session/stop")
    time.sleep(0.05)
    post_events(client, event("after.doubleclick.net"), event("rt.applovin.com"))  # after the session: not counted
    stopped = client.get("/api/label-check").json()
    assert stopped["session"]["stopped"] >= stopped["session"]["started"]
    assert stopped["observed"]["lookups"] == 7 and stopped["verdict"] == body["verdict"]

    other = client.get("/api/label-check", params={"app": "honest-game"}).json()  # another label, same session
    assert (other["level"], other["verdict"]) == (
        "consistent", "The label declares tracking (Identifiers, Usage Data, Location and more), "
                      "and this session contacted 2 advertising companies.")
    quiet = client.get("/api/label-check", params={"app": "Quiet Notes"}).json()
    assert (quiet["level"], quiet["verdict"]) == (
        "mismatch", "The label says no data is collected, but this session contacted 3 tracking companies.")


def test_session_without_a_matching_label(client):
    client.post("/api/session/start", json={"device_id": PHONE, "label": "Some Other App"})
    post_events(client, event("ms.applovin.com"))
    body = client.get("/api/label-check").json()
    assert (body["level"], body["label"], body["verdict"]) == ("no-label", None, "No privacy label on file for Some Other App.")
    assert body["observed"]["lookups"] == 1
    client.post("/api/session/start", json={"device_id": PHONE, "label": None})
    assert client.get("/api/label-check").json()["verdict"] == "No privacy label on file for this session (it has no app name)."
    client.post("/api/wipe")
    assert client.get("/api/label-check").json()["level"] == "no-session"


RULE = 'The label lists nothing under "Data Used to Track You", but this session contacted 1 advertising company.'


def start_demo_game(client):
    client.post("/api/session/start", json={"device_id": PHONE, "label": "Demo Game"})
    post_events(client, event("ms.applovin.com"))


def test_ai_sentence_becomes_the_verdict_and_the_endpoint_never_waits(monkeypatch):
    release = asyncio.Event()

    async def slow(label, stats):
        await release.wait()
        return "  The label is silent on tracking, yet an ad company was contacted.\x00 "

    calls = fake_ai(monkeypatch, label_check=slow)
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(main, "LABEL_AI_SECONDS", 0.0)
    with TestClient(main.app) as client:
        start_demo_game(client)
        first = client.get("/api/label-check").json()  # answered at once, although the AI is still thinking
        assert (first["verdict"], first["verdict_by"], first["rule_verdict"], first["level"]) == (RULE, "rules", RULE, "mismatch")
        assert client.get("/api/label-check").json()["verdict_by"] == "rules"
        assert len(calls.label_check) == 1  # one question at a time
        label, stats = calls.label_check[0]
        assert label["app"] == "Demo Game" and stats["label"] == "Demo Game" and stats["by_category"] == {"advertising": 1}

        client.portal.call(release.set)
        assert wait_for(lambda: client.get("/api/label-check").json()["verdict_by"] == "test-model")
        body = client.get("/api/label-check").json()
        assert body["verdict"] == "The label is silent on tracking, yet an ad company was contacted."
        assert (body["rule_verdict"], body["level"]) == (RULE, "mismatch")  # the facts line stays
        assert len(calls.label_check) == 1  # nothing new was looked up: the sentence is reused, the model is not asked again

        post_events(client, event("googleads.g.doubleclick.net"))
        client.get("/api/label-check")
        assert wait_for(lambda: len(calls.label_check) == 2)  # the picture changed: ask again
        client.post("/api/wipe")
        assert client.get("/api/label-check").json()["level"] == "no-session"


@pytest.mark.parametrize("failure", ["none", "raises", "hangs", "not-text"])
def test_ai_label_failures_leave_the_rule_verdict(monkeypatch, failure):
    async def broken(label, stats):
        if failure == "raises":
            raise RuntimeError("model server down")
        if failure == "hangs":
            await asyncio.sleep(60)
        return {"verdict": "wrong shape"} if failure == "not-text" else None

    calls = fake_ai(monkeypatch, label_check=broken)
    monkeypatch.setattr(main, "AI_TIMEOUT", 0.05)
    monkeypatch.setattr(main, "LABEL_AI_SECONDS", 0.0)
    with TestClient(main.app) as client:
        start_demo_game(client)
        client.get("/api/label-check")
        assert wait_for(lambda: main.state.label_ai is not None and not main.state.label_ai["busy"])
        body = client.get("/api/label-check").json()
        assert (body["verdict"], body["verdict_by"]) == (RULE, "rules") and calls.label_check
        assert client.get("/api/health").json()["ai"] is False


def test_ai_label_check_is_optional_and_rate_limited(monkeypatch):
    fake_ai(monkeypatch)  # a module without label_check: fine
    with TestClient(main.app) as client:
        start_demo_game(client)
        assert client.get("/api/label-check").json()["verdict_by"] == "rules"

    async def quick(label, stats):
        return "An AI sentence."

    calls = fake_ai(monkeypatch, label_check=quick)
    with TestClient(main.app) as client:  # LABEL_AI_SECONDS at its default of 10
        start_demo_game(client)
        client.get("/api/label-check")
        assert wait_for(lambda: client.get("/api/label-check").json()["verdict"] == "An AI sentence.")
        for i in range(5):
            post_events(client, event(f"more{i}.applovin.com"))
            client.get("/api/label-check")
        assert len(calls.label_check) == 1  # new lookups, but not more than one question per 10 s
        other = client.get("/api/label-check", params={"app": "No Such App"}).json()
        assert (other["level"], other["verdict_by"]) == ("no-label", "rules") and len(calls.label_check) == 1
