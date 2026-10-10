"""What a curious judge might try: hostile names from a phone, oversized requests, other websites."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import PHONE, event, post_events, until
from starlette.websockets import WebSocketDisconnect

from app import main

APP = Path(main.__file__).parent
FOREIGN = {"Origin": "https://evil.example"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "ai", None)
    with TestClient(main.app) as client:
        yield client


SINKS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
         "srcdoc", "javascript:", "setAttribute(")


def test_pages_never_build_markup_from_data():
    for page in ("debug.html", "present.html"):
        source = (APP / page).read_text()
        for sink in SINKS:
            assert sink not in source, f"{page} uses {sink}"
        assert "textContent" in source and " on" + "click=" not in source and " style=" not in source


def test_show_screen_never_builds_markup_from_data():
    script, markup = (main.FRONTEND / "app.js").read_text(), (main.FRONTEND / "index.html").read_text()
    for sink in SINKS:
        assert sink not in script and sink not in markup, f"the show screen uses {sink}"
    assert "textContent" in script
    # Nothing inline and nothing from another server: the policy would stop it, and the demo runs offline.
    assert "<style" not in markup and " style=" not in markup and not re.search(r"\son\w+=", markup)
    assert re.findall(r"<script[^>]*>", markup) == ['<script src="app.js">']
    for source in (script, markup, (main.FRONTEND / "app.css").read_text()):
        assert "http://" not in source.replace("http://www.w3.org/2000/svg", "") and "https://" not in source


def test_logo_page_is_plain_markup():
    """The logo preview at /logo: drawings and a stylesheet, no script at all."""
    markup, style = (main.FRONTEND / "logo" / "index.html").read_text(), (main.FRONTEND / "logo" / "logo.css").read_text()
    assert "<script" not in markup and "<style" not in markup and " style=" not in markup and not re.search(r"\son\w+=", markup)
    for source in (markup, style):
        assert "http://" not in source and "https://" not in source and "url(" not in source


def test_show_screen_loads_only_from_this_backend(client):
    for path in ("/", "/app.js", "/app.css"):
        policy = client.get(path).headers["content-security-policy"]
        assert "default-src 'none'" in policy and "script-src 'self'" in policy and "unsafe" not in policy
        assert "connect-src 'self' ws://testserver wss://testserver;" in policy and "frame-ancestors 'self'" in policy
        assert "img-src 'self' data:;" in policy  # the tab icon is drawn from the page's own logo; nothing else is loosened
    assert "ws://" not in client.get("/", headers={"Host": "bad host\"; script-src *"}).headers["content-security-policy"]
    logo = client.get("/logo/")
    assert logo.status_code == 200 and "script-src 'self'" in logo.headers["content-security-policy"]
    assert client.get("/logo", follow_redirects=False).headers["location"].endswith("/logo/")


def test_pages_run_only_their_own_script(client):
    for path in ("/debug", "/present"):
        response = client.get(path)
        policy = response.headers["content-security-policy"]
        nonce = re.search(r"script-src 'nonce-([\w-]{16,})'", policy).group(1)
        assert f'<script nonce="{nonce}">' in response.text and f'<style nonce="{nonce}">' in response.text
        assert "default-src 'none'" in policy and "unsafe-inline" not in policy and "frame-ancestors 'self'" in policy
        assert "connect-src 'self' ws://testserver wss://testserver;" in policy
        assert client.get(path).headers["content-security-policy"] != policy  # a fresh nonce for every response
    assert "Reads server names only, never content." in client.get("/present").text
    assert "ws://" not in client.get("/debug", headers={"Host": "bad host\"; script-src *"}).headers["content-security-policy"]


def test_every_response_forbids_content_sniffing(client):
    for response in (client.get("/api/health"), client.get("/debug"), client.post("/api/wipe"), client.get("/api/nothing-here")):
        assert response.headers["x-content-type-options"] == "nosniff"


def test_hostile_names_never_reach_clients(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        post_events(client, event("x<img src=x onerror=alert(1)>.example.com"), event("evil\x00.example.com"),
                    event("ms.applovin.com"))
        assert until(ws, "hit")["domain"] == "ms.applovin.com"
    state = client.get("/api/state").json()
    assert [h["domain"] for h in state["hits"]] == ["ms.applovin.com"] and state["health"]["malformed"] == 2
    assert client.post("/api/events", json={"events": [], "malformed": 5}).status_code == 200  # the sensor's own count
    assert client.get("/api/health").json()["malformed"] == 7


def test_request_limits(client):
    assert client.post("/api/events", json={"events": [event("a.example.com")] * 2001}).status_code == 422
    assert client.post("/api/events", json={"events": [], "malformed": -1}).status_code == 422
    assert client.post("/api/events", json={"events": [event("a" * 2000)]}).status_code == 422
    big = client.post("/api/block", content=b'{"company": "' + b"x" * (1024 * 1024) + b'"}',
                      headers={"Content-Type": "application/json"})
    assert big.status_code == 413 and big.json() == {"detail": "request body too large"}
    assert client.post("/api/block", content=b"{}", headers={"Content-Length": "banana"}).status_code in (400, 413)
    assert client.post("/api/block", json={"company": "x" * 101}).status_code == 422
    assert client.post("/api/block", json={"domain": "not a host name"}).status_code == 422
    assert client.post("/api/block", json={"domain": "<script>.example.com"}).status_code == 422
    assert client.post("/api/devices/not-an-address", json={"name": "x"}).status_code == 422
    assert client.post(f"/api/devices/{PHONE}", json={"name": "x" * 65}).status_code == 422
    assert client.post("/api/session/start", json={"device_id": "<b>", "label": "x"}).status_code == 422
    assert client.post("/api/session/start", json={"device_id": PHONE, "label": "x" * 101}).status_code == 422
    assert client.get("/api/label-check", params={"app": "x" * 101}).status_code == 422
    assert client.get("/api/history/sessions", params={"limit": "many"}).status_code == 422
    state = client.get("/api/state").json()
    assert (state["devices"], state["session"], state["blocked"]) == ([], None, {"companies": [], "domains": [], "covers": {}})


def test_block_list_is_bounded(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_BLOCKED", 3)
    for i in range(3):
        assert client.post("/api/block", json={"domain": f"d{i}.example.com"}).status_code == 200
    assert client.post("/api/block", json={"company": "One More"}).status_code == 422
    assert client.post("/api/unblock", json={"domain": "d0.example.com"}).status_code == 200  # unblocking always works
    assert client.post("/api/block", json={"company": "One More"}).status_code == 200


def test_text_typed_by_people_stays_text(client):
    name = "<img src=x onerror=alert(1)>"
    device = client.post(f"/api/devices/{PHONE}", json={"name": name + "\x00\x1b"}).json()
    assert device["name"] == name  # kept as typed, minus control characters; the pages show it as text
    session = client.post("/api/session/start", json={"device_id": PHONE, "label": " <b>App</b>\n"}).json()["session"]
    assert session["label"] == "<b>App</b>"
    assert client.post("/api/block", json={"company": "\x00\x07"}).status_code == 422  # nothing printable: nothing to block


def test_other_websites_cannot_write_or_listen(client):
    for path in ("/api/wipe", "/api/session/stop", "/api/history/clear"):
        response = client.post(path, headers=FOREIGN)
        assert response.status_code == 403 and response.json() == {"detail": "cross-site request refused"}
    assert client.post("/api/block", json={"company": "X"}, headers=FOREIGN).status_code == 403
    assert client.post("/api/events", json={"events": [event("ms.applovin.com")]}, headers=FOREIGN).status_code == 403
    assert client.post("/api/wipe", headers={"Origin": "null"}).status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers=FOREIGN):
            pass
    state = client.get("/api/state", headers=FOREIGN)  # reading is left to the browser's same-origin rule
    assert state.status_code == 200 and "access-control-allow-origin" not in state.headers
    assert state.json()["blocked"]["companies"] == [] and state.json()["hits"] == []
    # the page's own origin, and a dev server on this machine, are fine
    assert client.post("/api/wipe", headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/api/wipe", headers={"Origin": "http://localhost:5173"}).status_code == 200
    with client.websocket_connect("/ws", headers={"Origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "snapshot"


def test_websocket_clients_are_capped(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_CLIENTS", 2)
    with client.websocket_connect("/ws") as first, client.websocket_connect("/ws") as second:
        first.receive_json(), second.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass
    with client.websocket_connect("/ws") as again:  # a place is free again once someone leaves
        assert again.receive_json()["type"] == "snapshot"


def test_sql_takes_values_only_as_parameters():
    """Every statement in db.py is a constant string; the only thing spliced in is our own SEEN constant."""
    source = (APP / "db.py").read_text()
    statements = [line for line in source.splitlines() if re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FILTER)\b", line)
                  and line.lstrip().startswith(('"', 'f"', "self._put(", "sessions =", "top =", "labels =", "companies =", "rows ="))]
    assert len(statements) > 20
    assert {found for line in statements for found in re.findall(r"\{[^}]*\}", line)} <= {"{SEEN}"}
    assert "%s" in source and ".format(" not in source and '" %' not in source and "+ sql" not in source
