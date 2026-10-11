# AI quickstart

What `backend/app/ai.py` has to provide, how the backend uses it, and how to try it before plugging it in. The demo runs without this file; with it, unknown names get classified and the summary gets better. The contract is in [TEAM.md](TEAM.md); this page is the practical side.

## 1. What `ai.py` exposes

Four `async` functions. The first two are needed; the last two are optional.

```python
async def classify_domains(domains: list[str]) -> dict[str, dict] | None
async def summarize(stats: dict) -> str | None
async def label_check(label: dict, stats: dict) -> str | None   # optional
async def explain_company(company: str, category: str, domains: list[str]) -> str | None   # optional, new on Saturday evening
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

await explain_company("Unity", "advertising",
                      ["auction.unityads.unity3d.com", "outcome-ssp.supersonicads.com", "webview.unityads.unity3d.com",
                       "logs.ironsrc.mobi", "config.unityads.unity3d.com", "init.supersonicads.com"])
# must return a short plain paragraph (usually three to five sentences, 500 characters at most): who the company is,
# what kinds of servers the app contacted, and what it most likely uses them for,
# judging by the server names. For example:
"Unity makes a game engine and runs one of the big ad networks for mobile games. The names contacted here are its ad auction and ad display servers, so this app most likely shows Unity ads."
```

Rules for the answers:

- `category` is one of `advertising`, `analytics`, `social`, `fingerprinting`, `content`, `vendor`, `unknown`. Anything else is read as `unknown`.
- `company` is a string or `None`. `confidence` is a number from 0 to 1.
- Leaving a name out of the answer is fine: it stays `unknown`.
- On any failure return `None`, within 8 s. Don't raise.
- Say "contacted", never "sent your data": we see which servers were looked up, not what was sent. This matters most in `explain_company`, where a model is tempted to write "sends your location to…". It may say what a server is for; it may not claim what was sent.
- `blocked` is lookups blocked from the UI. `hidden_attempts` is the phone trying encrypted DNS or Private Relay; those are not in `by_category`.

## 2. How the backend calls it

- **Reaching the model.** Ollama on the AMD server listens on that server's `127.0.0.1:11434` only and has no key. The backend's machine reaches it through an SSH tunnel: `ssh -N -L 8081:127.0.0.1:11434 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes amd`. With that running, `.env` holds `AI_BASE_URL=http://127.0.0.1:8081/v1`, `AI_TOKEN=unused` (a placeholder: send it or not, Ollama ignores it) and `AI_MODEL=<model>`. Quick check: `curl http://127.0.0.1:8081/v1/models`.
- **`health.ai_endpoint`.** The backend asks `AI_BASE_URL` for its model list every 15 s and shows the result as `health.ai_endpoint` (the `ai endpoint` pill on `/debug`). It tells you the server and tunnel are up, even before `ai.py` exists. `health.ai` is separate: whether your last call worked.
- **`AI_MODEL` has to be the name Ollama lists.** The same request tells the backend whether `AI_MODEL` is in the server's list (`health.ai_model`, the `model` pill on `/debug`). If it is not, the screens say "AI: no model". On Sunday 06:30 the server listed one model, `qwen2.5-14b:latest` (a model file imported under that name, not `qwen2.5:14b`), and the demo VM's `.env` now says exactly that. If you load another model, tell BOX its name.
- **If the tunnel is refused:** the server's SSH server needs `AllowTcpForwarding local` in `/tmp/amd-oneclick-sshd_config`, and a container restart probably resets it. The steps, and a way round that needs no forwarding, are in `docs/RUNBOOK.md` ("If the tunnel stops working").
- **Import.** At startup the backend imports `app.ai`. If the file is missing, or the import fails (a missing package, a typo), it prints one line and runs without AI. Config comes from the environment: `AI_BASE_URL`, `AI_TOKEN`, `AI_MODEL`.
- **Packages.** `backend/requirements.txt` has no HTTP client. Add what you import (for example `httpx`) to that file.
- **`classify_domains`.** A background task looks once a second for names nobody knows, takes up to 10, and makes one call at a time. Names are exact host names, lowercase. The hit is already on screen as `unknown`; your answer upgrades it and is broadcast as a `classified` message.
  - A name is never sent if the kb, the overrides, the seed file or the database cache knows it. Each name is asked once until the next wipe.
  - `None`, an exception, or no answer in 10 s: `health.ai` turns `false`, and the same names are retried after 15 s.
- **`summarize`.** Called once, when a session stops. The template sentence is shown first; yours replaces it if it arrives within 10 s. The `by` field on screen is `AI_MODEL`.
- **`label_check`.** Optional. If your module has it, `GET /api/label-check` shows your sentence as the verdict and keeps the rule-based sentence next to it as the facts line. It gets the label file's content and the same `stats` as `summarize`.
  - The endpoint never waits: it answers with the rules and asks you in the background; the next call shows your sentence.
  - You are asked again only when the session has new lookups, at most every 10 s. Your sentence is cut to 400 characters.
