# Pitch and demo

The judge slot is 2 min setup, 6 min judging and questions, 2 min teardown. Aim for a ~3:30 talk, which leaves ~2:30 for questions.

## Before walking over (checklist)

The box is one laptop running two things: the hotspot and the sensor on the laptop itself, and the backend (which serves the page) in a virtual machine on it. Exact commands: `box/README.md`.

- In the VM:
  - backend running, started with `--host 0.0.0.0`
- On the laptop itself:
  - phone USB-tethered
  - Mullvad VPN disconnected
  - `box-up` done (it warns if the VPN is still on)
  - sensor running and showing `backend: connected`
  - OpenSnitch: the sensor's two allow rules are in place (DNS to `9.9.9.9`, HTTP to the VM), so no prompt appears mid-demo
  - page open full-screen at `http://<vm-ip>:8000/`
  - laptop set not to sleep
  - charger packed
- Test iPhone:
  - joined `Tattle-Demo`
  - cellular data off, if its lookups don't show up
  - demo app installed and closed
  - Low Power Mode off
  - charged
- The iPhone shows "Private Relay is turned off for this network": expected, tap "use without Private Relay".
- Hit Wipe, so the screen starts empty. The phone then shows as "Device 1".
- For the history view: mark our phone as `persist` after the Wipe and before starting the session. Never a judge's phone.
- Health shows sensor ✓. AI and DB may be ✗; the demo still works.
- Backup: the replay ready to start in the VM (`python3 tools/fake_sensor.py data/replays/<file>.jsonl --loop`), backup video on the second laptop (and on a phone).

## Script (~3:30)

**0:00 hook (A)**
"Your phone talks to dozens of companies you've never heard of. Want to see who? Here's our test phone."

**0:10 consent line (A), every time**
"It's our phone on our own password-protected demo network. We only see the names of the servers it looks up, never what's sent. And it's all wiped the moment you walk away."

**0:20 the judge acts (A)**
Hand over the iPhone: "Open <demo app> and just use it like normal."
- Start the session labeled with the app name.

**0:25–1:30 the screen fills (B narrates)**
- Point at the first bubbles: "That's an ad exchange… that's analytics… that's a data broker."
- Call out the counter: "<N> companies in <M> seconds."
- Read the plain-English summary aloud.

**1:30 block it (judge or B)**
"Tap that company to block it. Now close the app and open it again."
- A block stops **new** connections. What the app already has open stays open until it reconnects, so the reopen is part of the demo, not a workaround.
- After reopening: the bubble goes grey, and the blocked counter keeps climbing: the app keeps trying.
- The app still works.
- Block the company, not a single name: one app uses several names of the same company.

**1:50 label check (B; only if built)**
"Here's what the App Store label says this app collects. Here's what it actually contacted. You decide."

**2:10 how it works (C, with the diagram on screen)**
- The phone's Wi-Fi goes through our box. The box answers its DNS lookups, so we see every name before a connection starts.
- A tracker list puts known names into categories, and an open-source model on an AMD GPU sorts the names no list has ever seen.
- Blocking means we answer "that name doesn't exist".

**2:50 honest limits + AI tools (C)**
- "Some names hide from us": encrypted DNS, iCloud Private Relay, Encrypted Client Hello.
- "We built it with <AI tools> and here's what we got stuck on: <one real challenge>."

**3:20 close (A)**
"Anyone can hand a phone to Tattle and get the truth in a minute, with nothing to install."

**Optional, for a judge's own phone**
"Want to try your own phone? Totally optional. You'd join our Tattle-Demo Wi-Fi for a minute, we only see server names, and we wipe it right after. Forget the network when you're done."
- Never pressure, and never touch their phone ourselves.

## If it breaks

- **Hotspot or sensor dies:** say "Switching to a recording from earlier today with our own phone", start `fake_sensor` with the replay, and carry on. The UI looks identical. (Until we record our own phone, the only replay is `demo-synthetic.jsonl`, which is made-up traffic: say "a simulated session" then.)
- **Everything dies:** play the backup video, then keep talking over the architecture diagram.
- **AI down:** the template summary shows instead. Don't mention it unless asked.

## Technical talking points (everyone should be able to say these)

**What DNS is**
The phone asks "where is ads.example.com?" before every new connection. We are the one it asks, so we see the name. We never see what's sent after that.

