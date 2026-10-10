# AI quickstart

What `backend/app/ai.py` has to provide, how the backend uses it, and how to try it before plugging it in. The demo runs without this file; with it, unknown names get classified and the summary gets better. The contract is in [TEAM.md](TEAM.md); this page is the practical side.

## 1. What `ai.py` exposes

Three `async` functions. The first two are needed; the third is optional.

```python
async def classify_domains(domains: list[str]) -> dict[str, dict] | None
async def summarize(stats: dict) -> str | None
async def label_check(label: dict, stats: dict) -> str | None   # optional
```

Real calls from a replay run:

```python
await classify_domains(["api.puzzle-garden-game.example", "cdn.puzzle-garden-game.example"])
# must return something like:
{"api.puzzle-garden-game.example": {"company": "Puzzle Garden Games", "category": "vendor", "confidence": 0.6},
 "cdn.puzzle-garden-game.example": {"company": "Puzzle Garden Games", "category": "vendor", "confidence": 0.6}}

await summarize({"device": "Test iPhone A", "label": "Demo Game", "seconds": 27,
                 "by_category": {"advertising": 109, "analytics": 20, "social": 6, "content": 10, "vendor": 38},
                 "top_companies": [["Google", 38], ["Apple", 30], ["AppLovin", 25], ["Unity", 18], ["Puzzle Garden Games", 12]],
                 "blocked": 13, "hidden_attempts": 8})
# must return one or two plain sentences, e.g.:
"While Demo Game was open for 27 seconds, this phone contacted mostly advertising companies, led by Google, Apple, AppLovin."
```

Rules for the answers:

- `category` is one of `advertising`, `analytics`, `social`, `fingerprinting`, `content`, `vendor`, `unknown`. Anything else is read as `unknown`.
- `company` is a string or `None`. `confidence` is a number from 0 to 1.
- Leaving a name out of the answer is fine: it stays `unknown`.
- On any failure return `None`, within 8 s. Don't raise.
- Say "contacted", never "sent your data": we see which servers were looked up, not what was sent.
- `blocked` is lookups blocked from the UI. `hidden_attempts` is the phone trying encrypted DNS or Private Relay; those are not in `by_category`.

## 2. How the backend calls it

- **Import.** At startup the backend imports `app.ai`. If the file is missing, or the import fails (a missing package, a typo), it prints one line and runs without AI. Config comes from the environment: `AI_BASE_URL`, `AI_TOKEN`, `AI_MODEL`.
- **Packages.** `backend/requirements.txt` has no HTTP client. Add what you import (for example `httpx`) to that file.
- **`classify_domains`.** A background task looks once a second for names nobody knows, takes up to 10, and makes one call at a time. Names are exact host names, lowercase. The hit is already on screen as `unknown`; your answer upgrades it and is broadcast as a `classified` message.
  - A name is never sent if the kb, the overrides, the seed file or the database cache knows it. Each name is asked once until the next wipe.
  - `None`, an exception, or no answer in 10 s: `health.ai` turns `false`, and the same names are retried after 15 s.
- **`summarize`.** Called once, when a session stops. The template sentence is shown first; yours replaces it if it arrives within 10 s. The `by` field on screen is `AI_MODEL`.
- **`label_check`.** Optional. If your module has it, `GET /api/label-check` shows your sentence as the verdict and keeps the rule-based sentence next to it as the facts line. It gets the label file's content and the same `stats` as `summarize`.
  - The endpoint never waits: it answers with the rules and asks you in the background; the next call shows your sentence.
  - You are asked again only when the session has new lookups, at most every 10 s. Your sentence is cut to 400 characters.
- **`health.ai`** is simply whether the last call worked. It reads `false` until the first success.
- **Nothing waits for you.** The live loop never blocks on these calls.

## 3. Try it without the backend

```sh
backend/.venv/bin/python tools/try_ai.py                  # tests backend/app/ai.py
backend/.venv/bin/python tools/try_ai.py --file draft.py  # tests any file with the same functions
```

- Run `set -a; . ./.env; set +a` first if your module reads `.env` values from the environment (`set -a` exports what the file defines).
- It calls each function once with sample data and the backend's time limit, and checks the shape of the answer.

What a good run looks like (real output, from a stand-in module that only knows the `puzzle-garden-game` hosts):

```
classify_domains(5 names)
  note  answered in 0.2 s
  ok    api.puzzle-garden-game.example: Puzzle Garden Games / vendor / 0.6
  ok    telemetry.puzzle-garden-game.example: Puzzle Garden Games / vendor / 0.6
  ok    cdn.puzzle-garden-game.example: Puzzle Garden Games / vendor / 0.6
  note  metrics.shop-example.io: no answer (allowed; it stays 'unknown' and is not asked again until a wipe)
  note  ads-track.example.net: no answer (allowed; it stays 'unknown' and is not asked again until a wipe)
summarize(stats)
  note  answered in 0.2 s
  ok    summarize: 'While Demo Game was open for 95 seconds, this phone contacted mostly advertising companies, led by Google, AppLovin, Unity.'
label_check(label, stats)   [optional]
  note  answered in 0.2 s
  ok    label_check: 'Demo Game\'s label lists nothing under "Data Used to Track You", yet in 95 seconds it contacted advertising companies such as Google.'
RESULT: the backend can use this module
```

Then see it live: start the backend and the replay ([FRONT-QUICKSTART.md](FRONT-QUICKSTART.md), section 1) and open <http://127.0.0.1:8000/debug>. The `puzzle-garden-game.example` hosts in the replay are unknown to every list on purpose: they are your test names. The `ai` pill turns green after the first good call.

## 4. Caching

- **Database.** If Postgres is configured, the backend stores answers in `ai_cache` and loads them at startup. Only names that one of our own marked phones looked up are stored. You don't have to do anything.
- **Seed file, for the demo apps:** `data/ai_cache_seed.json`. If it exists, it is loaded at startup and those names never reach the model. Format (**proposed by BOX, change it if you like and tell BOX**):

```json
{ "domains": { "odd.example.io": { "company": "Example Analytics", "category": "analytics", "confidence": 0.7 } } }
```

  Same fields as a `classify_domains` answer, keyed by exact host name.

## 5. The other files that are yours

**Knowledge base** (a first version exists so the demo has real data):

```sh
python3 tools/build_kb.py     # downloads Disconnect's list, rewrites data/kb.json; needs internet
```

- `data/kb.json`: about 4,400 domains from Disconnect's list. Never edit by hand; rebuild.
- `data/kb_overrides.json`: hand fixes, same shape. An override wins over `kb.json` for its name and everything under it.
- The note at the top of `tools/build_kb.py` lists what v1 decided and what deserves a second look.
- Restart the backend to load changes. `health.kb` shows how many domains it read.

**Privacy labels:** one file per demo app, `data/labels/<app-slug>.json`, hand-entered from the App Store page:

```json
{"app": "Demo Game", "source_url": "<App Store link>", "checked": "<date>",
 "data_used_to_track_you": [], "data_linked_to_you": ["Identifiers", "Usage Data"],
 "data_not_linked_to_you": ["Diagnostics"], "data_not_collected": false}
```

- `GET /api/label-check` puts the label next to what the session contacted and gives a one-line verdict. It matches the session's app name against `app` or the file name, and re-reads the files on every call, so no restart is needed.
- The verdict rules: "no data collected" but tracking companies contacted is a mismatch; nothing under "Data Used to Track You" but advertising companies contacted is a mismatch; otherwise consistent.
- Whatever your functions return is shown as plain text and trimmed (company 80 characters, summary 600). Don't return markup.