- **`explain_company`.** Optional. It feeds the detail panel that opens when someone clicks a company on the show screen (`GET /api/explain`).
  - You get the company's name, the category it was mostly contacted for in this session, and up to 20 of its server names, most looked up first. The names are the evidence: "what is it most likely doing in this app" should follow from them.
  - The panel opens at once with a sentence built from the tracker list ("Unity: an advertising company, according to our tracker list.") and shows "AI is thinking…". Your text replaces it when it arrives; the list's sentence stays below it as the facts line, and the panel says which of the two is on screen.
  - You are asked once per company and session. The answer is kept until the next wipe or session start, so reopening a company costs nothing. After a failure you are asked again at the earliest 15 s later, and only if the panel is opened again.
  - Your text is cut to 500 characters and shown as plain text.
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
explain_company(company, category, domains)   [optional]
  note  explain_company is not there, which is fine: the detail panel keeps the tracker list's sentence
RESULT: the backend can use this module
```

Then see it live: start the backend and the replay ([FRONT-QUICKSTART.md](FRONT-QUICKSTART.md), section 1) and open <http://127.0.0.1:8000/debug>. The `puzzle-garden-game.example` hosts in the replay are unknown to every list on purpose: they are your test names. The `ai` pill turns green after the first good call.

On the show screen (<http://127.0.0.1:8000/>, the page the judges see; BOX owns it now) your work appears in five places: a company you classified gets a bubble with a dotted outline and the tag "AI guess"; the card "In plain words" shows your summary with "written by <model>"; the card "App Store privacy label" shows your `label_check` sentence with the rule-based one below it; a click on a company opens its detail panel, which shows your `explain_company` text under the badge "FROM THE AI"; and "AI: on" is green, top right, once one of your calls has worked (until then it reads "AI: no model" in amber if the server does not list `AI_MODEL`, and "AI: off" otherwise).

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
- `data/kb_overrides.json`: hand fixes, same shape. An override wins over `kb.json` for its name and everything under it. It holds Apple's system domains, the big CDNs, phone-only SDK hosts, and the own servers of four apps seen in the live tests (Netflix, Discord, OpenAI and Reddit, as `vendor`). Other well-known apps are left for your classifier.
- **BOX edited this file on Saturday evening, from what the live screen showed** (it is yours: change it back if you disagree). Reddit's own servers moved from `content` to `vendor`, with its two tracking-pixel hosts kept as the list has them. Microsoft's sign-in hosts were added (`microsoftonline.com`, `msftauth.net`, `msauth.net`, as `content` like `microsoft.com` in the list). And `linkedin.com` and `licdn.com` are now the company "LinkedIn": the list files them under the owner, Microsoft, as `social`, so a phone that looked up LinkedIn hosts made Microsoft appear as a social network.
- The note at the top of `tools/build_kb.py` lists what v1 decided and what deserves a second look.
- Restart the backend to load changes. `health.kb` shows how many domains it read.

**Privacy labels** are written by BOX now (moved on Saturday afternoon); you only need the shape, because `label_check` receives one. One file per demo app, `data/labels/<app-slug>.json`, entered from the App Store page:

```json
{"app": "Demo Game", "source_url": "<App Store link>", "checked": "<date>",
 "data_used_to_track_you": [], "data_linked_to_you": ["Identifiers", "Usage Data"],
 "data_not_linked_to_you": ["Diagnostics"], "data_not_collected": false}
