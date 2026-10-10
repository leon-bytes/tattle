# Backend

FastAPI app on port 8000: takes sensor events, turns names into companies with the kb, and pushes hits to the frontend over `/ws`. Interfaces are in [docs/TEAM.md](../docs/TEAM.md).

Everything captured lives in RAM. `POST /api/wipe` or a restart clears it. The one exception is the optional database, which stores sessions of our own lab phones (see "Database").

## Run (dev, no hotspot)

All commands from the repo root.

```sh
python3 -m venv backend/.venv                                  # once: a private Python environment
backend/.venv/bin/pip install -r backend/requirements-dev.txt  # once: fastapi, uvicorn, psycopg, plus pytest for the tests
```

```sh
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --no-access-log
```

- `--app-dir backend`: where the `app` package lives, so the command works from the repo root.
- `--port 8000`: the port the sensor and the Vite proxy expect. Without `--host` it listens on `127.0.0.1` only.
- `--no-access-log`: optional. Stops one log line per request (the sensor polls every second).
- Optional, dev only: add `--reload --reload-dir backend/app` to restart on code changes. A restart also empties the state.

Then, in a second terminal, feed it the synthetic session (plain Python, no venv needed):

```sh
python3 tools/fake_sensor.py data/replays/demo-synthetic.jsonl --loop
```

- `--loop`: start over when the 2-minute file ends. Optional.
- `--speed 4`: four times faster. Optional. At high speeds (10 and up) some repeated lookups merge, because the backend counts the same name within 2 s once.
- Blocking from the UI works in replay mode: the fake sensor reads the blocklist and sends matching names as blocked.

Open <http://127.0.0.1:8000/> for the show screen (the plain files in `frontend/`; its keys are in `frontend/README.md`), and <http://127.0.0.1:8000/debug> for the operator console: the live event stream, with block, session, rename, persist and wipe buttons.

The start-up line says what was loaded, for example `kb has 4467 domains, 0 seeded AI answers, ai module absent, database not configured`. If `data/kb.json` is missing the backend still runs and every name shows as `unknown`; rebuild it with `python3 tools/build_kb.py`.

`demo-synthetic.jsonl` is made-up traffic (a phone joining, then a free game with ad mediation) using real public hostnames, plus a fictional `puzzle-garden-game.example` that stays `unknown` on purpose.

## Run (demo: in the VM, sensor on the host)

One command, from anywhere:

```sh
bash backend/start.sh
```

It loads `.env` if there is one (as plain `KEY=value` lines; unfilled `<placeholders>` are skipped), prints the addresses to open, and runs the same command as above with `--host 0.0.0.0`, so the host laptop can reach it. The order of the whole demo start is in `docs/RUNBOOK.md`.

- `/` is the show screen: the files in `frontend/`, read at each request (no build step, reload after an edit). Without `frontend/index.html`, `/` redirects to the debug page. `/logo` is a preview of the logo variants, from the same folder.
- `/present` is a plain presenter view (companies as coloured blocks, a counter, the summary, the privacy banner). It is insurance in case the show screen fails; controls stay on `/debug`.

- The host reaches the VM at its `192.168.122.x` address (`ip -4 -brief addr` shows it). The sensor on the host gets `--backend http://<vm-ip>:8000`, and the browser opens `http://<vm-ip>:8000/`.
- The VM's firewall already allows port 8000 on that interface.
- The API has no login. `box/box-up.sh` keeps hotspot phones away from the VM's network; don't expose port 8000 anywhere else.
- The host steps are the checklist in [box/README.md](../box/README.md).

## Check it

```sh
backend/.venv/bin/python -m pytest backend/tests      # unit and API tests, about 2 s; database tests are skipped
backend/.venv/bin/python tools/selfcheck.py           # end to end, about 25 s; needs sensor/.venv too (see sensor/README.md)
```

`selfcheck.py` starts its own backend on port 8099 and a sensor on `127.0.0.1:5300`, replays the synthetic session, sends real DNS queries through the sensor, and checks what arrives on `/ws`. It needs working DNS on this machine and ports 8099 and 5300 free (`--backend-port`, `--sensor-port` change them).

