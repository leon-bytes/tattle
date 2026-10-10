# Submission text (draft)

Written on Saturday evening, at feature lock. Everything under "The text" is meant to be pasted into the submission form, section by section. It contains no names, no school and no location.

## Before pasting: check these

The text is true as of Saturday 19:45. These points can change before the deadline; each is marked in the text with `<…>` or named here.

- `<team name>`, `<repository link>`, `<video link>`: fill in.
- **AI paragraph and tech stack:** as of now the model module (`backend/app/ai.py`) is not written and the model server lists no model. The text says so. If the module lands, replace the marked sentence with the "once the model is live" variant below it and fill in `<model>`.
- `<other AI tools the team used>`: this draft only knows the tool used for the hotspot, sensor, backend and screen. Add what was used for the AI part and the diagram.
- **Privacy-label check:** no label files exist yet, so the text lists it under limitations. If labels for the demo apps are added, move that sentence up.
- **Database:** the history store is built and tested against a local Postgres, not yet connected to the organizers' one. Change the sentence if that happens.
- **Replay:** the only replay is simulated traffic. Change the sentence if a real session is recorded.
- Test counts (101 backend, 35 sensor, 21 end-to-end checks): re-run before pasting if code changed.
- Length: about 1,200 words in all, 270 in the longest section. If the form has one field with a limit, "What it is" and "How it works" together are the core (about 340 words).

---

## The text

### Tattle: who is your phone talking to?

Hand someone a phone, they open an app, and a screen fills with every company that app quietly contacts: live, in plain English, with one click to block one.

### What it is

Tattle is a laptop that acts as a Wi-Fi hotspot. A phone joins it, with nothing installed on the phone. Before an app can connect to a server it has to ask "where is this server?" (a DNS lookup), and on our Wi-Fi we are the one it asks. So we see the name of every server the phone looks up, and never what is sent afterwards.

The screen shows the phone in the middle and one bubble per company around it, coloured and tagged by what the company does: advertising, analytics, social, fingerprinting, content delivery, or the app's own servers. A click on a bubble opens a panel that says who the company is and lists every server name the phone asked for. One more click blocks the company: we answer "that name does not exist", the app cannot reach it, and a counter shows the app trying again and again while it keeps working.

### Who it helps

Anyone who wants to know what an app really does and has no time for packet captures. The tools that show this today are buried in settings, show raw server names, or need installing and configuring. Tattle takes a minute and reads like a sentence. From our simulated test session: "In 58 seconds, Demo Game contacted 14 companies: 9 advertising, 1 analytics, 1 social, and 3 others."

### How it works

1. The laptop runs a password-protected hotspot with an honest name. A firewall rule sends every DNS packet from the hotspot to our own resolver, whatever server the phone addressed it to.
2. The resolver answers the phone by asking a public resolver, and reports each name to a backend. It also refuses the names a phone uses to switch to encrypted DNS or iCloud Private Relay, so the phone falls back to DNS we can see; the screen counts these apart, as "hidden-traffic attempts".
3. The backend turns a name into a company and a category with an open tracker list plus a short hand-written list, and pushes each lookup to the screen within a fraction of a second.
4. Blocking a company makes the resolver answer "does not exist" for all of its names. Every answer we relay is given a 10-second lifetime, so a block takes hold the next time the app connects.

Tested with a real iPhone on the real hotspot: its lookups appeared live, and blocking one tracking company stopped that company's lookups while the app kept working.

### Tech stack

- **Hotspot:** Linux, NetworkManager, a virtual access-point interface on the laptop's one Wi-Fi card, `iptables` for the DNS redirect.
- **Resolver ("sensor"):** Python, one file, one dependency (`dnslib`).
- **Backend:** Python, FastAPI, WebSocket, state in memory. Optional Postgres for the history of our own test phones.
- **Screen:** plain HTML, CSS and JavaScript. No framework, no build step, nothing loaded from the internet.
- **Tracker data:** Disconnect's tracking-protection list (CC BY-NC-SA 4.0), about 4,400 domains, plus 65 hand-written entries.
- **AI:** an open-source model served by Ollama on an AMD Radeon PRO W7900 through ROCm, reached over an SSH tunnel. <As submitted: the backend's side is built and tested with a stand-in; the model module is not finished.>
- **Tests:** 101 backend tests, 35 resolver tests, and a 21-step end-to-end check that runs without Wi-Fi.

### AI tools we used

- **Claude Code** wrote most of the hotspot scripts, the resolver, the backend and the screen, working from our decisions and our hardware tests. We ran every hardware test ourselves: an AI assistant cannot see a Wi-Fi card.
- <other AI tools the team used>
- **In the product:** an open-source model is meant to name the servers no list knows, write the session summary and explain a company in the detail panel. The screen never waits for it and labels its answers as guesses. <As submitted: this part runs against a stand-in only.>

*Once the model is live, use instead:* "In the product, <model> (open source, on the AMD GPU) names the servers no list knows, writes the session summary and explains each company in the detail panel. The screen never waits for it and labels its answers as guesses."

### Challenges and what we learned

- **The hotspot took three tries on real hardware.** The network manager refused our virtual interface until it had a hardware address of its own, then moved the laptop's own Wi-Fi onto it. We stopped forcing a layout and let the script use whichever interface was left free.
- **The phone avoided us twice.** First it quietly used its cellular connection, then it sent its lookups to a leftover VPN server. Turning cellular data off fixed the first; redirecting all DNS traffic, whatever its destination, fixed the second.
- **Blocking looked broken.** We blocked an app's server and a message still went through. DNS blocking only acts when the phone asks for a name; it had the answer already and kept a connection open. Shortening every answer's lifetime to 10 seconds made blocks take hold at the app's next connection.
- **The tracker list is written for websites.** Phone-only advertising servers and the phone maker's own servers were missing, and one social network's servers showed up under its parent company. We found these by reading live lookups, not by tests.
- **A looked-up name is untrusted input.** A phone can ask for a name made of markup. We resolve and show plain host names only; anything else is refused and counted.
- **The screen was built in the last three hours** before feature lock, as a plain page instead of the planned framework app: no build to forget before the demo.

What we learned: the capture trick is old and simple. The work is in everything around it, and most of what was wrong could only be seen on a real phone.

### Honest limitations

- We see server names, not content. "Contacted" never means "sent your data".
- We see a phone, not an app. We attribute lookups to the app someone was using at the time; the phone's own background traffic can mix in.
- An app that uses its own encrypted DNS to an unknown server, connects straight to an address, or reuses an answer it already had, gets past us.
- A block stops new connections, not ones already open.
- The backend has no login. Phones on the hotspot are firewalled away from it, and requests from other websites are refused; a product would need more.
- Categories come from a list; a name no list knows shows as "Not identified" unless the model names it, and that is a guess.
- Comparing an app's lookups with its App Store privacy label is built, but we have no label files for real apps yet.
- The history of past sessions is stored but has no screen yet.
- The fallback replay is simulated traffic, not a recording of a real phone.
