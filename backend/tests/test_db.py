"""The Postgres layer, against a real server.

The tests that need one are skipped unless TEST_DATABASE_URL is set (see backend/README.md).
Each test works in its own throwaway schema, so tables in the default schema are never touched.
"""
import asyncio
import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from helpers import PHONE, event, fake_ai, post_events, until, wait_for

from app import db as db_module
from app import main

BASE_URL = os.environ.get("TEST_DATABASE_URL")
GUEST = "10.42.0.99"


@pytest.fixture
def database(monkeypatch):
    """A connection to a fresh schema; the backend under test is pointed at the same schema."""
    if not BASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    import psycopg
    from psycopg.rows import dict_row

    schema = f"tattle_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    url = BASE_URL + ("&" if "?" in BASE_URL else "?") + f"options=-csearch_path%3D{schema}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(db_module, "RETRY_SECONDS", 0.05)
    try:
        with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
            yield conn
    finally:
        with psycopg.connect(BASE_URL, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def client(database, monkeypatch):
    monkeypatch.setattr(main, "ai", None)
    with TestClient(main.app) as client:
        assert wait_for(lambda: main.state.health["db"])
        yield client


def rows(database, sql, *params):
    return database.execute(sql, params).fetchall()


def column(database, sql, *params):
    return [next(iter(row.values())) for row in rows(database, sql, *params)]


def settle(client):
    """Wait until every queued write is in the database."""
    async def wait():
        for _ in range(500):
            if main.db.conn is not None and not main.db.ops:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("queued database writes did not finish")
    client.portal.call(wait)


def mark(client, name="Test iPhone A"):
    assert client.post(f"/api/devices/{PHONE}", json={"name": name, "persist": True}).status_code == 200


def start(client, label, device_id=PHONE):
    assert client.post("/api/session/start", json={"device_id": device_id, "label": label}).status_code == 200


def stop(client):
    assert client.post("/api/session/stop").status_code == 200


def test_connects_applies_the_schema_and_mirrors_the_kb(client, database):
    assert wait_for(lambda: column(database, "SELECT count(*) FROM kb_domains") == [28])
    assert rows(database, "SELECT company, category, source FROM kb_domains WHERE domain = 'icloud.com'") == [
        {"company": "Apple", "category": "vendor", "source": "override"}]
    assert rows(database, "SELECT company, category, source FROM kb_domains WHERE domain = 'doubleclick.net'") == [
        {"company": "Google", "category": "advertising", "source": "list"}]
    assert client.get("/api/health").json()["db"] is True
    assert client.get("/api/history/sessions").json() == {"sessions": []}
    assert client.get("/api/history/top-companies").json() == {"labels": []}


def test_unmarked_phones_never_reach_the_database(client, database):
    post_events(client, event("a.doubleclick.net"))
    client.post(f"/api/devices/{PHONE}", json={"name": "Renamed, not marked"})
    start(client, "Demo Game")
    post_events(client, event("ms.applovin.com"), event("odd.example.io"))
    stop(client)
    client.post(f"/api/devices/{PHONE}", json={"persist": False})
    settle(client)
    for table in ("devices", "sessions", "hits", "ai_cache"):
        assert column(database, f"SELECT count(*) FROM {table}") == [0], table
    assert len(client.get("/api/state").json()["hits"]) == 3  # it was all there, in memory


def test_a_marked_phone_is_recorded_while_a_session_runs(client, database):
    mark(client)
    post_events(client, event("outside.doubleclick.net"))  # marked, but no session: memory only
    start(client, "Demo Game")
    post_events(client,
                event("googleads.g.doubleclick.net"), event("ms.applovin.com"), event("rt.applovin.com"),
                event("ms.applovin.com", qtype="AAAA"),                       # deduped
                event("d.applovin.com", client_ip=GUEST, client_name=None),   # another phone, not marked
                event("mask.icloud.com", blocked=True, block_reason="guard"),
                event("odd.example.io"),
                event("_dns.resolver.arpa"))                                   # plumbing, dropped
    stop(client)
    post_events(client, event("after.doubleclick.net"))
    settle(client)

    assert column(database, "SELECT domain FROM hits ORDER BY domain") == [
        "googleads.g.doubleclick.net", "mask.icloud.com", "ms.applovin.com", "odd.example.io", "rt.applovin.com"]
    assert rows(database, "SELECT company, category, source, blocked, block_reason FROM hits "
                          "WHERE domain = 'mask.icloud.com'") == [
        {"company": "Apple", "category": "vendor", "source": "override", "blocked": True, "block_reason": "guard"}]
    assert rows(database, "SELECT device_id, name, persist FROM devices") == [
        {"device_id": PHONE, "name": "Test iPhone A", "persist": True}]

    sessions = client.get("/api/history/sessions").json()["sessions"]
    assert len(sessions) == 1
    session = sessions[0]
    assert uuid.UUID(session["id"])
    assert (session["device_id"], session["device_name"], session["label"]) == (PHONE, "Test iPhone A", "Demo Game")
    # the guard-list lookup is stored, but counted apart: not a hit, not a blocked tracker, not an "Apple contact"
    assert (session["hits"], session["blocked"], session["hidden_attempts"], session["companies"]) == (4, 0, 1, 2)
    assert session["top_companies"] == [["AppLovin", 2], ["Google", 1]]
    assert abs(session["started"] - time.time()) < 30 and session["stopped"] >= session["started"]
    # stored hit times are on the backend's clock, inside the session
    assert column(database, "SELECT count(*) FROM hits h JOIN sessions s ON s.id = h.session_id "
                            "WHERE h.ts < s.started - interval '1 second' OR h.ts > s.stopped + interval '1 second'") == [0]


def test_marking_and_unmarking_mid_session(client, database):
    post_events(client, event("a.doubleclick.net"))
    start(client, "Demo Game")
    post_events(client, event("b.doubleclick.net"))  # captured while unmarked: stays in memory for good
    client.post(f"/api/devices/{PHONE}", json={"persist": True})
    post_events(client, event("c.doubleclick.net"))
    client.post(f"/api/devices/{PHONE}", json={"persist": False})
    post_events(client, event("d.doubleclick.net"))
    settle(client)
    assert column(database, "SELECT domain FROM hits") == ["c.doubleclick.net"]
    assert column(database, "SELECT stopped IS NOT NULL FROM sessions") == [True]  # recording ended at the unmark
    started = client.get("/api/state").json()["session"]["started"]  # the session itself is still running
    assert column(database, "SELECT abs(extract(epoch FROM started) - %s) < 0.01 FROM sessions", started) == [True]
    assert column(database, "SELECT persist FROM devices") == [False]


def test_wipe_deletes_the_running_session_only(client, database):
    mark(client)
    start(client, "First app")
    post_events(client, event("one.doubleclick.net"))
    stop(client)
    start(client, "Second app")
    post_events(client, event("two.doubleclick.net"))
    assert client.post("/api/wipe").status_code == 200
    settle(client)
    assert column(database, "SELECT label FROM sessions") == ["First app"]
    assert column(database, "SELECT domain FROM hits") == ["one.doubleclick.net"]
    assert column(database, "SELECT device_id FROM devices") == [PHONE]
    state = client.get("/api/state").json()
    assert (state["devices"], state["hits"], state["session"]) == ([], [], None)
    # after a wipe the phone is an unmarked "Device 1" again: nothing more is stored until it is marked
    post_events(client, event("three.doubleclick.net", client_name=None))
    start(client, "Third app")
    post_events(client, event("four.doubleclick.net", client_name=None))
    stop(client)
    settle(client)
    assert client.get("/api/state").json()["devices"][0] == {"device_id": PHONE, "name": "Device 1", "persist": False}
    assert column(database, "SELECT label FROM sessions") == ["First app"]


def test_wipe_without_a_session_leaves_history_alone(client, database):
    mark(client)
    start(client, "First app")
    post_events(client, event("one.doubleclick.net"))
    stop(client)
    client.post("/api/wipe")
    settle(client)
    assert column(database, "SELECT label FROM sessions") == ["First app"]
    assert column(database, "SELECT count(*) FROM hits") == [1]


def test_starting_a_new_session_closes_the_recorded_one(client, database):
    mark(client)
    start(client, "A")
    post_events(client, event("one.doubleclick.net"))
    start(client, "B")
    post_events(client, event("two.doubleclick.net"))
    stop(client)
    settle(client)
    assert rows(database, "SELECT s.label, s.stopped IS NOT NULL AS closed, count(h.id) AS hits FROM sessions s "
                          "LEFT JOIN hits h ON h.session_id = s.id GROUP BY s.id ORDER BY s.label") == [
        {"label": "A", "closed": True, "hits": 1}, {"label": "B", "closed": True, "hits": 1}]
    assert [s["label"] for s in client.get("/api/history/sessions").json()["sessions"]] == ["B", "A"]  # newest first
    assert len(client.get("/api/history/sessions?limit=1").json()["sessions"]) == 1


def test_top_companies_per_app_label(client, database):
    mark(client)
    plan = [("Game", ["a1.doubleclick.net", "a2.doubleclick.net", "a1.applovin.com", "a1.facebook.com"]),
            ("Game", ["b1.doubleclick.net", "b1.applovin.com", "b1.example.io"]),
            ("News", ["c1.facebook.com", "c1.app-measurement.com"]),
            (None, ["d1.doubleclick.net"])]
    for label, names in plan:
        start(client, label)
        post_events(client, *[event(name) for name in names])
        stop(client)
    client.post("/api/block", json={"company": "Meta"})  # blocking shows in later sessions, here via the event flag
    start(client, "News")
    post_events(client, event("e1.facebook.com", blocked=True, block_reason="user"),
                event("mask.icloud.com", blocked=True, block_reason="guard"))
    stop(client)

    labels = client.get("/api/history/top-companies").json()["labels"]
    assert [(entry["label"], entry["sessions"], entry["hits"], entry["hidden_attempts"]) for entry in labels] == [
        ("Game", 2, 7, 0), ("News", 2, 3, 1)]
    assert labels[0]["top_companies"] == [
        {"company": "Google", "category": "advertising", "hits": 3, "blocked": 0, "sessions": 2},
        {"company": "AppLovin", "category": "advertising", "hits": 2, "blocked": 0, "sessions": 2},
        {"company": "Meta", "category": "social", "hits": 1, "blocked": 0, "sessions": 1}]
    assert labels[1]["top_companies"] == [
        {"company": "Meta", "category": "social", "hits": 2, "blocked": 1, "sessions": 2},
        {"company": "Google", "category": "analytics", "hits": 1, "blocked": 0, "sessions": 1}]
    limited = client.get("/api/history/top-companies?limit=1").json()["labels"]
    assert [len(entry["top_companies"]) for entry in limited] == [1, 1]


def test_history_clear_deletes_everything_stored_about_phones(client, database):
    mark(client)
    start(client, "First app")
    post_events(client, event("one.doubleclick.net"))
    stop(client)
    start(client, "Second app")  # still being recorded when the history is cleared
    post_events(client, event("two.doubleclick.net"))
    assert column(database, "SELECT count(*) FROM kb_domains") == [28] or wait_for(
        lambda: column(database, "SELECT count(*) FROM kb_domains") == [28])
    assert client.post("/api/history/clear").json() == {"cleared": True}
    post_events(client, event("three.doubleclick.net"))
    stop(client)
    settle(client)
    assert column(database, "SELECT label FROM sessions") == ["Second app"]  # carried on in a fresh row
    assert column(database, "SELECT domain FROM hits") == ["three.doubleclick.net"]
    assert column(database, "SELECT count(*) FROM kb_domains") == [28]  # not history: kept
    assert len(client.get("/api/state").json()["hits"]) == 3  # the live view is not touched

    assert client.post("/api/history/clear").json() == {"cleared": True}
    assert client.get("/api/history/sessions").json() == {"sessions": []}
    assert column(database, "SELECT count(*) FROM devices") == [0]


def test_missing_table_rights_are_reported_until_someone_fixes_them(database, monkeypatch):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    role = f"tattle_limited_{uuid.uuid4().hex[:8]}"
    schema = column(database, "SELECT current_schema()")[0]
    try:
        database.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'limited'")
    except psycopg.Error:
        pytest.skip("the test database user may not create roles")
    try:
        database.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {role}')  # may look, may not create
        limited = make_conninfo(**{**conninfo_to_dict(BASE_URL), "user": role, "password": "limited",
                                   "options": f"-csearch_path={schema}"})
        monkeypatch.setenv("DATABASE_URL", limited)
        monkeypatch.setattr(main, "ai", None)
        with TestClient(main.app) as client:
            assert wait_for(lambda: main.state.health["db_error"])
            health = client.get("/api/health").json()
            assert health["db"] is False
            assert health["db_error"] == ("tables are missing and could not be created (InsufficientPrivilege): "
                                          "run backend/sql/schema.sql once, see backend/README.md")
            post_events(client, event("one.doubleclick.net"))  # the live loop carries on
            assert client.get("/api/state").json()["hits"][0]["company"] == "Google"
            assert client.get("/api/history/sessions").status_code == 503

            database.execute(db_module.SCHEMA.read_text())  # someone with rights runs the schema by hand...
            assert wait_for(lambda: "no read/write rights" in (main.state.health["db_error"] or ""))
            tables = ", ".join(db_module.TABLES)
            database.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO {role}")  # ...and grants access
            assert wait_for(lambda: main.state.health["db"])
            assert client.get("/api/health").json()["db_error"] is None

            mark(client)
            start(client, "Demo Game")
            post_events(client, event("two.doubleclick.net"))
            stop(client)
            settle(client)
            assert [s["hits"] for s in client.get("/api/history/sessions").json()["sessions"]] == [1]
    finally:
        database.execute(f"DROP OWNED BY {role}")
        database.execute(f"DROP ROLE {role}")


def test_ai_answers_are_cached_for_lab_phones_only(database, monkeypatch):
    async def classify(domains):
        return {d: {"company": "Example Analytics", "category": "analytics", "confidence": 0.7} for d in domains}

    calls = fake_ai(monkeypatch, classify=classify)
    monkeypatch.setenv("AI_MODEL", "test-model")
    with TestClient(main.app) as client:
        assert wait_for(lambda: main.state.health["db"])
        mark(client)
        start(client, "Demo Game")
        post_events(client, event("lab.example.io"), event("guest.example.io", client_ip=GUEST, client_name=None))
        assert wait_for(lambda: [h["source"] for h in client.get("/api/state").json()["hits"]] == ["ai", "ai"])
        settle(client)
        assert rows(database, "SELECT domain, company, category, model FROM ai_cache") == [
            {"domain": "lab.example.io", "company": "Example Analytics", "category": "analytics", "model": "test-model"}]
        assert rows(database, "SELECT domain, company, source FROM hits") == [
            {"domain": "lab.example.io", "company": "Example Analytics", "source": "ai"}]  # the stored hit was upgraded

    calls.classify.clear()
    with TestClient(main.app) as client:  # a restarted backend
        assert wait_for(lambda: "lab.example.io" in main.state.ai_seed)
        post_events(client, event("lab.example.io"))
        assert client.get("/api/state").json()["hits"][0]["source"] == "ai"  # known at once, from the database
        assert calls.classify == []
        client.post("/api/wipe")
        post_events(client, event("lab.example.io"), event("guest.example.io", client_ip=GUEST))
        assert wait_for(lambda: calls.classify == [["guest.example.io"]])  # only the uncached name is asked again


def test_lost_connection_is_noticed_and_queued_writes_land_after_reconnecting(client, database):
    mark(client)
    start(client, "Demo Game")
    post_events(client, event("one.doubleclick.net"))
    settle(client)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.portal.call(main.db.conn.close)  # as if the server went away
        post_events(client, event("two.doubleclick.net"))
        assert until(ws, "hit")["domain"] == "two.doubleclick.net"  # the live loop does not care
        assert until(ws, "health")["db"] is False
        assert until(ws, "health")["db"] is True
    settle(client)
    assert column(database, "SELECT domain FROM hits ORDER BY domain") == ["one.doubleclick.net", "two.doubleclick.net"]
    assert column(database, "SELECT count(*) FROM sessions") == [1]


def test_text_with_sql_in_it_is_stored_as_text(client, database):
    nasty = "Robert'); DROP TABLE hits; --"
    mark(client, name=nasty)
    start(client, nasty)
    post_events(client, event("one.doubleclick.net"))
    stop(client)
    session = client.get("/api/history/sessions").json()["sessions"][0]
    assert (session["label"], session["device_name"], session["hits"]) == (nasty, nasty, 1)
    assert client.get("/api/history/top-companies").json()["labels"][0]["label"] == nasty
    assert column(database, "SELECT count(*) FROM hits") == [1]  # the table is still there


def test_a_write_that_keeps_breaking_the_connection_is_dropped(client, database):
    mark(client)
    settle(client)
    main.db._put("SELECT pg_terminate_backend(pg_backend_pid())", None)  # kills its own connection, every time
    client.post(f"/api/devices/{PHONE}", json={"name": "Renamed afterwards"})
    settle(client)  # would never finish if the bad write were retried forever
    assert column(database, "SELECT name FROM devices") == ["Renamed afterwards"]
    assert wait_for(lambda: client.get("/api/health").json()["db"])


def unreachable(monkeypatch):
    monkeypatch.setattr(main, "ai", None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:9/none")
    monkeypatch.setattr(db_module, "RETRY_SECONDS", 0.05)


def exercise_without_database(client):
    """Everything a recorded session does; all of it must work with the database gone."""
    mark(client)
    start(client, "Demo Game")
    post_events(client, event("one.doubleclick.net"))
    stop(client)
    assert client.post("/api/wipe").status_code == 200
    post_events(client, event("two.doubleclick.net"))
    state = client.get("/api/state").json()
    assert [h["company"] for h in state["hits"]] == ["Google"] and state["health"]["db"] is False
    for response in (client.get("/api/history/sessions"), client.get("/api/history/top-companies"),
                     client.post("/api/history/clear")):
        assert response.status_code == 503 and response.json() == {"detail": "database not reachable"}


def test_unreachable_database_only_flips_health(monkeypatch):
    unreachable(monkeypatch)
    with TestClient(main.app) as client:
        exercise_without_database(client)
        time.sleep(0.3)  # several failed reconnects later
        exercise_without_database(client)
        assert client.get("/api/health").json()["db_error"] == "cannot reach the database (OperationalError)"


def test_missing_psycopg_package_only_flips_health(monkeypatch):
    unreachable(monkeypatch)
    monkeypatch.setitem(sys.modules, "psycopg", None)  # makes "import psycopg" fail
    with TestClient(main.app) as client:
        exercise_without_database(client)
        assert client.get("/api/health").json()["db_error"] == "DATABASE_URL is set but the psycopg package is not installed"


def test_write_queue_is_bounded(monkeypatch):
    monkeypatch.setattr(db_module, "QUEUE_MAX", 3)
    db = db_module.Db("postgresql://unused", on_health=lambda ok, problem: None, on_ready=None)
    for i in range(5):
        db.save_device({"device_id": f"10.42.0.{i}", "name": None, "persist": True})
    assert [op[1][0] for op in db.ops] == ["10.42.0.2", "10.42.0.3", "10.42.0.4"]