The database tests need a Postgres to talk to. A throwaway one in a container:

```sh
podman run -d --rm --name tattle-pg-test -e POSTGRES_PASSWORD=tattle-test -p 127.0.0.1:55432:5432 docker.io/library/postgres:17-alpine
TEST_DATABASE_URL=postgresql://postgres:tattle-test@127.0.0.1:55432/postgres backend/.venv/bin/python -m pytest backend/tests
podman stop tattle-pg-test
```

- `-d --rm`: run in the background, and delete the container (with its data) when it stops.
- `-e POSTGRES_PASSWORD=…`: password for this throwaway server only.
- `-p 127.0.0.1:55432:5432`: reachable on this machine's port 55432, not from outside.
- Each test creates its own schema and drops it afterwards, so `TEST_DATABASE_URL` is safe to point at a database that has real tables.

## Database (optional)

Set `DATABASE_URL` and the backend connects in the background, creates its tables (`backend/sql/schema.sql`, safe to repeat), and copies the kb into `kb_domains`. Without it, or if the server is away, everything else works and `health.db` is `false`. `health.db_error` then says why in one sentence, and the `db` pill on `/debug` shows it as a tooltip.

**If our database user may not create tables,** `db_error` reads `tables are missing and could not be created (InsufficientPrivilege): …`. Someone who may create them runs the schema once; the backend notices within seconds, no restart needed:

```sh
psql "<url-of-a-user-who-may-create-tables>" -f backend/sql/schema.sql
```

- No `psql` at hand? The same with the backend's own Python:
  `backend/.venv/bin/python -c "import pathlib, psycopg; psycopg.connect('<url>', autocommit=True).execute(pathlib.Path('backend/sql/schema.sql').read_text())"`
- Or paste the file into the provider's SQL console.
- If the tables then belong to a different user than ours, that user also runs:
  `GRANT SELECT, INSERT, UPDATE, DELETE ON kb_domains, devices, sessions, hits, ai_cache TO <our-db-user>;`
  Until then `db_error` reads `no read/write rights on our tables: …`.

What gets stored, and what never does:

- **Stored:** a session while its device is marked `persist: true` (our own lab phones): the session, and each hit of that phone during it. Mark the phone first, then start the session.
- **Never stored:** anything from a phone that is not marked; hits outside a session.
- **Wipe** deletes the running session's rows. Finished sessions stay as history.
- **`POST /api/history/clear`** deletes all stored sessions, their hits and the lab-phone list, on purpose: `curl -X POST http://127.0.0.1:8000/api/history/clear`. The kb copy and the AI cache stay.
- After a wipe or restart every phone is unmarked again. The mark is never restored from the database, because hotspot addresses get reused.
- **AI answers** go to `ai_cache` only for names a marked phone looked up. They are loaded at startup.

History, for the frontend (shapes in docs/TEAM.md):

```
GET  /api/history/sessions?limit=50        stored sessions, newest first, with counts and top companies
GET  /api/history/top-companies?limit=10   per app label: most contacted companies across stored sessions
POST /api/history/clear                    delete all stored history
```

All three answer `503` when no database is configured or reachable.

To try it with the test container from above:

```sh
DATABASE_URL=postgresql://postgres:tattle-test@127.0.0.1:55432/postgres backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --no-access-log
```

Then on `/debug`: pick the device, "Persist on/off", start a session, stop it, and open the "sessions" link.

## Config (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `KB_PATH` | `data/kb.json` | knowledge base; relative paths count from the repo root |
| `KB_OVERRIDES_PATH` | `data/kb_overrides.json` | hand fixes that win over the kb |
| `AI_CACHE_SEED_PATH` | `data/ai_cache_seed.json` | optional precomputed AI answers, loaded at startup |
| `LABELS_DIR` | `data/labels` | App Store privacy labels for the label check |
| `DATABASE_URL` | (none) | Postgres connection string; unset means no database |
| `AI_MODEL` | (none) | used as the `by` name on AI summaries and stored with cached AI answers |
| `AI_BASE_URL` | (none) | the model server, for `ai.py`. If set, the backend also checks every 15 s whether it answers and shows that as `health.ai_endpoint`. With the SSH tunnel: `http://127.0.0.1:8081/v1` |
| `AI_TOKEN` | (none) | for `ai.py`. `unused` is fine for a server without a key |

