# Runbook: cold laptop to demo-ready in two minutes

One page for the walk to the judges' table. Details and troubleshooting are in `box/README.md`; this is only the order.

Placeholders, fill them in once and keep this page open: `<vm-name>` (the VM in libvirt), `<vm-ip>` (its `192.168.122.x` address), `<wifi-interface>` (from `iw dev`).

Re-checked on Saturday evening against what exists. Marked **(untried)** where a step has not been done on the real laptop yet.

## Done once, before the day

These are not part of the two minutes. Without them the two minutes don't hold.

- VM: `backend/.venv` exists (backend/README.md). The show screen at `/` needs no build: it is the plain files in `frontend/`.
- VM: a backend that was started before the last change to `backend/app/` or to the knowledge base still runs the old code. Stop it and start it again (step 2). Files in `frontend/` need only a reload of the page.
- VM, only for the AI or the database: a `.env` in the repo root (copy `.env.example`, fill in). `start.sh` reads it when the backend starts, so it has to be there before step 2. Without `.env` the backend runs with no AI and no database, and the demo works.
- Host: copies of `sensor/` and `box/` in one folder, and `sensor/.venv` exists (box/README.md, step 5).
- Host: OpenSnitch has lasting allow rules for the sensor (DNS to `9.9.9.9`, HTTP to `<vm-ip>` port 8000).
- Host: the VM's address is pinned (box/README.md, "A fixed address for the VM"), so `<vm-ip>` never changes.
- Host: the laptop is set not to sleep or blank its screen.
- The test iPhone has joined `Tattle-Demo` once, so it joins by itself. Demo app installed. Cellular data off.

## The two minutes

The clock starts at the host's desktop. Steps 4 to 6 are typed on the host, in the folder that holds `sensor/` and `box/`.

