**Internal team document. Not for public release; it is removed before the repo goes public.**

# Tattle: project guide

**Last updated: Saturday 2026-10-10, 19:03 local time.**

## Note to an AI reader

This file is the complete context for a hackathon project called Tattle. It is written so that a person can paste it into a fresh chat with you and you can then explain any part of the project, say why it is built the way it is, and help continue the work without asking for background. Assume you have nothing else: no repository, no other documents, no earlier conversation.

- It is the source of truth as of the "Last updated" time above. Things change fast in a hackathon; the changelog at the end says what changed and when.
- If this file and the code ever disagree, the code wins. Say so, and suggest fixing this file.
- It is organized from the ground up: what the project is, the situation, a glossary, the architecture, one lookup followed end to end, every component, every interface with its exact data shapes, the reasons behind each decision, what was tested and what was not, and the current status with next steps.
- Words like "tested", "works" and "done" are used strictly. Anything not verified is marked **unverified**. Planned work is described as planned.
- People are referred to by role only: BOX, FRONT and AI (section 2). FRONT merged into BOX on Saturday afternoon; the name still appears where it explains history.

## Contents

1. What Tattle is
2. The situation: team, deadlines, judging
3. Glossary
4. Architecture: what runs where, and why
5. The life of one DNS lookup
6. Components and files
7. Interfaces, with the exact data shapes
8. Design decisions and the alternatives we rejected
9. What the hardware tests showed, and what is still unverified
10. Privacy and consent
11. Security model and known gaps
12. Limitations: what hides from us
13. How to run, test and demo it, and the fallbacks
14. Prior art and how we differ
15. Team working rules
16. Current status and next tasks
17. Challenges we hit and AI tools used
18. Changelog

---

## 1. What Tattle is

**In one sentence:** Tattle is a laptop that acts as a Wi-Fi hotspot; a phone joins it, and a screen shows, live and in plain English, which companies the phone's apps contact, with one tap to block a company.

