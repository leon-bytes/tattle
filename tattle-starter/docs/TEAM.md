# Tattle: team doc

Working name: **Tattle** (renaming = find/replace). This doc is the contract between our three parts. To change an interface, change it here first, then tell the team.

## The pitch

Tattle is a pocket Wi-Fi box that X-rays a phone in a minute. Hand someone the phone, they open an app, and the screen fills with every company that app quietly calls: in plain English, checked against the app's own privacy label, with one tap to shut a tracker up.

## Ground rules

**Privacy and consent**
- Hotspot uses a WPA2 password and the SSID `Tattle-Demo`. Never use an official-looking name, never run an open network.
- Only our own test phones join, plus judges who explicitly opt in.
- We only read DNS lookups (server names), never content.
- Devices are **ephemeral by default**: their data lives in RAM only and is gone on Wipe or restart. Only devices we mark as our own lab phones (`persist: true`) get written to Postgres.
- Replays in `data/replays/` come from our own phones only, with device names replaced (`Test iPhone A`).
- Never commit raw packet captures.

**Repo hygiene**
- No personal info in any file: names, usernames, emails, school, location, absolute paths with a home folder. Use placeholders like `<your-name>`.
- Secrets go in `.env` (git-ignored). Copy `.env.example` to start.
- If a tool creates files that shouldn't be committed, add them to `.gitignore` before pushing.
- Python: always inside a venv (or `nix-shell`). Never `pip install` into a system Python.

**Challenges log**
- Write problems in `docs/CHALLENGES.md` as you hit them: one line each, how it was solved, and which AI tool helped. Judges score honesty about challenges and AI tools, and this is where those answers come from.

## How it works

```
test iPhone --Wi-Fi--> THE BOX (Linux laptop)
                       |- NetworkManager hotspot (DHCP + NAT) --USB tether--> phone's cellular --> internet
                       |- firewall rule: any DNS (port 53) from the hotspot --> sensor :5300
                       |- sensor: our DNS resolver (records the name, blocks, forwards to upstream)
                       |     | POST /api/events          ^ GET /api/blocklist (every 1 s)
                       |     v                           |
                       |- backend (FastAPI :8000) -- kb.json lookup -- AI on AMD notebook (optional) -- Postgres (provided)
                       |     | WebSocket /ws
                       |     v
                       '- frontend (React, served by the backend on the box) --> laptop screen
```

**Why we act as the resolver:** the hotspot's DHCP tells phones "ask this box for DNS", and a firewall rule also catches apps that try to use their own DNS server (like 8.8.8.8). Being the resolver makes capture and blocking the same job. To block a tracker, we answer "that name doesn't exist" (NXDOMAIN).

## Owners

- **BOX**: hotspot, sensor, `box/` scripts, backend core (events, kb lookup, state, WebSocket, Postgres).
- **FRONT**: the React app. Live bubble graph, device panel, block buttons, session controls, How-it-works view.
- **AI**: AMD notebook and model server, `backend/app/ai.py`, `tools/build_kb.py` and `data/kb*.json`, privacy labels for demo apps, visual identity (palette, type), pitch diagram.

Each owner edits only their own folders. Shared files: this doc, `docs/PITCH.md`, `docs/CHALLENGES.md`, `.gitignore`, `README.md`.

## Interfaces (the contract)

### Categories

