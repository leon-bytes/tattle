# Pitch and demo

The judge slot is 2 min setup, 6 min judging and questions, 2 min teardown. Aim for a ~3:30 talk, which leaves ~2:30 for questions.

## Before walking over (checklist)

- Box running on the host:
  - phone USB-tethered
  - `box-up` done
  - sensor and backend running
  - page open full-screen
  - laptop set not to sleep
  - charger packed
- Test iPhone:
  - joined `Tattle-Demo`
  - demo app installed and closed
  - Low Power Mode off
  - charged
- Test iPhone's iCloud Private Relay is off for this network (or it shows the notice: tap "use without Private Relay").
- Hit Wipe, so the screen starts empty.
- Health shows sensor ✓. AI and DB may be ✗; the demo still works.
- Backup: replay file loaded and ready, backup video on the second laptop (and on a phone).

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
"Tap that company to block it."
- The bubble goes grey, and the blocked counter keeps climbing: the app keeps trying.
- The app still works.

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

- **Hotspot or sensor dies:** say "Switching to a recording from earlier today with our own phone", start `fake_sensor` with the replay, and carry on. The UI looks identical.
- **Everything dies:** play the backup video, then keep talking over the architecture diagram.
- **AI down:** the template summary shows instead. Don't mention it unless asked.

## Technical talking points (everyone should be able to say these)

**What DNS is**
The phone asks "where is ads.example.com?" before every new connection. We are the one it asks, so we see the name. We never see what's sent after that.

**Why we answer instead of just listening**
Being the resolver means the same piece of code captures and blocks. A firewall rule also catches apps that hardcode their own DNS server, like 8.8.8.8.

**Blocking**
We return NXDOMAIN ("doesn't exist"). The app can't connect, so it often retries, and that's why the blocked counter keeps going up.

**SNI (we skipped it on purpose)**
- SNI is the site name a phone sends in plain text at the start of an encrypted connection.
- We skipped it because DNS already gives us the names, and SNI is getting hidden by Encrypted Client Hello (ECH) anyway.

**What hides from us**
- Encrypted DNS (DoH/DoT). We block the well-known servers so phones fall back to normal DNS.
- iCloud Private Relay. We use Apple's documented network opt-out, and the iPhone tells the user.
- ECH.
- Names the phone looked up before it joined (cached).
- Apps that connect straight to an IP address.

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
- Only our own lab phones are stored in Postgres (history view).
- Wipe clears everything.

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
