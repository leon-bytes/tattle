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
- Device names are **hidden by default**: phones show as "Device 1", "Device 2". A phone's own name is only read when the sensor is started with `--names` (our own phones).
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
                       |- backend (FastAPI :8000, in a VM on the laptop) -- kb.json lookup -- AI on the AMD server, through an SSH tunnel (optional) -- Postgres (provided)
                       |     | WebSocket /ws
                       |     v
                       '- frontend (a plain page, served by the backend at /) --> laptop screen
```

**Where things run on the box:** the hotspot and the sensor run on the laptop itself. The backend, which also serves the frontend, runs in a virtual machine on that laptop. The sensor reaches it over the laptop's internal VM network (`BACKEND_URL=http://<vm-ip>:8000`), and so does the browser. Phones on the hotspot cannot reach the backend.

**Why we act as the resolver:** the hotspot's DHCP tells phones "ask this box for DNS", and a firewall rule also catches apps that try to use their own DNS server (like 8.8.8.8). Being the resolver makes capture and blocking the same job. To block a tracker, we answer "that name doesn't exist" (NXDOMAIN).

## Owners

- **BOX**: hotspot, sensor, `box/` scripts, backend core (events, kb lookup, state, WebSocket, Postgres), privacy labels for the demo apps (`data/labels/`, moved from AI on Saturday afternoon), and the frontend (`frontend/`, moved from FRONT on Saturday afternoon).
- **FRONT**: merged into BOX on Saturday afternoon. The frontend is the show screen in `frontend/`: the live bubble graph, counters, block by click, session controls, the How-it-works view. It is a plain page with no build step, not the React app first planned.
- **AI**: the model server on the AMD server, `backend/app/ai.py`, `tools/build_kb.py` and `data/kb*.json`, visual identity (palette, type), pitch diagram.

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
- **v1 exists** (built by BOX; AI owns it from here): `tools/build_kb.py` downloads Disconnect's `services.json` and writes `data/kb.json` (about 4,400 domains). Its choices and open points are in the note at the top of that script. `data/kb_overrides.json` holds Apple's system domains (`vendor`, with Apple's ad hosts as `advertising`), the big CDNs (`content`) and phone-only SDK hosts the list lacks. Both files may carry other top-level keys (`license`, `about`); only `domains` is read.

### Sensor → backend: `POST /api/events`

```json
{ "events": [
  { "ts": 1760070000.123, "client_ip": "10.42.0.23", "client_name": null,
    "qname": "ads.example.com", "qtype": "A", "blocked": false, "block_reason": null }
]}
```

- `ts` is unix seconds as a float. `qname` is lowercase with no trailing dot.
- `client_name` is `null` unless the sensor was started with `--names`; then it is the DHCP hostname, if known.
- `block_reason` is `"user"` (blocked from the UI), `"guard"` (built-in bypass block, see below) or `null`.
- The sensor sends a batch about every 250 ms.
- **Added by BOX:** the body may also carry `"malformed": 3`, the number of lookups the sensor refused since its last batch because the name was not a plain host name (see "Names are untrusted" below).
- iPhones ask for A, AAAA and HTTPS records of the same name at once. The backend counts the same device + name within 2 s as one hit.

### Backend → sensor: `GET /api/blocklist`

```json
{ "version": 3, "domains": ["doubleclick.net"] }
```

- Suffix match, same as the kb.
- The sensor polls every second. If the backend is down, the sensor keeps the last list and keeps resolving.
- **Added by BOX: a block stops new connections, not open ones.** DNS blocking acts when an app asks for a name. An answer the phone already has, or a connection that is already open, is not touched. The sensor therefore cuts the lifetime (TTL) of every answer it relays to 10 s (`--max-ttl`), so phones ask again within seconds and a block or unblock takes hold at the app's next connection. For the demo: block, then close and reopen the app.

### Built-in guard list (the sensor always answers NXDOMAIN)

- iCloud Private Relay: `mask.icloud.com`, `mask-h2.icloud.com`, `mask.apple-dns.net`. Answering NXDOMAIN for the `mask` names is Apple's documented way for a network to opt out; the iPhone then shows a notice.
- `_dns.resolver.arpa`: the iPhone asking its resolver for an encrypted-DNS upgrade. We say no, so it keeps using plain DNS.
- Well-known DNS-over-HTTPS hostnames, so apps fall back to normal DNS: `dns.google`, `cloudflare-dns.com`, `one.one.one.one`, `dns.quad9.net`, `doh.opendns.com`, `use-application-dns.net`.
- Matching is by suffix, like the blocklist, so `mozilla.cloudflare-dns.com` is covered too.

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

**Added by BOX while building the backend (all additive; nothing above changed):**
- `hit` also carries `"block_reason"`: `"user"`, `"guard"` or `null`.
- **Guard-list lookups are "hidden-traffic attempts", not blocked trackers.** They arrive as hits with `blocked: true` and `block_reason: "guard"`: the phone tried encrypted DNS or Private Relay and we said no. Show and count them separately. Don't add them to "blocked attempts" or to a company's bubble (their `company` is whoever runs the relay, e.g. Apple, or `null`). The backend's own counts (`summary`, history, label check) already keep them apart.
- `snapshot` also carries `"summary"`: the latest `summary` message, or `null`.
- `snapshot` (and `GET /api/state`) also carries `"last_session"`: the session that just stopped, `{"device_id", "label", "started", "stopped"}`, or `null` while one runs, before the first one, and after a wipe. A page opened after the stop can still show that session. The `session` message itself is unchanged (`null` on stop).
- `health` (and `snapshot.health`, `GET /api/health`) also carries `"kb"`: how many kb domains are loaded. `0` means `data/kb.json` is missing.
- `health` also carries `"db_error"`: `null`, or one sentence saying why the database is not usable (unreachable, tables missing, no rights). `null` with `db: false` means no database is configured.
- `health` also carries `"malformed"`: how many lookups were refused since the backend started because the name was not a plain host name. Worth showing: it is the phone (or someone) sending names that are not names.
- `summary` is sent when a session stops, and about every 3 s while one runs and new hits arrived.
- `wiped` is followed by an empty `blocked` and a `session` with `null`. Wipe also clears all blocks.
- Hits for network plumbing are dropped by the backend: names ending in `.arpa` or `.local`, and names without a dot. Guard-list lookups are the exception (`_dns.resolver.arpa` arrives as a hidden-traffic attempt).
- kb lookup detail: `kb_overrides.json` is searched first, all the way up the name. An override wins over `kb.json` for its own name and everything under it; among overrides the most specific wins (`ca.iadsdk.apple.com` beats `apple.com`).
- `device.name` is never `null`. A new phone is "Device 1", "Device 2", … until it is renamed with `POST /api/devices/{id}` or the sensor sends its name (`--names`). Numbering starts over after a wipe.
- A device whose `device_id` is a loopback address (`127.0.0.1`, `::1`) is the box asking its own sensor (the self-test in the start checklist), not a phone. It is named `box self-test` and takes no device number. Leave it out of device lists and counts.
- `blocked` (also inside `snapshot`, and as the answer of block and unblock) carries `"covers"`: for each blocked company, the list of names the block covers, e.g. `{"Example Ads": ["example-ads.com", "exads.net"]}`. Every name also covers everything under it. An empty list means no domain of that company is known, so nothing is blocked. A blocked domain covers itself and its subdomains only.
- `hit.ts` is on the backend's clock, the same clock as `session.started`. The sensor runs on another machine, so the backend shifts each batch to make its newest event "now"; the spacing inside a batch is kept.

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

**Added by BOX: history, read from Postgres**

```
GET  /api/history/sessions?limit=50        stored sessions, newest first
GET  /api/history/top-companies?limit=10   per app label, the most contacted companies across all stored sessions
POST /api/history/clear                    deletes all stored sessions, their hits and the lab-phone list -> {"cleared": true}
```

```json
{"sessions": [
  {"id": "<uuid>", "device_id": "10.42.0.23", "device_name": "Test iPhone A", "label": "<app name>",
   "started": 1760070000.0, "stopped": 1760070090.0, "hits": 87, "blocked": 5, "hidden_attempts": 2, "companies": 14,
   "top_companies": [["Example Ads", 14], ["Example Analytics", 9]]}
]}
{"labels": [
  {"label": "<app name>", "sessions": 2, "hits": 170, "hidden_attempts": 4,
   "top_companies": [{"company": "Example Ads", "category": "advertising", "hits": 28, "blocked": 3, "sessions": 2}]}
]}
```

- `hits`, `companies` and `top_companies` leave out hidden-traffic attempts; those are in `hidden_attempts`. `blocked` counts lookups blocked from the UI.
- Wipe never deletes finished sessions. `POST /api/history/clear` is the only thing that does, and it is meant to be a deliberate button. The kb mirror and the AI cache stay.

- All three answer `503` with `{"detail": "no database configured"}` or `{"detail": "database not reachable"}` when there is no database. Hide the history view then; everything else keeps working.
- `stopped` is `null` for a session that is still running. `top_companies` in a session holds its five most contacted companies; `limit` on the second endpoint is companies per label.
- `category` is the company's most frequent category under that label. `sessions` inside a company is the number of sessions it appeared in.
- Sessions without a label are listed by the first endpoint and left out of the second.

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
- **Added by BOX:** `stats` also carries `"blocked"` (lookups blocked from the UI) and `"hidden_attempts"` (guard-list lookups; these are left out of `by_category` and `top_companies`).
- **Added by BOX:** the backend calls all three. `label_check` is optional: if it exists, its sentence becomes the verdict of the label endpoint below. How the calls are made is in `docs/AI-QUICKSTART.md`.

`data/ai_cache_seed.json` (**proposed by BOX, AI owner may change**): precomputed answers, loaded at startup if the file exists.

```json
{ "domains": { "odd.example.io": { "company": "Example Analytics", "category": "analytics", "confidence": 0.7 } } }
```

- Same fields as a `classify_domains` answer, keyed by the exact host name (no walking up the name). The kb is asked first; a seeded name then shows with `source: "ai"`, is never sent to the model, and survives a wipe.
- **The live demo never waits on AI.**
- Config comes from `.env`: `AI_BASE_URL`, `AI_TOKEN`, `AI_MODEL` (OpenAI-compatible `/chat/completions`).

**The model server** (set up by AI; recorded here by BOX)

- Hardware: the AMD server has an AMD Radeon PRO W7900 (gfx1100, 48 GB of video memory), 128 cores and 503 GB of memory, and runs Ubuntu 24.04.
- Software: Ollama, listening on `127.0.0.1:11434` on that server only, with no API key. Its protection is that nothing outside the server can reach it except through SSH.
- From the machine the backend runs on, it is reached through an SSH tunnel (`amd` is the SSH name of the server there, with key authentication):

  ```
  ssh -N -L 8081:127.0.0.1:11434 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes amd
  ```

  `-N`: no remote command, only the tunnel. `-L 8081:127.0.0.1:11434`: local port 8081 leads to Ollama's port on the server. `ServerAliveInterval=30`: notice a dead connection within about a minute. `ExitOnForwardFailure=yes`: stop at once if the port cannot be forwarded, instead of sitting there uselessly.
- Backend `.env`: `AI_BASE_URL=http://127.0.0.1:8081/v1`, `AI_TOKEN=unused` (a placeholder; Ollama ignores it), `AI_MODEL=<model>`.
- **Added by BOX:** `health` carries `"ai_endpoint"`: `true` or `false` for "the model server answers at `AI_BASE_URL`" (checked every 15 s with a request to `/models`), or `null` when no `AI_BASE_URL` is set. It is about the server and the tunnel. `health.ai` stays what it was: whether the last call made by `ai.py` worked.

### Privacy labels (stretch): `data/labels/<app-slug>.json`

Written by BOX from each app's App Store label (text or screenshots).

```json
{"app": "<app name>", "source_url": "<App Store link>", "checked": "<date>",
 "data_used_to_track_you": [], "data_linked_to_you": [], "data_not_linked_to_you": [], "data_not_collected": false}
```

**Added by BOX: the fact-check endpoint** (works without AI and without the database)

```
GET /api/label-check            the label for the session's app name, next to what the session contacted
GET /api/label-check?app=<name> the same, against another label
```

```json
{"session": {"device_id": "10.42.0.23", "label": "<app name>", "started": 1760070000.0, "stopped": null},
 "label": {"app": "<app name>", "…": "the label file, as is"},
 "observed": {"seconds": 95, "lookups": 87, "blocked": 5, "hidden_attempts": 2,
              "by_category": {"advertising": 41, "vendor": 16},
              "companies": [{"company": "Example Ads", "category": "advertising", "hits": 14}],
              "advertising_companies": 9, "tracking_companies": 12},
 "level": "mismatch",
 "verdict": "The label lists nothing under \"Data Used to Track You\", but this session contacted advertising servers of 9 companies.",
 "verdict_by": "rules",
 "rule_verdict": "The label lists nothing under \"Data Used to Track You\", but this session contacted advertising servers of 9 companies.",
 "note": "Tattle sees which servers a phone looks up, not what is sent to them."}
```

- The session is the running one, or the one that just stopped. A label matches when its `app` field or its file name equals the session's app name (case and punctuation ignored). Label files are re-read on every call.
- `level` is `mismatch`, `consistent`, `no-label` or `no-session`. `label` and `observed` are `null` where there is nothing to show. It always comes from the rules.
- `rule_verdict` is always the rule-based sentence: the facts line. `verdict` is the sentence to show big: the AI's (`ai.label_check`), once there is one, otherwise the same rule-based sentence. `verdict_by` is `"rules"` or the model's name.
- The endpoint never waits for the AI. The first call answers with the rules and asks the model in the background; a later call (poll every few seconds while the panel is open) carries the AI's sentence. The model is asked again only when new lookups arrived, and at most every 10 s.
- `companies` holds up to 20, most contacted first, each with its most frequent category. `tracking_companies` counts companies with advertising, analytics, social or fingerprinting lookups.
- The sentences say "advertising servers of N companies": N counts every company with at least one advertising lookup. The show screen's "advertising" counter counts companies *mostly* contacted for advertising, so it can be lower.
- The rules: "no data collected" but tracking companies contacted is a mismatch; nothing under "Data Used to Track You" but advertising companies contacted is a mismatch; everything else is consistent. Always "contacted", never "sent".

### Postgres (provided): `backend/sql/schema.sql`

- Tables: `kb_domains` (seeded from the kb), `devices`, `sessions`, `hits` (only for `persist` devices), `ai_cache`.
- If the DB is unreachable, the backend keeps running in memory and reports `health.db = false`.

**Added by BOX: what exactly gets stored**
- The backend applies `schema.sql` itself each time it connects, and copies the kb into `kb_domains`.
- A session is recorded while its device has `persist: true`: one `sessions` row, plus a `hits` row for each hit of that device during the session. So: mark the phone first, then start the session.
- Not stored: anything from a device that is not marked, and hits outside a session. Marking a phone mid-session records from that moment on; unmarking stops it.
- **Wipe** deletes the running session's rows (the session and its hits). Finished sessions stay, as history.
- After a wipe or a restart every phone is unmarked again. The backend never restores `persist` from the database: hotspot addresses get reused, and a guest's phone must not inherit it.
- `ai_cache` only receives answers for names that a `persist` device looked up. It is loaded at startup, so those names are classified at once and the model is not asked again.
- `POST /api/history/clear` deletes all sessions, hits and device rows on purpose.
- If our database user may not create tables, the backend keeps running without the database and says so in `health.db_error`. The one-time manual fix is in `backend/README.md`.

### Names are untrusted, and other limits (added by BOX)

- A phone chooses the names it looks up, and DNS allows any bytes in them. The sensor only resolves and reports **plain host names**: labels of letters, digits, `-` and `_`, separated by dots, 253 characters at most. Anything else is answered `REFUSED`, never forwarded, never shown, and counted in `health.malformed`. The backend applies the same rule to every event again.
- **Frontend: put names on the page as text, never as HTML.** That goes for `domain`, `company`, `device.name`, session labels and summaries. Company names and summaries can come from a model; device names and labels are typed by people.
- Device ids must be IP addresses. Blocked domains must be host names. Free text is cut to printable characters and a maximum length (device name 64, label and company 100).
- Requests are limited: 1 MB per body, 2,000 events per batch, 500 blocks, 256 devices, 50 WebSocket clients.
- Requests that change something (every `POST`), and WebSocket connections, are refused with `403` when they come from a page on another site. A page served by the backend itself, or by a dev server on the same machine (`localhost`), is fine. The API still has no login.
- The backend's own pages (`/debug`, `/present`) are served with a content security policy that runs only their own script.
- The show screen's files at `/` are served with a policy that allows only files from the backend itself (script, style, font, image; nothing inline, nothing from the internet), and with `Cache-Control: no-cache`, so a reload always shows the latest edit.

### Ports

- sensor: UDP/TCP 5300 (not 5353: that's mDNS, often already taken on Linux)
- backend: 8000, inside the VM on the box laptop (it also serves the frontend at `/`)
- no frontend dev server: the frontend is plain files read by the backend at each request

Env vars are listed in `.env.example`.

## Repo layout

```
README.md            what it is + how to run (points here)
.gitignore
.env.example         copy to .env, fill in, never commit .env
docs/TEAM.md         this file
docs/PITCH.md        demo script + talking points
docs/CHALLENGES.md   running log of problems and AI tools used
docs/FRONT-QUICKSTART.md  run the backend with replayed traffic; real examples of every message
docs/AI-QUICKSTART.md     what ai.py must expose and how the backend calls it
docs/RUNBOOK.md           cold laptop to demo-ready in two minutes, and the switch to replay mode
docs/PROJECT-GUIDE.md     the whole project in one self-contained file, for pasting into an AI chat
sensor/              DNS resolver that runs on the box (the laptop itself, not the VM)
box/                 scripts to bring the hotspot up/down on the box (Linux + NetworkManager)
backend/app/         FastAPI app (main, kb lookup, state, db, ai), plus two plain pages: /debug (operator console) and /present (fallback view)
backend/start.sh     one command to start the backend for the demo
backend/sql/         schema.sql
frontend/            the show screen served at /: index.html, app.css, app.js, assets/ (plain files, no build step)
data/kb.json         tracker knowledge base (built by tools/build_kb.py)
data/kb_overrides.json
data/ai_cache_seed.json   optional precomputed AI answers
data/labels/         App Store privacy labels for demo apps (hand-entered)
data/replays/        recorded sessions from OUR test phones only (anonymized)
tools/               fake_sensor.py (replays events into the backend), build_kb.py, try_ai.py (exercises ai.py), selfcheck.py
```

## Running it

- Exact commands live in each folder's README. Owners keep them current.
- **Dev (no hotspot needed):** run the backend, then `tools/fake_sensor.py` with a file from `data/replays/`. It feeds the backend exactly as a live phone would.
- **Demo (on the box):** start the backend in the VM (`bash backend/start.sh`), then on the laptop itself `box/box-up.sh` and the sensor. The short order is in `docs/RUNBOOK.md`, the full checklist in `box/README.md`.
- **The screens:** `/` is the show screen for the judges (`frontend/README.md` has its keys). `/debug` is the operator console. If the show screen ever fails, the backend serves a plain presenter view at `/present` (companies as coloured blocks, a counter, the summary, the privacy banner) and the controls at `/debug`.

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
3. **AMD model server reachable from the backend's machine** (AI).
   - Pass: with the SSH tunnel up, `curl http://127.0.0.1:8081/v1/models` answers, and `health.ai_endpoint` is `true`.
   - Fallback: template summaries plus AI answers precomputed in the notebook and saved to `data/ai_cache_seed.json`.
4. **Provided Postgres reachable from a laptop over a phone hotspot** (AI).
   - Fallback: Postgres in a container on the box. We keep the feature but probably lose the track.
5. **Tracker-heavy demo app** (BOX, once test 1 passes).
   - Find 2–3 free iPhone apps that light up fast, then pick the demo app.

## Judging logistics

- Teams go to the judges: 2 min setup, 6 min judging and questions, 2 min teardown.
- The box must already be running when we walk over: hotspot up, test iPhone joined, demo app installed, page full-screen, laptop not allowed to sleep, chargers packed.
- The checklist is in `docs/PITCH.md`.
