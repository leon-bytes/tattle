# Tattle

Hand someone a phone, they open an app, and the screen fills with every company that app quietly contacts: live, in plain English, with one tap to block a tracker.

Tattle is a laptop acting as a Wi-Fi hotspot. It answers the phone's DNS lookups, so it sees each server name (never content), maps names to companies with a tracker list and an open-source LLM, and blocks by answering "that name doesn't exist".

- Team plan, interfaces and run steps: [docs/TEAM.md](docs/TEAM.md)
- Demo script and talking points: [docs/PITCH.md](docs/PITCH.md)
- The whole project explained in one file, written to be pasted into an AI chat: [docs/PROJECT-GUIDE.md](docs/PROJECT-GUIDE.md)

## Run it

- Without any hardware (backend, replayed traffic, live debug page): [backend/README.md](backend/README.md)
- The DNS sensor on its own: [sensor/README.md](sensor/README.md)
- The real thing, hotspot and all: [box/README.md](box/README.md)

## Privacy

- Our own test phones only, plus people who explicitly opt in.
- Password-protected network.
- Data is kept in memory and wiped after each demo.
- Phones show as "Device 1", "Device 2": their own names are not read.

## Credits

Tracker categories: [Disconnect tracking protection list](https://github.com/disconnectme/disconnect-tracking-protection) (CC BY-NC-SA 4.0). `data/kb.json` is built from it by `tools/build_kb.py` and is shared under the same license, for non-commercial use.
