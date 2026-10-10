"""The HTTP and WebSocket surface, through FastAPI's test client."""
import asyncio
import importlib.util
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from helpers import PHONE, event, fake_ai, post_events, until

from app import main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "ai", None)
    with TestClient(main.app) as client:
        yield client


def test_this_checkout_has_no_ai_module_and_still_imports():
    if importlib.util.find_spec("app.ai") is None:
        assert main.load_ai() is None


def test_snapshot_then_live_hits(client):
    with client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert (snapshot["devices"], snapshot["hits"], snapshot["session"]) == ([], [], None)
        assert snapshot["blocked"] == {"companies": [], "domains": [], "covers": {}}
        assert snapshot["health"] == {"db": False, "db_error": None, "ai": False, "sensor_seen": None, "kb": 28, "malformed": 0, "ai_endpoint": None}

        assert post_events(client, event("googleads.g.doubleclick.net", 1000.0),
                           event("googleads.g.doubleclick.net", 1000.01, qtype="AAAA"),
                           event("gateway.icloud.com", 1000.5),
                           event("odd.example.io", 1001.0)) == {"accepted": 4}
        assert until(ws, "device") == {"type": "device", "device_id": PHONE, "name": "Test iPhone A", "persist": False}
        google = until(ws, "hit")
        assert google == {"type": "hit", "device_id": PHONE, "domain": "googleads.g.doubleclick.net",
                          "company": "Google", "category": "advertising", "source": "list",
                          "blocked": False, "block_reason": None, "ts": google["ts"]}
        apple = until(ws, "hit")
        assert (apple["company"], apple["category"], apple["source"]) == ("Apple", "vendor", "override")
        odd = until(ws, "hit")
        assert (odd["company"], odd["category"], odd["source"]) == (None, "unknown", "unknown")
        # The sensor's clock (here: year 1970) is replaced by ours; the spacing between events is kept.
        assert abs(odd["ts"] - time.time()) < 5
        assert (round(apple["ts"] - google["ts"], 3), round(odd["ts"] - apple["ts"], 3)) == (0.5, 0.5)

    with client.websocket_connect("/ws") as ws:  # a late joiner gets it all in the snapshot
        snapshot = ws.receive_json()
        assert [h["domain"] for h in snapshot["hits"]] == ["googleads.g.doubleclick.net", "gateway.icloud.com", "odd.example.io"]
        assert snapshot["devices"] == [{"device_id": PHONE, "name": "Test iPhone A", "persist": False}]
    assert client.get("/api/state").json()["hits"] == snapshot["hits"]


def test_bad_event_payload_is_rejected(client):
    assert client.post("/api/events", json={"events": [{"qname": "x.example.com"}]}).status_code == 422
    assert client.get("/api/state").json()["hits"] == []


