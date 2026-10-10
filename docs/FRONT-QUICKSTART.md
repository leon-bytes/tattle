# Frontend quickstart

Everything you need to build against the backend without the hotspot: three commands to get a live stream of replayed phone traffic, then one real example of every message. The contract itself is in [TEAM.md](TEAM.md); this page shows it running.

## 1. Run it (5 minutes)

You need Python 3.11 or newer. All commands from the repo root. Tested on Linux only; the macOS and Windows lines are the standard equivalents and have not been run.

**Linux / macOS**

```sh
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --no-access-log
```

**Windows (PowerShell or cmd)**

```
py -3 -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt
backend\.venv\Scripts\uvicorn app.main:app --app-dir backend --port 8000 --no-access-log
```

Leave that running. In a second terminal, start the fake phone (plain Python, nothing to install):

```sh
python3 tools/fake_sensor.py data/replays/demo-synthetic.jsonl --loop        # Windows: py -3 tools\fake_sensor.py data\replays\demo-synthetic.jsonl --loop
```

- It replays a made-up 2-minute session of one phone ("Test iPhone A") opening an ad-heavy game, then starts over.
- `--speed 4` plays it four times faster.
- Blocking works in replay: block a company and its next lookups arrive as blocked.

If your UI is not ready at demo time, the backend has a plain fallback at `/present`. It is insurance, not a replacement.

Check it: open <http://127.0.0.1:8000/debug>. Rows should scroll in. That page uses only the API below, so its source (`backend/app/debug.html`, one file, about 200 lines) is a working example of nearly everything here.

## 2. Connect from Vite

The backend listens on port 8000. In `vite.config.js`, proxy both the REST calls and the WebSocket:

```js
server: { proxy: { "/api": "http://127.0.0.1:8000", "/ws": { target: "ws://127.0.0.1:8000", ws: true } } }
```

Then ``new WebSocket(`ws://${location.host}/ws`)`` and `fetch("/api/…")` work in dev and in the built app, which the backend serves from `frontend/dist`.

## 3. WebSocket `/ws`: what arrives

You only listen; the page never sends on the socket. The first message is always a `snapshot` with everything so far. After that, single messages. Reconnect if the socket closes: you get a fresh snapshot.

All examples below are real, captured from one run of the replay.

**`snapshot`**: first message after connecting (and the body of `GET /api/state`)

```json
{"type": "snapshot",
 "devices": [{"device_id": "10.42.0.23", "name": "Test iPhone A", "persist": true}, {"device_id": "10.42.0.31", "name": "Device 2", "persist": false}],
 "hits": [{"type": "hit", "device_id": "10.42.0.23", "domain": "captive.apple.com", "company": "Apple", "category": "vendor", "source": "override", "blocked": false, "block_reason": null, "ts": 1791655719.712},
          {"type": "hit", "device_id": "10.42.0.23", "domain": "_dns.resolver.arpa", "company": null, "category": "unknown", "source": "unknown", "blocked": true, "block_reason": "guard", "ts": 1791655719.724},
          … 191 more hits …],
 "blocked": {"companies": [], "domains": ["tracker.example.com"], "covers": {}},
 "session": null,
 "summary": {"type": "summary", "device_id": "10.42.0.23", "text": "While Demo Game was open for 28 seconds, this phone contacted mostly advertising companies, led by Google, Apple, AppLovin.", "by": "demo-model"},
 "health": {"db": true, "db_error": null, "ai": true, "sensor_seen": 1791655748.4878745, "kb": 4482, "malformed": 1}}
```

**`device`**: a phone appeared, or its name or `persist` flag changed

```json
{"type": "device", "device_id": "10.42.0.23", "name": "Test iPhone A", "persist": true}
{"type": "device", "device_id": "10.42.0.31", "name": "Device 2", "persist": false}
```

Live phones are "Device 1", "Device 2", … until someone renames them. The replay's phone carries its name in the file. A device whose `device_id` is `127.0.0.1` (or `::1`) is the box testing its own sensor, named "box self-test": leave it out of device lists and counts.

**`hit`**: one lookup. This is the stream that feeds the bubbles.