```

- `GET /api/label-check` puts the label next to what the session contacted and gives a one-line verdict. It matches the session's app name against `app` or the file name, and re-reads the files on every call, so no restart is needed.
- The verdict rules: "no data collected" but tracking companies contacted is a mismatch; nothing under "Data Used to Track You" but advertising companies contacted is a mismatch; otherwise consistent.
- Whatever your functions return is shown as plain text and trimmed (company 80 characters, summary 600, label verdict 400, company explanation 500). Don't return markup.

## 6. Where `ai.py` stands (Sunday 07:15), and what BOX changed in it

Your file was tried against the live model before it went in. It parsed every answer and its wording filter worked. What follows was measured, then changed. Your structure, your names and your seed mechanism are kept.

**Measured on the server** (`qwen2.5-14b:latest`, through the tunnel):

- About 40 tokens a second. Requests are answered **one at a time**: two at once took 2.9 s and 5.0 s.
- A model that is not loaded takes about 5 s to load. Ollama unloads it after 5 idle minutes.
- Your file, ten names in one `classify_domains` call: 5.9 to 7.3 s. The limit is 8 s.
- Now: ten names 3.5 to 4.7 s; `explain_company` 1.7 to 4.0 s (median 2.4 s, 39 companies); `summarize` and `label_check` about 2 s.
- A burst of 30 unknown names with four company panels opened meanwhile: 29 names classified within 18 s, every explanation within 6 s, the backend's own answers in 2 to 9 ms throughout.
- 76 real server names the list lacks: all answered; 5 named the wrong company.

**What was changed, and why:**

1. **The model's name.** `DEFAULT_MODEL` was `qwen2.5:14b`; the server lists `qwen2.5-14b:latest`. Every call got "404 Not Found".
2. **The `.env` loading at import was removed.** `python-dotenv` *is* installed in the backend's venv (the web server brings it), so importing the module put the whole `.env` into the process: every test run and every backend started by hand would have used the real model server, and later the database. Settings come from the environment; `backend/start.sh` reads `.env`.
3. **`keep_alive: "12h"` in every request**, so the model stays loaded (see the 5 s above).
4. **`classify_domains` asks for one line per name** (`number|company|category|confidence`, the names numbered) instead of a JSON object. Under half the tokens, and a cut-off answer still yields its complete lines. `_parse_json_object` went; `_clean_entry` stayed and also reads "ad networks" as `advertising` and "cdn" as `content`, and drops a company name that is "-", "none" or not in Latin letters.
5. **One 8 s limit for the whole of `classify_domains`**, however many chunks of 10 it takes (it was 8 s per chunk). Entries that are not text are skipped.
6. **The classify prompt** says which words are categories, how to spell the big companies (Google, Apple, Meta, Amazon, Microsoft, as our list does), that a name under an app's own domain is `vendor`, and gives a worked example with made-up names.
7. **`summarize` gets plain lines instead of the stats as JSON**, with the shares already worked out ("advertising 58 (60%)") and our categories in plain words ("the phone maker's or the app's own servers", never "vendor"). A sentence with a number that was not in those lines is rejected: the model wrote "39 of 42 (93%)" where it had been given 40 of 42 (95%). With no company to name the model is not asked. The phone's name (`stats["device"]`) is no longer sent to the server.
8. **`label_check`: the module decides which way the verdict goes**, by the backend's rules, and the model words it. With the rules only in the prompt, the model said "does not match" for a label that matched, and once added a note about its own word count. The same number check applies.
9. **The `explain_company` prompt** gives the three sentences their jobs, makes the second begin with "The app contacted" plus real server names, asks for 45 words, and has one worked example (a company that is not in the demo). Apple's system servers get a note that these are the phone's own lookups. Before, most answers repeated the prompt's own example list ("ad auctions, ad display, analytics").
10. **The check of every text is per sentence now.** Kept: your pattern for "sent your data". Added: "tracks you", "your location" and the like; the label's section title "Data Used to Track You" is allowed. A sentence that fails loses its guess if its fact can be kept ("The app contacted x, most likely for sending usage data" becomes "The app contacted x."), otherwise it is dropped. Dropped too: a sentence with letters from another script (one answer ended in Chinese), a sentence cut off by `max_tokens`, anything after a blank line. A text without the word "contacted" is `None`.
11. **Small things:** the seed path follows `AI_CACHE_SEED_PATH`; the log line for a failed call names the error (a timeout has no text); `max_tokens` lowered to match the shorter answers; line endings are now Unix ones.

**Added later on Sunday morning (08:15 to 08:45), asked for by BOX and from what the demo's uplink showed:**

12. **`explain_company` answers more fully.** The prompt now says what a lookup is, lists the kinds of servers a name can point to (ad auction, ad server, measurement, settings, logs and crashes, sign-in, content delivery, an app's own API) and asks what the app most likely uses them for. The model judges the length: usually three or four sentences, 300 to 450 characters. `max_tokens` is 140.
13. **The connection into the tunnel is kept open between calls** (`_post_tunnel`). With the demo's uplink (a tethered phone), opening a new connection through the tunnel took 0.9 to 1.8 s per call; a call on an open one takes about 0.45 s. A kept connection that has died gets one retry on a new one; a timeout gets none. Other addresses are called as before.
14. **An answer cut off by `max_tokens` loses its unfinished sentence** (`finish_reason`). A host name's dot had made a cut-off sentence look finished.
15. **The wording check also catches the passive form** ("where usage data are sent").

Measured at 08:20 with all of this, on the tethered uplink, while the live backend was using the model too: `explain_company` 2.2 to 4.0 s, median 3.1 s (13 companies). Of that, the model itself takes 1.4 to 2.5 s.

**Left as it was, for you to decide:** `status()`, `model_name()` and `template_summary()` are not called by anything in the repo (the last one names `tools/build_seed.py`, which is not here). The seed file's three extra keys are written down in `docs/TEAM.md`.

**Known weak spots:** the model names a wrong company with confidence now and then (5 of 76 above), and confidence is almost always 0.9 or 0.6, so it says little. Explanations of analytics companies tend to say "tracking usage". Nothing was tried with a real phone's traffic yet.

Tests for the parts that need no model: `backend/tests/test_ai.py`.