**The problem.** A phone app talks to many companies its user never chose: advertising networks, analytics services, data brokers. This is invisible. The tools that reveal it are either buried (the iPhone's own App Privacy Report), technical (raw lists of server names), or need installing and configuring.

**The idea.** Before an app can connect to a server, the phone has to look up the server's name (a DNS lookup, see the glossary). If the phone is on our Wi-Fi, we are the one it asks. So we see every server name, and we can refuse to answer for names we want to block. We never see what is sent after that: only names.

**What it does with a name.**
1. Records which phone asked for which name.
2. Turns the name into a company and a category (advertising, analytics, social, fingerprinting, content, vendor, unknown) using a public tracker list plus a small hand-written list. Names nobody knows can be sent to an open-source language model for a guess.
3. Shows it on a live screen.
4. If someone blocks a company, answers "that name does not exist" for all of that company's names, so the app cannot reach it.
5. Stretch goal: compares what an app contacted with the privacy label the app's maker published in the App Store.

**Who it is for.** Anyone curious about what a phone app really does, with nothing to install on the phone: hand over a phone, open an app, look at the screen. In the hackathon, the audience is judges at our table.

**The pitch** (the team's own wording): "Tattle is a pocket Wi-Fi box that X-rays a phone in a minute. Hand someone the phone, they open an app, and the screen fills with every company that app quietly calls: in plain English, checked against the app's own privacy label, with one tap to shut a tracker up."

**The honest framing we use with judges:** "The capture trick is old, and we say so. What's new is making it instant, understandable, and checkable against what the app promised."

"Tattle" is a working name; renaming is a find-and-replace.

### How it is judged

Judges score five things: **Originality**, **Technical Understanding**, **Functionality** (reliable, end to end, no fragile live dependencies), **Design**, and **Wow**. They also value honesty about what was hard and which AI tools were used; our answers come from the challenges log (section 17).

### Sponsor tracks we enter, and why

| Track | Why we fit | What it needs from us |
| --- | --- | --- |
| Best Use of Provided Backend (a Postgres database the organizers provide) | The database does real work: a copy of the tracker list, session history, a cache of AI answers, a "top companies per app" view | The history view working on screen (backend side is built; the screen is not) |
| Best Use of Open Source AI | An open model classifies names no list knows, writes the summary, fact-checks privacy labels, and explains a company in the detail panel | A clear before/after: lists only versus with AI. The detail panel shows exactly that, sentence from the list first and the AI's text after it (the AI module is not written yet) |
| Best Use of Graphics Technologies (ROCm) | The model is served on an AMD GPU (a Radeon PRO W7900 with 48 GB of video memory) through ROCm | Notes and screenshots of the ROCm setup, and real numbers such as tokens per second (not done yet) |
| Best Design / Prettiest Hack | The live graph is the showpiece | A consistent palette and type. The show screen exists since Saturday 17:30 (section 6.7); its look was chosen by BOX from the architecture diagram's colours and has not been reviewed by the AI owner, who holds the visual identity |

Tracks we skip: Data Capturing Hardware, Jetson, Financial Services, Innovation for Good, Pathways & Perception, the robot dashboard, and the Analytics Platform.

---

## 2. The situation: team, deadlines, judging

**Team of three, by role:**

| Role | Owns |
| --- | --- |
| **BOX** | The hotspot, the DNS sensor (`sensor/`), the hotspot scripts (`box/`), the backend core (`backend/app/` except `ai.py`), `tools/fake_sensor.py`, and since Saturday afternoon the privacy labels for the demo apps (`data/labels/`) and the frontend (`frontend/`): the screen the judges look at |
| **FRONT** | Merged into BOX on Saturday afternoon, before any frontend code existed. The role's work (live bubble graph, block by click, session controls, a "how it works" view) is now BOX's, built as the show screen in `frontend/` |
| **AI** | The model server on the AMD server, `backend/app/ai.py`, the tracker knowledge base (`tools/build_kb.py`, `data/kb.json`, `data/kb_overrides.json`), `data/ai_cache_seed.json`, the visual identity (palette, type), the pitch diagram |

Each owner edits only their own folders. Shared files: `docs/TEAM.md` (the interface contract), `docs/PITCH.md`, `docs/CHALLENGES.md`, `.gitignore`, `README.md`.

**Deadlines (local time):**
- **Feature lock: Saturday 20:00.** After that, only bug fixes and polish.
- **Hackathon ends: Sunday 10:00.** The real submission deadline may be earlier: check it.

**Judging format.** Teams walk to the judges' table. We get **2 minutes to set up, 6 minutes of judging and questions, 2 minutes to tear down**. The talk is planned at about 3:30, leaving about 2:30 for questions. Everything must already be running when we walk over.

**Timeline as planned:**

| When | What |
| --- | --- |
| Sat 02:00–05:00 | Set up, run the de-risk tests (section 9), lock the interfaces |
| Sat 05:00–10:00 | Sleep (BOX's part of the software was built in this window) |
| Sat 10:00–15:00 | Build the minimum product |
| **Sat 15:00** | Checkpoint: the full loop works with a real iPhone on the real hotspot |
| Sat 15:00–20:00 | Stretch goals, design polish, record replays from our own phones |
| **Sat 20:00** | Feature lock |
| Sat 20:00–00:00 | Record the backup video, write the submission text, rehearse twice |
| Sun 06:30–09:00 | Rehearse with a timer (three times or more), fresh-boot test of the box, restart the AI session, submit |
| Sun 09:00–10:00 | Buffer |

**Scope.**

Minimum product, must work end to end by Saturday 15:00:
1. Hotspot and sensor capture DNS from a real iPhone.
2. The backend categorizes lookups and pushes them to the screen.
3. Live bubble graph: the phone in the middle, company bubbles around it coloured by category, growing and pulsing on each lookup.
4. One-tap block of a company: the bubble greys out and a "blocked attempts" counter keeps ticking.
5. Session start/stop with an app name, a Wipe button, an always-visible privacy banner.
6. A plain-English summary per session.
7. Replay mode working, as the backup.

Stretch goals, in order: (1) privacy-label fact-check for two or three demo apps, our biggest originality lever; (2) AI classification of unknown names, shown with an "AI guess" badge; (3) AI-written summary; (4) history view from the database; (5) a how-it-works view; (6) an accuracy check against the iPhone's own App Privacy Report; (7) training a small classifier on the AMD GPU, only if the AI core is done by 16:00.

Deliberately not built: user accounts or login, a mobile app, capturing anything beyond DNS (no TLS or SNI capture), multi-box or cloud deployment, settings pages, a hardware enclosure.

**Who says what at the table:** presenter A does the demo and network questions, B the screen and design, C the AI and data. Everyone can answer about challenges and AI tools.

---

## 3. Glossary

Plain-word definitions of everything the project relies on. Later sections use these terms without re-explaining them.

**Networking basics**

- **IP address.** A number that identifies a device on a network, like `10.42.0.23`. Phones on our hotspot get addresses starting `10.42.0.`; the laptop is `10.42.0.1` there.
- **Port.** A number from 1 to 65535 that says which program on a device a message is for. DNS uses port 53, our sensor listens on 5300, our backend on 8000.
- **UDP and TCP.** Two ways of sending data. UDP sends single messages with no setup (most DNS). TCP sets up a connection first and guarantees delivery (web traffic, and DNS when an answer is too big).
- **Loopback (`127.0.0.1`, "localhost").** An address that means "this same machine". Used for testing without a network.
- **MAC address.** The hardware address of a network card, like `52:54:00:…`. Used inside a local network, for example by DHCP to recognize a device. A **locally administered** MAC address (for example `02:00:00:00:00:01`) is one from the range set aside for addresses people make up themselves, as opposed to one burned into hardware by a manufacturer.
- **DHCP.** The service that hands a device its IP address when it joins a network, and tells it which DNS server and gateway to use. A device may also tell DHCP its name (typically "<owner's name>'s iPhone"); the record of who got which address is a **lease**, kept in a **lease file**.
- **NAT (network address translation).** What a router does so many devices can share one internet connection: it rewrites the sender address of outgoing packets to its own and remembers who to hand the replies to.
- **Gateway.** The device that forwards your traffic to the rest of the internet. For phones on our hotspot, that is our laptop.
- **Wi-Fi access point (AP), hotspot, SSID, WPA2.** An access point is the device phones connect to over Wi-Fi. A hotspot is a laptop or phone acting as one. The SSID is the network's name (`Tattle-Demo`). WPA2 is the password-based protection of the Wi-Fi link.
- **Virtual interface.** A second, software-made network interface on the same Wi-Fi card. Ours is called `tattle0`. With it the card has two interfaces: one stays connected to ordinary Wi-Fi and the other runs the hotspot. Which one does which is decided by NetworkManager at start-up (section 9). Not every card can do both at once; ours can.
- **Uplink.** Whatever gives the laptop itself internet: ordinary Wi-Fi, or a phone connected by cable ("USB tethering").
- **NetworkManager, dnsmasq.** NetworkManager is the Linux service that manages network connections; its command-line tool is `nmcli`. For a hotspot it runs dnsmasq, a small program that does DHCP (and DNS, which we replace) for the hotspot's phones.
- **`iw`, `tcpdump`.** `iw` is the Linux tool for Wi-Fi hardware (we use it to create the virtual interface). `tcpdump` prints the raw packets passing an interface (we used it to confirm we could see a phone's DNS).
- **Firewall, iptables, chains, redirect rule.** A firewall decides which packets may pass. On Linux, `iptables` is the tool that edits its rules. Rules live in lists called chains: `INPUT` (packets for the laptop itself), `FORWARD` (packets passing through to somewhere else), `PREROUTING` in the `nat` table (packets just arrived, before any decision). A **redirect rule** rewrites an arriving packet so it goes to a port on the laptop itself; ours sends every DNS packet from the hotspot to our sensor, whatever server the phone addressed it to.
- **VPN.** Software that sends a device's traffic through an encrypted tunnel to a provider. A phone with a VPN configuration may keep using the VPN's DNS server address. A VPN on our laptop (it has one, Mullvad) can also interfere with sharing its connection, so it is turned off for the demo.
- **Application firewall (OpenSnitch).** A program on the laptop that asks the user before letting each application make outgoing connections. Ours must be told to allow the sensor.

**DNS**

- **DNS (Domain Name System).** The internet's phone book. Before connecting to `ads.example.com`, a device asks "what is the IP address of this name?" That question is a **DNS lookup** or **query**; names are also called **host names** or **domains**.
- **Resolver.** The server a device sends its DNS questions to. Normally the network's router or the provider's. In Tattle, **we are the resolver**: our sensor answers the phones' questions, by asking a real resolver itself (the **upstream** resolver, `9.9.9.9`, a public one run by Quad9) and passing the answer back.
- **Query types.** A lookup asks for one kind of record. **A**: the IPv4 address. **AAAA**: the IPv6 address. **HTTPS** (type 65) and **SVCB**: extra connection details, such as "this site supports HTTP/3". **PTR**: the reverse, a name for an address. An iPhone typically asks A, AAAA and HTTPS for the same name at once, so one "the app contacted X" is three queries.
- **Answer codes.** Every DNS answer carries a result code. **NOERROR**: here is your answer. **NXDOMAIN**: that name does not exist. **SERVFAIL**: I could not find out. **REFUSED**: I will not answer this.
- **Blocking by NXDOMAIN.** If we answer NXDOMAIN, the app cannot find the server and cannot connect. Apps often retry, which is why a "blocked attempts" counter keeps climbing.
- **Suffix match.** A rule for `example.com` also covers `a.example.com` and `x.a.example.com`: we walk up the name label by label.
- **Cache, TTL.** Devices remember answers for a while; each answer says for how long (its time to live, TTL, in seconds). A name the phone looked up before it joined our hotspot may not be asked again for some time. On our hotspot the sensor shortens every answer's TTL to 10 seconds, so the phone asks again almost at once.
- **Encrypted DNS: DoH, DoT, DoQ.** Ways to send DNS questions encrypted, so the network cannot read them: DNS-over-HTTPS (inside ordinary web traffic, port 443), DNS-over-TLS and DNS-over-QUIC (port 853). If a phone used them, we would see nothing.
- **DDR and `_dns.resolver.arpa`.** "Discovery of Designated Resolvers": a device asks its plain resolver, through the special name `_dns.resolver.arpa`, "do you offer an encrypted version of yourself?" iPhones do this on joining a network. We answer no.
- **iCloud Private Relay.** An Apple service that hides a user's browsing from the network by routing it through two relays. Apple documents a way for a network to opt out: if the names `mask.icloud.com` and `mask-h2.icloud.com` do not resolve, the iPhone turns Private Relay off for that network and tells the user.
- **mDNS (`.local`).** Local name discovery between devices on the same network (printers, AirPlay). Not companies; we ignore it.

**Encryption around web traffic**

- **TLS.** The encryption behind `https`. We never touch it.
- **SNI.** The site name a device sends in plain text at the start of a TLS connection. A second way to learn which sites a device contacts.
- **ECH (Encrypted Client Hello).** A newer feature that encrypts the SNI. It is one reason we chose DNS rather than SNI.

**Our own vocabulary**

- **The box.** The demo laptop: hotspot, sensor, and (inside a virtual machine) the backend.
- **Sensor.** Our DNS resolver program. It answers the phones and reports each name to the backend.
- **Backend.** Our server program. It turns names into companies, keeps the state, and feeds the screens.
- **Hit.** One counted lookup: a phone asked for a name. The same phone and name within 2 seconds is one hit.
- **Knowledge base (kb).** The table that maps names to a company and a category. Built from **Disconnect's tracking-protection list**, an openly licensed list of tracker domains, plus our **overrides**, a short hand-written file that wins over the list.
- **Categories.** `advertising`, `analytics`, `social`, `fingerprinting` (identifying a device by its technical traits), `content` (content delivery networks and embedded media), `vendor` (the phone maker's or the app's own servers), `unknown`.
- **Tracker, SDK, ad mediation.** A tracker is a service that collects data about users across apps. An SDK is a code library an app includes; ad and analytics companies ship SDKs. Ad mediation is an SDK that asks many ad networks at once, which is why one free game contacts a dozen ad companies.
- **CDN.** Content delivery network: servers that deliver files (images, video) for many companies.
- **Guard list.** A fixed list of names our sensor always answers NXDOMAIN for: the names a phone uses to switch to encrypted DNS or Private Relay. Blocking them makes the phone fall back to plain DNS that we can see.
- **Hidden-traffic attempt.** A lookup of a guard-list name: the phone tried a private channel and we said no. Counted separately; not a blocked tracker.
- **Malformed name.** A looked-up name that is not a plain host name (it contains other characters). Refused and counted, never shown.
- **Box self-test.** A lookup the laptop makes through its own sensor to check that it works (a step of the start checklist). It comes from the loopback address, so it is not a phone; on screen it sits under the name "box self-test" and takes no device number.
- **Session.** A stretch of time on one phone with an app name attached ("Demo Game"), started and stopped from the screen. It is how we attribute lookups to an app: we see devices, not apps.
- **Summary.** A few sentences describing a session, written by a template or by the AI.
- **Wipe.** Forget everything captured: the reset between two judges.
- **Persist, lab phone.** A device we mark as our own test phone. Only marked devices are ever written to the database.
- **Replay, fake sensor.** A replay is a file of recorded lookup events. The fake sensor is a tool that feeds a replay to the backend with the original timing, so the whole system can be developed, tested and demonstrated without the hotspot.
- **Privacy label.** The "App Privacy" section an app's maker fills in on its App Store page: data used to track you, data linked to you, and so on.
- **App Privacy Report.** The iPhone's built-in list of domains each app contacted in the last seven days.
- **Health.** A small status record the backend broadcasts: is the sensor alive, is the database usable, did the last AI call work.

**Software terms**

- **FastAPI, uvicorn, asyncio.** FastAPI is the Python web framework the backend is written in; uvicorn is the server program that runs it; asyncio is Python's way of doing many things at once in one process.
- **REST, JSON.** REST here simply means ordinary web requests (`GET` to read, `POST` to change) to addresses like `/api/block`. JSON is the text format of the data, like `{"company": "Google"}`.
- **WebSocket.** A connection a web page keeps open to a server so the server can push messages the moment something happens. Our screens receive every hit this way, at `/ws`.
- **Postgres, SQL.** Postgres is a database server; SQL is the language for talking to it. The organizers provide one. **Parameterized SQL** means values are passed separately from the command text, which prevents **SQL injection** (text that is mistaken for commands).
- **venv.** A private Python environment in a folder (`.venv`), so packages are installed for one project only and never into the system.
- **Virtual machine (VM), libvirt, VM networking.** A VM is a computer simulated inside a computer. libvirt is the Linux software that manages VMs; its tool is `virsh`. By default libvirt puts VMs on a private network (`192.168.122.0/24`) inside the laptop: the laptop (the **host**) can reach the VM directly at the VM's `192.168.122.x` address, and the VM reaches the internet through the host by NAT.
- **Container, podman.** A lightweight way to run a program in isolation. We use podman only to run a throwaway Postgres for tests.
- **React, Vite.** The JavaScript library and build tool the frontend was first planned in. We did not use them: the show screen is plain HTML, CSS and JavaScript with no build step (decision 32a in section 8).
- **Show screen, operator console, fallback view.** Our three pages. The **show screen** (`/`) is what the judges look at: the phone in the middle with a bubble per company. The **operator console** (`/debug`) is the plain page with every control and a table of lookups. The **fallback view** (`/present`) is a plain presenter page in case the show screen fails.
- **Detail panel.** The large panel the show screen opens when someone clicks a company's bubble: who the company is, every server name the phone asked for, and the buttons to block.
- **SVG, inline SVG.** SVG is a way to describe a drawing as shapes (circles, paths) in text. "Inline" means the drawing is written directly into the page's HTML instead of being a separate image file. Our logo is one.
- **Browser-tab icon (favicon), `data:` address.** The small picture a browser shows on a tab. A `data:` address is an "address" that contains the file itself instead of pointing to one; our page builds its tab icon that way from its own logo.
- **Headless browser.** A real browser run by a script, without a window, used to load a page, click on it and save screenshots. We use the VM's Firefox this way to check the show screen.
- **LLM, OpenAI-compatible API, ROCm.** An LLM is a large language model. "OpenAI-compatible" means the model server speaks the widely used `/chat/completions` request format. ROCm is AMD's software for running models on AMD graphics cards.
- **Ollama.** A program that runs language models on a machine and offers them over an OpenAI-compatible API. Ours runs on the AMD server and listens only on that server's own loopback address.
- **SSH, SSH tunnel.** SSH is the standard encrypted way to log in to another machine. A tunnel uses that connection to make a port on the far machine appear as a port on this one: with ours, `127.0.0.1:8081` on the backend's machine leads to Ollama on the AMD server. Nothing else can reach Ollama.
- **XSS (cross-site scripting).** Getting a page to run attacker-supplied script, typically by sneaking markup such as `<img onerror=…>` into text the page inserts as HTML. Prevented by inserting text as text.
- **CSP (content security policy), nonce.** A response header that tells the browser what a page may run and load. Ours allows only the page's own script, identified by a random one-time value (the nonce).
- **Cross-site request, Origin header, CSRF, cross-site WebSocket.** A browser page from site A can send requests to site B. For anything that changes state this is an attack called CSRF. Browsers attach an `Origin` header saying which site the page came from; we refuse state-changing requests and WebSocket connections whose Origin is another site.
- **DNS rebinding.** An attack where a malicious site's name is made to resolve to a victim's internal address, so the browser treats the internal service as "the same site". We do not defend against it (section 11).
- **Soak test.** Running a system under steady load for a long time to see whether memory grows or anything falls over.

---

## 4. Architecture: what runs where, and why

```
                                  THE BOX (one Linux laptop)
 ┌──────────────┐   Wi-Fi    ┌──────────────────────────────────────────────────────────────────┐
 │ test iPhone  │──────────▶ │ ON THE LAPTOP ITSELF ("the host")                                │
 │ (10.42.0.x)  │            │                                                                  │
 └──────────────┘            │  hotspot "Tattle-Demo" on one of the card's two interfaces       │
                             │    NetworkManager: DHCP for phones, NAT to the uplink            │
                             │  firewall (iptables, set by box/box-up.sh):                      │
                             │    any packet to port 53 from the hotspot ──▶ sensor :5300       │
                             │    port 853 from the hotspot: rejected                           │
                             │    hotspot ──▶ VM network: rejected                              │
                             │  sensor (sensor/tattle_sensor.py, port 5300)                     │
                             │    answers the phone; forwards allowed names to 9.9.9.9 ─────────┼──▶ internet
                             │      │ POST /api/events (every 250 ms)   ▲ GET /api/blocklist    │   (via uplink)
                             │      ▼                                   │ (every second)        │
                             │ ┌──────────────────────────────────────────────────────────────┐ │
                             │ │ IN A VIRTUAL MACHINE on the laptop (192.168.122.x)           │ │
                             │ │  backend (FastAPI, port 8000)                                │ │
                             │ │    names ──▶ company + category (data/kb.json, overrides)    │ │
                             │ │    state in memory; optional: ai.py ──▶ model server (AI)    │─┼──▶ AMD server, by SSH tunnel (optional)
                             │ │                     optional: Postgres history               │─┼──▶ provided Postgres (optional)
                             │ │    WebSocket /ws + REST /api/…                               │ │
                             │ │    serves: show screen at /, /debug, /present                │ │
                             │ └──────────────────────────────────────────────────────────────┘ │
                             │  browser on the laptop ──▶ http://<vm-ip>:8000/  ──▶ big screen  │
                             └──────────────────────────────────────────────────────────────────┘

 Teammates' machines: anyone can run the backend plus tools/fake_sensor.py locally (no hotspot needed).
 The AMD server runs the model server (Ollama), reached through an SSH tunnel. The organizers run the Postgres.
```

**What runs where, and the reason:**

| Where | What | Why there |
| --- | --- | --- |
| The laptop itself (host) | Hotspot and sensor, nothing else | The Wi-Fi card is the laptop's and cannot be handed to the VM. The sensor must sit where the phones' packets arrive. It needs only plain Python and one small package, which keeps the host clean. |
| A VM on the same laptop | Backend, the show screen it serves, the dev tools | All development happens in the VM; running the backend where it was built and tested avoids setting up a second Python environment on the host. The host reaches the VM over libvirt's internal network, which does not depend on the Wi-Fi card. |
| Teammates' laptops | Backend plus the fake sensor, for development | So the AI owner (and anyone else) can work without the hotspot. |
| The AMD server | The language model server (Ollama) | That is where the sponsor's GPU is: a Radeon PRO W7900 (48 GB of video memory), 128 cores, 503 GB of memory, Ubuntu 24.04. It listens on its own loopback address only and is reached from the backend's VM through an SSH tunnel. Optional at demo time. |
| Organizers' server | Postgres | It is the "provided backend" of a sponsor track. Optional at demo time. |

Two properties of this design matter everywhere else:

- **The live path has no optional parts.** Phone → sensor → backend → screen works with no database, no AI and no internet access from the VM. The database and the AI are attached at the side and may fail without anyone noticing on screen (health shows it).
- **Phones can reach only the sensor.** The firewall lets hotspot phones talk to DHCP and DNS on the laptop and to the internet, and nothing else: not the backend, not the VM.

That the host reaches the VM while the Wi-Fi card runs the hotspot was confirmed by the hardware test (section 9).

---

## 5. The life of one DNS lookup

Follow one name from a phone to the screen. Step numbers are referred to later.

**Before any app is opened.** The phone joins the Wi-Fi network `Tattle-Demo` with its WPA2 password. DHCP on the laptop gives it an address such as `10.42.0.23` and tells it: your gateway and your DNS server are `10.42.0.1` (the laptop). An iPhone then does some housekeeping lookups by itself: a connectivity check, a DDR lookup of `_dns.resolver.arpa`, and the Private Relay names.

1. **The app wants to connect.** Someone opens a game. An advertising SDK inside it wants to reach `ms.applovin.com`. The phone sends DNS queries for that name: usually three at once (A, AAAA, HTTPS), addressed to its DNS server. That is normally `10.42.0.1`, but a phone can also keep using another server it remembers, for example a VPN's.

2. **The firewall steers it to us.** The packet arrives on the hotspot interface (`tattle0` or the card's real interface, whichever got the hotspot). A redirect rule sends every packet for port 53 arriving there to port 5300 on the laptop, **whatever server it was addressed to**. So we also catch apps and phones that try to use their own DNS server.

3. **The sensor decides.** The sensor reads the question and checks, in this order:
   - Not a readable DNS question, or it is an answer rather than a question: dropped silently.
   - The name is not a plain host name (it contains characters other than letters, digits, `-`, `_` and dots): answered **REFUSED**, never forwarded, and counted as *malformed*.
   - The name is on the **guard list** (or under one of its names): answered **NXDOMAIN**, reported with reason `guard`.
   - The name is on the **blocklist** fetched from the backend (or under one of its names): answered **NXDOMAIN**, reported with reason `user`.
   - Otherwise: the question is forwarded unchanged to the upstream resolver `9.9.9.9`. The answer is passed back with one change: every record's lifetime (TTL) is cut to 10 seconds, so the phone asks again soon (this is what lets a block take hold quickly). If the upstream does not answer within 3 seconds, the phone gets **SERVFAIL**.

4. **The sensor reports.** For every question it answered (except malformed ones and lookups of the DNS root), the sensor puts an event in a queue: when, which phone address, which name, which query type, whether it was blocked and why. A separate thread sends the queue to the backend every 250 ms. **Answering the phone never waits for the backend.** If the backend is down, events wait (up to 5,000, oldest dropped first) and are delivered when it is back.

5. **The backend turns it into a hit.**
   - It moves the batch onto its own clock (the sensor runs on another machine with another clock; sessions are timed on the backend).
   - It checks the name again (same plain-host-name rule) and counts rejects as malformed.
   - It drops network plumbing: names ending in `.arpa` or `.local`, and names without a dot. Guard-list names are the exception.
   - It finds or creates the device for that phone address. A new phone is called "Device 1", "Device 2", and so on.
   - It drops repeats: the same phone and name within 2 seconds is one hit (this merges the A, AAAA and HTTPS queries).
   - It classifies the name: first the overrides, then the tracker list, walking up the name (`ms.applovin.com`, then `applovin.com`). If neither knows it, an earlier AI answer is used if there is one; otherwise the hit is `unknown` and the name is queued for the AI.
   - It stores the hit in memory (the last 5,000 are kept) and pushes it to every connected screen over the WebSocket.
   - If a session is being recorded for one of our own marked phones, the hit is also queued for the database.

6. **The screen shows it.** Each connected page receives a `hit` message within a fraction of a second. The show screen adds the company's bubble or makes it pulse and grow, and puts the name at the top of its live list; the other two pages (`/debug`, `/present`) add a row or update a block.

7. **Meanwhile, the phone connects.** With the DNS answer from step 3, the phone connects to the server directly, through the laptop's NAT to the internet. We do not look at that traffic at all.

8. **In the background.** If an AI module is present, a background task asks the model about unknown names in small batches and broadcasts a `classified` message when it gets an answer; the screens then upgrade the hits they already show. While a session runs, a summary sentence is broadcast about every 3 seconds.

**When a company is blocked.** Someone clicks the company's bubble on the show screen and then "Block AppLovin" in the detail panel that opens (or "block" on `/debug`). The page sends `POST /api/block {"company": "AppLovin"}`. The backend adds the company to its block set and from then on lists all known names of that company in `/api/blocklist`. The sensor fetches that list every second. The next time the app **asks** for `ms.applovin.com`, step 3 answers NXDOMAIN; the app cannot connect; the event arrives as a hit with `blocked: true` and reason `user`. Apps retry, so blocked hits keep arriving. The rest of the app keeps working.

**A block stops new connections, not open ones.** This matters and was learned in the live test. The sensor only gets a say when the phone asks for a name. A connection that is already open never asks again, and a phone reuses an answer it already has until that answer's lifetime runs out. So right after a block, an app can keep talking over what it already has. Two things shorten this: the 10-second lifetime the sensor puts on every answer (the phone must ask again within seconds), and closing and reopening the app (which drops its open connections). Also, an app uses several names: blocking one name of a company leaves its other names alone, which is why the demo blocks the **company**. (The detail panel can also block a single server name, `POST /api/block {"domain": "ms.applovin.com"}`; that covers the name and everything under it.)

**When it is a guard-list name.** For example `mask.icloud.com` (Private Relay) or `_dns.resolver.arpa` (the request to upgrade to encrypted DNS). Step 3 answers NXDOMAIN and reports reason `guard`. The phone gives up on that private channel and keeps using plain DNS, which we can see; an iPhone shows the user a notice that Private Relay is off for this network. On screen this is a **hidden-traffic attempt**: counted on its own, never as a blocked tracker and never as a contact to a company.

**When the name is refused.** A name with other characters, for example one containing `<script>`, is answered REFUSED, not looked up, not shown anywhere, and only counted. Reason: a name we cannot safely show must not become a way to look something up without it appearing on screen.

---

## 6. Components and files

Everything lives in one repository. `backend/app/ai.py` does not exist yet.

```
README.md                 what it is, privacy, credits, where to start
.env.example              the settings, with placeholders; copy to .env (never committed)
.gitignore
test.txt                  a leftover dummy file, not used by anything
docs/TEAM.md              the interface contract between the three roles
docs/PITCH.md             demo script, pre-demo checklist, talking points
docs/CHALLENGES.md        log of problems, fixes and AI tools
docs/FRONT-QUICKSTART.md  the frontend's reference: run it locally, real examples of every message
docs/AI-QUICKSTART.md     for AI: what ai.py must provide and how it is called
docs/RUNBOOK.md           the two-minute start order for the demo, and the fallbacks
docs/PROJECT-GUIDE.md     this file
sensor/                   the DNS sensor (runs on the laptop itself)
box/                      hotspot scripts (run on the laptop itself)
backend/                  the backend (runs in the VM)
frontend/                 the show screen the backend serves at / (plain files, no build step)
tools/                    fake_sensor.py, selfcheck.py, build_kb.py, try_ai.py
data/kb.json              tracker knowledge base, built from Disconnect's list
data/kb_overrides.json    hand-written fixes that win over kb.json
data/replays/             recorded sessions; today only demo-synthetic.jsonl
data/labels/              App Store privacy labels for demo apps (empty today)
```

### 6.1 Sensor: `sensor/tattle_sensor.py`

- **What:** the DNS resolver the phones end up talking to. One Python file, Python 3.11 or newer, one dependency (`dnslib`, a pure-Python DNS library). It needs no administrator rights, because the firewall redirects port 53 to its port 5300.
- **How:** it listens on UDP and TCP, handles each question in its own thread, and behaves as in section 5, steps 3 and 4. Two background threads: one sends event batches every 250 ms, one fetches the blocklist every second. If the backend is unreachable, it keeps resolving with the last blocklist it got.
- **Options** (each flag also has an environment variable):

| Flag | Env | Default | Meaning |
| --- | --- | --- | --- |
| `--listen` | `SENSOR_LISTEN` | `0.0.0.0:5300` | address and port, UDP and TCP |
| `--upstream` | `UPSTREAM_DNS` | `9.9.9.9` | resolver to forward to; 3 s timeout, then SERVFAIL |
| `--backend` | `BACKEND_URL` | `http://127.0.0.1:8000` | where events go and the blocklist comes from; on the box, the VM's address |
| `--names` | | off | read each phone's DHCP name and send it. Off: phones are reported by address only |
| `--leases` | `LEASES_FILE` | `/var/lib/NetworkManager/dnsmasq-tattle0.leases` | the lease file `--names` reads. It is named after the hotspot interface, which may be the real one; `box-up.sh` prints the right path |
| `--max-ttl` | `SENSOR_MAX_TTL` | `10` | cut the lifetime of every relayed answer to this many seconds; `0` leaves answers as they are |
| `--debug` | | off | print one line per query (development only) |
| `--record FILE` | | off | append events to a replay file, with device names replaced by "Test iPhone A", "B", … |

- **The guard list** (always NXDOMAIN, matched by suffix): `mask.icloud.com`, `mask-h2.icloud.com`, `mask.apple-dns.net` (Private Relay); `_dns.resolver.arpa` (DDR); `dns.google`, `cloudflare-dns.com`, `one.one.one.one`, `dns.quad9.net`, `doh.opendns.com`, `use-application-dns.net` (well-known DNS-over-HTTPS hosts and the name some apps check before using DoH).
- **Privacy:** names are never printed or written to disk unless `--debug` or `--record` is given. Normal output is two start lines and "backend: connected" or "backend: unreachable, queueing events".
- **Short lifetimes:** the sensor rewrites only the four TTL bytes of each record in an upstream answer, in place; nothing else in the answer changes, and an answer it cannot read is passed on untouched. Checked against real answers with alias chains, HTTPS records and negative answers.
- **Robustness:** events wait in memory while the backend is down (5,000 at most). A batch the backend rejects with an error status is dropped rather than resent forever. Its background threads survive network errors.
- **Inputs:** DNS questions from phones; the blocklist from the backend. **Outputs:** DNS answers; event batches to the backend.
- **Tests:** `sensor/tests/test_sensor.py`, 35 tests. They run a real sensor on a loopback port against a fake upstream resolver and a fake backend: forwarding over UDP and TCP, every guard name, blocklist and unblock, hostile names (markup, spaces, raw bytes, terminal escape codes, a NUL byte), the lifetime cap on real record types, batching, the backend being down and coming back, a dead upstream, lease-file names, `--names` off by default, `--record`.
- **Other files:** `requirements.txt` (dnslib only: this is what the laptop needs), `requirements-dev.txt` (adds pytest), `README.md`.

### 6.2 Hotspot scripts: `box/box-up.sh`, `box/box-down.sh`

**Passed on the real hardware on the third run** (section 9): with `box-up.sh` and the real sensor, an iPhone on the hotspot showed up live on the screen. `box-down.sh` has worked as the cleanup after two failed starts; taking down a hotspot that really ran is not confirmed.

`box-up.sh <wifi-interface> [ssid]`, run with `sudo bash`:
1. Asks for the hotspot password unless `PASSWORD` is set (8 to 63 characters; never taken as an argument, so it does not land in the process list). Refuses to run twice.
2. Prints a warning if the VPN client (`mullvad status`) reports a connection, and carries on.
3. Creates the virtual access-point interface `tattle0` on the Wi-Fi card, with a MAC address of its own (`iw dev <wifi> interface add tattle0 type __ap addr 02:00:00:00:00:01`; the address can be changed with `AP_MAC`). Then waits up to 10 seconds until NetworkManager lists `tattle0` as anything other than "unmanaged". If it is still unmanaged, it asks once with `nmcli device set tattle0 managed yes` and waits again; if that fails too, it stops with a clear message and cleans up.
4. Lets NetworkManager settle, for up to 20 seconds, and does not force a layout. Adding an interface makes NetworkManager reshuffle; on our card it moves the normal Wi-Fi onto `tattle0` and frees the real interface. The script waits until one of the two interfaces has held the normal Wi-Fi for 3 seconds while the other is usable, and picks **the other one** for the hotspot. If neither is on the normal Wi-Fi after 20 seconds it carries on, with a clear warning that the hotspot will have no internet. It saves the hotspot interface's name in `/run/tattle-box.state`, a file that disappears at reboot.
5. Adds three firewall chains of its own (gone after a reboot):
   All three name the hotspot interface chosen in step 4.
   - `TATTLE-IN`: from the hotspot, only DHCP (67), DNS (53) and the sensor's port (5300) may reach the laptop.
   - `TATTLE-DNS` (nat): every packet to port 53 from the hotspot is redirected to port 5300.
   - `TATTLE-FWD`: from the hotspot, port 853 (DNS-over-TLS and DNS-over-QUIC) is rejected, and so is the VM's network (`VM_NET`, default `192.168.122.0/24`), so phones cannot reach the backend.
6. Starts the NetworkManager hotspot on the chosen interface: 2.4 GHz, WPA2. NetworkManager provides DHCP and NAT. Phones get `10.42.0.x`; the laptop is `10.42.0.1`. It prints NetworkManager's device table before and after, and says in plain words which interface is the hotspot and which carries the internet.
7. If anything fails halfway, it runs `box-down.sh`.

`box-down.sh` removes exactly those three chains, stops and deletes the hotspot profile (it holds the password), and removes `tattle0`. It reads the hotspot interface's name from the state file, and also works without it by finding the rules that point at our chains. If the normal Wi-Fi was on `tattle0`, the laptop's internet drops for a few seconds until NetworkManager reconnects on the real interface. Safe to run twice.

`box/README.md` holds the full host checklist and troubleshooting. The laptop needs only plain copies of `sensor/` and `box/`, side by side, anywhere; no repository checkout.

### 6.3 Backend: `backend/`

A single Python process (FastAPI on uvicorn, port 8000). Everything captured lives in memory and is gone on Wipe or restart; the optional database is the one exception (6.4).

| File | What it does |
| --- | --- |
| `app/main.py` | The web application: all routes, the WebSocket, background tasks (health and summary ticker, AI worker), wiring to the database and the optional AI module. It also serves the show screen's files from `frontend/` at `/` (read at each request; if `frontend/index.html` is missing, `/` redirects to `/debug`) |
| `app/state.py` | The in-memory state and all its rules: turning events into hits, devices, dedupe, blocking, sessions, wipe, bounds |
| `app/kb.py` | Loads the knowledge base and overrides; looks a name up by walking up its labels; lists a company's domains for blocking |
| `app/summary.py` | Session statistics, and the template sentence that describes a session |
| `app/labels.py` | The privacy-label fact-check: finds the label file, counts what the session contacted, applies the verdict rules |
| `app/explain.py` | "Who is this company?" for the detail panel: collects a company's server names from the lookups on record and builds the plain sentence that needs no model |
| `app/db.py` | The optional Postgres layer: a write queue drained by one background task, schema set-up, history queries |
| `app/hub.py` | Sends each message to every connected WebSocket client without ever waiting for a slow one |
| `app/validate.py` | The checks for untrusted input: is this a plain host name, is this an IP address, cut free text to printable characters |
| `app/guard.py` | A layer in front of every request: 1 MB body limit, refusal of cross-site writes, a no-sniffing header |
| `app/debug.html` | A plain control page at `/debug`: live table of hits, block, session start/stop, rename, persist, wipe |
| `app/present.html` | A plain presenter page at `/present`: one phone's companies as coloured blocks, a counter, the summary, the privacy banner. **Insurance only**, in case the show screen fails. It shares no code with the show screen |
| `start.sh` | One command to start the backend for the demo (`bash backend/start.sh`): reads `.env` as plain text, prints the addresses, listens on all interfaces |
| `sql/schema.sql` | The database tables (6.4) |
| `requirements.txt` | fastapi, uvicorn, psycopg (the Postgres driver). `requirements-dev.txt` adds pytest and httpx for the tests |

**Rules worth knowing** (all implemented and tested):

- **Clock:** each batch from the sensor is shifted so its newest event is "now" on the backend's clock; spacing inside the batch is kept.
- **Dedupe:** same phone and name within 2 s is one hit. The window does not slide, so an app retrying a blocked name every second still counts once per 2 s.
- **Classification order:** overrides (searched all the way up the name), then the tracker list, then known AI answers; otherwise `unknown`.
- **Devices:** identified by their hotspot address. Named "Device N" until renamed through the API or named by a sensor running with `--names`. At most 256. A loopback address (`127.0.0.1`) is the box asking its own sensor: that "device" is named "box self-test", takes no number, and is left out of device counts on the backend's pages.
- **Blocking:** by company or by single domain. Blocking a company blocks every domain the knowledge base assigns to it (and names the AI assigned to it). At most 500 blocks. The `blocked` message lists what each company block covers, and `/debug` shows it in words, with the reminder that a block acts on new connections only.
- **Sessions:** one at a time: a device, an optional app name, a start time. Starting a new one replaces the old.
- **Summary:** a few short sentences made to be read aloud, for example: "In 40 seconds, Demo Game contacted 9 companies: 4 advertising (Google, AppLovin, Unity and 1 more), 2 analytics (Sentry, AppsFlyer), and 3 others. 2 lookups were blocked." A company counts once, under the category it was mostly contacted for. Advertising, analytics, social and fingerprinting are named; the rest are "others". It says "contacted", never "sent".
- **Company explanation:** `GET /api/explain` describes one company for the detail panel (7.6a). It answers at once with a sentence built from the knowledge base. If the AI module has `explain_company`, the backend asks it in the background and hands out its text from the next call on. One text per company, phone and session is kept in memory (500 at most) until the next wipe; after a failed call the model is asked again 15 s later at the earliest.
- **Wipe:** clears devices, hits, blocks, the session, the summary, company explanations and AI answers from memory, and deletes the running session's rows from the database. It does not delete finished sessions.
- **AI is optional:** if `app/ai.py` is missing or fails to import, the backend runs without it. Its calls happen in background tasks with a 10 s limit; a failure only sets `health.ai` to false.
- **Health:** broadcast every 5 s and whenever it changes. If `AI_BASE_URL` is set, the backend also asks the model server for its list of models every 15 s and reports whether it answered as `ai_endpoint`: that shows a dead tunnel before any AI call is made.
- **Memory bounds:** last 5,000 hits; 500 names waiting for the AI; 5,000 remembered AI answers; 500 company explanations; 256 devices; 50 WebSocket clients, each allowed to fall 2,000 messages behind before it is dropped.

**Settings** (environment variables; the backend does not read `.env` itself, `start.sh` does):

| Variable | Default | Meaning |
| --- | --- | --- |
| `KB_PATH` | `data/kb.json` | the knowledge base |
| `KB_OVERRIDES_PATH` | `data/kb_overrides.json` | the hand-written overrides |
| `AI_CACHE_SEED_PATH` | `data/ai_cache_seed.json` | optional precomputed AI answers |
| `LABELS_DIR` | `data/labels` | privacy label files |
| `DATABASE_URL` | none | Postgres connection string; unset means no database |
| `AI_MODEL` | none | shown as the author of AI-written sentences |
| `AI_BASE_URL` | none | the model server's address, used by `ai.py`. If set, the backend checks every 15 s that it answers. With the SSH tunnel: `http://127.0.0.1:8081/v1` |
| `AI_TOKEN` | none | used by `ai.py`. Ollama needs no key, so the placeholder `unused` is fine |

**Tests:** `backend/tests/`, 116 tests with a Postgres available (102 without; the database tests skip). They cover the knowledge base, every state rule, the whole HTTP and WebSocket surface, the label check, the company explanation, the database layer against a real Postgres in a container, and the security rules (section 11). The AI module is replaced by a stand-in in tests.

### 6.4 Database layer (optional): `backend/app/db.py`, `backend/sql/schema.sql`

- **What for:** history of our own lab phones (the "provided backend" sponsor track), and a cache of AI answers.
- **Never on the live path:** writes go into a queue (5,000 at most) and one background task executes them. If the database is slow or gone, nothing on screen changes; `health.db` becomes false and `health.db_error` says why in one sentence.
- **Set-up:** on every connect the backend runs `schema.sql` (all statements are "create if not exists") and copies the knowledge base into the `kb_domains` table. If our database user may not create tables, the backend keeps running and reports it; someone with rights runs `schema.sql` once by hand, and the backend notices within seconds.
- **Tables:**

| Table | Holds |
| --- | --- |
| `kb_domains` | a copy of the knowledge base: domain, company, category, source |
| `devices` | lab phones: device id, name, persist flag, updated time |
| `sessions` | one row per recorded session: id (a UUID made by the backend), device id, label, started, stopped (empty while running or if the backend stopped first) |
| `hits` | lookups during a recorded session: session id, time, domain, company, category, source, blocked, block reason. Deleting a session deletes its hits |
| `ai_cache` | AI answers: domain, company, category, confidence, model, created |

- **What gets stored:** a session is recorded only while its device is marked `persist`. Nothing from an unmarked phone is ever written. Hits outside a session are not stored. The mark is never restored from the database after a wipe or restart, because hotspot addresses get reused and a guest's phone must not inherit a lab phone's mark. AI answers are cached only for names a marked phone looked up.
- **Tests:** against a real Postgres 17 in a container, each test in its own throwaway schema. Including: a database user without rights, a lost connection, a write that keeps failing.
- **Unverified:** the organizers' Postgres itself (rights, encryption settings, speed).

### 6.5 Tools: `tools/`

| File | What it does |
| --- | --- |
| `fake_sensor.py` | Replays a recorded file of events into the backend with the original timing, standard library only. Options: `--backend`, `--speed N`, `--loop`. It reads the blocklist too, so blocking works in replay mode. This is the development loop for FRONT and AI, and the demo fallback |
| `selfcheck.py` | End-to-end check without Wi-Fi: starts its own backend and a sensor on loopback, replays the synthetic session, sends real DNS queries through the sensor, checks what arrives on `/ws`, and that the show screen is served at `/` (21 checks) |
| `build_kb.py` | Downloads Disconnect's `services.json` and writes `data/kb.json`. It tidies company names by one rule for all entries: names written entirely in lowercase get capitals ("reddit" becomes "Reddit"), stray spaces are removed, and a short table holds hand-picked renames; names styled on purpose ("eBay") are left alone. A note at its top lists the choices made and what deserves a second look. Written by BOX as a first version; it belongs to AI |
| `try_ai.py` | Calls each function of an `ai.py` once with sample data, under the backend's time limit, and checks the shape of the answers (the two optional functions, `label_check` and `explain_company`, only if they exist). For the AI owner |

### 6.6 Data: `data/`

- **`kb.json`**: 4,430 domains from Disconnect's list (2,738 advertising, 974 analytics, 429 content, 239 fingerprinting, 50 social), 1,877 companies (52 of the names tidied by the rule above). Licensed CC BY-NC-SA 4.0, like the list it is derived from; credited in the README; non-commercial use only. Never edited by hand: rebuilt with `python3 tools/build_kb.py`.
- **`kb_overrides.json`**: 65 hand entries in five groups. With them the backend knows 4,489 names in all.
  - Apple's system domains as `vendor` (with Apple's advertising hosts as `advertising`).
  - The big content networks (Akamai, Fastly, CloudFront and `amazonaws.com` as "Amazon Web Services") as `content`.
  - Phone-only SDK hosts the web-centred list lacks (Firebase, Google's app analytics and app advertising hosts `app-analytics-services.com` and `app-ads-services.com`, AppLovin's second domain, Unity Ads, ironSource, Vungle, Mintegral, InMobi, AppsFlyer's SDK domain).
  - The own servers of four apps seen in the live tests, as `vendor`: Netflix (`netflix.com`, `nflxvideo.net`, `fast.com` and others), Discord (`discord.com`, `discord.gg`, `discordapp.net` and others), OpenAI (`chatgpt.com`, `openai.com`, `oaistatic.com` and others) and, since Saturday 18:30, Reddit (`reddit.com`, `redd.it`, `redditmedia.com`). The list files `reddit.com` as `content`, which showed Reddit's own servers as a "CDN" while the Reddit app was the one being used. Because an override also covers every name under it, the two Reddit hosts the list files as trackers (`alb.reddit.com`, `pixel-config.reddit.com`, category `social`) got overrides of their own that keep that category. `redditstatic.com` is untouched: the list files it as `advertising`.
  - Microsoft, since Saturday 18:30. Its sign-in hosts `microsoftonline.com`, `msftauth.net` and `msauth.net` were unknown; they are now Microsoft, `content`, the category the list gives `microsoft.com`. And `linkedin.com` and `licdn.com` are the company "LinkedIn", `social`. Why: the list files LinkedIn's hosts under their owner, Microsoft, with the category `social`. A phone that loaded only LinkedIn pages therefore showed a bubble "Microsoft, social network", which is wrong about Microsoft and hides LinkedIn. No Microsoft name is `social` any more.
  - Other apps' own servers are deliberately left for the AI classifier. The file belongs to the AI owner; the Saturday 18:30 entries were made by BOX from what the live screen showed, and are marked in `docs/TEAM.md` for review.
- **`replays/demo-synthetic.jsonl`**: 274 made-up events over 119 seconds: a phone ("Test iPhone A") joining, then a free game with ad mediation, using real public host names plus a fictional `puzzle-garden-game.example` that stays unknown on purpose. With the real knowledge base it gives 96 lookups to 13 companies and 4 hidden-traffic attempts. **It is simulated traffic, not a recording of a real phone.** No real recording exists yet.
- **`labels/`**: empty. One file per demo app is planned (shape in section 7.8). BOX writes them, from the App Store label of each app as text or screenshots.
- **`ai_cache_seed.json`**: does not exist. Optional (shape in 7.7).

### 6.7 The show screen: `frontend/`

The page the judges look at, full screen on the laptop, while one of them uses the test iPhone. Built by BOX on Saturday between 17:00 and 17:45, after the FRONT role merged into BOX; the detail panel and the logo were added between 18:15 and 18:45. It is **plain HTML, CSS and JavaScript**: no framework, no build step, no `npm install`, and nothing loaded from the internet (the font is a file in the repository). The backend serves the folder at `/` and reads the files at each request, so an edit shows after a reload.

| File | What it does |
| --- | --- |
| `index.html` | The page's structure: the stage, the counters, three cards, three overlays (How it works, operator, detail panel), and the logo as an inline SVG drawing. No inline script or style |
| `app.css` | The look: dark, sized to be read from one to two metres. Colours and the scaling unit are variables at the top |
| `app.js` | About 650 lines: the WebSocket, what to count, the bubble layout, the detail panel with blocking, the operator keys |
| `logo/index.html`, `logo/logo.css` | The logo preview page at `/logo`: the three turtle drawings the team chose from. No script |
| `assets/tattle-architecture.png` | A copy of `docs/tattle-architecture.png`, shown by "How it works" |
| `assets/fonts/` | The Inter typeface (one variable font file, latin characters) and its license (SIL Open Font License) |
| `README.md` | How to see it, what is on it, the keys |

**What is on the screen:**

- **The stage.** A phone outline in the middle with the phone's name ("Device 1") and the session's app name under it. Around it, one **bubble per company** the phone contacted. A bubble's colour and a short text tag give the category (`AD` advertising, `AN` analytics, `SO` social, `FP` fingerprinting, `CDN` content delivery, `OWN` the phone maker's or the app's own servers, `?` not identified); colour is never the only signal. Its size follows the number of lookups (the square root, so one busy company does not swallow the screen). It pulses at every new lookup, and a thin line to the phone flashes. Servers that no list or model knows share one bubble, "Not identified". A company the AI named has a dotted outline and the tag "AI guess".
- **The detail panel.** A click on a bubble no longer blocks at once (it did until Saturday 18:15): it opens a large panel about that company. From top to bottom:
  - The company's name with the same category tag as its bubble, and how many server names and lookups it stands for.
  - **Who it is.** The panel opens immediately with one plain sentence built from the knowledge base, for example "AppLovin: an advertising company, according to our tracker list." At the same time it asks the backend (`GET /api/explain`, section 7.6a). If the AI module can explain companies, "AI is thinking…" blinks next to the sentence, and after a few seconds the AI's two or three sentences take its place: who the company is and what it is most likely doing in this app, judging by the server names. A badge always says which text is on screen: "FROM OUR TRACKER LIST", "FROM THE AI" (with "written by <model>"), or "AI GUESS, NOT ON OUR LIST" for a company only the AI has named. Under an AI text the list's sentence stays as a smaller facts line. The page remembers each answer, and so does the backend, so opening the same company a second time shows the AI's text at once.
  - **What is blocked right now**, as a large badge: "BLOCKED" (red), "2 OF 7 BLOCKED" (amber) or "NOT BLOCKED", with one line of explanation ("A block stops new connections: close the app and open it again.") and the button "Block <company>", which becomes "Unblock <company>".
  - **Every server name** the phone asked for under that company, most looked up first: its own category tag, the name, how many times it was asked for, when it was last seen ("12 s ago", counting on), and its state: "open", "BLOCKED · refused ×4" (refused means: the phone asked and we answered "does not exist"), or "refused ×4 earlier" for a name that was blocked and is open again. Each row has its own Block or Unblock button; a blocked row is tinted red with the name struck through. While the whole company is blocked the row buttons are hidden, because a single name cannot be let through then.
  - A long server name is shortened in its front part and never at its end, because the last two parts of a name say whose server it is: `telemetry.puzzle-garden-game.example` may shrink to "teleme…puzzle-garden-game.example", never the other way round. The front part is shown dimmer. The full name appears when the pointer rests on it. Names are inserted as text only.
  - "Not identified" opens the same panel: the names no list knows, each with a Block button of its own, and "AI guess: analytics" under a name where the AI gave a category but no company. (A name the AI can put a company to leaves this bubble and joins that company's.)
  - It closes with `Esc`, with its Close button, or with a click outside it. Its text is sized for one to two metres: at 1920x1080 the explanation is 28 pixels high and the rows 24.
- **On the bubbles.** A blocked company's bubble is grey with a dashed outline and a struck-through name, and its count becomes "blocked ×N", which keeps climbing as the app keeps trying. A company with only some names blocked keeps its colour and gets a dashed outline.
- **Counters** (right): companies contacted (large); how many of them are advertising and how many analytics; seconds into the session; blocked attempts; hidden-traffic attempts.
- **"In plain words":** the backend's summary sentence, with "written by <model>" when the AI wrote it.
- **"App Store privacy label":** appears when a label file matches the session's app name. It shows "DOES NOT MATCH" or "CONSISTENT" (word and colour), the verdict sentence, the rule-based sentence under it when the AI wrote the verdict, and what the label says. The page asks `GET /api/label-check` when a session starts or stops and every 4 seconds while one is on screen.
- **"Live: what the phone asks for":** the latest server names, newest first, each with its tag and company; refused ones are struck through. It makes the step from raw name to company visible. It gives way to the label card when there is one, because both do not fit.
- **Top right:** "live" or "reconnecting…" (the WebSocket), "sensor: live" or "sensor: silent" (whether the sensor's heartbeat is moving), "AI: on" or "AI: off" (`health.ai_endpoint` or `health.ai`), and buttons for the two overlays.
- **The privacy banner** at the bottom, always: "Reads server names only, never content. Nothing is kept after you leave."
- **Overlays:** "How it works" (the architecture diagram with one sentence under it) and the operator panel (choose the phone, type the app name, start, stop, wipe).

**Operator keys:** `S` opens the panel with the app-name field ready when no session runs (Enter starts it) and stops the session when one runs. `W` pressed twice within 3 seconds wipes everything. `H` opens "How it works", `C` the operator panel, `F` full screen, `Esc` closes. Keys are ignored while typing in a field.

**The logo.** A turtle, drawn as inline SVG in the page (no image file). Three variants are on a preview page at `/logo`, each at browser-tab size, at header size next to the name, and large, on a dark and on a light background: **A "Radar"** (seen from above, the shell is a radar screen with a sweep and a blip), **B "Network"** (seen from above, the shell's plates form a node with six links) and **C "Hotspot"** (seen from the side, the shell is a dome over a hotspot's signal arcs). **The team chose A** on Saturday at 19:00, and it is the drawing in the header and on the browser tab. (C was there for the first three quarters of an hour, as BOX's pick; the preview page stays as a record of the choice.) The browser-tab icon is not a second file: when the page loads, the script turns the header's drawing into a `data:` address and sets it as the icon, so changing the logo means changing one drawing. The drawing's colours are written out as values (the same ones as the variables in `app.css`), because the tab icon is shown without the stylesheet.

**Which phone and which lookups it shows.** One phone at a time: the session's phone, from the session's start; after a stop it keeps showing that session (frozen, marked "ended") until the next start or a wipe. Without any session it shows the phone that sent the latest lookup, with everything it sent. The laptop's own test lookups ("box self-test") are never shown. A company's category is the one it was mostly contacted for, the same rule as the summary sentence, so the counters and the sentence agree. Guard-list lookups only feed the hidden-traffic counter.

**How the bubbles are placed.** A small physics loop of our own, about 40 lines, run once per screen frame: every bubble is pulled towards the middle (more strongly up and down than sideways, so the cloud takes the screen's wide shape), bubbles that overlap push each other apart, a rectangle around the phone and its labels pushes bubbles out, and the whole cloud is shifted so that its centre of mass stays on the phone. All bubbles are scaled together so that they fill about 40 % of the stage whether there are five or seventy. The loop stops when nothing moves. *Rejected:* a charting or graph library (one more thing to vendor and to trust for a layout this small).

**Rules the code follows** (each one is tested, section 11): text from the network is put on the page with `textContent` only; no `innerHTML`, no `setAttribute`, no inline script or style; no address outside the backend appears in the files. The WebSocket reconnects after one second and starts from a fresh snapshot; message types the page does not know are ignored. Not covered by a test, but deliberate: the detail panel's rows are updated in place and keep their order while the pointer is on the list. Lookups arrive several times a second, and a list that is rebuilt or re-sorted between pressing and releasing the mouse button swallows the click.

**How it was checked.** In a headless Firefox in the VM, against a separate test backend fed by `tools/fake_sensor.py`, at 1920x1080 and 1440x900: the simulated session; a made-up session with 72 companies at once; blocking, the bar, Undo and unblocking; the label card with a stand-in label; start, stop and wipe by keyboard; a phone name and an app name containing `<img …>` and `<script>` (shown as text, no element created). With 72 bubbles and lookups arriving five times faster than real, the headless browser drew 32 to 37 frames a second without a graphics card. **Not yet checked:** on the real laptop's browser, with a real phone, or at the distance of a judges' table.

**How the detail panel was checked** (Saturday 18:30, same set-up, with a stand-in AI module that answers after four seconds): at 1920x1080, opening Google's panel shows the list's sentence and "AI is thinking…" at once and the stand-in's text four seconds later; blocking the company turns every row to "BLOCKED" and the refused counts climb with the replay; blocking and unblocking one server name gives "1 OF 6 BLOCKED"; the "Not identified" panel lists its name with "AI guess: analytics" and blocks it; `Esc`, the Close button and a click outside each close it; reopening a company shows the AI's text at once, with no "thinking" state; a company name made of `<img …>` and an AI text made of `<script>` and `<b>`, both from the stand-in module, are shown as text and create no element. One look at 1440x900. The tab icon was checked only as far as "the page sets a `data:` icon and the policy allows it"; **nobody has looked at a real browser tab yet**, and the panel has not been seen with a real phone's traffic or a real model.

**Known weak points.** The architecture image has small text that is hard to read from two metres, and it was drawn before this screen existed (its "Browser" box does not mention it). The look has not been reviewed by the AI owner. There is no history view (the `/api/history/…` endpoints have no screen yet) and the `malformed` count is not shown here (it is on `/debug`). In the detail panel, the sentence from the list only knows a company's category, so it is thin ("an advertising company") until an AI text replaces it; and an AI text is written once per company and session, from the server names seen at that moment, and is not refreshed when more names arrive.

### 6.8 Not built yet

- **`backend/app/ai.py`** (AI) and the model server behind it. That includes `explain_company`, the function behind the detail panel's AI text: the backend and the screen are ready for it and tested with a stand-in.
- **A history view** on the show screen for `/api/history/sessions` and `/api/history/top-companies`.

---

## 7. Interfaces, with the exact data shapes

This section is the contract between the parts. Times are seconds since 1970 as decimal numbers. Names are lowercase without a trailing dot.

### 7.1 Categories

`advertising`, `analytics`, `social`, `fingerprinting`, `content`, `vendor`, `unknown`.

### 7.2 Knowledge base files

```json
{ "domains": { "doubleclick.net": { "company": "Google", "category": "advertising", "source": "disconnect" } } }
```

`data/kb_overrides.json` has the same shape. Both may carry other top-level keys (`license`, `about`); only `domains` is read. **Lookup:** the overrides are searched first, walking up the name (`a.b.example.com`, `b.example.com`, `example.com`); only if no override matches is the list searched the same way. So an override wins for its name and everything under it, and among overrides the most specific wins (`ca.iadsdk.apple.com` beats `apple.com`).

### 7.3 Sensor → backend: `POST /api/events`

```json
{ "events": [
    { "ts": 1760070000.123, "client_ip": "10.42.0.23", "client_name": null,
      "qname": "ads.example.com", "qtype": "A", "blocked": false, "block_reason": null }
  ],
  "malformed": 0 }
```

- `client_name` is `null` unless the sensor runs with `--names`.
- `block_reason` is `"user"` (blocked from the screen), `"guard"` (guard list) or `null`.
- `malformed` (optional) is how many names the sensor refused since its last batch.
- At most 2,000 events per request. The answer is `{"accepted": <number of events received>}`. Events with a bad name are dropped and counted, without failing the batch.

### 7.4 Backend → sensor: `GET /api/blocklist`

```json
{ "version": 3, "domains": ["doubleclick.net"] }
```

Matched by suffix. The sensor fetches it every second; this also serves as the sensor's heartbeat.

### 7.5 Backend → screens: WebSocket `/ws`

The page only listens. The first message is a `snapshot` of everything so far; then single messages. If the connection drops, reconnect and a fresh snapshot arrives.

```json
{"type":"snapshot","devices":[{"device_id":"10.42.0.23","name":"Test iPhone A","persist":true}],
 "hits":[ …hit messages… ],"blocked":{"companies":[],"domains":[],"covers":{}},
 "session":null,"last_session":null,"summary":null,
 "health":{"db":false,"db_error":null,"ai":false,"sensor_seen":1760070000.0,"kb":4486,"malformed":0,"ai_endpoint":null}}

{"type":"device","device_id":"10.42.0.23","name":"Device 1","persist":false}

{"type":"hit","device_id":"10.42.0.23","domain":"ms.applovin.com","company":"AppLovin","category":"advertising",
 "source":"list","blocked":false,"block_reason":null,"ts":1760070000.1}

{"type":"classified","domain":"odd.example.io","company":"Example Analytics","category":"analytics","source":"ai","confidence":0.7}

{"type":"summary","device_id":"10.42.0.23","text":"In 40 seconds, Demo Game contacted 9 companies: …","by":"template"}

{"type":"blocked","companies":["AppLovin"],"domains":[],
 "covers":{"AppLovin":["adjust.com","applovin.com","applvn.com","axon.ai","mopub.com"]}}

{"type":"session","session":{"device_id":"10.42.0.23","label":"Demo Game","started":1760070000.0}}
{"type":"session","session":null}

{"type":"health","db":true,"db_error":null,"ai":false,"sensor_seen":1760070000.0,"kb":4486,"malformed":0,"ai_endpoint":null}

{"type":"wiped"}
```

- `hit.source` is `list` (tracker list), `override`, `ai` or `unknown`. `company` is `null` when unknown.
- `hit.blocked` with `block_reason: "user"` is a **blocked attempt**. With `block_reason: "guard"` it is a **hidden-traffic attempt**: show and count it on its own, not in a company's bubble (its `company` is whoever runs the relay, such as Apple, or `null`).
- `hit.ts` is on the backend's clock, the same clock as `session.started`. A hit belongs to the session when the device matches and `ts >= started`.
- `snapshot.last_session` (also in `GET /api/state`): the session that just stopped, `{"device_id","label","started","stopped"}`; `null` while a session runs, before the first one and after a wipe. Added for the show screen, so that a page opened after the stop still shows that session, and so that the page counts exactly the lookups the final summary counted (`ts <= stopped`). The `session` message is unchanged: `null` on stop.
- `classified`: the AI named a domain that arrived as `unknown`; update the hits already shown for that `domain`.
- `summary`: about every 3 s while a session runs and new hits arrived, once when it stops, and again if the AI writes a better one. `by` is `"template"` or the model's name.
- `device.name` is never empty. A device whose `device_id` is a loopback address (`127.0.0.1`, `::1`) is the box testing itself, named "box self-test": leave it out of device lists and counts.
- `blocked.covers` says, for each blocked company, which names the block covers. Each name also covers everything under it. An empty list means no domain of that company is known, so nothing is blocked. A blocked single domain covers itself and its subdomains only.
- `health.sensor_seen`: when the sensor last called in; older than about 10 s means it is gone. `kb`: how many domains are loaded (0 means the file is missing). `db_error`: `null`, or why the database is unusable. `malformed`: names refused since the backend started. `ai`: whether the last call made by `ai.py` worked. `ai_endpoint`: whether the model server answers at `AI_BASE_URL` (`null` if none is set); it is about the server and the tunnel, not about `ai.py`.
- `wiped`: forget everything shown. An empty `blocked` and a `null` session follow.

### 7.6 Screens → backend: REST

```
POST /api/block            {"company": "AppLovin"}  or  {"domain": "x.example.com"}   → the new "blocked" message
POST /api/unblock          same body                                                   → the new "blocked" message
POST /api/devices/{id}     {"name": "Test iPhone A", "persist": true}  (either field)  → the "device" message
POST /api/session/start    {"device_id": "10.42.0.23", "label": "Demo Game"}           → the "session" message
POST /api/session/stop                                                                 → {"type":"session","session":null}
POST /api/wipe                                                                         → {"type":"wiped"}
GET  /api/state            the snapshot
GET  /api/health           the health fields
GET  /api/label-check      see 7.8
GET  /api/explain?company=<name>[&device_id=<ip>]    see 7.6a
GET  /api/history/sessions?limit=50          needs the database, see below
GET  /api/history/top-companies?limit=10     needs the database
POST /api/history/clear                      needs the database → {"cleared": true}
```

Every change is also broadcast on the WebSocket, so a page can ignore the response.

Errors: `422` with `{"detail": "…"}` for input that breaks a rule (no company or domain given, a device id that is not an IP address, a domain that is not a host name, text too long, more than 500 blocks). `413` for a body over 1 MB. `403 {"detail": "cross-site request refused"}` when a page from another site makes a `POST` or opens the WebSocket. `503 {"detail": "no database configured"}` or `{"detail": "database not reachable"}` from the history endpoints without a usable database.

**History answers:**

```json
{"sessions": [
  {"id": "<uuid>", "device_id": "10.42.0.23", "device_name": "Test iPhone A", "label": "Demo Game",
   "started": 1760070000.0, "stopped": 1760070090.0, "hits": 87, "blocked": 5, "hidden_attempts": 2, "companies": 14,
   "top_companies": [["Google", 14], ["AppLovin", 9]]}
]}

{"labels": [
  {"label": "Demo Game", "sessions": 2, "hits": 170, "hidden_attempts": 4,
   "top_companies": [{"company": "Google", "category": "advertising", "hits": 28, "blocked": 3, "sessions": 2}]}
]}
```

Sessions come newest first; `stopped` is `null` for one that is running or was cut off. `hits`, `companies` and `top_companies` leave out hidden-traffic attempts. `blocked` counts lookups blocked from the screen. `top-companies` groups by app name across all stored sessions; `limit` is companies per app; sessions without an app name are left out. `history/clear` deletes all stored sessions, their hits and the lab-phone rows; the knowledge-base copy and the AI cache stay.

### 7.6a Who is this company? `GET /api/explain`

Asked by the show screen when a detail panel opens. It works with no AI and no database.

```json
{"company": "Unity", "category": "advertising",
 "domains": ["auction.unityads.unity3d.com", "outcome-ssp.supersonicads.com", "logs.ironsrc.mobi"],
 "text": "Unity: an advertising company, according to our tracker list.",
 "by": "list",
 "fallback": "Unity: an advertising company, according to our tracker list.",
 "pending": true}
```

- **It never waits for the AI**, the same pattern as the label check (7.8). The first call answers with the sentence built from the knowledge base and, if the AI module has `explain_company`, starts that call in the background. `pending` is `true` while the model is being asked; the page asks again every 1.2 seconds while it is. A later call carries the AI's text in `text` and the model's name in `by`.
- `by` is `"list"` (no model wrote `text`) or the model's name. `fallback` is always the knowledge-base sentence, so a page can show it as a facts line under an AI text.
- `category` is the category the company was mostly contacted for. `domains` are its server names, most looked up first, 20 at most. Those three things (name, category, names) are exactly what the AI is given.
- **Which lookups count:** those of the session, running or just stopped, on the session's phone, in the session's time window; this is what the show screen displays. Without any session: the lookups of `device_id` if it is given, otherwise of every phone. Guard-list lookups never count.
- **The sentence without a model:** "<company>: <kind>, according to our tracker list.", where the kind follows the category (advertising: "an advertising company"; analytics: "an analytics company: it measures how an app is used"; social: "a social network"; fingerprinting: "a company known for fingerprinting: telling devices apart by their technical traits"; content: "a content delivery company: it serves files such as images and video for other companies"; vendor: "the phone maker's or the app's own servers"). For a company the knowledge base does not contain (the AI named it), it ends "…according to the AI's guess. It is not on our tracker list." The show screen builds the same sentence itself, so its panel opens before this endpoint has answered; the wording lives in two places (`backend/app/explain.py`, and the category table at the top of `frontend/app.js`) and must be changed in both.
- **Caching:** one AI text per company, phone and session start, kept in memory until the next wipe (500 at most; beyond that, only the list's sentence). The model is asked once per entry. After a failure (`None`, an exception, no answer within 10 s) `health.ai` turns false and the next question for that company is allowed 15 s later, when the panel asks again.
- The AI's text is cut to printable characters and 500 characters, and shown as text.
- A company nobody contacted gets the sentence, `"domains": []` and no AI call. `422` if `company` is missing, empty or longer than 100 characters, or `device_id` is not an IP address.
- **Unverified:** no real `explain_company` exists. The endpoint is tested with a stand-in function (12 tests: the sentences, the session window, the background call, caching, failures, the cap).

### 7.7 The AI module: `backend/app/ai.py` (not written yet)

```python
async def classify_domains(domains: list[str]) -> dict[str, dict] | None
    # -> {"odd.example.io": {"company": str | None, "category": str, "confidence": float}}
async def summarize(stats: dict) -> str | None
async def label_check(label: dict, stats: dict) -> str | None        # optional
async def explain_company(company: str, category: str, domains: list[str]) -> str | None   # optional
```

`stats` is:

```json
{"device": "Test iPhone A", "label": "Demo Game", "seconds": 27,
 "by_category": {"advertising": 109, "analytics": 20, "social": 6, "content": 10, "vendor": 38},
 "top_companies": [["Google", 38], ["Apple", 30], ["AppLovin", 25], ["Unity", 18], ["Puzzle Garden Games", 12]],
 "blocked": 13, "hidden_attempts": 8}
```

The contract: each function answers within 8 seconds and returns `None` on any failure, never raising. Answers are plain text; say "contacted", never "sent".

How the backend uses it:
- **`classify_domains`**: a background task looks once a second for unknown names, takes up to 10, and makes one call at a time with a 10 s limit. The names are exact host names. An answer upgrades the hits on screen (a `classified` message). A name is never sent if the overrides, the list, the seed file or the database cache know it, and never if it is a guard-list name. Each name is asked once until the next wipe. On failure, `health.ai` turns false and the same names are retried after 15 s.
- **`summarize`**: called once when a session stops. The template sentence is shown first; the AI's replaces it if it arrives in time.
- **`label_check`**: if it exists, its sentence becomes the verdict of the label check (7.8). It is asked in the background, never while a request waits, at most every 10 s, and only when the session has new lookups.
- **`explain_company`** (added to the contract on Saturday 18:30; the AI owner has still to write it): if it exists, its text becomes the explanation in the detail panel (7.6a). It receives the company's name, the category it was mostly contacted for, and up to 20 of its server names from the session, for example `("AppLovin", "advertising", ["ms.applovin.com", "rt.applovin.com"])`, and returns two or three plain sentences: who the company is, and what it is most likely doing in this app, judging by those names. It may say what a server is for; it must not claim that data was sent. Asked in the background, once per company and session.
- Whatever the module returns is trimmed (company 80 characters, summary 600, label verdict 400, company explanation 500) and shown as text.

**Seed file `data/ai_cache_seed.json`** (format proposed by BOX; the AI owner may change it): precomputed answers, loaded at startup if the file exists.

```json
{ "domains": { "odd.example.io": { "company": "Example Analytics", "category": "analytics", "confidence": 0.7 } } }
```

Keyed by the exact host name. Seeded names show with source `ai`, are never sent to the model, and survive a wipe.

**The model server** (set up by AI, in progress): Ollama on the AMD server, listening on that server's `127.0.0.1:11434` only, with no API key. From the backend's machine it is reached through an SSH tunnel:

```
ssh -N -L 8081:127.0.0.1:11434 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes amd
```

- `-N`: no remote command, only the tunnel. `-L 8081:127.0.0.1:11434`: local port 8081 leads to Ollama's port on the server. `ServerAliveInterval=30`: notice a dead connection. `ExitOnForwardFailure=yes`: stop at once if the port cannot be forwarded. `amd` is the SSH name of the server on the backend's machine (key authentication).
- The backend's `.env` then holds `AI_BASE_URL=http://127.0.0.1:8081/v1`, `AI_TOKEN=unused` (a placeholder; Ollama ignores it) and `AI_MODEL=<model>`. `ai.py` reads all three from the environment.
- `health.ai_endpoint` turns `true` once the tunnel is up and Ollama answers. **Unverified:** nobody has run the tunnel against this backend yet; the health check is tested against a stand-in server.

### 7.8 Privacy labels and the fact-check

One file per demo app, `data/labels/<app-slug>.json`, written by BOX from the App Store page (none exists yet):

```json
{"app": "Demo Game", "source_url": "<App Store link>", "checked": "<date>",
 "data_used_to_track_you": [], "data_linked_to_you": ["Identifiers", "Usage Data"],
 "data_not_linked_to_you": ["Diagnostics"], "data_not_collected": false}
```

`GET /api/label-check` (optionally `?app=<name>` to check another label) answers:

```json
{"session": {"device_id": "10.42.0.23", "label": "Demo Game", "started": 1760070000.0, "stopped": null},
 "label": { …the label file as is… },
 "observed": {"seconds": 95, "lookups": 87, "blocked": 5, "hidden_attempts": 2,
              "by_category": {"advertising": 41, "vendor": 16},
              "companies": [{"company": "Google", "category": "advertising", "hits": 14}],
              "advertising_companies": 9, "tracking_companies": 12},
 "level": "mismatch",
 "verdict": "The label lists nothing under \"Data Used to Track You\", but this session contacted advertising servers of 9 companies.",
 "verdict_by": "rules",
 "rule_verdict": "The label lists nothing under \"Data Used to Track You\", but this session contacted advertising servers of 9 companies.",
 "note": "Tattle sees which servers a phone looks up, not what is sent to them."}
```

- The session is the running one, or the one that just stopped. A label matches when its `app` field or its file name equals the session's app name, ignoring case and punctuation. Files are re-read on every call.
- `level`: `mismatch`, `consistent`, `no-label` (then `label` is `null`) or `no-session` (then `observed` is `null` too). It always comes from the rules.
- **"advertising servers of N companies".** N counts every company with at least one advertising lookup, also a company mostly contacted for something else (Google's ad servers count even when most of its lookups were analytics). The show screen's "advertising" counter counts companies *mostly* contacted for advertising, so it can be lower. The sentence used to say "N advertising companies", which looked like a contradiction next to the counter.
- **The rules:** the label says "no data collected" but tracking companies were contacted: mismatch. The label lists nothing under "Data Used to Track You" but advertising companies were contacted: mismatch. Everything else: consistent.
- `rule_verdict` is always the rule-based sentence (the facts line). `verdict` is the sentence to show large: the AI's once there is one, otherwise the same rule-based sentence. `verdict_by` is `"rules"` or the model's name.
- The endpoint never waits for the AI: the first call answers by the rules; a later call carries the AI's sentence. Pages poll every few seconds while the panel is open.
- `companies` holds up to 20, most contacted first. `tracking_companies` counts companies with advertising, analytics, social or fingerprinting lookups.

### 7.9 Ports and addresses

| What | Where |
| --- | --- |
| Sensor | UDP and TCP 5300 on the laptop (not 5353, which is mDNS) |
| Backend | 8000 in the VM |
| Frontend | no port of its own: plain files the backend serves at `/` on 8000 |
| Hotspot | laptop `10.42.0.1`, phones `10.42.0.x` |
| VM network | `192.168.122.0/24`; the VM's address there is written `<vm-ip>` in the docs |

---

## 8. Design decisions and the alternatives we rejected

Each entry: what we do, why, and what we decided against.

**Capturing**

1. **We are the phone's DNS resolver; we do not sniff.** Being the one who answers means the same piece of code both sees every name and can refuse to answer, so capture and blocking are one job. *Rejected:* passively listening with a packet sniffer (sees names but cannot block; kept only as a fallback plan); ARP spoofing on someone else's network, as IoT Inspector does (an attack technique, intrusive); an app or VPN profile on the phone (needs installing, which kills "hand me your phone"); decrypting traffic with a proxy (looks at content, which we promise never to do).
2. **DNS only; no SNI capture.** DNS gives us the name before the connection even starts. Reading SNI would need packet inspection for the same information, and ECH is making SNI unreadable anyway. It is on the "don't build" list.
3. **Block by answering NXDOMAIN.** Simple, instant, and done by the code that already answers. The app fails fast and usually retries, which makes a good "it keeps trying" counter. It stops new connections only (see 3a). *Rejected:* blocking IP addresses in the firewall (one address serves many companies on a CDN), answering with a fake address (apps hang instead of failing).
3a. **Every answer gets a 10-second lifetime.** A block can only act when the phone asks again, and by default it may not ask again for minutes or hours. In the live test a blocked name stayed reachable for exactly this reason. So the sensor shortens every answer's TTL to 10 seconds. The cost is more lookups, which is harmless here and makes the screen livelier. *Rejected:* leaving lifetimes alone (blocks seem broken); a lifetime of zero (some systems treat it oddly, and 10 seconds is fast enough for a demo); cutting open connections (we would have to interfere with traffic, which we do not touch).
4. **Our own password-protected hotspot with an honest name.** The phone must use us as its gateway, and nothing may be installed on it. The network is called `Tattle-Demo`, has a WPA2 password, and is never open and never named to look official: people must know what they join.
5. **Redirect port 53 for any destination.** In the hardware test an iPhone kept sending DNS to a leftover server (its VPN's). Relying on DHCP's "use this DNS server" alone would have missed it.
6. **A guard list for encrypted DNS and Private Relay.** If the phone switched to DoH, DoT or Private Relay we would see nothing. We answer NXDOMAIN for the well-known names involved, and reject port 853, so the phone falls back to plain DNS. For Private Relay this is Apple's documented opt-out, and the iPhone tells its user. *Rejected:* ignoring it (blind), blocking provider IP addresses (endless list). We are open about this in the pitch.
7. **Guard-list lookups are counted apart ("hidden-traffic attempts").** They used to inflate "blocked trackers" and showed up as contacts to Apple. They are neither.
8. **Odd names are refused outright.** A name that is not a plain host name gets REFUSED and is not looked up. *Rejected:* looking it up but keeping it off the screen. That would be "resolved but hidden", exactly what we tell judges we don't allow, and it would let an app tunnel data through names we never show. The cost: a real app using such a name would fail on it; underscores, hyphens and international names in their encoded `xn--` form are all fine, so this should be rare.

**The box**

9. **Hotspot and normal Wi-Fi on one card, through a virtual interface.** Observed to work on our card. It avoids a second adapter and lets the laptop keep its own internet. The virtual interface gets a MAC address of its own: when it inherited the card's address, NetworkManager refused to manage it (section 9).
9a. **We do not force which interface does which job.** When the virtual interface appears, NetworkManager moves the normal Wi-Fi onto it and frees the real one. The first version of the script forced it back ("pinning") so the layout would be predictable; on the real card that step failed, because the real interface was not usable at that moment. Both layouts work, so the script now waits for NetworkManager to settle and puts the hotspot on whichever interface is free; the firewall rules follow. *Rejected:* forcing the layout (fights the network manager and failed on hardware); always using the real interface for the hotspot (wrong whenever the Wi-Fi stays put).
10. **The sensor listens on port 5300 and the firewall redirects 53 to it.** So the sensor needs no administrator rights. 5300 rather than 5353 because 5353 is mDNS and often taken.
11. **Narrow firewall rules for hotspot phones: DHCP, DNS and 5300 only.** The hand test allowed everything on the hotspot interface. Narrower is safer when judges' phones join. Because the narrow set is untested, the one-line fallback to "allow everything" is documented in `box/README.md`.
12. **Our own firewall chains, temporary.** Three chains with our name make it possible to remove exactly what we added. Nothing is saved across a reboot.
13. **Phones are firewalled away from the VM network.** The backend's API has no login and now listens beyond the laptop itself; a guest phone must not be able to wipe or block.
14. **The password is typed at a prompt, never passed as an argument.** Arguments show up in the process list and the shell history.
15. **The laptop's VPN is off during the demo; upstream stays `9.9.9.9`.** A VPN client on the laptop can break connection sharing and DNS. The script warns if it is on.

**The split**

16. **Hotspot and sensor on the laptop itself; backend in a VM on the same laptop.** The Wi-Fi card cannot be given to the VM, so the hotspot and the sensor must be on the host. Everything else was built and tested in the VM, and the host should stay free of a second development environment: it gets plain Python and one package. *Rejected:* everything on the host (a full Python set-up there), everything in the VM (no Wi-Fi card).
17. **The sensor is one file with one dependency, and never waits for the backend.** It is the piece phones depend on: it must be easy to install and must keep answering whatever happens behind it. It queues events and delivers them later.
18. **The backend re-times events onto its own clock.** Two machines, two clocks; "lookups since the session started" compares them.

**Data and privacy**

19. **Everything in memory by default; the database is optional.** A reliable demo must not depend on a remote database. *Rejected:* storing every lookup (privacy).
20. **Only our own marked phones are stored, only during a session, and the mark is never restored from the database.** Hotspot addresses get reused; a guest's phone must never inherit a lab phone's mark.
21. **Device names are hidden by default.** A phone announces a name to DHCP that usually contains its owner's first name; on a big screen that is personal information. The sensor does not even read it unless started with `--names`, meant for our own phones.
22. **Wipe forgets the screen; stored history has its own, separate delete.** Wipe is pressed between judges; history of our own lab phones is a feature and must survive it.
22a. **The box's own test lookup is not a phone.** The start checklist sends one lookup through the sensor from the laptop itself. On screen it used to become "Device 1". Lookups from a loopback address are now named "box self-test" and take no number. *Rejected:* dropping them, because the same path is how the sensor is tried out on a development machine.

**Turning names into companies**

23. **A public tracker list plus a short override file; overrides win.** Disconnect's list is open, maintained and credible, but built for websites: phone-only SDK hosts and all of Apple's own servers were missing, so they are in the overrides. *Rejected:* writing our own list from scratch.
23a. **Company names are tidied by rule when the list is built, never by hand per entry.** Disconnect writes some names in lowercase ("reddit"). One rule in `build_kb.py` fixes all of them the same way, so a rebuild cannot undo a hand edit.
23b. **A company on screen is the name people know, not always the legal owner.** The list files LinkedIn's servers under Microsoft, which owns it. On screen that became "Microsoft: social network". The overrides file them under "LinkedIn". The same thinking as decision 24. Blocking follows the name on screen: blocking Microsoft no longer blocks LinkedIn.
23c. **The own servers of the app being shown are `vendor`, also when the list calls them `content`.** The list is written from a website's point of view, where `reddit.com` embedded in another site is third-party content. In our demo the Reddit app is the app in the judge's hand, and its own servers showing as a "CDN" misleads. This is a per-app hand entry, not a rule: only apps we have seen live get one.
24. **"Amazon Web Services" is a separate company from "Amazon".** CloudFront and `amazonaws.com` host half the internet; blocking Amazon's advertising business must not take them down, and calling hosted content "Amazon" would be inaccurate.
25. **Apple's own servers are `vendor`, except its advertising hosts.** A phone talks to its maker constantly; that is not an app tracking you.
26. **The same phone and name within 2 seconds is one lookup.** iPhones ask three record types at once.
27. **AI is optional, in the background, and shown as a guess.** Unknown names appear at once as `unknown` and are upgraded if the model answers. The live loop never waits for a model. Answers are cached.

**The screen**

28. **A session ties lookups to an app.** We see devices, not apps. Attribution is "what this phone looked up while the judge used this app"; background traffic can mix in, and we say so.
29. **The label check is rule-based first.** It works with no AI and no database. The AI's sentence, when available, is shown on top while the rule-based sentence stays as the facts line.
30. **Wording: "contacted", never "sent your data".** We see which servers were looked up, not what went to them.
31. **Replay mode exists from day one.** `fake_sensor.py` is the development loop for the teammates and the demo's safety net.
32. **A plain presenter page (`/present`) as insurance.** Only for the case that the show screen fails. It is one file inside the backend and shares no code with the show screen, so one bug cannot take out both.
32a. **The show screen is a plain page, not a React app.** Three files the backend serves as they are. Reasons: there is no build step to forget before the demo and no build output that can be stale; nothing is fetched from the internet at run time (the venue's network is not ours); no Node toolchain is needed on any machine that runs the demo; and with three hours to feature lock, one person can read all of it. *Rejected:* React + Vite as first planned (a toolchain and a build for a single screen), and a graph library for the bubbles (the layout is forty lines).
32b. **Bubbles are HTML buttons, not drawings on a canvas.** Each bubble is a real button moved by a CSS transform: clicks, keyboard focus and readable text come for free, and the browser animates them cheaply. Only the thin lines to the phone are SVG. *Rejected:* a canvas (we would have to rebuild hit-testing and text fitting).
32c. **A click on a company opens its detail panel; blocking is a button in it.** Until Saturday 18:15 one click on a bubble blocked the company at once, with an Undo bar. That was fast, but nobody watching could tell what had been blocked or why that company deserved it, and a stray click blocked something. Now the click answers "who is this?" first, and the block is one more click, with the result spelled out ("BLOCKED", the names struck through, "refused ×N" counting). There is still no confirm dialog and nothing needs undoing by a special control: the same button unblocks. The wipe, which cannot be undone, needs two key presses. *Rejected:* keeping one-click blocking and putting the details somewhere else (two gestures to learn, and the dangerous one would be the easy one).
32d. **The operator's controls are on the same screen but out of the way.** Keys and one small panel, so the person at the laptop never has to switch windows in front of a judge. Rename and `persist` stay on `/debug`. Blocking a single server name used to be there only; it is now in the detail panel as well.
32e. **The explanation comes from the list first and from the AI second, and says which.** The panel must never wait for a model: the sentence from the knowledge base is there the moment the panel opens, built by the page itself, and the AI's text replaces it only if and when it arrives. A badge names the source, because a model's account of "what this company is probably doing here" is an informed guess from server names and must not look like a fact from our list. The AI text is written once per company and session and then kept. *Rejected:* waiting for the AI before showing anything (a dead panel for seconds, or for ever without the tunnel); pushing the AI text over the WebSocket (a new message type for something only an open panel needs; asking again every 1.2 s while "pending" is the pattern the label check already uses); refreshing the text whenever a new server name arrives (the text would change under the reader's eyes, and every lookup would cost a model call).
32f. **The logo is a drawing in the page, and the tab icon is made from it.** Nothing to load, nothing that can be missing offline, and one drawing to change when the team picks a variant. It costs one exception in the show screen's content security policy: images may also come from `data:` addresses. An image cannot run script, so this does not weaken what the policy is for. *Rejected:* an image file for the icon (a second copy of the logo to keep in step).

**Security**

33. **No login for the demo.** Protection is network position (phones cannot reach the backend) plus refusing cross-site requests. A token would be a small change in the backend and in the three pages; decided against for now (section 11).
33a. **The model server has no key and no public port.** Ollama listens only on the AMD server's own loopback address, so the only way in is an SSH tunnel from the backend's machine, which needs the SSH key. That replaces an API key. *Rejected:* opening Ollama's port on the network (it has no authentication of its own).
34. **Everything from the network is shown as text, and our pages run only their own script.** See section 11.

---

## 9. What the hardware tests showed, and what is still unverified

**Observed on the real laptop and a real iPhone** (early Saturday, done by hand, before the scripts existed):

- A NetworkManager hotspot works on the laptop's Wi-Fi card.
- The card can be a normal Wi-Fi client and an access point at the same time (the driver reports: up to 2 client interfaces, 1 access point, 2 in total, on up to 2 channels). The working set-up: a second virtual interface created with `iw dev <wifi> interface add tattle0 type __ap`, normal Wi-Fi on one interface, hotspot on the other.
- NetworkManager swapped which interface got which job: the normal Wi-Fi ended up on `tattle0` and the hotspot ran on the card's real interface. That swapped layout worked: phone online, lookups visible.
- The iPhone could not join at first (stuck on "joining"): the laptop's firewall (it runs NixOS) dropped DHCP from hotspot phones. Allowing input on the hotspot interface fixed it. `iptables` works on that laptop.
- Phones get `10.42.0.x`; the laptop is `10.42.0.1`.
- At first no DNS was visible at all: the iPhone was quietly using its cellular connection instead of our Wi-Fi. Turning cellular data off forced it through us.
- The laptop lost its own internet when the same phone was both its uplink and the test phone. Running client and access point on one card solved that.
- The iPhone sent DNS to a leftover server (a VPN's DNS address) instead of ours. Hence the redirect for any destination.
- With that, the iPhone was online through the laptop and its DNS lookups were visible with `tcpdump`.
- The laptop has `tcpdump`, `iw` and Node.js. It has plain Python but no Python packages; the sensor gets its own venv with `dnslib`.

**The first run of the hotspot script on the real card** (Saturday, about 13:00):

- `box-up.sh` got as far as starting the hotspot and failed there. NetworkManager's message: "Connection 'tattle-hotspot' is not available on device tattle0 because device is strictly unmanaged". ("Unmanaged" means NetworkManager has decided to leave an interface alone.)
- The script's cleanup then ran (`box-down.sh`) and worked: this is the one part of the two scripts proven on hardware.
- Inferred, not observed directly: the hotspot start comes after the firewall section in the script, and the script stops at the first failing command, so its firewall rules must have been added without error and were then removed by the cleanup. They have not carried any traffic.
- Found by hand afterwards: the script created `tattle0` without an address of its own, so it inherited the Wi-Fi card's MAC address, and it only waited half a second. Creating it with `addr 02:00:00:00:00:01` and waiting 3 seconds, NetworkManager listed `tattle0` as "disconnected", which means managed and ready.
- The script now does both (section 6.2).

**The second run** (Saturday, about 13:30):

- The MAC address and the wait worked: NetworkManager managed `tattle0`.
- Then NetworkManager moved the laptop's normal Wi-Fi onto `tattle0`, as in the hand test. The script's next step tried to force it back onto the real interface and failed: "Connection … is not available on device … because device is not available". The real interface was not usable at that moment.
- The cleanup worked again.
- Consequence: the script no longer forces a layout (section 6.2, step 4; decision 9a in section 8). **This version has not been run on the card yet.**

**The third run: passed** (Saturday, about 14:00):

- With the current `box-up.sh` and the real sensor on the laptop, a real iPhone joined `Tattle-Demo` and showed up live on `/debug`.
- What that proves: the script completes on the real card; an iPhone can join with the narrow input rules and gets working internet; its lookups reach the sensor through the redirect and are answered; the sensor on the laptop reaches the backend in the VM while the hotspot is up; the screen updates live.
- **Blocking looked broken.** `discord.com` was blocked; a Discord message still went through and the counter showed 0 blocked. The likely cause, not yet confirmed by a re-test: the phone already had the answer and reused it, Discord keeps a long-lived connection open, and it uses other names as well (`discord.gg`). DNS blocking only acts on new lookups. Since then: the sensor caps answer lifetimes at 10 seconds, `/debug` says what a block covers, Discord's names are in the knowledge base as one company, and the demo is "block the company, then close and reopen the app".
- **"Device 1" was the laptop itself:** its own test lookup through the sensor. Now shown as "box self-test".
- **Names the knowledge base did not know:** Netflix's (`fast.com`, `nflxvideo.net`), Discord's and OpenAI's. Added to the overrides as `vendor`.

**Blocking confirmed on the phone** (Saturday, about 16:10), with the new sensor:

- The company AppsFlyer was blocked, Reddit was force-quit and reopened about 15 seconds later. New `appsflyersdk.com` lookups arrived as blocked (the counter went to 4) and Reddit kept working.
- The 10-second lifetime cap is what made the block take hold that fast, without airplane mode.
- The laptop's own test lookup shows as "box self-test" and is not counted: with one phone joined the page shows 1 device.
- Reddit's traffic showed more names the knowledge base lacked (Google's app analytics and app advertising hosts, Reddit's media hosts) and a company shown in lowercase as "reddit". All fixed (section 6.6).

**Seen on the live screen with a real phone** (Saturday, about 18:00, with the show screen on the real traffic of our own phone):

- Microsoft appeared as a `social` company. Its lookups were almost all LinkedIn hosts (`linkedin.com`, `licdn.com`), which the list files under Microsoft as `social`. Fixed in the overrides (section 6.6, decision 23b).
- `login.microsoftonline.com`, `aadcdn.msauth.net` and `aadcdn.msftauth.net` (Microsoft's sign-in service) were unknown. Added.
- Reddit's own servers showed as "CDN" (`content`). Filed as the app's own (decision 23c).
- About a quarter of that capture (54 of 213 lookups) was names no list knew: "Not identified", as long as there is no AI module. They are left for the AI classifier and deliberately not written down here: which apps a phone has is exactly the kind of thing we keep in memory only.
- **Not re-checked on the live screen yet:** the three fixes above were verified by looking the names up in the knowledge base, not by a new capture.

**Still unverified on hardware** (as of the timestamp at the top):


- `box-down.sh` taking down a hotspot that actually ran, and NetworkManager then reconnecting the Wi-Fi on the real interface. Which of the two layouts the passing run ended up in was not recorded. Also: that the narrow input rules let an iPhone join; that our chains sit ahead of the laptop's own firewall rules; that the hotspot hands out IPv4 only (our rules are IPv4 only).
- The sensor behind the real redirect: real phone addresses, a real iPhone, blocking actually stopping an app (de-risk test 2 below).
- The sensor forwarding to `9.9.9.9` from the laptop. In the development VM, public resolvers were not reachable on port 53 and the VM's own resolver timed out on advertising names; whether the laptop itself is affected with its VPN off is unknown. The checklist tests it.
- The laptop reaching the backend in the VM while the hotspot is up.
- The application firewall on the laptop letting the sensor out (it needs two allow rules: DNS to `9.9.9.9`, and HTTP to the VM on port 8000).
- Device names from a real lease file (`--names`).
- The organizers' Postgres.
- Timing of the start-up on the real laptop.

**The de-risk tests the team defined, and where they stand:**

| # | Test | Status |
| --- | --- | --- |
| 1 | Hotspot up, an iPhone joins, has internet, its DNS is visible on the laptop | Passed by hand, and again with the scripts and the sensor |
| 2 | Redirected lookups reach the sensor; blocking a domain stops it working on the iPhone | **Passed**: blocked AppsFlyer, reopened Reddit, AppsFlyer's lookups were refused and Reddit kept working |
| 3 | The model server on the AMD server answers from the backend's machine (through the SSH tunnel) | In progress (AI is setting up Ollama); not verified |
| 4 | The provided Postgres is reachable from a laptop | Unknown to this document (AI's task) |
| 5 | Find two or three free iPhone apps that light up fast; pick the demo app | **Not done yet** |

Fallbacks if test 1 or 2 had failed or fails later: a USB Wi-Fi adapter that supports access-point mode; setting the test iPhone's DNS server by hand; capture only without blocking; replay mode.

---

## 10. Privacy and consent

The rules the product follows, and how the code enforces them:

- **Names only, never content.** We read DNS lookups. We do not decrypt, inspect or store traffic.
- **Whose phones.** Our own test phones, plus judges who explicitly choose to join. Never pressure anyone; never touch their phone ourselves. The spoken consent line: "It's our phone on our own password-protected demo network. We only see the names of the servers it looks up, never what's sent. And it's all wiped the moment you walk away."
- **An honest, protected network.** WPA2 password, the name `Tattle-Demo`. Never open, never official-looking.
- **Memory by default.** Captured lookups live in the backend's memory and are gone on Wipe or restart. Nothing is written to disk except: database rows for our own marked lab phones, and replay files we deliberately record from our own phones.
- **Wipe between people.** One button clears devices, lookups, blocks, the session and the summary.
- **No names on screen.** Phones show as "Device 1", "Device 2". Their own names are not read unless we start the sensor with `--names` for our own phones.
- **The sensor does not log.** It prints or writes names only with `--debug` or `--record`. A recording replaces device names with "Test iPhone A", and replays in the repository come only from our own phones.
- **The database only ever holds lab phones** (section 6.4), and `POST /api/history/clear` deletes it all.
- **A banner, always visible on every screen:** "Reads server names only, never content. Nothing is kept after you leave."
- **Careful words.** "Contacted", never "sent your data": we know a server was looked up, not what was said to it.
- **Private Relay.** We use Apple's documented network opt-out and the iPhone informs its user. We say this in the pitch.
- **Raw packet captures are never committed.**

---

## 11. Security model and known gaps

The team presents as a security team, so judges may probe.

**What is untrusted:** everything a phone sends. A phone picks the names it looks up, and DNS allows any bytes in a name; it also picks its own DHCP name. Text written by a language model (company names, sentences) is untrusted too. Text typed by us on the screen (device names, app names) is trusted but still handled as plain text.

**What is done about it** (all implemented and tested):

| Risk | Defence |
| --- | --- |
| A phone looks up `<img src=x onerror=…>.example.com` and the name is drawn on the screen as markup (XSS) | The sensor resolves and reports plain host names only (letters, digits, `-`, `_`, dots; 253 characters). The backend applies the same rule again. Rejects are counted (`health.malformed`), never stored or shown |
| A name we cannot show is still resolved: a way to look things up unseen | Such names get REFUSED and are not forwarded |
| Markup slips through anyway | All three pages insert everything as text; a test fails if any of them uses an HTML-building call or `setAttribute`. `/debug` and `/present` are served with a content security policy that runs only the page's own script, identified by a fresh nonce per response. The show screen's files are served with a policy that allows only files from the backend itself: no inline script or style, nothing from the internet (a test also fails if an outside address appears in those files). Its one exception is that images may be `data:` addresses, which the page needs to make its tab icon from its logo; an image cannot run script. Checked in a headless browser with a phone name and an app name made of markup: shown as text |
| Any website open in the demo browser wipes the screen or listens to the live stream through that browser (cross-site POST, cross-site WebSocket) | Every `POST` and WebSocket connection is refused when its `Origin` is another site. Pages from the backend itself, or from a development server on `localhost`, are accepted |
| Huge requests or endless new names exhaust memory | 1 MB per request, 2,000 events per batch, length limits on every text field, caps on devices (256), blocks (500), clients (50), remembered AI answers (5,000), company explanations (500), stored lookups (5,000) |
| Junk identifiers | Device ids must be IP addresses; blocked domains must be host names; free text is cut to printable characters and a maximum length |
| SQL injection | All database commands pass values as parameters. One test scans every statement; another stores `Robert'); DROP TABLE hits; --` as an app name and reads it back |
| Guest phones reaching the backend | The hotspot firewall rejects traffic from phones to the VM network (**unverified on hardware**) |
| The hotspot password leaking | Asked at a prompt; stored only in the hotspot profile, which `box-down.sh` deletes |
| The model server has no API key | It listens only on its own machine's loopback address; the backend reaches it through an SSH tunnel, which needs our SSH key |

**Known gaps, and why they are acceptable for a demo:**

- **No login on the API.** Anyone who can reach port 8000 can read the state, block, and wipe. Who can reach it: the laptop itself and other virtual machines on it. Phones on the hotspot are firewalled away, and other websites are refused. For a six-minute supervised demo on our own laptop this is enough; a real product would need authentication. Decided explicitly: no login for now.
- **No rate limit per phone in the sensor.** A phone flooding lookups could slow the laptop. Only invited phones join, for minutes.
- **DNS rebinding is not handled.** A malicious website could, in theory, make the demo browser treat the backend as "its own site". It would need the presenter to browse to such a site on the demo laptop during the demo.
- **Two reading requests make the backend ask the model.** `GET /api/explain` and `GET /api/label-check` start a model call in the background. Reading is not refused across sites (only changing is), so a web page open in the demo browser could trigger such calls. They are bounded (one per company and session; one label verdict per 10 s), they cost the model server time and nothing else, and the page that triggered them cannot read the answers.
- **Two firewall rules have not been challenged.** The redirect and the input rules worked in the hardware test. The two reject rules (port 853, and phones reaching the VM's network) are in place, but nobody has tried to get past them.

These are written down openly in the challenges log as well; saying them unprompted is part of the pitch.

---

## 12. Limitations: what hides from us

What Tattle cannot see, why, and the sentence for a judge.

| Hidden | Why | What we say |
| --- | --- | --- |
| Encrypted DNS (DoH, DoT) | The lookup is encrypted inside other traffic | "We refuse the well-known encrypted-DNS servers and the phone's request to upgrade, so it falls back to normal DNS. An app that ships its own encrypted DNS to an unknown server would get past us." |
| iCloud Private Relay | Apple relays the traffic so the network sees nothing | "We use Apple's documented way for a network to opt out, and the iPhone tells you." |
| ECH | Hides the site name inside the connection | "That is why we don't rely on SNI at all." |
| Names looked up before joining | The phone remembers answers for a while | "Open the app fresh; most names have short lifetimes." |
| Connections straight to an IP address | No lookup happens | "Rare for the trackers we care about; we'd miss it." |
| What is actually sent | We never look at content | "We see who was contacted, not what was said. That is a promise, not only a limit." |
| Which app made a lookup | DNS shows the device, not the app | "We attribute by session: what the phone did while you used this one app. The phone's own background chatter can mix in; we label the phone maker's servers as 'vendor'." |
| Unknown companies | No list knows every name | "Unknown names go to an open model, and we label its answer as a guess." |
| Connections already open, and answers the phone already has | DNS blocking acts only when the phone asks for a name | "A block stops new connections. We make the phone ask again within ten seconds, and reopening the app drops what it had open. We don't cut connections: we never touch the traffic itself." |

Other limits of the current build:
- Session numbers (summary, label check) are computed from the last 5,000 lookups kept in memory. A very long, very busy session would undercount there; the database history does not have this limit.
- A device is identified by its hotspot address. If a phone leaves and another gets the same address later, they look like one device until a Wipe.
- The only replay is simulated traffic until we record our own phone.

---

## 13. How to run, test and demo it, and the fallbacks

All commands from the repository root. Python 3.11 or newer.

**Development (no hotspot):**

```sh
python3 -m venv backend/.venv                                   # once: a private Python environment
backend/.venv/bin/pip install -r backend/requirements-dev.txt   # once
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --no-access-log    # the backend
python3 tools/fake_sensor.py data/replays/demo-synthetic.jsonl --loop                    # second terminal: a simulated phone
```

Then open `http://127.0.0.1:8000/` (the show screen: press `S`, type an app name, Enter; click a bubble for its detail panel), `/logo` (the three logo variants), `/debug` (the operator console: controls and a live table) or `/present` (the plain fallback view). `--speed 4` makes the replay four times faster. The show screen needs no build: the backend reads `frontend/` at each request.

**Tests:**

```sh
python3 -m venv sensor/.venv && sensor/.venv/bin/pip install -r sensor/requirements-dev.txt   # once
sensor/.venv/bin/python -m pytest sensor/tests       # 35 tests, about 50 s
backend/.venv/bin/python -m pytest backend/tests     # 102 tests; 14 database tests are skipped
backend/.venv/bin/python tools/selfcheck.py          # end to end on loopback, 21 checks

# with a throwaway Postgres for the database tests:
podman run -d --rm --name tattle-pg-test -e POSTGRES_PASSWORD=tattle-test -p 127.0.0.1:55432:5432 docker.io/library/postgres:17-alpine
TEST_DATABASE_URL=postgresql://postgres:tattle-test@127.0.0.1:55432/postgres backend/.venv/bin/python -m pytest backend/tests   # 116 tests
podman stop tattle-pg-test
```

**The demo, in order** (the full version is `docs/RUNBOOK.md`; the host details are `box/README.md`):

Done once beforehand: the backend venv in the VM; copies of `sensor/` and `box/` on the laptop with `sensor/.venv` (`pip install -r sensor/requirements.txt`); lasting allow rules for the sensor in the laptop's application firewall; the test iPhone has joined `Tattle-Demo` once.

| # | Where | Command | Expect |
| --- | --- | --- | --- |
| 1 | Laptop | start the VM; plug in the uplink | |
| 2 | Laptop | `mullvad disconnect` | VPN off |
| 3 | Laptop | `sudo bash box/box-up.sh <wifi-interface>` (asks for the hotspot password; up to half a minute) | `HOTSPOT: … runs on <interface>` and `INTERNET: … is on <interface>` |
| 4 | Laptop | `sensor/.venv/bin/python sensor/tattle_sensor.py --backend http://<vm-ip>:8000` | `backend: connected` |
| 5 | VM | `bash backend/start.sh` | the addresses to open |
| 5a | VM, only if the AI is used | `ssh -N -L 8081:127.0.0.1:11434 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes amd` | no output; `health.ai_endpoint` turns true within 15 s |
| 6 | Laptop browser | `http://<vm-ip>:8000/`, then `F` for full screen | the show screen; "live" and "sensor: live" green, top right |
| 7 | iPhone | joins `Tattle-Demo` | "Device 1" appears under the phone in the middle |
| 8 | Show screen | `W` twice (wipe) | empty screen, ready |
| 9 | Show screen, when the judge has the phone | `S`, the app's name, Enter | the app's name under the phone; seconds counting |

Between steps 3 and 4 phones on the hotspot have no DNS. The laptop's own test lookup shows on the page as "box self-test". Afterwards: stop the sensor, then `sudo bash box/box-down.sh`.

**After a change to the code or the data, what has to be restarted:** the backend, for anything under `backend/app/` and for `data/kb.json` or `data/kb_overrides.json` (the knowledge base is read once at start). Restarting it empties the screen; the sensor reconnects by itself. Nothing for files under `frontend/` (read at each request: reload the page) or `data/labels/` (read at each call). The sensor only when `sensor/` changed.

**Recording a replay from our own phone** (the full steps are in `box/README.md`): on the laptop, restart the sensor with `--record <app-slug>.raw.jsonl` added; use the app for two minutes; stop. The file is written in the folder the sensor was started from. Device names are already replaced in it ("Test iPhone A"); host names are not, so it holds everything the phone looked up, including its background apps. It is copied into the VM as `data/replays/<app-slug>.raw.jsonl` (a name git ignores), looked through, and saved without the lines that do not belong as `data/replays/<app-slug>.jsonl`. No real recording exists yet.

**The talk** (about 3:30): hook ("Your phone talks to dozens of companies you've never heard of. Want to see who?"); the consent line; hand over the iPhone and start a session named after the app; narrate as the screen fills, read the summary aloud; click a company to open its panel (who it is, which servers the app asked for), block it there, have the app closed and reopened (a block stops new connections, not open ones), and watch "refused" and the blocked counter climb while the app keeps working; the label check, if labels exist; how it works, with the diagram; honest limits and the AI tools we used; close ("Anyone can hand a phone to Tattle and get the truth in a minute, with nothing to install").

**Fallbacks:**

| What fails | Do |
| --- | --- |
| Hotspot or sensor, or no lookups 20 s after the phone joined | **Replay mode:** wipe (`W` twice); in the VM run `python3 tools/fake_sensor.py data/replays/demo-synthetic.jsonl --loop`; say "we're switching to a simulated session". Blocking still works |
| The laptop cannot open the page on the VM | Use the browser inside the VM: `http://127.0.0.1:8000/` |
| The show screen is broken | `/present` on the big screen, `/debug` in a second tab for Start, Block, Wipe |
| The backend stopped | `bash backend/start.sh` again; the screen starts empty; the sensor reconnects and delivers what it queued |
| The sensor stopped | Start it again; phones recover by themselves |
| AI or database down | Nothing to do: the template summary and in-memory mode take over |
| Everything | Play the backup video (not recorded yet) and talk over the diagram |

---

## 14. Prior art and how we differ

Judges will ask "isn't this just X?"

| Existing thing | What it is | How Tattle differs |
| --- | --- | --- |
| **Pi-hole** | A network-wide ad blocker for a home, with a dashboard of lookups | Ours is a portable "hand it over and see" experience: names turned into companies and plain English, live, per device |
| **IoT Inspector** (a university research tool) | Shows who smart-home devices talk to; a desktop app that intercepts the home network by ARP spoofing | Ours needs no install and no interception trick: you join our network knowingly. It is aimed at a person holding a phone |
| **Firewalla** | A commercial router box with per-device flows and blocking, for people managing a home network | Ours is a one-minute X-ray for anyone, not an admin tool |
| **iPhone App Privacy Report** | Built into iOS: raw domain lists per app, last 7 days, buried in Settings | We turn names into companies and categories, live, and check them against the app's own privacy label |
| **OpenSnitch / Little Snitch** | Per-application firewalls | They only see the computer they are installed on |

The line: the capture technique is old and we say so; what is new is making it instant, understandable, and checkable against what the app promised.

---

## 15. Team working rules

These apply to everyone on the team.

- **Interfaces change in `docs/TEAM.md` first.** That file is the contract between the three parts. Change it there, then tell the team. Additions made by one role are marked "Added by <role>" there.
- **Each role edits only its own folders** (section 2). Shared files: `docs/TEAM.md`, `docs/PITCH.md`, `docs/CHALLENGES.md`, `.gitignore`, `README.md`.
- **No personal information in any file:** no names, usernames, emails, school, location, or file paths containing a home folder. Use placeholders such as `<your-name>`, `<vm-ip>`, `<wifi-interface>`. Roles, not names.
- **Secrets only in `.env`,** which is never committed. `.env.example` lists the settings with placeholders.
- **Python always in an isolated environment** (a venv). Never install packages into a system Python.
- **Keep `.gitignore` current:** anything a tool generates (environments, caches, build output, raw recordings) is added before it can be committed.
- **Never commit raw packet captures.** Replays come from our own phones only, with device names replaced.
- **Log challenges as they happen** in `docs/CHALLENGES.md`: one line with the time, the role, the problem, how it was solved or not, and the AI tool used. Judges score honesty here.
- **Credit the tracker list** (Disconnect, CC BY-NC-SA 4.0) in the README; `data/kb.json` carries the same license.
- **Wording:** "contacted", never "sent your data". The privacy banner is always on screen.
- **This guide is kept in step with the code** at the end of every piece of work.
- **This guide is internal.** It stays in the team repository while we work, and it must never reach a public one. Before the repository goes public: make a fresh public repository from a clean copy of the project with a new history (deleting a file later leaves it in the old history), leave this file out of that copy and list it in that repository's `.gitignore`, and re-check every file for personal information and secrets (`.env` files, tokens, IP addresses, MAC addresses). The same checklist is in `docs/PITCH.md` under "Submission".

---

## 16. Current status and next tasks

As of the timestamp at the top. "Tested" means tested in the development VM, on loopback, unless it says otherwise.

### Works and is tested

| Part | State |
| --- | --- |
| Sensor | Complete. 35 tests. Real DNS forwarding, guard list, blocklist, refusal of odd names, the 10-second lifetime cap, batching, surviving a backend outage. **Ran on the real laptop in the hardware test** |
| Backend core | Complete. 116 tests with Postgres, 102 without. Events, classification, devices, blocking with coverage, sessions, summary, wipe, health, WebSocket, limits, cross-site refusal. **Received a real phone's lookups in the hardware test** |
| Knowledge base | First version: 4,430 domains from Disconnect plus 65 overrides. Checked against the simulated replay; the live tests showed gaps and one mislabel (apps' own servers, Google's app hosts, Reddit's hosts, Microsoft's sign-in hosts, LinkedIn shown as "Microsoft, social"), which were fixed by hand. The latest fixes (Saturday 18:30) are checked by lookup only, not yet seen on the live screen |
| Label fact-check | Endpoint complete, tested with stand-in label files. No real labels exist yet |
| Database layer and history endpoints | Complete, tested against Postgres 17 in a container. Not yet connected to the organizers' Postgres |
| AI hooks | The backend's side is complete and tested with a stand-in module (classification, summary, label verdict, company explanation, failures, time-outs), and `health.ai_endpoint` is tested against a stand-in server. No real `ai.py`; the tunnel to the real model server has not been tried from this backend |
| Show screen (`frontend/`, served at `/`) | Working against replayed traffic: bubbles, counters, the detail panel (explanation from the list and from a stand-in AI, every server name, blocking a company or a single name), summary, label card, live list, How it works, operator keys, the turtle logo and tab icon. Checked in a headless browser at 1920x1080 and 1440x900, with up to 72 companies and with hostile names (section 6.7). The first version was seen with a real phone at about 18:00; **the detail panel and the logo have not been seen on the real laptop or with a real phone** |
| Logo | Variant A (the radar turtle) is in the header and the tab icon, chosen by the team. Checked in a headless browser at header size; **not yet seen in a real browser tab**. The preview of all three stays at `/logo` |
| `/debug` and `/present` | Working. Checked in a scripted browser, including hostile input; `/present` also in one real browser screenshot |
| Fake sensor and simulated replay | Working |
| End-to-end self-check | 21 checks. Passed in four of five runs on Saturday 17:40; one run failed two checks that were not recorded. On Saturday 18:35, one of two runs failed one check ("example.com forwarded over UDP" got SERVFAIL, the resolver's "I could not find out") and the other passed. Failures of this kind come from the development VM's own DNS resolver timing out, not from our code, as far as we can tell |
| Soak test | 10.5 minutes at about 25 lookups a second with two backend restarts: backend memory flat at about 79 MB once the 5,000-lookup buffer was full, sensor at 26 MB, the sensor kept answering and delivered everything it had queued, clients reconnected within 7 s. Two lookups in about 400 failed; traced to the development VM's upstream resolver taking over 3 s |
| Start script, runbook, quickstarts | Written; the VM-side steps were run |

### Hotspot scripts: passed on hardware

`box/box-up.sh` passed on the third real run: an iPhone on the hotspot showed up live on the screen (section 9). Blocking is confirmed on a real phone: a blocked company's lookups were refused after the app was reopened, and the app kept working. `box/box-down.sh` has worked twice as the cleanup after a failed start; taking down a hotspot that really ran is not confirmed. The remaining unverified items are listed in section 9.

### Not built

| What | Owner |
| --- | --- |
| A history view on the show screen (the endpoints exist, no screen uses them) | BOX; only if time allows before feature lock |
| `backend/app/ai.py` and the model server, including the new optional `explain_company` for the detail panel; notes and numbers for the GPU track | AI |
| Privacy labels for the demo apps (`data/labels/`) | BOX (moved from AI); waiting for the apps' App Store label texts |
| `data/ai_cache_seed.json` | AI (optional) |
| A recording of a real session from our own phone (`sensor --record`) | BOX, after the hardware test |
| The backup video, the submission text | Everyone |
| The accuracy check against the iPhone's App Privacy Report; the small GPU-trained classifier | Stretch, not started |

### Known bugs

None open at the time of writing. Known limits are in sections 11 and 12.

### Open questions and pending decisions

1. How the `sensor/` and `box/` folders get onto the laptop (a plain copy is assumed; the transport is undecided).
2. Which uplink at the demo: a USB-tethered phone (the plan) or the venue Wi-Fi through the same card (what the hand test used).
3. Whether our user on the organizers' Postgres may create tables. If not, someone runs `backend/sql/schema.sql` there once.
4. Which two or three apps are the demo apps (they need labels, and ideally seeded AI answers).
5. The format of `data/ai_cache_seed.json` is BOX's proposal; AI may change it.
6. Knowledge-base choices for AI to review (listed at the top of `tools/build_kb.py`): which category wins when a domain is in several, what to do with anti-fraud and email-tracker entries, display names of companies.
7. The exact submission deadline.
8. (Settled Saturday 19:00: logo variant A.)
9. The knowledge-base edits BOX made on Saturday 18:30 are in the AI owner's file: to be confirmed or changed by the AI owner. One open point among them: `redditstatic.com` is still `advertising`, as the list has it, while Reddit's other servers are now `vendor`.

### Next tasks, by role, in priority order

**BOX**
0. Restart the backend so the new endpoint and the knowledge-base fixes are live; then look at the show screen and the detail panel on the real laptop with the real phone, from two metres; fix what does not read. Decide what to do about the architecture image (small text, drawn before the screen existed).
1. Write the label files for the demo apps (`data/labels/<app-slug>.json`) as their App Store label texts arrive.
2. Pick the demo apps with AI (de-risk test 5).
3. Record a real session from our own phone with `--record`, so replay mode is real traffic.
4. Connect the organizers' Postgres (`DATABASE_URL` in `.env`), check `health.db`.
5. Integrate AI's `ai.py` when it lands; re-run all tests.
6. Time the runbook on the real laptop; fresh-boot test on Sunday morning.

**FRONT:** merged into BOX. Its list is done except the history view and showing the `malformed` count (both optional).

**AI** (start with `docs/AI-QUICKSTART.md`)
1. Ollama running on the AMD server and reachable through the SSH tunnel (`health.ai_endpoint` true); `ai.py` with `classify_domains` and `summarize`; check it with `tools/try_ai.py`.
2. `explain_company(company, category, domains)` in `ai.py` (section 7.7): it is what turns the detail panel from one list sentence into the AI showpiece. `tools/try_ai.py` exercises it.
3. Review the knowledge base and overrides (the notes at the top of `tools/build_kb.py`), including BOX's edits of Saturday 18:30 (section 6.6).
3a. Optional: `label_check`; the seed file for the demo apps.
4. Review the show screen's look (the colours and type are variables at the top of `frontend/app.css`); the pitch diagram, which the show screen displays under "How it works"; notes and numbers for the GPU track.

**Everyone:** keep the challenges log going; record the backup video after feature lock; write the submission text; rehearse with a timer.

---

## 17. Challenges we hit and AI tools used

From `docs/CHALLENGES.md`. The AI tool used throughout BOX's work is Claude (Claude Code).

| When (Sat) | Problem | What happened |
| --- | --- | --- |
| 02:40 | iPhone could not join the hotspot | The laptop's firewall blocked DHCP; input on the hotspot interface was allowed |
| 02:50 | No DNS visible at first | The iPhone silently used cellular; turning cellular data off forced it through us |
| 02:55 | The laptop lost internet during the test | The same phone was uplink and test phone; fixed by running hotspot and normal Wi-Fi on one card |
| 03:00 | iPhone sent DNS to its VPN's DNS server | Redirect all port-53 traffic to our resolver |
| 03:35 | (milestone) | iPhone online through the box, every lookup visible |
| 04:50 | In the development VM, public resolvers were unreachable and tracker names timed out | The sensor behaved correctly; the self-check uses the machine's own resolver and neutral names. Open: is the laptop affected? |
| 05:00 | Backend tests failed two runs in three while closing a WebSocket | Two helper tasks per connection raced with cancellation; replaced by one send loop |
| 05:30 | Backend in a VM, sensor on the laptop: two clocks | The backend moves each batch of events onto its own clock |
| 06:00 | The tracker list is built for websites; phone SDK hosts and Apple's servers were missing | A hand-written override file; unknowns go to the model |
| 06:10 | Lookups we refuse on purpose inflated "blocked trackers" and counted as contacts to Apple | Counted on their own as hidden-traffic attempts |
| 10:20 | A looked-up name can contain markup or terminal escape codes | Plain host names only; the rest refused and counted |
| 10:20 | A name we cannot show was still resolved | REFUSED instead of forwarding |
| 10:25 | Our pages would run markup if it slipped through | Text-only insertion, enforced by a test; a strict content security policy |
| 10:25 | No login: another website could wipe or listen through the demo browser | Cross-site POSTs and WebSockets refused |
| 10:30 | No limits on request size or list lengths | Limits and caps everywhere |
| 10:30 | Identifiers and free text stored as sent | Validated and trimmed |
| 10:30 | SQL injection check | Parameters only, verified by tests |
| 10:35 | Not fixed: no login, no per-phone rate limit, no DNS-rebinding defence | Known limits, said openly |
| 10:55 | Would it survive ten minutes of load and a crash? | Soak test passed (section 16) |
| 13:00 | First run of the hotspot script on the real card failed: NetworkManager called the new interface "strictly unmanaged" | It had inherited the card's MAC address; with its own address and a few seconds' wait it was managed. Confirmed in the second run |
| 13:30 | Second run: NetworkManager moved the normal Wi-Fi onto the new interface and our step that forced it back failed | We stopped forcing a layout: the hotspot goes on whichever interface is free, the firewall rules follow |
| 14:00 | (milestone) Third run passed | A real iPhone on the hotspot shows up live on the screen, through the script and the real sensor |
| 14:00 | Blocking looked broken: a blocked app kept working and the counter stayed at 0 | DNS blocking acts on new lookups only. Answers now live 10 seconds, the screen says what a block covers, and the demo is: block the company, reopen the app. Re-test pending |
| 14:00 | "Device 1" was the laptop's own test lookup | Shown as "box self-test", not numbered |
| 14:00 | Real traffic hit names no list knew (Netflix, Discord, OpenAI) | Their own servers added to the hand-written list as "vendor"; the rest is for the AI |
| 16:10 | (milestone) Blocking confirmed on the real phone | Blocked AppsFlyer, reopened Reddit after about 15 s: AppsFlyer's lookups refused, Reddit kept working. The 10-second lifetime cap did it |
| 16:20 | More gaps with Reddit: Google's app hosts, Reddit's media hosts, a company shown as lowercase "reddit" | Hosts added by hand; company names are now tidied by rule when the list is built |
| 17:30 | Three hours before feature lock the judge-facing screen had no code, and its role merged into BOX | Built as a plain page the backend serves, not the planned React app: no build to forget, nothing from the internet. Checked in a headless browser at two sizes, up to 72 companies |
| 17:30 | Three numbers on the new screen disagreed (the advertising counter, the summary, the label check) | The page now takes the session's end time from the backend, and the label sentence says "advertising servers of N companies", which is what it counts |
| 17:30 | The first bubble layout looked wrong: names broken mid-word, bubbles sliding over the phone's label, the cloud ignoring the screen's width | Fixed after looking at screenshots; tests would not have found it |
| 18:30 | Microsoft showed on the live screen as a social network, and Reddit's own servers as a CDN | The list files LinkedIn's hosts under their owner, Microsoft, as "social". LinkedIn is now its own company in the hand-written list, Microsoft's sign-in hosts were added, Reddit's servers are the app's own. Found by reading live lookups, not by a test |
| 18:30 | One click blocked a company at once: nobody could see what was blocked or why | A click opens a detail panel: who the company is (the list's sentence at once, an AI text when it arrives, labelled), every server name, block buttons. The AI part runs against a stand-in only |
| 18:30 | In the new panel, a list rebuilt on every lookup would have swallowed clicks on its buttons | Rows are updated in place and keep their order while the pointer is on them. Thought of while writing it; not something a test showed |

---

## 18. Changelog

| When | What changed in this guide |
| --- | --- |
| Sat 2026-10-10 19:03 | **Logo chosen: variant A**, the turtle seen from above with a radar screen for a shell. It replaces variant C in the header and the tab icon (sections 6.7 and 16). Nothing else changed. |
| Sat 2026-10-10 18:40 | **Detail panel, company explanation, logo, knowledge-base fixes.** A click on a bubble now opens a detail panel instead of blocking (section 6.7, decision 32c rewritten, new 32e and 32f). New endpoint `GET /api/explain` and new optional AI function `explain_company` (sections 6.3, 7.6a, 7.7); tested with a stand-in, no real AI text yet. Turtle logo as inline SVG with a preview of three variants at `/logo`; the show screen's policy now also allows `data:` images for the tab icon (section 11). Overrides: Reddit's own servers as `vendor`, Microsoft's sign-in hosts added, LinkedIn as its own company (65 entries; section 6.6, decisions 23b and 23c, section 9). Tests: 116 with Postgres, 102 without. Glossary, sections 1, 5, 13, 16, 17 follow. |
| Sat 2026-10-10 17:45 | **The show screen exists.** FRONT merged into BOX; the frontend was built as a plain page in `frontend/` and is served at `/` (new section 6.7, decisions 32a to 32d, glossary, architecture, sections 11, 13 and 16). Backend additions for it: `last_session` in the snapshot, a content security policy and `no-cache` for the files at `/`, the label sentence now says "advertising servers of N companies". Tests: 103 with Postgres, 89 without; self-check 21 checks. Runbook, pitch and quickstarts follow the new screen and its keys. |
| Sat 2026-10-10 16:23 | **Blocking confirmed on a real phone.** Knowledge base: company names tidied by rule in `build_kb.py` (52 names), 4 overrides added (57). Model server: Ollama on the AMD server behind an SSH tunnel; new `health.ai_endpoint`; `.env` values for the tunnel. Privacy labels moved from AI to BOX. Recording procedure for a real replay written down. Sections 1, 2, 3, 4, 6, 7.5, 7.7, 7.8, 8 (23a, 33a), 9, 11, 13, 16, 17 updated. |
| Sat 2026-10-10 14:08 | **Hardware test passed** on the third run. Findings from it: blocking acts on new connections only (sensor now caps answer lifetimes at 10 s with `--max-ttl`; `/debug` shows what a block covers; `blocked` messages carry `covers`); the laptop's own test lookup is shown as "box self-test"; Netflix, Discord and OpenAI added to the overrides (53 entries). Sections 3, 4, 5, 6, 7.5, 8 (3a, 22a), 9, 11, 12, 13, 16, 17 updated. Blocking is not yet re-tested on a real phone. |
| Sat 2026-10-10 13:34 | Second hardware run: the MAC address fix worked; the run then failed where the script forced the Wi-Fi back onto the real interface. `box-up.sh` no longer forces a layout: it waits for NetworkManager to settle, runs the hotspot on the free interface, and records it in a state file for `box-down.sh`. Sections 3, 4, 5, 6.2, 8 (new decision 9a), 9, 13, 16, 17 updated. Not yet re-run on hardware. |
| Sat 2026-10-10 13:14 | First hardware run of `box-up.sh` failed at the hotspot start (interface "strictly unmanaged"); cause found by hand; script changed to give `tattle0` its own MAC address and to wait for NetworkManager to manage it. Sections 3, 6.2, 8, 9, 16, 17 updated. The changed script is not yet re-run on hardware. |
| Sat 2026-10-10 12:20 | Marked as an internal document, with the checklist for the day the repository goes public (section 15). No change to the project itself. |
| Sat 2026-10-10 12:15 | First version. Describes the project after four overnight work batches by BOX: sensor, backend, database layer, knowledge base v1, label check, security pass, soak test, runbook, presenter page. No frontend, no `ai.py`, no label files exist yet; the hotspot scripts are untested on hardware. |