```json
{"type": "hit", "device_id": "10.42.0.23", "domain": "graph.facebook.com", "company": "Meta", "category": "social", "source": "list", "blocked": false, "block_reason": null, "ts": 1791655720.63}
{"type": "hit", "device_id": "10.42.0.23", "domain": "captive.apple.com", "company": "Apple", "category": "vendor", "source": "override", "blocked": false, "block_reason": null, "ts": 1791655719.712}
{"type": "hit", "device_id": "10.42.0.23", "domain": "api.puzzle-garden-game.example", "company": null, "category": "unknown", "source": "unknown", "blocked": false, "block_reason": null, "ts": 1791655720.547}
{"type": "hit", "device_id": "10.42.0.23", "domain": "ms.applovin.com", "company": "AppLovin", "category": "advertising", "source": "list", "blocked": true, "block_reason": "user", "ts": 1791655734.365}
{"type": "hit", "device_id": "10.42.0.23", "domain": "_dns.resolver.arpa", "company": null, "category": "unknown", "source": "unknown", "blocked": true, "block_reason": "guard", "ts": 1791655719.724}
```

- `category`: `advertising`, `analytics`, `social`, `fingerprinting`, `content`, `vendor`, `unknown`. `company` is `null` when unknown.
- `source`: `list` (tracker list), `override` (hand fix), `ai`, `unknown`.
- Line 4, `block_reason: "user"`: a tracker someone blocked, still trying. Count these as **blocked attempts**.
- Line 5, `block_reason: "guard"`: a **hidden-traffic attempt**. The phone tried encrypted DNS or Private Relay and we said no. Show and count these on their own: not as blocked attempts, and not in any company's bubble.
- The same name from the same phone within 2 s is one hit, so the count is "lookups", not packets.

**`classified`**: the AI put a name to a domain that arrived as `unknown`. Update the hits you already have for that `domain`.

```json
{"type": "classified", "domain": "api.puzzle-garden-game.example", "company": "Puzzle Garden Games", "category": "vendor", "source": "ai", "confidence": 0.6}
```

**`summary`**: the plain-English sentence. About every 3 s while a session runs (`by: "template"`), once more when it stops, and again if the AI writes a better one.

```json
{"type": "summary", "device_id": "10.42.0.23", "text": "In 2 seconds, Demo Game contacted 14 companies: 8 advertising (AppLovin, AppsFlyer, Unity and 5 more), 2 analytics (Google, Sentry), 1 social (Meta), and 3 others. 4 hidden-traffic attempts were refused.", "by": "template"}
{"type": "summary", "device_id": "10.42.0.23", "text": "While Demo Game was open for 28 seconds, this phone contacted mostly advertising companies, led by Google, Apple, AppLovin.", "by": "demo-model"}
```

**`blocked`**: the full block list after any change. `covers` says which names each company block covers (each name also covers everything under it); show it, so people see what "block AppLovin" means.

```json
{"type": "blocked", "companies": ["AppLovin"], "domains": [], "covers": {"AppLovin": ["adjust.com", "applovin.com", "applvn.com", "axon.ai", "mopub.com"]}}
```

**`session`**: a session started, or stopped (`null`)

```json
{"type": "session", "session": {"device_id": "10.42.0.23", "label": "Demo Game", "started": 1791655719.5896008}}
{"type": "session", "session": null}
```

**`health`**: every 5 s, and at once when something changes

```json
{"type": "health", "db": true, "db_error": null, "ai": false, "sensor_seen": 1791655719.9024026, "kb": 4482, "malformed": 0}
```

- `sensor_seen` is the time the sensor last called in (seconds since 1970, backend clock). Older than about 10 s means the sensor is gone.
- `db` and `ai` may be `false`: the demo works without both. `db_error` says why when the database is configured but unusable. `kb` is the number of known domains.
- `malformed` counts lookups we refused because the name was not a plain host name (see section 6). Worth a small counter on screen.

**`wiped`**: forget everything on screen. An empty `blocked` and a `null` `session` follow.

```json
{"type": "wiped"}
```

## 4. REST: what you send

