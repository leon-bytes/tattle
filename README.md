# Tattle

**Who is your phone talking to?** Hand someone a phone, they open an app, and a screen fills with every company that app quietly contacts: live, in plain English, with one click to block one.

## What it is

Tattle is a laptop that acts as a Wi-Fi hotspot. A phone joins it, with nothing installed on the phone. Before an app can connect to a server it has to ask for the server's address (a DNS lookup), and on Tattle's Wi-Fi the laptop is the one it asks. So Tattle sees the name of every server the phone looks up, and never what is sent afterwards.

- Each name is turned into a company and a category (advertising, analytics, social, fingerprinting, content delivery, the app's own servers) with an open tracker list plus a short hand-written list.
- A live screen shows the phone in the middle and one bubble per company. A click on a bubble says who the company is and lists every server name the phone asked for.
- One more click blocks the company: Tattle answers "that name does not exist", the app cannot reach it, and a counter shows it trying again while the app keeps working.
- Optional: an open-weights language model names the servers no list knows, writes a summary and explains a company. Its answers are marked as guesses, and the screen never waits for it.
- Optional: the app's App Store privacy label next to what the app contacted.

It was built in one weekend at a hackathon, and tested with a real iPhone on the real hotspot.

## How it works

```
phone --Wi-Fi--> laptop
                 |- hotspot (NetworkManager), password-protected
                 |- firewall rule: every DNS packet from the hotspot --> sensor
                 |- sensor (sensor/): answers the phone, forwards to a public resolver,
                 |     refuses blocked names, reports each name to the backend
                 |- backend (backend/): name --> company and category, state in memory,
                 |     pushes every lookup to the screen over a WebSocket
                 '- show screen (frontend/): plain HTML, CSS and JavaScript, served by the backend
```

The interfaces between the parts, with their data shapes, are in [docs/TEAM.md](docs/TEAM.md).

## Run it

Without any hardware, from the repository root (Python 3.11 or newer):

```sh
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --no-access-log
python3 tools/fake_sensor.py data/replays/demo-synthetic.jsonl --loop
```

- Line 1 makes a private Python environment in `backend/.venv`, so nothing is installed system-wide. Line 2 installs the backend's packages into it (once).
- Line 3 starts the backend on port 8000. `--app-dir backend` says where the code is; `--no-access-log` keeps it from printing a line per request.
- Line 4, in a second terminal, plays a simulated phone session into the backend with its original timing. `--loop` starts over at the end. The session is made up: real public server names plus a fictional game.

Then open <http://127.0.0.1:8000/>. Press `S`, type an app name and press Enter to start a session; click a bubble for its details and the Block button. <http://127.0.0.1:8000/debug> is a plain operator page.

Tests:

```sh
backend/.venv/bin/python -m pytest backend/tests
backend/.venv/bin/python tools/selfcheck.py
```

The first runs the backend's tests. The second starts its own backend and sensor on this machine and checks the whole loop without Wi-Fi; it needs the sensor's environment too ([sensor/README.md](sensor/README.md)).

More:

- The backend, its settings and the optional database: [backend/README.md](backend/README.md)
- The DNS sensor on its own: [sensor/README.md](sensor/README.md)
- The real thing, hotspot and all (Linux with NetworkManager): [box/README.md](box/README.md), and the short start order in [docs/RUNBOOK.md](docs/RUNBOOK.md)
- The show screen and its keys: [frontend/README.md](frontend/README.md)
- The language model (optional; settings in [.env.example](.env.example)): [docs/AI-QUICKSTART.md](docs/AI-QUICKSTART.md)
- What went wrong on the way, and the AI tools we used: [docs/CHALLENGES.md](docs/CHALLENGES.md)
- Demo script and talking points: [docs/PITCH.md](docs/PITCH.md)

## Privacy

- Tattle reads server names only, never content.
- Our own test phones only, plus people who explicitly opt in. The network has a password and an honest name.
- What is captured stays in memory and is wiped after each demo. Nothing is written to disk unless we mark one of our own phones for it.
- Phones show as "Device 1", "Device 2": their own names are not read.
- A name the lists do not know may be sent to our own model server for a guess. Nothing else about the phone goes there.

## Limits

- "Contacted" never means "sent your data": we see who was looked up, not what was said.
- We see a phone, not an app. Lookups are counted for the app someone was using at the time; the phone's own background traffic can mix in.
- An app that brings its own encrypted DNS, connects straight to an address, or reuses an answer it already had gets past us.
- A block stops new connections, not ones that are already open.
- The backend has no login. Run it only on a machine and a network you control.

## Credits and licences

- **Our code:** MIT License, see [LICENSE](LICENSE).
- **`data/kb.json` is not covered by the MIT License.** It is derived from the [Disconnect tracking protection list](https://github.com/disconnectme/disconnect-tracking-protection) (built by `tools/build_kb.py`) and is shared under that list's licence, [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/): with credit to Disconnect, for non-commercial use only, and with changes shared under the same licence.
- Typeface: Inter, under the SIL Open Font License ([frontend/assets/fonts/LICENSE-Inter.txt](frontend/assets/fonts/LICENSE-Inter.txt)).