def test_block_and_unblock(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        before = client.get("/api/blocklist").json()
        assert before["domains"] == []
        assert client.post("/api/block", json={"company": "AppLovin"}).status_code == 200
        blocked = client.post("/api/block", json={"company": "Nobody Knows"}).json()
        assert blocked["covers"] == {"AppLovin": ["applovin.com", "applvn.com"], "Nobody Knows": []}  # says what each block covers
        client.post("/api/unblock", json={"company": "Nobody Knows"})
        assert until(ws, "blocked") == {"type": "blocked", "companies": ["AppLovin"], "domains": [],
                                        "covers": {"AppLovin": ["applovin.com", "applvn.com"]}}
        until(ws, "blocked"), until(ws, "blocked")  # the block and unblock of "Nobody Knows"
        client.post("/api/block", json={"domain": "odd.example.io"})
        assert until(ws, "blocked")["domains"] == ["odd.example.io"]
        blocklist = client.get("/api/blocklist").json()
        assert blocklist["domains"] == ["applovin.com", "applvn.com", "odd.example.io"]
        assert blocklist["version"] > before["version"]
        client.post("/api/unblock", json={"company": "AppLovin"})
        assert until(ws, "blocked") == {"type": "blocked", "companies": [], "domains": ["odd.example.io"], "covers": {}}
        assert client.get("/api/blocklist").json()["domains"] == ["odd.example.io"]
    assert client.post("/api/block", json={}).status_code == 422


def test_devices_are_numbered_unless_the_sensor_sends_names(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        post_events(client, event("apple.com", client_name=None), event("apple.com", client_ip="10.42.0.24", client_name=None))
        assert until(ws, "device") == {"type": "device", "device_id": PHONE, "name": "Device 1", "persist": False}
        assert until(ws, "device") == {"type": "device", "device_id": "10.42.0.24", "name": "Device 2", "persist": False}
        client.post("/api/devices/10.42.0.24", json={"name": "Lab phone"})
        assert until(ws, "device")["name"] == "Lab phone"
        client.post("/api/wipe")
        post_events(client, event("apple.com", client_ip="10.42.0.30", client_name=None))
        assert until(ws, "device")["name"] == "Device 1"  # numbering starts over after a wipe


def test_the_box_testing_itself_is_not_a_phone(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        post_events(client, event("example.com", client_ip="127.0.0.1", client_name=None))  # the checklist's self-test lookup
        assert until(ws, "device") == {"type": "device", "device_id": "127.0.0.1", "name": "box self-test", "persist": False}
        post_events(client, event("apple.com", client_name=None))
        assert until(ws, "device")["name"] == "Device 1"  # the first real phone is still number one


def test_device_rename_and_persist(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        post_events(client, event("apple.com"))
        until(ws, "device")
        client.post(f"/api/devices/{PHONE}", json={"name": "Lab phone", "persist": True})
        assert until(ws, "device") == {"type": "device", "device_id": PHONE, "name": "Lab phone", "persist": True}
        client.post(f"/api/devices/{PHONE}", json={"persist": False})
        assert until(ws, "device")["name"] == "Lab phone"


def test_session_start_stop_gives_a_template_summary(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post("/api/session/start", json={"device_id": PHONE, "label": "Demo Game"})
        session = until(ws, "session")["session"]
        assert session["device_id"] == PHONE and session["label"] == "Demo Game"
        assert abs(session["started"] - time.time()) < 5
        post_events(client, event("ms.applovin.com"), event("app-measurement.com"))
        assert client.post("/api/session/stop").status_code == 200
        assert until(ws, "session") == {"type": "session", "session": None}
        summary = until(ws, "summary")
        assert summary["by"] == "template" and summary["device_id"] == PHONE
        assert summary["text"].endswith("Demo Game contacted 2 companies: 1 advertising (AppLovin), 1 analytics (Google).")
    assert client.get("/api/state").json()["summary"] == summary
    assert client.post("/api/session/stop").status_code == 200  # stopping twice is harmless


def test_live_summary_while_a_session_runs(client, monkeypatch):
    monkeypatch.setattr(main, "SUMMARY_SECONDS", 1)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post("/api/session/start", json={"device_id": PHONE, "label": None})
        post_events(client, event("ms.applovin.com"))
        assert until(ws, "summary")["text"].endswith("this phone contacted 1 company: 1 advertising (AppLovin).")


def test_wipe(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        post_events(client, event("ms.applovin.com"))
        client.post("/api/block", json={"company": "AppLovin"})
        client.post("/api/session/start", json={"device_id": PHONE, "label": "Demo Game"})
        assert client.post("/api/wipe").json() == {"type": "wiped"}
        assert until(ws, "wiped") == {"type": "wiped"}
        assert until(ws, "blocked") == {"type": "blocked", "companies": [], "domains": [], "covers": {}}
        assert until(ws, "session") == {"type": "session", "session": None}
    state = client.get("/api/state").json()
    assert (state["devices"], state["hits"], state["session"], state["summary"]) == ([], [], None, None)
    assert client.get("/api/blocklist").json()["domains"] == []


def test_history_needs_a_database(client):
    for response in (client.get("/api/history/sessions"), client.get("/api/history/top-companies"),
                     client.post("/api/history/clear")):
        assert response.status_code == 503 and response.json() == {"detail": "no database configured"}


def test_seeded_ai_answers_apply_from_the_start(client):
    post_events(client, event("seeded.example.io"), event("mixed.case.example.io"), event("useless.example.io"))
    found = {h["domain"]: (h["company"], h["category"], h["source"]) for h in client.get("/api/state").json()["hits"]}
    assert found == {"seeded.example.io": ("Example Seed", "analytics", "ai"),
                     "mixed.case.example.io": ("Example Seed", "advertising", "ai"),
                     "useless.example.io": (None, "unknown", "unknown")}
    client.post("/api/wipe")
    post_events(client, event("seeded.example.io"))
    assert client.get("/api/state").json()["hits"][0]["source"] == "ai"  # the seed is not captured data: it survives a wipe


def test_health_tracks_the_sensor(client):
    assert client.get("/api/health").json() == {"db": False, "db_error": None, "ai": False, "sensor_seen": None, "kb": 28, "malformed": 0, "ai_endpoint": None}
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.get("/api/blocklist")  # the sensor's poll is its heartbeat
        health = until(ws, "health")
        assert abs(health["sensor_seen"] - time.time()) < 5
        assert (health["db"], health["ai"]) == (False, False)


class ModelServer:
    """A stand-in for the model server behind AI_BASE_URL: answers GET /v1/models like an OpenAI-style API."""

    def __init__(self):
        outer = self
        self.authorization = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.authorization.append(self.headers.get("Authorization"))
                body = b'{"object": "list", "data": [{"id": "test-model"}]}' if self.path == "/v1/models" else b"{}"
                self.send_response(200 if self.path == "/v1/models" else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def test_health_shows_whether_the_ai_endpoint_answers(monkeypatch):
    server = ModelServer()
    monkeypatch.setattr(main, "ai", None)  # no ai.py needed: this watches the server, not the module
    monkeypatch.setattr(main, "AI_PROBE_SECONDS", 0.05)
    monkeypatch.setenv("AI_BASE_URL", server.url + "/")
    monkeypatch.setenv("AI_TOKEN", "unused")  # the placeholder for a server that needs no key
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert until(ws, "health")["ai_endpoint"] is True
        assert server.authorization[0] == "Bearer unused"
        server.stop()  # the tunnel drops
        while until(ws, "health")["ai_endpoint"] is not False:
            pass
        assert client.get("/api/health").json()["ai"] is False  # "ai" still means: the last call of ai.py worked
        post_events(client, event("ms.applovin.com"))  # and the live loop does not care
        assert until(ws, "hit")["company"] == "AppLovin"


@pytest.mark.parametrize("url", ["http://127.0.0.1:9/v1", "not a url"])
def test_unreachable_or_nonsense_ai_endpoint_is_just_false(monkeypatch, url):
    monkeypatch.setattr(main, "ai", None)
    monkeypatch.setenv("AI_BASE_URL", url)
    monkeypatch.delenv("AI_TOKEN", raising=False)
    with TestClient(main.app) as client:
        deadline = time.time() + 5
        while client.get("/api/health").json()["ai_endpoint"] is None and time.time() < deadline:
            time.sleep(0.02)
        assert client.get("/api/health").json()["ai_endpoint"] is False


def test_pages(client):
    page = client.get("/debug")
    assert page.status_code == 200 and "Reads server names only, never content." in page.text
    if not main.DIST.is_dir():
        assert client.get("/", follow_redirects=False).headers["location"] == "/debug"


def test_missing_kb_files_still_run(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "ai", None)
    monkeypatch.setenv("KB_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setenv("KB_OVERRIDES_PATH", str(tmp_path / "nope2.json"))
    with TestClient(main.app) as client:
        post_events(client, event("googleads.g.doubleclick.net"))
        state = client.get("/api/state").json()
        assert state["health"]["kb"] == 0 and state["hits"][0]["category"] == "unknown"


def test_ai_classifies_unknown_names_in_the_background(monkeypatch):
    async def classify(domains):
        return {d: {"company": "Example Analytics", "category": "analytics", "confidence": 0.7} for d in domains}

    calls = fake_ai(monkeypatch, classify=classify)
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        post_events(client, event("odd.example.io"), event("ms.applovin.com"))
        assert until(ws, "hit")["source"] == "unknown"  # the hit is on screen before the AI answers
        assert until(ws, "classified") == {"type": "classified", "domain": "odd.example.io",
                                           "company": "Example Analytics", "category": "analytics",
                                           "source": "ai", "confidence": 0.7}
        assert calls.classify == [["odd.example.io"]]  # names the kb knows are never sent
        state = client.get("/api/state").json()
        assert state["health"]["ai"] is True
        assert [h["source"] for h in state["hits"]] == ["ai", "list"]


def test_ai_summary_replaces_the_template(monkeypatch):
    async def summarize(stats):
        return "A friendlier sentence."

    calls = fake_ai(monkeypatch, summarize=summarize)
    monkeypatch.setenv("AI_MODEL", "test-model")
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post("/api/session/start", json={"device_id": PHONE, "label": "Demo Game"})
        post_events(client, event("ms.applovin.com"))
        client.post("/api/session/stop")
        assert until(ws, "summary")["by"] == "template"
        assert until(ws, "summary") == {"type": "summary", "device_id": PHONE, "text": "A friendlier sentence.",
                                        "by": "test-model"}
        assert calls.summarize[0]["by_category"] == {"advertising": 1}


@pytest.mark.parametrize("failure", ["none", "raises", "hangs"])
def test_ai_failures_only_flip_health(monkeypatch, failure):
    async def broken(_):
        if failure == "raises":
            raise RuntimeError("model server down")
        if failure == "hangs":
            await asyncio.sleep(60)
        return None

    calls = fake_ai(monkeypatch, classify=broken, summarize=broken)
    monkeypatch.setattr(main, "AI_TIMEOUT", 0.05)
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post("/api/session/start", json={"device_id": PHONE, "label": None})
        post_events(client, event("odd.example.io"))
        assert until(ws, "hit")["domain"] == "odd.example.io"
        client.post("/api/session/stop")
        assert until(ws, "summary")["by"] == "template"
        deadline = time.time() + 3
        while len(calls.classify) < 2 and time.time() < deadline:  # it retries, and the app keeps serving
            time.sleep(0.02)
        assert len(calls.classify) >= 2 and calls.summarize
        state = client.get("/api/state").json()
        assert state["health"]["ai"] is False
        assert state["summary"]["by"] == "template" and state["hits"][0]["source"] == "unknown"


def test_late_ai_answer_after_a_wipe_is_dropped(monkeypatch):
    release = asyncio.Event()

    async def classify(domains):
        await release.wait()
        return {d: {"company": "Example Analytics", "category": "analytics", "confidence": 0.7} for d in domains}

    calls = fake_ai(monkeypatch, classify=classify)
    with TestClient(main.app) as client:
        post_events(client, event("odd.example.io"))
        deadline = time.time() + 3
        while not calls.classify and time.time() < deadline:
            time.sleep(0.02)
        client.post("/api/wipe")
        client.portal.call(release.set)
        time.sleep(0.2)
        assert "odd.example.io" not in main.state.ai_results and client.get("/api/state").json()["hits"] == []