Every answer is JSON. Each change is also broadcast on the socket, so you can ignore the response and let the socket update your state.

```
POST /api/block  {"company": "AppLovin"}
→ 200  {"type": "blocked", "companies": ["AppLovin"], "domains": [], "covers": {"AppLovin": ["adjust.com", "applovin.com", "applvn.com", "axon.ai", "mopub.com"]}}

POST /api/unblock  {"company": "AppLovin"}
→ 200  {"type": "blocked", "companies": [], "domains": [], "covers": {}}

POST /api/block  {"domain": "tracker.example.com"}
→ 200  {"type": "blocked", "companies": [], "domains": ["tracker.example.com"], "covers": {}}

POST /api/block  {}
→ 422  {"detail": "give a company or a domain"}

POST /api/devices/10.42.0.23  {"name": "Test iPhone A", "persist": true}
→ 200  {"type": "device", "device_id": "10.42.0.23", "name": "Test iPhone A", "persist": true}

POST /api/session/start  {"device_id": "10.42.0.23", "label": "Demo Game"}
→ 200  {"type": "session", "session": {"device_id": "10.42.0.23", "label": "Demo Game", "started": 1791655719.5896008}}

POST /api/session/stop
→ 200  {"type": "session", "session": null}

POST /api/wipe
→ 200  {"type": "wiped"}

GET /api/health
→ 200  {"db": true, "db_error": null, "ai": true, "sensor_seen": 1791655748.4878745, "kb": 4482, "malformed": 1}

GET /api/state
→ 200  the snapshot above
```

