"""Tattle backend: sensor events in, categorized hits out over a WebSocket."""
from __future__ import annotations

import asyncio
import http.client
import importlib
import importlib.util
import json
import os
import re
import secrets
import sys
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import explain, labels
from .db import Db
from .guard import Guard
from .hub import Hub
from .kb import Kb, clean
from .state import State, read_ai_seed
from .summary import session_stats
from .validate import is_hostname, is_ip, plain

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"  # the show screen: plain files, no build step

SUMMARY_SECONDS = 3   # live template summary refresh while a session runs
HEALTH_SECONDS = 5    # periodic health broadcast
AI_BATCH = 10         # unknown names per classify call
AI_POLL = 1.0         # seconds between looks at the unknown queue
AI_TIMEOUT = 10.0     # the AI module promises 8 s; this is the backstop
AI_RETRY = 15.0       # pause after a failed AI call
DB_READ_TIMEOUT = 5.0  # seconds a history request may take
LABEL_AI_SECONDS = 10.0  # at most one AI label verdict per session this often
MAX_EXPLAINED = 500   # company explanations remembered until the next wipe
MAX_BLOCKED = 500     # blocked companies plus domains; the sensor fetches the list every second
MAX_CLIENTS = 50      # WebSocket clients at once
AI_PROBE_SECONDS = 15.0  # how often the model server is asked whether it is there
AI_PROBE_TIMEOUT = 8.0   # as long as one AI call may take: on a slow uplink, opening a connection through the tunnel took over 2 s


def load_ai():
    """The AI module is optional and owned by someone else: missing or broken, the backend runs without it."""
    name = f"{__package__}.ai"
    if importlib.util.find_spec(name) is None:
        return None
    try:
        return importlib.import_module(name)
    except Exception as error:
        print(f"ai: module failed to load ({type(error).__name__}: {error}); running without it", file=sys.stderr)
        return None


ai = load_ai()
state: State
hub: Hub
db: Db | None = None  # only with DATABASE_URL
background: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state, hub, db
    env = os.environ
    # Relative paths count from the repo root, wherever the backend was started.
    kb = Kb.load(ROOT / (env.get("KB_PATH") or "data/kb.json"),
                 ROOT / (env.get("KB_OVERRIDES_PATH") or "data/kb_overrides.json"))
    state, hub = State(kb), Hub()
    state.health["ai_module"] = ai is not None
    state.seed_ai(read_ai_seed(ROOT / (env.get("AI_CACHE_SEED_PATH") or "data/ai_cache_seed.json")))
    url = env.get("DATABASE_URL")
    db = Db(url, on_health=db_health, on_ready=db_ready) if url else None
    print(f"backend: kb has {len(kb)} domains, {len(state.ai_seed)} seeded AI answers, "
          f"ai module {'loaded' if ai else 'absent'}, database {'configured' if db else 'not configured'}", file=sys.stderr)
    tasks = [asyncio.create_task(ticker())]
    if ai:
        tasks.append(asyncio.create_task(classify_worker()))
    if db:
        tasks.append(asyncio.create_task(db.run()))
    if env.get("AI_BASE_URL"):
        tasks.append(asyncio.create_task(watch_ai_endpoint(env["AI_BASE_URL"], env.get("AI_TOKEN"), env.get("AI_MODEL"))))
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)  # lets the database connection close


app = FastAPI(title="Tattle", lifespan=lifespan)
app.add_middleware(Guard)


def ai_state() -> str:
    """The one word the pages show for the AI, checked in this order. "off": no ai.py, or the model
    server does not answer. "no-model": it answers, but AI_MODEL is not in its list. "on": the last
    call of ai.py worked. Anything else (ai.py is there, but no call has worked yet) is "off" too."""
    health = state.health
    if ai is None or health["ai_endpoint"] is False:
        return "off"
    if health["ai_endpoint"] and health["ai_model"] is False:
        return "no-model"
    return "on" if health["ai"] else "off"


def set_health(**changes: object) -> None:
    before = dict(state.health)
    state.health.update(changes)
    state.health["ai_state"] = ai_state()
    if state.health != before:
        hub.publish([{"type": "health", **state.health}])


def sensor_seen() -> None:
    first = state.health["sensor_seen"] is None
    state.health["sensor_seen"] = time.time()
    if first:
        hub.publish([{"type": "health", **state.health}])


