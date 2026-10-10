"""Optional Postgres layer: history for our own lab phones.

Nothing here is on the live path. Writes are queued and executed by one background task;
when the database is slow or gone, the oldest queued writes are dropped and only
health.db changes. Reads are for the history endpoints only.
"""
from __future__ import annotations

import asyncio
import collections
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
TABLES = ["kb_domains", "devices", "sessions", "hits", "ai_cache"]

QUEUE_MAX = 5000        # queued writes kept while the database is away
RETRY_SECONDS = 5.0     # pause before reconnecting
CONNECT_TIMEOUT = 5     # seconds
IDLE_CHECK = 30.0       # seconds without writes before the connection is tested
SETTLE_SECONDS = 2.0    # how long a read waits for queued writes, so history includes what just happened

# SQL test for "a real lookup": everything except hidden-traffic attempts (guard-list lookups).
SEEN = "h.block_reason IS DISTINCT FROM 'guard'"


class Db:
    def __init__(self, url: str, on_health: Callable[[bool, str | None], None],
                 on_ready: Callable[[], Awaitable[None]]) -> None:
        self.url = url
        self.on_health = on_health
        self.on_ready = on_ready
        self.conn = None
        self.ops: collections.deque[tuple[str, object, bool]] = collections.deque(maxlen=QUEUE_MAX)
        self.wake = asyncio.Event()
        self.session_id: uuid.UUID | None = None  # the stored session, while one is being recorded
        self.kb_seeded = False
        self.reported: tuple[bool, str | None] | None = None  # last state passed to on_health
        self.failed: object = None  # the write that broke the last connection

    # --- background task ---

    async def run(self) -> None:
        try:
            import psycopg  # imported here: without DATABASE_URL the backend runs without the package
            from psycopg.rows import dict_row
        except ImportError:
            self._report(False, "DATABASE_URL is set but the psycopg package is not installed")
            return
        try:
            while True:
                problem = None
                try:
                    self.conn = await psycopg.AsyncConnection.connect(
                        self.url, autocommit=True, row_factory=dict_row, connect_timeout=CONNECT_TIMEOUT)
                    problem = await self._prepare(psycopg)
                    if problem is None:
                        self._report(True, None)
                        await self.on_ready()
                        await self._write_forever(psycopg)
                except Exception as error:  # error text can quote row values, so only its type is reported
                    problem = f"cannot reach the database ({type(error).__name__})"
                self._report(False, problem)
                await self._close()
                await asyncio.sleep(RETRY_SECONDS)
        finally:
            await self._close()

    def _report(self, ok: bool, problem: str | None) -> None:
        if (ok, problem) != self.reported:
            self.reported = (ok, problem)
            print("db: " + ("connected" if ok else problem), file=sys.stderr)
            self.on_health(ok, problem)

    async def _prepare(self, psycopg) -> str | None:
        """Create our tables if needed, then check they can be used. Returns what is wrong, or None."""
        try:
            await self.conn.execute(SCHEMA.read_text(encoding="utf-8"))
            failed = ""
        except psycopg.Error as error:  # typically: this user may not create tables
            failed = f" and could not be created ({type(error).__name__})"
        rows = await (await self.conn.execute(
            "SELECT name FROM unnest(%s::text[]) AS name WHERE to_regclass(name) IS NULL", (TABLES,))).fetchall()
        if rows:
            return f"tables are missing{failed}: run backend/sql/schema.sql once, see backend/README.md"
        rows = await (await self.conn.execute(
            "SELECT name FROM unnest(%s::text[]) AS name WHERE NOT (has_table_privilege(name, 'SELECT') "
            "AND has_table_privilege(name, 'INSERT') AND has_table_privilege(name, 'UPDATE') "
            "AND has_table_privilege(name, 'DELETE'))", (TABLES,))).fetchall()
        if rows:
            return "no read/write rights on our tables: see the GRANT line in backend/README.md"
        return None

    async def _close(self) -> None:
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass

    async def _write_forever(self, psycopg) -> None:
        while True:
            if not self.ops:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), IDLE_CHECK)
                except TimeoutError:
                    await self.conn.execute("SELECT 1")  # notice a dead connection while idle
                continue
            op = self.ops[0]
            sql, params, many = op
            try:
                if many:
                    async with self.conn.cursor() as cursor:
                        await cursor.executemany(sql, params)
                else:
                    await self.conn.execute(sql, params)
            except (psycopg.OperationalError, psycopg.InterfaceError) as error:
                if op is not self.failed:
                    self.failed = op
                    raise  # connection trouble: the write stays queued for after the reconnect
                # It failed again on a fresh connection, so it is this write. Drop it rather than loop forever.
                print(f"db: one write dropped after failing twice ({type(error).__name__})", file=sys.stderr)
            except psycopg.Error as error:
                print(f"db: one write skipped ({type(error).__name__})", file=sys.stderr)
            if self.ops and self.ops[0] is op:  # still there unless the full queue dropped it meanwhile
                self.ops.popleft()

    def _put(self, sql: str, params: object, many: bool = False) -> None:
        self.ops.append((sql, params, many))  # a full deque drops its oldest write
        self.wake.set()

    # --- writes: queued, never awaited ---

    def seed_kb(self, entries: list[tuple]) -> None:
        if self.kb_seeded or not entries:
            return
        self.kb_seeded = True
        self._put("INSERT INTO kb_domains (domain, company, category, source) VALUES (%s, %s, %s, %s) "
                  "ON CONFLICT (domain) DO UPDATE SET company = EXCLUDED.company, category = EXCLUDED.category, "
                  "source = EXCLUDED.source", entries, many=True)

    def save_device(self, device: dict) -> None:
        """Remember a lab phone, or record that it is no longer one. Unmarked phones never get a row."""
        if device["persist"]:
            self._put("INSERT INTO devices (device_id, name, persist) VALUES (%s, %s, true) "
                      "ON CONFLICT (device_id) DO UPDATE SET name = EXCLUDED.name, persist = true, updated = now()",
                      (device["device_id"], device["name"]))
        else:
            self._put("UPDATE devices SET persist = false, updated = now() WHERE device_id = %s", (device["device_id"],))

    def start_session(self, session: dict, device: dict) -> None:
        self.save_device(device)  # the session row needs the device row
        self.session_id = uuid.uuid4()
        self._put("INSERT INTO sessions (id, device_id, label, started) VALUES (%s, %s, %s, to_timestamp(%s))",
                  (self.session_id, session["device_id"], session["label"], session["started"]))

    def stop_session(self, now: float) -> None:
        self._put("UPDATE sessions SET stopped = to_timestamp(%s) WHERE id = %s", (now, self.session_id))
        self.session_id = None

    def drop_session(self) -> None:
        """Wipe: delete the running session and, through the foreign key, its hits."""
        self._put("DELETE FROM sessions WHERE id = %s", (self.session_id,))
        self.session_id = None

    def clear_history(self) -> None:
        """Delete every stored session, its hits, and the lab-phone list. The kb mirror and the AI cache stay."""
        self._put("DELETE FROM sessions", None)
        self._put("DELETE FROM devices", None)
        self.session_id = None

    def save_hits(self, hits: list[dict]) -> None:
        rows = [(self.session_id, hit["ts"], hit["domain"], hit["company"], hit["category"], hit["source"],
                 hit["blocked"], hit["block_reason"]) for hit in hits]
        if rows:
            self._put("INSERT INTO hits (session_id, ts, domain, company, category, source, blocked, block_reason) "
                      "VALUES (%s, to_timestamp(%s), %s, %s, %s, %s, %s, %s)", rows, many=True)

    def save_classified(self, answer: dict, model: str | None, cache: bool) -> None:
        """An AI answer arrived: upgrade the running session's stored hits and, if asked, cache the answer."""
        if self.session_id:
            self._put("UPDATE hits SET company = %s, category = %s, source = 'ai' "
                      "WHERE session_id = %s AND domain = %s AND source = 'unknown'",
                      (answer["company"], answer["category"], self.session_id, answer["domain"]))
        if cache:
            self._put("INSERT INTO ai_cache (domain, company, category, confidence, model) VALUES (%s, %s, %s, %s, %s) "
                      "ON CONFLICT (domain) DO UPDATE SET company = EXCLUDED.company, category = EXCLUDED.category, "
                      "confidence = EXCLUDED.confidence, model = EXCLUDED.model, created = now()",
                      (answer["domain"], answer["company"], answer["category"], answer["confidence"], model))

    # --- reads: for start-up and the history endpoints ---

    async def _rows(self, sql: str, params: object = None) -> list[dict]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SETTLE_SECONDS
        while self.conn is not None and self.ops and loop.time() < deadline:
            await asyncio.sleep(0.02)
        if self.conn is None:
            raise ConnectionError("database not connected")
        cursor = await self.conn.execute(sql, params)
        return await cursor.fetchall()

    async def ai_cache(self) -> dict[str, dict]:
        cursor = await self.conn.execute("SELECT domain, company, category, confidence FROM ai_cache")
        return {row["domain"]: {"company": row["company"], "category": row["category"],
                                "confidence": row["confidence"]} for row in await cursor.fetchall()}

    async def sessions(self, limit: int) -> list[dict]:
        """Stored sessions, newest first, each with its counts and five most contacted companies.
        Hidden-traffic attempts (guard-list lookups) are counted apart and never towards a company."""
        sessions = await self._rows(
            "SELECT s.id, s.device_id, d.name AS device_name, s.label, "
            "extract(epoch FROM s.started)::float8 AS started, extract(epoch FROM s.stopped)::float8 AS stopped, "
            f"count(h.id) FILTER (WHERE {SEEN}) AS hits, count(h.id) FILTER (WHERE h.blocked AND {SEEN}) AS blocked, "
            f"count(h.id) FILTER (WHERE NOT {SEEN}) AS hidden_attempts, "
            f"count(DISTINCT h.company) FILTER (WHERE {SEEN}) AS companies "
            "FROM sessions s JOIN devices d USING (device_id) LEFT JOIN hits h ON h.session_id = s.id "
            "GROUP BY s.id, d.name ORDER BY s.started DESC LIMIT %s", (limit,))
        top = await self._rows(
            "SELECT h.session_id, h.company, count(*) AS hits FROM hits h "
            f"WHERE h.session_id = ANY(%s) AND h.company IS NOT NULL AND {SEEN} "
            "GROUP BY h.session_id, h.company ORDER BY hits DESC, h.company", ([s["id"] for s in sessions],))
        for session in sessions:
            mine = [[row["company"], row["hits"]] for row in top if row["session_id"] == session["id"]]
            session.update(id=str(session["id"]), top_companies=mine[:5])
        return sessions

    async def top_companies(self, limit: int) -> list[dict]:
        """Per app label: the most contacted companies across all stored sessions with that label."""
        labels = await self._rows(
            f"SELECT s.label, count(DISTINCT s.id) AS sessions, count(h.id) FILTER (WHERE {SEEN}) AS hits, "
            f"count(h.id) FILTER (WHERE NOT {SEEN}) AS hidden_attempts "
            "FROM sessions s LEFT JOIN hits h ON h.session_id = s.id "
            "WHERE s.label IS NOT NULL GROUP BY s.label ORDER BY s.label")
        companies = await self._rows(
            "SELECT s.label, h.company, mode() WITHIN GROUP (ORDER BY h.category) AS category, count(*) AS hits, "
            "count(*) FILTER (WHERE h.blocked) AS blocked, count(DISTINCT s.id) AS sessions "
            "FROM hits h JOIN sessions s ON s.id = h.session_id "
            f"WHERE s.label IS NOT NULL AND h.company IS NOT NULL AND {SEEN} "
            "GROUP BY s.label, h.company ORDER BY hits DESC, h.company")
        for label in labels:
            mine = [{key: row[key] for key in ("company", "category", "hits", "blocked", "sessions")}
                    for row in companies if row["label"] == label["label"]]
            label["top_companies"] = mine[:limit]
        return labels