The backend reads environment variables only, not `.env` itself. To load `.env` into a shell: `set -a; . ./.env; set +a` (`set -a` exports everything the file defines).

## How it behaves

- **Clock:** the sensor runs on another machine, so each batch of events is moved onto the backend's clock (its newest event becomes "now"). Hit times and session times are therefore comparable.
- **Dedupe:** the same device and name within 2 s is one hit (iPhones ask A, AAAA and HTTPS at once).
- **Ignored names:** anything ending in `.arpa` or `.local`, and names without a dot.
- **Device names:** phones are "Device 1", "Device 2", … until renamed (`POST /api/devices/{id}`) or named by a sensor started with `--names`.
- **Knowledge base:** `data/kb_overrides.json` is searched first, so an override wins over `data/kb.json` for its name and everything under it.
- **Blocking:** by company or by domain. `/api/blocklist` expands each blocked company into its kb domains. Blocked lookups still arrive as hits, with `blocked: true`. The `blocked` message says what each company block covers (`covers`), and `/debug` shows it. A block acts on new lookups only: an open connection stays open until the app reconnects.
- **The box itself:** lookups from a loopback address (the self-test in the start checklist, or `dig` on the same machine) appear under the device "box self-test", which takes no device number and is left out of device counts.
- **Hidden-traffic attempts:** guard-list lookups (the phone trying encrypted DNS or Private Relay) arrive as hits with `block_reason: "guard"`. They are counted on their own everywhere: not as blocked trackers, and not towards a company.
- **Label check:** `GET /api/label-check` returns the App Store privacy label for the session's app name next to what the session contacted, with a rule-based one-line verdict. Labels are the files in `data/labels/`; the shape is in docs/TEAM.md.
- **Company explanation:** `GET /api/explain?company=<name>` describes one company for the show screen's detail panel. It answers at once with a sentence built from the kb ("AppLovin: an advertising company, according to our tracker list."). If `ai.py` has `explain_company`, that is asked in the background and a later call carries its text, which is then kept until the next wipe or session. The shape is in docs/TEAM.md.
- **Summary:** a few short sentences made to be read aloud, for example "In 40 seconds, Demo Game contacted 9 companies: 4 advertising (Google, AppLovin, Unity and 1 more), 2 analytics (Sentry, AppsFlyer), and 3 others." A company counts once, under what it was mostly contacted for.
- **Untrusted input:** names that are not plain host names are dropped and counted in `health.malformed`. Device ids must be IP addresses, blocked domains must be host names, free text is cut to printable characters and a maximum length. Limits: 1 MB per request, 2,000 events per batch, 500 blocks, 256 devices, 50 WebSocket clients.
- **Other websites:** every `POST` and every WebSocket connection is refused when it comes from a page on another site (the `Origin` header). There is still no login.
- **The two pages** (`/debug`, `/present`) insert everything as text and are served with a policy that runs only their own script.
- **AI is optional.** If `app/ai.py` is missing or fails to import, the backend runs without it and `health.ai` stays `false`. With it, unknown names are sent to `classify_domains` in batches of 10 in the background, `summarize` upgrades the summary after a session stops, `label_check` (if the module has it) supplies the label verdict, and `explain_company` (if the module has it) supplies the text of the show screen's detail panel. A failing or slow call only flips `health.ai`. Details for the AI owner: docs/AI-QUICKSTART.md.
- **Database is optional.** Writes are queued and done in the background; nothing on the live path waits for them. If the server is away, up to 5000 writes wait, oldest dropped first.
- **Memory bounds:** the last 5000 hits are kept for the snapshot.