**Label fact-check** (the app's App Store label next to what the session contacted; no AI or database needed)

```
GET /api/label-check            uses the running session, or the one that just stopped
GET /api/label-check?app=<name> the same session against another label
```

```json
{"session": {"device_id": "10.42.0.23", "label": "Demo Game", "started": 1791655719.5896008, "stopped": null},
 "label": {"app": "Demo Game", "source_url": "https://apps.apple.com/app/id0000000000", "checked": "2026-10-10", "data_used_to_track_you": [], "data_linked_to_you": ["Identifiers", "Usage Data"], "data_not_linked_to_you": ["Diagnostics"], "data_not_collected": false},
 "observed": {"seconds": 28, "lookups": 184, "blocked": 13, "hidden_attempts": 8,
              "by_category": {"advertising": 110, "vendor": 38, "analytics": 20, "content": 10, "social": 6}, "companies": [{"company": "Google", "category": "advertising", "hits": 38}, {"company": "Apple", "category": "vendor", "hits": 30}, {"company": "AppLovin", "category": "advertising", "hits": 26}, {"company": "Unity", "category": "advertising", "hits": 18}, … 10 more …], "advertising_companies": 11, "tracking_companies": 12},
 "level": "mismatch",
 "verdict": "Demo Game's label lists nothing under \"Data Used to Track You\", yet in 27 seconds it contacted advertising companies such as Google.",
 "verdict_by": "demo-model",
 "rule_verdict": "The label lists nothing under \"Data Used to Track You\", but this session contacted 11 advertising companies.",
 "note": "Tattle sees which servers a phone looks up, not what is sent to them."}
```

- `level`: `mismatch`, `consistent`, `no-label` (then `label` is `null`) or `no-session` (then `observed` is `null` too).
- `verdict` is the sentence to show big. `rule_verdict` is always the rule-based sentence: show it as the small "facts" line. `verdict_by` says who wrote `verdict`: `"rules"`, or the model's name.
- The endpoint never waits for the AI. In this run the first call answered `"verdict_by": "rules"` and the call a second later carried the model's sentence, shown above. So poll every few seconds while the panel is open.
- A label file exists only for apps the AI owner entered in `data/labels/`. The session's app name must match the label's `app` or its file name.

**History** (only with the database; without it all three answer `503 {"detail": "no database configured"}`, so hide the view)

```
GET /api/history/sessions
→ 200  {"sessions": [{"id": "6f041f31-e10a-4161-ab0b-9d1a63c9b002", "device_id": "10.42.0.23", "device_name": "Test iPhone A", "label": "Demo Game", "started": 1791655719.589601, "stopped": 1791655748.48913, "hits": 184, "blocked": 13, "hidden_attempts": 8, "companies": 14, "top_companies": [["Google", 38], ["Apple", 30], ["AppLovin", 26], ["Unity", 18], ["Meta", 12]]}]}

GET /api/history/top-companies?limit=3
→ 200  {"labels": [{"label": "Demo Game", "sessions": 1, "hits": 184, "hidden_attempts": 8, "top_companies": [{"company": "Google", "category": "advertising", "hits": 38, "blocked": 0, "sessions": 1}, {"company": "Apple", "category": "vendor", "hits": 30, "blocked": 0, "sessions": 1}, {"company": "AppLovin", "category": "advertising", "hits": 26, "blocked": 13, "sessions": 1}]}]}

POST /api/history/clear
→ 200  {"cleared": true}
```

- Only sessions of phones marked `persist` are stored. In `hits`, `companies` and `top_companies`, hidden-traffic attempts are left out; they are in `hidden_attempts`.
- `history/clear` deletes all stored sessions. Wipe does not.

## 5. Things that bite

- **Names on screen:** always use `device.name`. It is never empty.
- **A block stops new connections, not open ones.** After a block, an app can keep talking over a connection it already has; blocked lookups only start arriving when it reconnects (phones re-ask within about 10 s). Say so next to the block button, for example "close and reopen the app". Offer blocking by company: one app uses several names.
- **Times:** `ts`, `started`, `stopped` and `sensor_seen` are seconds since 1970 on the backend's clock, as floats. Multiply by 1000 for `new Date()`.
- **Sessions and hits:** a hit belongs to the session when `hit.device_id === session.device_id` and `hit.ts >= session.started`.
- **Nothing here needs a login**, and nothing is stored unless a phone is marked `persist`.
- **Privacy banner**, always visible: "Reads server names only, never content. Nothing is kept after you leave."

## 6. Security notes for FRONT

We are a security team and judges may poke at the screen. The one rule: **everything from the API goes onto the page as text, never as HTML.**

- **Why:** a phone chooses the names it looks up, and someone will try `<img src=x onerror=alert(1)>.example.com`. The sensor and the backend refuse names that are not plain host names (they are counted in `health.malformed` and never reach you), but that is the first line of defence, not the only one. Company names and summaries can come from a model; device names and session labels are typed by people and are passed on as typed.
- **In React:** `{hit.domain}` in JSX is safe, it is always text. Never use `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML` or `insertAdjacentHTML` with anything from the API. Outside React, use `textContent`.
- **Not in attributes that run or load:** don't build `href`, `src` or `style` strings from API values. A link to `"https://" + domain` would send a judge's click to a tracker.
- **This applies to:** `hit.domain`, `hit.company`, `device.name`, `session.label`, `summary.text`, `verdict`, `rule_verdict`, `db_error`, and everything in the history and label answers.
- **What the backend refuses.** Real answers from this run:

```
POST /api/events   with one good event and one named x<img src=x onerror=alert(1)>.example.com
→ 200  {"accepted": 2}      the batch is accepted, the bad name is dropped and counted

POST /api/wipe   (sent by a page on another site)
→ 403  {"detail": "cross-site request refused"}
```

- **Other sites:** every `POST` and the WebSocket are refused (`403`) when the page making the request was loaded from another site. Pages served by the backend, or by a dev server on `localhost`, are fine. If you open the Vite dev server through a LAN address instead of `localhost`, leave the proxy's `changeOrigin` at its default (off).
- **Limits you might hit:** 1 MB per request, device name 64 characters, session label and company 100, 500 blocks, 50 WebSocket connections. Over the limit is a `422` (or `413` for size).
- **How we check our own pages:** `/debug` and `/present` insert text only, a test fails if either uses an HTML-building call, and both are served with a content security policy that runs nothing but their own script. Feel free to copy that.

The `classified` message, the second `summary` and the history examples came from a run with a stand-in AI module and a local Postgres. Without them the shapes are the same; those messages just never arrive.