def db_health(ok: bool, problem: str | None) -> None:
    """Called by the database task whenever its state changes. `problem` says why it is not usable."""
    if (state.health["db"], state.health["db_error"]) != (ok, problem):
        state.health.update(db=ok, db_error=problem)
        hub.publish([{"type": "health", **state.health}])


def ask_ai_endpoint(base_url: str, token: str | None, model: str | None) -> tuple[bool, bool | None]:
    """One small request to the model server's list of models (the OpenAI-style API has one at /models).
    A placeholder token is fine: a server that needs none, such as Ollama, ignores it.
    Returns whether it answered, and whether `model` is in the list (None: no AI_MODEL set, no
    answer, or a list we cannot read). Ollama lists a model pulled without a tag as "<name>:latest"."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # straight there, whatever proxy variables say
    try:
        request = urllib.request.Request(base_url.rstrip("/") + "/models",
                                         headers={"Authorization": f"Bearer {token}"} if token else {})
        with opener.open(request, timeout=AI_PROBE_TIMEOUT) as response:
            if response.status != 200:
                return False, None
            body = response.read(1_000_000)
    except (OSError, ValueError, http.client.HTTPException):  # unreachable, refused, or not a URL at all
        return False, None
    if not model:
        return True, None
    try:
        listed = {entry.get("id") for entry in json.loads(body).get("data") or []}  # an empty Ollama says "data": null
    except (ValueError, AttributeError, TypeError):
        return True, None
    return True, model in listed or f"{model}:latest" in listed


async def watch_ai_endpoint(base_url: str, token: str | None, model: str | None) -> None:
    """Keep health.ai_endpoint and health.ai_model current: is the model server reachable (for us:
    is the SSH tunnel up), and does it have our model? Independent of ai.py: it shows a dead tunnel
    even before any AI call is made. Runs in a thread, so a server that hangs never holds up the live loop."""
    while True:
        answers, listed = await asyncio.to_thread(ask_ai_endpoint, base_url, token, model)
        set_health(ai_endpoint=answers, ai_model=listed)
        await asyncio.sleep(AI_PROBE_SECONDS)


async def db_ready() -> None:
    """Runs each time the database connects."""
    state.seed_ai(await db.ai_cache())
    db.seed_kb(state.kb.entries())


def sync_recording(now: float) -> None:
    """Record the running session in the database exactly while its device is marked persist."""
    if db is None:
        return
    device = state.devices.get(state.session["device_id"]) if state.session else None
    wanted = bool(device and device["persist"])
    if wanted and not db.session_id:
        db.start_session(state.session, device)
    elif not wanted and db.session_id:
        db.stop_session(now)


async def ticker() -> None:
    tick = 0
    while True:
        await asyncio.sleep(1)
        tick += 1
        if tick % SUMMARY_SECONDS == 0:
            summary = state.refresh_summary(time.time())
            if summary:
                hub.publish([summary])
        if tick % HEALTH_SECONDS == 0:
            hub.publish([{"type": "health", **state.health}])


async def classify_worker() -> None:
    """Ask the AI about unknown names in small batches. Hits are already on screen; this only upgrades them."""
    while True:
        await asyncio.sleep(AI_POLL)
        names = state.take_pending(AI_BATCH)
        if not names:
            continue
        generation = state.generation
        try:
            results = await asyncio.wait_for(ai.classify_domains(names), AI_TIMEOUT)
        except Exception:
            results = None
        ok = isinstance(results, dict)
        set_health(ai=ok)
        if state.generation != generation:
            continue  # wiped while we waited
        if not ok:
            state.requeue(names)
            await asyncio.sleep(AI_RETRY)
            continue
        answers = state.apply_classified(names, results)
        hub.publish(answers)
        for answer in answers if db else []:
            # Only names a lab phone looked up are written to the database's cache.
            cache = state.seen_by_persist_device(answer["domain"])
            if cache:
                state.seed_ai({answer["domain"]: {key: answer[key] for key in ("company", "category", "confidence")}})
            db.save_classified(answer, os.environ.get("AI_MODEL"), cache)


async def upgrade_summary(stats: dict, template_summary: dict) -> None:
    try:
        text = await asyncio.wait_for(ai.summarize(stats), AI_TIMEOUT)
    except Exception:
        text = None
    text = plain(text, 600)  # a model wrote it: text only, bounded
    set_health(ai=text is not None)
    if text and state.summary is template_summary:  # still the summary on screen: no wipe or new session since
        by = os.environ.get("AI_MODEL") or "ai"
        hub.publish([state.set_summary(text, by, template_summary["device_id"])])


async def ask_label_ai(entry: dict, label: dict, stats: dict, lookups: int) -> None:
    """Fetch the AI's sentence for the label check. The endpoint never waits for this: it shows the
    rule-based verdict now and this sentence on a later call."""
    try:
        text = await asyncio.wait_for(ai.label_check(label, stats), AI_TIMEOUT)
    except Exception:
        text = None
    text = plain(text, 400)
    set_health(ai=text is not None)
    entry["busy"] = False
    if text:
        entry.update(text=text, lookups=lookups)  # ignored if a wipe or another session replaced the entry meanwhile


async def ask_explain_ai(entry: dict, company: str, category: str, domains: list[str]) -> None:
    """Fetch the AI's explanation of a company. The endpoint never waits for this: it shows the
    tracker-list sentence now and this text on a later call."""
    try:
        text = await asyncio.wait_for(ai.explain_company(company, category, domains), AI_TIMEOUT)
    except Exception:
        text = None
    text = plain(text, 500)
    set_health(ai=text is not None)
    entry["busy"] = False
    if text:
        entry["text"] = text  # kept until the next wipe: opening the same company again is instant


# --- sensor side ---

# Sizes are bounded here; whether a name is a real host name is checked per event in State.ingest,
# so one odd event costs only itself, not its whole batch.
class Event(BaseModel):
    ts: float
    client_ip: str = Field(max_length=45)
    client_name: str | None = Field(None, max_length=255)
    qname: str = Field(max_length=1024)
    qtype: str = Field("A", max_length=16)
    blocked: bool = False
    block_reason: str | None = Field(None, max_length=16)


class Events(BaseModel):
    events: list[Event] = Field(max_length=2000)
    malformed: int = Field(0, ge=0, le=1_000_000)  # names the sensor refused since its last batch


@app.post("/api/events")
async def post_events(body: Events) -> dict:
    sensor_seen()
    state.health["malformed"] += body.malformed
    messages = state.ingest([event.model_dump() for event in body.events], time.time())
    hub.publish(messages)
    if db and db.session_id:
        device_id = state.session["device_id"]
        db.save_hits([m for m in messages if m["type"] == "hit" and m["device_id"] == device_id])
    return {"accepted": len(body.events)}


@app.get("/api/blocklist")
async def get_blocklist() -> dict:
    sensor_seen()  # the sensor polls this every second, so it doubles as its heartbeat
    return state.blocklist()


# --- frontend side ---

class BlockBody(BaseModel):
    company: str | None = Field(None, max_length=100)
    domain: str | None = Field(None, max_length=253)


class DeviceBody(BaseModel):
    name: str | None = Field(None, max_length=64)
    persist: bool | None = None


class SessionBody(BaseModel):
    device_id: str = Field(max_length=45)
    label: str | None = Field(None, max_length=100)


def need_device_id(device_id: str) -> None:
    if not is_ip(device_id):
        raise HTTPException(422, "a device id is the phone's IP address")


def change_block(body: BlockBody, on: bool) -> dict:
    company, domain = plain(body.company, 100), clean(body.domain or "")
    if not company and not domain:
        raise HTTPException(422, "give a company or a domain")
    if domain and not is_hostname(domain):
        raise HTTPException(422, "that is not a host name")
    if on and len(state.blocked_companies) + len(state.blocked_domains) >= MAX_BLOCKED:
        raise HTTPException(422, "too many blocks: unblock something first")
    message = state.set_blocked(company, domain, on)
    hub.publish([message])
    return message


@app.post("/api/block")
async def block(body: BlockBody) -> dict:
    return change_block(body, True)


@app.post("/api/unblock")
async def unblock(body: BlockBody) -> dict:
    return change_block(body, False)


@app.post("/api/devices/{device_id}")
async def update_device(device_id: str, body: DeviceBody) -> dict:
    need_device_id(device_id)
    message = state.set_device(device_id, plain(body.name, 64), body.persist)
    hub.publish([message])
    if db and (message["persist"] or body.persist is False):
        db.save_device(message)
    sync_recording(time.time())
    return message


@app.post("/api/session/start")
async def session_start(body: SessionBody) -> dict:
    need_device_id(body.device_id)
    now = time.time()
    if db and db.session_id:  # a new session replaces the running one
        db.stop_session(now)
    message = state.start_session(body.device_id, plain(body.label, 100), now)
    hub.publish([message])
    sync_recording(now)
    return message


@app.post("/api/session/stop")
async def session_stop() -> dict:
    now = time.time()
    messages, stats = state.stop_session(now)
    hub.publish(messages)
    sync_recording(now)
    if ai and stats:
        task = asyncio.create_task(upgrade_summary(stats, messages[-1]))
        background.add(task)
        task.add_done_callback(background.discard)
    return {"type": "session", "session": None}


@app.post("/api/wipe")
async def wipe() -> dict:
    if db and db.session_id:
        db.drop_session()
    hub.publish(state.wipe())
    return {"type": "wiped"}


@app.get("/api/state")
async def get_state() -> dict:
    return state.snapshot()


@app.get("/api/health")
async def get_health() -> dict:
    return state.health


# --- history (database only) ---

async def from_db(query) -> list[dict]:
    if db is None:
        raise HTTPException(503, "no database configured")
    try:
        return await asyncio.wait_for(query(), DB_READ_TIMEOUT)
    except Exception as error:
        print(f"db: history read failed ({type(error).__name__})", file=sys.stderr)
        raise HTTPException(503, "database not reachable") from None


@app.get("/api/history/sessions")
async def history_sessions(limit: int = 50) -> dict:
    return {"sessions": await from_db(lambda: db.sessions(max(1, min(limit, 200))))}


@app.get("/api/history/top-companies")
async def history_top_companies(limit: int = 10) -> dict:
    return {"labels": await from_db(lambda: db.top_companies(max(1, min(limit, 50))))}


@app.post("/api/history/clear")
async def history_clear() -> dict:
    """Delete all stored history, on purpose. Wipe never does this."""
    if db is None:
        raise HTTPException(503, "no database configured")
    if db.conn is None:
        raise HTTPException(503, "database not reachable")
    db.clear_history()
    sync_recording(time.time())  # a session that is being recorded right now carries on in a fresh row
    return {"cleared": True}


# --- privacy-label fact-check ---

@app.get("/api/label-check")
async def label_check(app_name: str | None = Query(None, alias="app", max_length=100)) -> dict:
    """The app's privacy label next to what the current (or just stopped) session contacted."""
    session = state.session or state.last_session
    if session is None:
        text = "No session yet: start one, use the app, then check again."
        return {"session": None, "label": None, "observed": None, "level": "no-session", "verdict": text,
                "verdict_by": "rules", "rule_verdict": text, "note": labels.NOTE}
    now = time.time()
    name = app_name or session["label"] or ""
    label = labels.find_label(ROOT / (os.environ.get("LABELS_DIR") or "data/labels"), name)
    seen = labels.observed(state.hits, session, now)
    if label is None:
        level, rule_text = "no-label", f"No privacy label on file for {name or 'this session (it has no app name)'}."
    else:
        level, rule_text = labels.verdict(label, seen)
    text, by = rule_text, "rules"
    if label is not None and hasattr(ai, "label_check"):
        # The AI's sentence, if we have one for this session and label. Asking again is rate-limited
        # and happens in the background; this request is answered from what is already known.
        key = (session["device_id"], session["started"], labels.slug(name))
        entry = state.label_ai
        if entry is None or entry["key"] != key:
            entry = state.label_ai = {"key": key, "text": None, "lookups": -1, "asked": 0.0, "busy": False}
        if entry["text"]:
            text, by = entry["text"], os.environ.get("AI_MODEL") or "ai"
        if not entry["busy"] and entry["lookups"] != seen["lookups"] and now - entry["asked"] >= LABEL_AI_SECONDS:
            entry.update(busy=True, asked=now)
            device = state.devices.get(session["device_id"], {})
            task = asyncio.create_task(ask_label_ai(entry, label, session_stats(state.hits, session, device.get("name"), now),
                                                    seen["lookups"]))
            background.add(task)
            task.add_done_callback(background.discard)
    return {"session": {**session, "stopped": session.get("stopped")}, "label": label, "observed": seen,
            "level": level, "verdict": text, "verdict_by": by, "rule_verdict": rule_text, "note": labels.NOTE}