`advertising`, `analytics`, `social`, `fingerprinting`, `content` (CDNs, embedded media), `vendor` (the OS maker or the app's own servers), `unknown`.

### Knowledge base: `data/kb.json`

```json
{
  "domains": {
    "doubleclick.net": { "company": "Google", "category": "advertising", "source": "disconnect" }
  }
}
```

- `data/kb_overrides.json` has the same shape and wins over `kb.json` (hand fixes, e.g. Apple's own domains map to `vendor`).
- **Lookup** walks up the name, `a.b.example.com` → `b.example.com` → `example.com`, and the first match wins.
- Keys are lowercase with no trailing dot.
- Tracker list credit: Disconnect's list is CC BY-NC-SA 4.0 (non-commercial). Credit it in the README.

### Sensor → backend: `POST /api/events`

```json
{ "events": [
  { "ts": 1760070000.123, "client_ip": "10.42.0.23", "client_name": "iPhone",
    "qname": "ads.example.com", "qtype": "A", "blocked": false, "block_reason": null }
]}
```

- `ts` is unix seconds as a float. `qname` is lowercase with no trailing dot.
- `client_name` is the DHCP hostname if known, otherwise `null`.
- `block_reason` is `"user"` (blocked from the UI), `"guard"` (built-in bypass block, see below) or `null`.
- The sensor sends a batch about every 250 ms.
- iPhones ask for A, AAAA and HTTPS records of the same name at once. The backend counts the same device + name within 2 s as one hit.

### Backend → sensor: `GET /api/blocklist`

```json
{ "version": 3, "domains": ["doubleclick.net"] }
```

- Suffix match, same as the kb.
- The sensor polls every second. If the backend is down, the sensor keeps the last list and keeps resolving.

### Built-in guard list (the sensor always answers NXDOMAIN)

- iCloud Private Relay: `mask.icloud.com`, `mask-h2.icloud.com`. This is Apple's documented way for a network to opt out; the iPhone then shows a notice.
- Well-known DNS-over-HTTPS hostnames, so apps fall back to normal DNS.

### Backend → frontend: WebSocket `/ws`

The first message on connect is a full snapshot, then individual events follow:

```json
{"type":"snapshot","devices":[],"hits":[],"blocked":{"companies":[],"domains":[]},"session":null,"health":{}}
{"type":"device","device_id":"10.42.0.23","name":"Test iPhone A","persist":true}
{"type":"hit","device_id":"10.42.0.23","domain":"ads.example.com","company":"Example Ads","category":"advertising","source":"list","blocked":false,"ts":1760070000.1}
{"type":"classified","domain":"odd.example.io","company":"Example Analytics","category":"analytics","source":"ai","confidence":0.7}
{"type":"summary","device_id":"10.42.0.23","text":"...","by":"<model-name or template>"}
{"type":"blocked","companies":["Example Ads"],"domains":[]}
{"type":"session","session":{"device_id":"10.42.0.23","label":"<app name>","started":1760070000.0}}
{"type":"health","db":true,"ai":false,"sensor_seen":1760070000.0}
{"type":"wiped"}
```

- `source` is one of `list`, `override`, `ai` or `unknown`.
- `company` is `null` when unknown.

### Frontend → backend: REST

```
POST /api/block           {"company": "Example Ads"}  or  {"domain": "x.example.com"}
POST /api/unblock         same body
POST /api/devices/{id}    {"name": "Test iPhone A", "persist": true}
POST /api/session/start   {"device_id": "10.42.0.23", "label": "<app name>"}
POST /api/session/stop
POST /api/wipe            clears all in-memory data, plus DB rows of the current session
GET  /api/state           same shape as the snapshot
GET  /api/health
```

### AI module: `backend/app/ai.py` (AI owns it, the backend calls it)

```python
async def classify_domains(domains: list[str]) -> dict[str, dict] | None
    # -> {"odd.example.io": {"company": str | None, "category": str, "confidence": float}}
async def summarize(stats: dict) -> str | None
    # stats: {"device": str, "label": str | None, "seconds": int,
    #         "by_category": {"advertising": 9}, "top_companies": [["Example Ads", 14]]}
async def label_check(label: dict, stats: dict) -> str | None   # stretch
```

- Every call times out within 8 s and returns `None` on any failure. The backend then falls back to a template sentence.
- Results are cached: Postgres `ai_cache`, plus `data/ai_cache_seed.json` for the demo apps.
- **The live demo never waits on AI.**
- Config comes from `.env`: `AI_BASE_URL`, `AI_TOKEN`, `AI_MODEL` (OpenAI-compatible `/chat/completions`).

### Privacy labels (stretch): `data/labels/<app-slug>.json`

```json
{"app": "<app name>", "source_url": "<App Store link>", "checked": "<date>",
 "data_used_to_track_you": [], "data_linked_to_you": [], "data_not_linked_to_you": [], "data_not_collected": false}
```

### Postgres (provided): `backend/sql/schema.sql`

- Tables: `kb_domains` (seeded from the kb), `devices`, `sessions`, `hits` (only for `persist` devices), `ai_cache`.
- If the DB is unreachable, the backend keeps running in memory and reports `health.db = false`.

### Ports

- sensor: UDP/TCP 5300 (not 5353: that's mDNS, often already taken on Linux)
- backend: 8000 (on the box it also serves the built frontend)
- Vite dev server: 5173, proxying `/api` and `/ws` to 8000

Env vars are listed in `.env.example`.

## Repo layout

```
README.md            what it is + how to run (points here)
.gitignore
.env.example         copy to .env, fill in, never commit .env
docs/TEAM.md         this file
docs/PITCH.md        demo script + talking points
docs/CHALLENGES.md   running log of problems and AI tools used
sensor/              DNS resolver that runs on the box
box/                 scripts to bring the hotspot up/down on the box (Linux + NetworkManager)
backend/app/         FastAPI app (main, kb lookup, state, db, ai)
backend/sql/         schema.sql
frontend/            React + Vite app
data/kb.json         tracker knowledge base (built by tools/build_kb.py)
data/kb_overrides.json
data/labels/         App Store privacy labels for demo apps (hand-entered)
data/replays/        recorded sessions from OUR test phones only (anonymized)
tools/               fake_sensor.py (replays events into the backend), build_kb.py
```

## Running it

- Exact commands live in each folder's README. Owners keep them current.
- **Dev (no hotspot needed):** run the backend, then `tools/fake_sensor.py` with a file from `data/replays/`. It feeds the backend exactly as a live phone would.
- **Demo (on the box):** `box/box-up.sh`, then start the sensor and the backend. Details are in `box/README.md`.

## Scope

**MVP: must work end-to-end by Saturday 15:00**
1. Hotspot + sensor capture DNS from a real iPhone.
2. The backend categorizes lookups via the kb and pushes them over the WebSocket.
3. Live bubble graph: the device in the middle, company bubbles around it colored by category, growing and pulsing on each hit.
4. One-tap block of a company. The sensor NXDOMAINs it, the bubble greys out, and a "blocked attempts" counter keeps ticking.
5. Session start/stop with an app label, a Wipe button, and an on-screen privacy banner.
6. A plain-English summary per session (a template is fine for the MVP, AI when ready).
7. Replay mode (`fake_sensor`) working. It's our backup.

**Stretch, in this order**
1. Privacy-label fact-check for 2–3 demo apps: the App Store label (hand-entered) side by side with what we saw. This is our biggest originality lever. It works without AI; AI adds a one-line verdict. Say "contacted", never "sent your data": we see lookups, not content.
2. AI classification of unknown domains, shown with an "AI guess" badge.
3. AI summary from the AMD-hosted model.
4. Postgres history view: past sessions of our lab phones, top offenders per app.
5. How-it-works view inside the app (a diagram of this flow).
6. Accuracy check against the iPhone's built-in App Privacy Report for the same session.
7. ROCm: train a small domain classifier on the AMD GPU and compare it with the LLM (only if the AI core is done by 16:00).

**Don't build**
- user accounts or login
- a mobile app
- TLS/SNI capture, or any capture beyond DNS
- multi-box support or cloud deployment
- settings pages
- a Jetson port or a physical enclosure

## Sponsor tracks we enter

- **Best Use of Provided Backend.** Postgres does real work: the kb, session history, the AI cache, and a top-offenders view. Needs: the history view working.
- **Best Use of Open Source AI.** An open model classifies domains no list knows, writes the summaries, and fact-checks labels. Needs: a clear before/after (lists only vs. with AI).
- **Best Use of Graphics Technologies (ROCm).** The model is served on the AMD GPU via ROCm, and stretch 7 makes this stronger. Needs: notes and screenshots of the ROCm setup, plus real numbers (tokens/s).
- **Best Design / Prettiest Hack.** The live graph is the showpiece. Needs: a consistent palette and type.
- **Skipping:** Data Capturing Hardware (no sensors or enclosure), Jetson, Financial Services, Innovation for Good, Pathways & Perception, the robot dashboard, and the Analytics Platform (unless someone finds a cheap fit).

## Timeline (local time)

**Saturday**
- 02:00–05:00: set up and run the de-risk tests. Interfaces in this doc are locked.
- 05:00: checkpoint. What worked, which fallbacks we pick.
- 05:00–10:00: sleep.
- 10:00–15:00: build the MVP.
- 15:00: checkpoint. The full loop works with a real iPhone on the real hotspot.
- 15:00–20:00: stretch goals, design polish, record replays from our phones.
- **20:00: feature lock.** Only bug fixes and polish after this.
- 20:00–00:00: record the backup video, write the submission text, rehearse twice.

**Sunday**
- 00:00–06:30: sleep.
- 06:30–09:00: rehearse with a timer (3+ times), fresh-boot test of the box, restart the AMD session, submit.
- 09:00–10:00: buffer. **Check the real submission deadline; it may be earlier.**

## De-risk tests (first 2–3 hours)

1. **Hotspot + see DNS on the box** (BOX).
   - Pass: an iPhone joins `Tattle-Demo`, gets internet, and its DNS lookups show up live on the box.
   - Fallbacks, in order: a USB Wi-Fi adapter that supports AP mode; the test iPhone's DNS set manually to the box while both are on the phone hotspot; replay mode.
2. **Sensor as resolver** (BOX).
   - Pass: redirected lookups reach the sensor, and blocking a domain stops it working on the iPhone.
   - Fallback: capture only, from the hotspot's own DNS, with no blocking.
3. **AMD model server reachable from a laptop** (AI).
   - Pass: a request to `<hub>/user/<hub-username>/proxy/<port>/v1/models` with an API token works.
   - Fallback: template summaries plus AI answers precomputed in the notebook and saved to `data/ai_cache_seed.json`.
4. **Provided Postgres reachable from a laptop over a phone hotspot** (AI).
   - Fallback: Postgres in a container on the box. We keep the feature but probably lose the track.
5. **Tracker-heavy demo app** (BOX, once test 1 passes).
   - Find 2–3 free iPhone apps that light up fast, then pick the demo app.

## Judging logistics

- Teams go to the judges: 2 min setup, 6 min judging and questions, 2 min teardown.
- The box must already be running when we walk over: hotspot up, test iPhone joined, demo app installed, page full-screen, laptop not allowed to sleep, chargers packed.
- The checklist is in `docs/PITCH.md`.
