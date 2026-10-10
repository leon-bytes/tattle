# Frontend: the show screen

The judge-facing screen, served by the backend at `/`. Plain HTML, CSS and JavaScript: no framework, no build step, no `npm install`, nothing loaded from the internet. Owner: BOX.

| File | What it is |
| --- | --- |
| `index.html` | the page: stage, counters, cards, the two overlays |
| `app.css` | the look. Colours and sizes are variables at the top |
| `app.js` | everything live: the WebSocket, the bubble layout, blocking, the operator keys |
| `assets/tattle-architecture.png` | the diagram behind "How it works" (a copy of `docs/tattle-architecture.png`) |
| `assets/fonts/` | Inter (variable, latin), SIL Open Font License, with its license text |

## See it

```
bash backend/start.sh                                                   # the backend, port 8000
python3 tools/fake_sensor.py data/replays/demo-synthetic.jsonl --loop   # made-up traffic, second terminal
```

Open <http://127.0.0.1:8000/>. Press `S`, type an app name, Enter. The backend reads these files at each request, so after an edit a reload is enough.

## What is on it

- The phone in the middle; one bubble per company it contacted. Colour and a text tag (`AD`, `AN`, `SO`, `FP`, `CDN`, `OWN`, `?`) give the category, the size follows the number of lookups, and a bubble pulses at each new lookup. "Not identified" collects the servers no list or model knows.
- Click a bubble to block that company: it turns grey and dashed, its count becomes "blocked ×N", and a bar offers Undo. Click it again to unblock.
- Counters: companies, how many of them are mostly advertising and mostly analytics, seconds into the session, blocked attempts, hidden-traffic attempts (Private Relay and encrypted-DNS lookups we refused).
- "In plain words": the read-aloud summary from the backend; it names the model when the AI wrote it.
- "App Store privacy label": shown when `data/labels/` has a label for the session's app name (`GET /api/label-check`, asked every 4 s).
- "Live: what the phone asks for": the latest server names with the company each belongs to. It gives way to the label card when there is one.
- The privacy banner, always.

## Operator keys

| Key | Does |
| --- | --- |
| `S` | no session: opens the panel with the app-name field ready (Enter starts). Session running: stops it |
| `W` `W` | wipe everything (two presses within 3 s) |
| `H` | How it works |
| `C` | the operator panel (phone, app name, start, stop, wipe) |
| `F` | full screen |
| `Esc` | close a panel |

Which phone is shown: the session's phone (also after the session ended, until the next one or a wipe); without a session, the phone that sent the latest lookup. The laptop's own test lookups ("box self-test") are never shown.

## Rules this code follows

- Names from the network go on the page with `textContent`, never as markup. No `innerHTML`, no `setAttribute`, no inline script or style: `backend/tests/test_security.py` checks this, and the backend serves these files with a policy that allows only files from the backend itself.
- The WebSocket reconnects by itself after a second; message types the page does not know are ignored.
- No external requests at all: the demo has to work without internet.