# --- who is this company? (the show screen's detail panel) ---

@app.get("/api/explain")
async def explain_company(company: str = Query(max_length=100), device_id: str | None = Query(None, max_length=45)) -> dict:
    """One company in a few plain sentences. Answered at once with a sentence built from the tracker
    list; if `ai.explain_company` exists it is asked in the background and its text comes with a
    later call. The lookups that count are the session's (running or just stopped); without a
    session, those of `device_id`, or of every phone."""
    name = plain(company, 100)
    if not name:
        raise HTTPException(422, "give a company")
    if device_id is not None:
        need_device_id(device_id)
    session = state.session or state.last_session
    phone, since, until = (session["device_id"], session["started"], session.get("stopped")) if session else (device_id, 0.0, None)
    category, domains = explain.seen(state.hits, name, phone, since, until)
    fallback = explain.fallback(name, category, bool(state.kb.company_domains(name)))
    text, by, pending = fallback, "list", False
    if domains and hasattr(ai, "explain_company"):
        key = (name, phone, since)
        entry = state.explained.get(key)
        if entry is None and len(state.explained) < MAX_EXPLAINED:
            entry = state.explained[key] = {"text": None, "asked": 0.0, "busy": False}
        now = time.time()
        if entry and entry["text"]:
            text, by = entry["text"], os.environ.get("AI_MODEL") or "ai"
        elif entry and not entry["busy"] and now - entry["asked"] >= AI_RETRY:  # first time, or a while after a failure
            entry.update(busy=True, asked=now)
            task = asyncio.create_task(ask_explain_ai(entry, name, category, domains))
            background.add(task)
            task.add_done_callback(background.discard)
        pending = bool(entry and entry["busy"])
    return {"company": name, "category": category, "domains": domains, "text": text, "by": by,
            "fallback": fallback, "pending": pending}


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    if len(hub.clients) >= MAX_CLIENTS:
        return await websocket.close(code=1013)  # "try again later"
    await websocket.accept()
    queue = hub.join(state.snapshot())
    try:
        while (message := await queue.get()) is not None:
            await websocket.send_json(message)
        await websocket.close()
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass  # the client left; noticed at the next send, at the latest the next health tick
    finally:
        hub.leave(queue)