| # | Where | Do | What you should see |
| --- | --- | --- | --- |
| 1 | Host | `virsh -c qemu:///system start <vm-name>` (skip if the VM is running). Plug in the USB-tethered phone. | `Domain '<vm-name>' started` |
| 2 | VM, terminal | `bash backend/start.sh` | `Tattle backend starting. / shows the show screen (frontend/).` and the addresses |
| 3 | VM, own terminal, only with `.env` and an AI module | `ssh -N -L 8081:127.0.0.1:11434 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes amd` | no output; within 15 s the `ai endpoint` pill on `/debug` shows a tick |
| 4 | Host | `mullvad disconnect` | `Disconnected` |
| 5 | Host | `sudo bash box/box-up.sh <wifi-interface>` and type the hotspot password (it may take up to half a minute) | `HOTSPOT: … runs on <interface>` with `10.42.0.1/24`, and `INTERNET: …` naming the other interface |
| 6 | Host, own terminal | `sensor/.venv/bin/python sensor/tattle_sensor.py --backend http://<vm-ip>:8000` | `sensor: listening on …`, then `backend: connected` |
| 7 | Host, browser, window 1 | open `http://<vm-ip>:8000/` and press `F11` (the browser's own full screen) | the show screen: "live" and "sensor: live" are green, top right |
| 8 | Host, browser, window 2 | open `http://<vm-ip>:8000/debug` and leave it behind window 1 (`Alt`+`Tab` switches) | the operator console: `websocket ✓ sensor ✓` |
| 9 | iPhone | unlock it; it joins `Tattle-Demo` | "Device 1" appears under the phone in the middle within seconds |
| 10 | Window 1 | press `W` twice | "Wiped. Nothing is kept." The counters start again from zero |
| 11 | Window 1, when the judge has the phone | press `S`, type the app's name, Enter | the app's name under the phone; the seconds counter runs |

- Steps 5 and 6 belong together: between them, phones on the hotspot have no DNS.
- The backend comes first (step 2) so that the sensor says `backend: connected` at once. If the sensor does start first, it waits for the backend and loses nothing.
- **Full screen: `F11`, not `F`.** The page's own `F` key also fills the screen, but in that mode the browser keeps `Esc` for itself: the first `Esc` leaves full screen instead of closing a panel. With `F11`, `Esc` reaches the page. This is how browsers behave in general; **(untried)** on the laptop's browser.
- After the wipe, an idle iPhone still looks things up now and then (mostly its maker's servers), so a few bubbles can come back within seconds. That is not a failed wipe.
- Keys on the show screen: `S` start or stop a session, `W` `W` wipe, `H` how it works, `C` operator panel, `Esc` close. Pressing `S` while a session runs stops it at once: don't type on window 1 during a session.
- To show blocking: click the company's bubble (its detail panel opens: who the company is, and every server name the phone asked for), click "Block <company>" there, then have the app closed and opened again. A block stops new connections, not ones already open. Leave the panel open to watch "refused ×N" climb, or close it with `Esc`, the Close button or a click outside. The same button unblocks.
- Window 2 (`/debug`) is for what the show screen cannot do: rename a phone, mark it `persist`, see the health pills and the malformed count. It can also start, stop, block and wipe if window 1 misbehaves.
- "box self-test" on `/debug` is the laptop's own test lookup, not a phone. The show screen never shows it.
- For the history view: after the wipe, mark our own phone as `persist` (on `/debug`), then start the session. Never a judge's phone. (The backend stores it; no screen shows the history yet.)
- What each command does: `virsh … start` boots the VM; `start.sh` runs the backend on port 8000 for the host to reach, with the show screen at `/`, the operator console at `/debug` and the fallback view at `/present`; `mullvad disconnect` turns the VPN off; `box-up.sh` creates the hotspot and the DNS redirect; the sensor answers the phones' lookups and reports each name to the backend.

**Step 3, the tunnel to the model server.** Ollama on the AMD server listens on its own `127.0.0.1` only; the tunnel makes it appear as port 8081 in the VM. `-N`: no remote command. `-L 8081:127.0.0.1:11434`: local port 8081 leads to Ollama. `ServerAliveInterval=30`: notice a dead connection. `ExitOnForwardFailure=yes`: stop at once if port 8081 is taken. It needs `AI_BASE_URL=http://127.0.0.1:8081/v1`, `AI_TOKEN=unused` and `AI_MODEL=<model>` in `.env`. Check by hand: `curl http://127.0.0.1:8081/v1/models` (`curl` fetches the address and prints the answer).

- Where this stands (Saturday 19:40): from the VM, `ssh amd` works with the key and Ollama answers, but it lists **no models yet**, and `backend/app/ai.py` does not exist. Until both are there, skip step 3.
- The tunnel alone turns the show screen's chip to "AI: on" (the chip also follows `ai endpoint`), even while no AI module is loaded. With the chip on and no module, nothing is classified or explained.
- The demo works without it.

Measured in the VM: `backend/start.sh` answers requests about a second after Enter. The whole sequence has **not been timed** on the real hardware yet.

## If anything fails: replay mode

Decide fast. If the phone's lookups are not on screen 20 seconds after it joined, switch. Nothing below needs the hotspot, the sensor or the host's Wi-Fi.

1. Press `W` twice (wipe).
2. In the VM, second terminal: `python3 tools/fake_sensor.py data/replays/demo-synthetic.jsonl --loop`
   Replays a session into the backend, over and over (two minutes per pass). A phone called "Test iPhone A" appears. Blocking works. `--speed 2` plays it twice as fast.
3. Press `S`. The Phone field must say "Test iPhone A" (choose it if the real phone is listed too). Type the app's name, Enter. From then on the screen shows only that phone, so stray lookups from the real phone do not mix in.
4. Say it: "We're switching to a simulated session." The only replay so far is made-up traffic; no recording of a real phone exists yet.

Run through in the VM on Saturday evening against a test backend, in a scripted browser: session by keyboard, detail panels, block a company, block and unblock a single name, stop, wipe.

Other failures:

| What broke | Do |
| --- | --- |
| The host cannot open the page (`<vm-ip>` unreachable) | Use the browser inside the VM: `http://127.0.0.1:8000/`. Replay mode works there too. |
| The show screen at `/` is broken | `http://<vm-ip>:8000/present` on the big screen (companies, counter, summary), window 2 (`/debug`) for Start, Block and Wipe. Both are single files inside the backend and share no code with the show screen. |
| The show screen says "reconnecting…" | The backend stopped: step 2 again. The page reconnects by itself within seconds and starts empty, like after a wipe: the session is gone, press `S` again. The sensor reconnects by itself and delivers what it queued. |
| "sensor: silent" on the show screen | The sensor stopped: step 6 again. Phones recover by themselves within seconds. |
| A panel is open and `Esc` left full screen instead | `F11` again; close panels with the Close button or a click outside. |
| The page looks like an old version | Reload it (`Ctrl`+`R`). If a new feature is missing after that, the backend runs old code: step 2 again. |
| "AI: off" on the show screen (the `ai endpoint` pill on `/debug` shows a cross) | The tunnel dropped: step 3 again. Meanwhile unknown names stay "Not identified", the summary is the built-in one and the detail panel shows the tracker list's sentence. Don't mention it unless asked. |
| The phone joined but shows nothing | Is cellular data off? Does the sensor's terminal say `backend: connected`? Otherwise: replay mode. |
| An OpenSnitch prompt appears | Allow, "forever". Lookups stall until it is answered. |

## Afterwards

Ctrl+C in the sensor's terminal, then `sudo bash box/box-down.sh` on the host (removes the firewall rules, the hotspot and `tattle0`). In the VM, Ctrl+C stops the tunnel, and Ctrl+C stops the backend and forgets everything captured.