**Why we answer instead of just listening**
Being the resolver means the same piece of code captures and blocks. A firewall rule redirects every DNS packet (port 53) coming from the hotspot to our resolver, whatever server the phone addressed it to. That catches apps that hardcode a DNS server like 8.8.8.8, and phones still using a leftover one (we saw an iPhone use its VPN's).

**Blocking**
We return NXDOMAIN ("doesn't exist"). The app can't connect, so it often retries, and that's why the blocked counter keeps going up.

- **It stops new connections, not open ones.** We act at the moment an app asks for a name. A connection that is already open never asks again, and a phone reuses an answer for as long as the answer says it may (its TTL). We found this the hard way: we blocked `discord.com`, and a message still went through.
- **What we do about it:** our resolver shortens every answer's lifetime to 10 seconds, so the phone asks again almost at once and the block takes hold at the app's next connection. We cannot cut a connection that is already open; reopening the app does.
- **What a block covers:** a company block covers every name we know for that company and everything under those names (Discord alone uses `discord.com`, `discord.gg` and `discordapp.net`). A single-name block covers that name and its subdomains only.

**SNI (we skipped it on purpose)**
- SNI is the site name a phone sends in plain text at the start of an encrypted connection.
- We skipped it because DNS already gives us the names, and SNI is getting hidden by Encrypted Client Hello (ECH) anyway.

**What hides from us**
- Encrypted DNS (DoH/DoT). Our "guard list" always answers "doesn't exist" for the well-known DoH servers and for `_dns.resolver.arpa`, the name an iPhone uses to ask its resolver for an encrypted upgrade. The firewall also rejects DNS-over-TLS (port 853). The phone falls back to normal DNS.
- iCloud Private Relay. We use Apple's documented network opt-out (`mask.icloud.com`, `mask-h2.icloud.com`, `mask.apple-dns.net` don't resolve), and the iPhone tells the user.
- The screen counts these as "hidden-traffic attempts", apart from blocked trackers: the phone tried a private channel and we said no.
- ECH.
- Names the phone looked up before it joined (cached).
- Apps that connect straight to an IP address.

**Where it runs**
One laptop. The hotspot and the DNS resolver run on the laptop itself, because that is where the Wi-Fi card is. The backend and the page run in a virtual machine on the same laptop. Phones on the hotspot cannot reach the backend.

**The tracker list**
About 4,400 domains from Disconnect's open tracking-protection list, plus our own short list for Apple's system servers, big CDNs and phone-only ad SDKs. Names no list knows go to the model.

**Device vs. app**
- We see devices, not apps.
- We attribute traffic to an app by session: whatever happens while the judge uses one app.
- Background traffic from the phone can mix in. We mark the phone's own OS servers as "vendor".

**AI**
- Model: <model>, served with <llama.cpp/vLLM> on ROCm on the AMD <GPU> cloud node.
- It classifies names no list knows (shown as "AI guess") and writes the summary.
- Its answers are cached, and the demo never waits on it.

**Data**
- RAM by default.
- Phone names are hidden by default: the screen says "Device 1", not the name its owner gave it. We only read names for our own phones.
- Only our own lab phones are stored in Postgres (history view), and only while we mark them.
- Wipe clears everything on screen and in memory. Stored history has its own, separate delete.

## "Isn't this just X?" (judges will ask)

- **Pi-hole:** a network ad blocker for your home, with a dashboard of lookups. Ours is a portable "hand it over and see" experience: names turned into companies and plain English, live per-device view.
- **IoT Inspector** (NYU/Princeton research tool): shows who smart-home devices talk to. It's a desktop app that intercepts your home network (ARP spoofing). Ours needs no install, is aimed at a person holding a phone, and explains in plain English.
- **Firewalla:** a commercial router box with per-device flows and blocking, built for admins managing a home network. Ours is a one-minute X-ray for anyone.
- **iPhone App Privacy Report:** buried in Settings, raw domain lists, last 7 days. We turn those names into companies and categories, live, and check them against the app's own privacy label.
- **OpenSnitch / Little Snitch:** per-app firewalls that only see the computer they're installed on.
- **The line:** "The capture trick is old, and we say so. What's new is making it instant, understandable, and checkable against what the app promised."

## Who answers what

- A: demo and network/DNS questions
- B: UI and design
- C: AI and data
- Everyone: our AI tools and our challenges (from `docs/CHALLENGES.md`)

## Submission: before the repo goes public

If the submission needs a public repository, or before this one is opened up:

- [ ] Make a **fresh** public repository from a clean copy of the project, with a new history. Deleting a file later is not enough: it stays in the old history.
- [ ] Leave `docs/PROJECT-GUIDE.md` out of that copy and list it in the public repository's `.gitignore`. It is an internal team document. Remove the links to it in `README.md` and `docs/TEAM.md` as well.
- [ ] Until then, do not add it to this repository's `.gitignore`: it has to keep reaching the whole team.
- [ ] Re-check every file for personal information and secrets: `.env` files, tokens, IP addresses, MAC addresses, names.