# --- pages ---

def sockets(host: str) -> str:
    """The WebSocket addresses of this backend, for a policy's connect-src. Some browsers do not count ws:// as 'self'."""
    return f" ws://{host} wss://{host}" if re.fullmatch(r"[A-Za-z0-9.:\[\]-]+", host) else ""


def page(name: str, request: Request) -> HTMLResponse:
    """One of our own single-file pages, under a policy that runs only the page's own script and style
    and lets it talk only to this backend. If a name from the network ever slipped in as markup, it
    still could not run or call out."""
    nonce = secrets.token_urlsafe(16)
    html = Path(__file__).with_name(name).read_text(encoding="utf-8")
    html = html.replace("<script>", f'<script nonce="{nonce}">').replace("<style>", f'<style nonce="{nonce}">')
    policy = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
              f"connect-src 'self'{sockets(request.headers.get('host', ''))}; "
              "base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
    return HTMLResponse(html, headers={"Content-Security-Policy": policy, "Cache-Control": "no-store"})


class Frontend(StaticFiles):
    """The show screen's files, read from frontend/ at each request. The policy allows only files from
    this backend (script, style, font, image; nothing inline, nothing from the internet) and
    "no-cache" makes the browser ask every time, so a reload always shows the latest edit.
    The one exception is "data:" for images: the page draws its browser-tab icon from its own logo."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
            f"connect-src 'self'{sockets(host)}; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
        response.headers["Cache-Control"] = "no-cache"
        return response


@app.get("/debug")
async def debug_page(request: Request) -> HTMLResponse:
    return page("debug.html", request)


@app.get("/present")
async def present_page(request: Request) -> HTMLResponse:
    """The plain presenter view: insurance in case the real frontend is not ready."""
    return page("present.html", request)


if (FRONTEND / "index.html").is_file():
    app.mount("/", Frontend(directory=FRONTEND, html=True), name="frontend")  # last, so every route above wins
else:
    @app.get("/")
    async def no_frontend() -> RedirectResponse:
        return RedirectResponse("/debug")
