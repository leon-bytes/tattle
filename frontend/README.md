# Frontend: the show screen

The judge-facing screen, served by the backend at `/`. Plain HTML, CSS and JavaScript: no framework, no build step, no `npm install`, nothing loaded from the internet. Owner: BOX.

| File | What it is |
| --- | --- |
| `index.html` | the page: stage, counters, cards, the three overlays, and the logo as an inline drawing |
| `app.css` | the look. Colours and sizes are variables at the top |
| `app.js` | everything live: the WebSocket, the bubble layout, the detail panel with blocking, the operator keys |
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
- Click a bubble to open that company's **detail panel**:
  - who the company is: at once a sentence from our tracker list, then the AI's explanation when it arrives ("AI is thinking…" meanwhile). A badge says which one is on screen: "FROM OUR TRACKER LIST" or "FROM THE AI". The text is asked from `GET /api/explain` and kept, so opening the same company again is instant;
  - every server name the phone asked for, most looked up first: how often, when last, and whether it is blocked now or was refused. A long name is cut in its front part (the end says whose it is); the full name shows on hover;
  - "Block <company>" for the whole company and a "Block" button per server name; the same buttons unblock. A large badge says what is blocked right now: "BLOCKED", "2 OF 7 BLOCKED" or "NOT BLOCKED";
  - `Esc`, the Close button or a click outside closes it.
- A blocked company's bubble is grey and dashed and counts "blocked ×N". A bubble with only some names blocked keeps its colour and gets a dashed outline.
- "Not identified" opens the same panel with the servers no list knows, each with the AI's guess where there is one, and a block button per name.
- Counters: companies, how many of them are mostly advertising and mostly analytics, seconds into the session, blocked attempts, hidden-traffic attempts (Private Relay and encrypted-DNS lookups we refused).
- "In plain words": the read-aloud summary from the backend; it names the model when the AI wrote it.
- "App Store privacy label": shown when `data/labels/` has a label for the session's app name (`GET /api/label-check`, asked every 4 s).
- "Live: what the phone asks for": the latest server names with the company each belongs to. It gives way to the label card when there is one.
- The privacy banner, always.

## Operator keys

| Key | Does |
| --- | --- |
| `S` | no session: opens the panel with the app-name field ready (Enter starts); the last app name is marked, so typing replaces it. Session running: stops it |
| `W` `W` | wipe everything (two presses within 3 s) |
| `H` | How it works |
| `C` | the operator panel (phone, app name, start, stop, wipe) |
| `F` | full screen. For the demo use the browser's own `F11` instead: in the `F` kind of full screen the browser keeps `Esc` for itself, so the first `Esc` leaves full screen instead of closing a panel |
| `Esc` | close a panel |

Which phone is shown: the session's phone (also after the session ended, until the next one or a wipe); without a session, the phone that sent the latest lookup. The laptop's own test lookups ("box self-test") are never shown.

## The logo

A turtle, drawn as inline SVG in `index.html` (no image file). The browser-tab icon is made from that same drawing when the page loads, so there is one drawing to change. It is seen from above, and its shell is a radar screen: two rings, a sweep and one blip. To change it, change the shapes inside `<svg id="logo">`. Colours are written out in the drawing (the same values as the variables in `app.css`), because the tab icon has to work without the stylesheet.

## Rules this code follows

- Names from the network go on the page with `textContent`, never as markup. No `innerHTML`, no `setAttribute`, no inline script or style: `backend/tests/test_security.py` checks this, and the backend serves these files with a policy that allows only files from the backend itself.
- The WebSocket reconnects by itself after a second; message types the page does not know are ignored.
- The detail panel's rows are updated in place and keep their order while the pointer is on them: with lookups arriving several times a second, a button must not move away under a click.
- The tracker list's sentence in the detail panel is always built by the page, from the bubble as it is now (`listSentence`). From `GET /api/explain` the page takes only the AI's text, who wrote it, and `pending`. The backend's copy of the list sentence dates from the moment the panel asked, and a company's category can change as lookups arrive.
- No external requests at all: the demo has to work without internet.
