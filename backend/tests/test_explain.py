"""The detail panel's "who is this company?": the tracker-list sentence, and the AI's text behind it."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from helpers import PHONE, event, fake_ai, post_events, wait_for

from app import explain, main

LIST = "AppLovin: an advertising company, according to our tracker list."


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "ai", None)
    with TestClient(main.app) as client:
        yield client


def ask(client, company, **params):
    return client.get("/api/explain", params={"company": company, **params}).json()


def test_every_category_has_a_sentence_that_never_says_sent():
    from app.kb import CATEGORIES
    assert set(explain.KINDS) == set(CATEGORIES)
    for category in CATEGORIES:
        for listed in (True, False):
            text = explain.fallback("Example", category, listed)
            assert text.startswith("Example: ") and "sent" not in text and "data" not in text
    assert "not on our tracker list" in explain.fallback("Example", "analytics", False)


def test_without_ai_the_list_speaks(client):
    post_events(client, event("ms.applovin.com"), event("rt.applovin.com"), event("gateway.icloud.com"),
                event("mask.icloud.com", blocked=True, block_reason="guard"))
    time.sleep(2.1)  # past the dedupe window: a second lookup of the same name
    post_events(client, event("rt.applovin.com", blocked=True, block_reason="user"))
    body = ask(client, "AppLovin")
    assert body == {"company": "AppLovin", "category": "advertising", "domains": ["rt.applovin.com", "ms.applovin.com"],
                    "text": LIST, "by": "list", "fallback": LIST, "pending": False}
    apple = ask(client, "Apple")  # the guard-list lookup is not a contact to Apple
    assert (apple["category"], apple["domains"]) == ("vendor", ["gateway.icloud.com"])
    assert apple["text"] == "Apple: the phone maker's or the app's own servers, according to our tracker list."
    nobody = ask(client, "Never Seen Inc")
    assert (nobody["domains"], nobody["by"], nobody["pending"]) == ([], "list", False)
    assert "not on our tracker list" in nobody["text"]
    assert main.state.explained == {}


def test_the_lookups_that_count_are_the_sessions(client):
    post_events(client, event("before.applovin.com"), event("other.applovin.com", client_ip="10.42.0.99", client_name=None))
    assert ask(client, "AppLovin")["domains"] == ["before.applovin.com", "other.applovin.com"]
    assert ask(client, "AppLovin", device_id="10.42.0.99")["domains"] == ["other.applovin.com"]
    time.sleep(0.05)
    client.post("/api/session/start", json={"device_id": PHONE, "label": "Demo Game"})
    post_events(client, event("ms.applovin.com"), event("late.applovin.com", client_ip="10.42.0.99", client_name=None))
    assert ask(client, "AppLovin", device_id="10.42.0.99")["domains"] == ["ms.applovin.com"]  # the session's phone, from its start
    client.post("/api/session/stop")
    time.sleep(0.05)
    post_events(client, event("after.applovin.com"))
    assert ask(client, "AppLovin")["domains"] == ["ms.applovin.com"]


def test_bad_input_is_refused(client):
    assert client.get("/api/explain").status_code == 422
    assert client.get("/api/explain", params={"company": "x" * 101}).status_code == 422
    assert client.get("/api/explain", params={"company": "\x00\x07"}).status_code == 422
    assert client.get("/api/explain", params={"company": "Google", "device_id": "<b>"}).status_code == 422


def test_ai_text_arrives_later_and_is_kept(monkeypatch):
    release = asyncio.Event()

    async def slow(company, category, domains):
        await release.wait()
        return "  AppLovin runs an ad network. Here its servers were contacted to pick ads.\x00 "

    calls = fake_ai(monkeypatch, explain=slow)
    monkeypatch.setenv("AI_MODEL", "test-model")
    with TestClient(main.app) as client:
        post_events(client, event("ms.applovin.com"), event("rt.applovin.com"))
        first = ask(client, "AppLovin")  # answered at once, although the AI is still thinking
        assert (first["text"], first["by"], first["pending"]) == (LIST, "list", True)
        assert ask(client, "AppLovin")["pending"] is True and len(calls.explain) == 1  # one question at a time
        assert calls.explain[0] == ("AppLovin", "advertising", ["ms.applovin.com", "rt.applovin.com"])

        client.portal.call(release.set)
        assert wait_for(lambda: ask(client, "AppLovin")["by"] == "test-model")
        body = ask(client, "AppLovin")
        assert body["text"] == "AppLovin runs an ad network. Here its servers were contacted to pick ads."
        assert (body["fallback"], body["pending"]) == (LIST, False)  # the list's sentence stays available
        post_events(client, event("more.applovin.com"))
        assert ask(client, "AppLovin")["by"] == "test-model" and len(calls.explain) == 1  # cached: not asked again
        assert client.get("/api/health").json()["ai"] is True

        assert ask(client, "Never Seen Inc")["pending"] is False and len(calls.explain) == 1  # nothing contacted: nothing to ask
        client.post("/api/wipe")
        assert main.state.explained == {}  # the text was made from captured names: a wipe forgets it


def test_a_new_session_gets_a_new_explanation(monkeypatch):
    async def quick(company, category, domains):
        return f"Seen: {', '.join(domains)}."

    calls = fake_ai(monkeypatch, explain=quick)
    with TestClient(main.app) as client:
        for label, name in (("App One", "one.applovin.com"), ("App Two", "two.applovin.com")):
            client.post("/api/session/start", json={"device_id": PHONE, "label": label})
            post_events(client, event(name))
            ask(client, "AppLovin")
            assert wait_for(lambda: ask(client, "AppLovin")["text"] == f"Seen: {name}.")
        assert len(calls.explain) == 2


@pytest.mark.parametrize("failure", ["none", "raises", "hangs", "not-text"])
def test_ai_failures_leave_the_list_sentence(monkeypatch, failure):
    async def broken(company, category, domains):
        if failure == "raises":
            raise RuntimeError("model server down")
        if failure == "hangs":
            await asyncio.sleep(60)
        return {"text": "wrong shape"} if failure == "not-text" else None

    calls = fake_ai(monkeypatch, explain=broken)
    monkeypatch.setattr(main, "AI_TIMEOUT", 0.05)
    monkeypatch.setattr(main, "AI_RETRY", 60.0)
    with TestClient(main.app) as client:
        post_events(client, event("ms.applovin.com"))
        assert ask(client, "AppLovin")["pending"] is True
        assert wait_for(lambda: ask(client, "AppLovin")["pending"] is False)
        body = ask(client, "AppLovin")
        assert (body["text"], body["by"]) == (LIST, "list") and len(calls.explain) == 1  # no hammering after a failure
        assert client.get("/api/health").json()["ai"] is False
        monkeypatch.setattr(main, "AI_RETRY", 0.0)
        assert ask(client, "AppLovin")["pending"] is True  # asked again once the pause is over
        assert wait_for(lambda: len(calls.explain) == 2)


def test_a_module_without_explain_company_is_fine(monkeypatch):
    calls = fake_ai(monkeypatch)
    with TestClient(main.app) as client:
        post_events(client, event("ms.applovin.com"))
        assert ask(client, "AppLovin") == {"company": "AppLovin", "category": "advertising", "domains": ["ms.applovin.com"],
                                          "text": LIST, "by": "list", "fallback": LIST, "pending": False}
        assert calls.explain == []


def test_explanations_are_bounded(monkeypatch):
    async def quick(company, category, domains):
        return "A sentence."

    fake_ai(monkeypatch, explain=quick)
    monkeypatch.setattr(main, "MAX_EXPLAINED", 1)
    with TestClient(main.app) as client:
        post_events(client, event("ms.applovin.com"), event("googleads.g.doubleclick.net"))
        ask(client, "AppLovin")
        assert ask(client, "Google")["pending"] is False and len(main.state.explained) == 1
