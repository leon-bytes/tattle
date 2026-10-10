# Runbook: cold laptop to demo-ready in two minutes

One page for the walk to the judges' table. Details and troubleshooting are in `box/README.md`; this is only the order.

Placeholders, fill them in once and keep this page open: `<vm-name>` (the VM in libvirt), `<vm-ip>` (its `192.168.122.x` address), `<wifi-interface>` (from `iw dev`).

## Done once, before the day

These are not part of the two minutes. Without them the two minutes don't hold.

- VM: `backend/.venv` exists (backend/README.md). The show screen at `/` needs no build: it is the plain files in `frontend/`.
- Host: copies of `sensor/` and `box/` in one folder, and `sensor/.venv` exists (box/README.md, step 5).
- Host: OpenSnitch has lasting allow rules for the sensor (DNS to `9.9.9.9`, HTTP to `<vm-ip>` port 8000).
- Host: the VM's address is pinned (box/README.md, "A fixed address for the VM"), so `<vm-ip>` never changes.
- The test iPhone has joined `Tattle-Demo` once, so it joins by itself. Demo app installed. Cellular data off.

## The two minutes

The clock starts at the host's desktop. Steps 2 to 4 are typed on the host in the folder that holds `sensor/` and `box/`.

| # | Where | Do | What you should see |
| --- | --- | --- | --- |
| 1 | Host | `virsh -c qemu:///system start <vm-name>` (skip if the VM is running). Plug in the USB-tethered phone. | `Domain '<vm-name>' started` |
| 2 | Host | `mullvad disconnect` | `Disconnected` |
| 3 | Host | `sudo bash box/box-up.sh <wifi-interface>` and type the hotspot password (it may take up to half a minute) | `HOTSPOT: … runs on <interface>` with `10.42.0.1/24`, and `INTERNET: the normal Wi-Fi … is on <interface>` |
| 4 | Host, own terminal | `sensor/.venv/bin/python sensor/tattle_sensor.py --backend http://<vm-ip>:8000` | `sensor: listening on …`, later `backend: connected` |
| 5 | VM, terminal | `bash backend/start.sh` | `Tattle backend starting.` and the addresses |
| 5a | VM, own terminal, only if the AI is used | `ssh -N -L 8081:127.0.0.1:11434 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes amd` | no output; within 15 s the `ai endpoint` pill on `/debug` turns green |
| 6 | Host, browser | open `http://<vm-ip>:8000/` and press `F` (full screen) | the show screen: "live" and "sensor: live" are green, top right |
| 7 | iPhone | unlock it; it joins `Tattle-Demo` | "Device 1" appears under the phone in the middle within seconds |
| 8 | Page | press `W` twice | "Wiped. Nothing is kept." and an empty screen, ready for the judge |
| 9 | Page, when the judge has the phone | press `S`, type the app's name, Enter | the app's name under the phone; the seconds counter runs |

- Steps 3 and 4 belong together: between them, phones on the hotspot have no DNS.
- Step 5 can be done while steps 2 to 4 run. The sensor waits for the backend and loses nothing.
- Step 5a is the SSH tunnel to the model server (Ollama on the AMD server, which listens on its own `127.0.0.1` only). `-N`: no remote command. `-L 8081:127.0.0.1:11434`: local port 8081 leads to Ollama. `ServerAliveInterval=30`: notice a dead connection. `ExitOnForwardFailure=yes`: stop at once if port 8081 is taken. It needs `AI_BASE_URL=http://127.0.0.1:8081/v1` and `AI_TOKEN=unused` in `.env`. Check by hand: `curl http://127.0.0.1:8081/v1/models`. The demo works without it.
- Keys on the show screen: `S` start or stop a session, `W` `W` wipe, `H` how it works, `C` operator panel, `F` full screen, `Esc` close. A second browser tab with `/debug` is the operator console (rename a phone, mark it `persist`, block a single domain).
- To show blocking: click the company's bubble (its detail panel opens: who the company is, and every server name the phone asked for), click "Block <company>" there, then have the app closed and opened again. A block stops new connections, not ones already open. Leave the panel open to watch "refused ×N" climb, or close it with `Esc`. The same button unblocks.
- "box self-test" on the page is the laptop's own test lookup, not a phone.
- For the history view: after the Wipe, mark our own phone as `persist` (on `/debug`), then start the session. Never a judge's phone.
- What each command does: `virsh … start` boots the VM; `mullvad disconnect` turns the VPN off; `box-up.sh` creates the hotspot and the DNS redirect; `start.sh` runs the backend on port 8000 for the host to reach, with the show screen at `/`, the operator console at `/debug` and the fallback view at `/present`.

Measured in the VM: `backend/start.sh` answers requests about a second after Enter. The host steps have not been timed on the real hardware yet.

## If anything fails: replay mode

Decide fast. If the phone's lookups are not on screen 20 seconds after it joined, switch. Nothing below needs the hotspot, the sensor or the host's Wi-Fi.

1. Press `W` twice (wipe).
2. In the VM, second terminal: `python3 tools/fake_sensor.py data/replays/demo-synthetic.jsonl --loop`
   Replays a recorded session into the backend, over and over. The screen fills exactly as with a live phone, and blocking works.
3. Say it: "We're switching to a simulated session." (Until we have recorded our own phone, the only replay is made-up traffic.)

Other failures:

| What broke | Do |
| --- | --- |
| The host cannot open the page (`<vm-ip>` unreachable) | Use the browser inside the VM: `http://127.0.0.1:8000/`. Replay mode works there too. |
| The show screen at `/` is broken | `http://<vm-ip>:8000/present` on the big screen (companies, counter, summary), `http://<vm-ip>:8000/debug` in a second tab for Start, Block and Wipe. Both are single files inside the backend and share no code with the show screen. |
| The backend stopped | `bash backend/start.sh` again. The screen starts empty, like after a Wipe; the sensor reconnects by itself and delivers what it queued. |
| The sensor stopped | Step 4 again. Phones recover by themselves within seconds. |
| "AI: off" on the show screen (the `ai endpoint` pill on `/debug` is red) | The tunnel dropped: step 5a again. Meanwhile unknown names stay "unknown" and the summary is the built-in one. Don't mention it unless asked. |
| The phone joined but shows nothing | Is cellular data off? Does the sensor's terminal say `backend: connected`? Otherwise: replay mode. |
| An OpenSnitch prompt appears | Allow, "forever". Lookups stall until it is answered. |

## Afterwards

Ctrl+C in the sensor's terminal, then `sudo bash box/box-down.sh` on the host. Ctrl+C in the VM stops the backend and forgets everything captured.
