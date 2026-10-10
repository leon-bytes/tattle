# Sensor

`tattle_sensor.py` is the DNS resolver the hotspot's phones end up talking to. For every lookup it:

1. answers NXDOMAIN if the name is on the guard list or the backend's blocklist, otherwise forwards the query to the upstream resolver and relays the answer;
2. reports the name to the backend (`POST /api/events`, batched every 250 ms).

One file, one dependency (`dnslib`). It never needs root: the box redirects port 53 to its port 5300.

At demo time it runs on the host laptop, next to the hotspot, and reports to the backend in the VM. The host only needs copies of this folder and `box/`; the steps are in `box/README.md`.

## Run (dev)

From the repo root:

```sh
python3 -m venv sensor/.venv                                # once: a private Python environment
sensor/.venv/bin/pip install -r sensor/requirements-dev.txt # once: dnslib, plus pytest for the tests (on the host: requirements.txt, dnslib only)
```

```sh
sensor/.venv/bin/python sensor/tattle_sensor.py --listen 127.0.0.1:5300 --debug
```

Then ask it something from another terminal:

```sh
dig @127.0.0.1 -p 5300 example.com         # forwarded: a normal answer
dig @127.0.0.1 -p 5300 mask.icloud.com     # guard list: status NXDOMAIN
dig @127.0.0.1 -p 5300 +tcp example.com    # same over TCP
```

- `@127.0.0.1 -p 5300`: ask the sensor instead of the system resolver.

## Flags (each also has an environment variable)

| Flag | Env | Default | Meaning |
| --- | --- | --- | --- |
| `--listen` | `SENSOR_LISTEN` | `0.0.0.0:5300` | address and port, UDP and TCP |
| `--upstream` | `UPSTREAM_DNS` | `9.9.9.9` | resolver to forward to, `host` or `host:port`; 3 s timeout, then SERVFAIL |
| `--backend` | `BACKEND_URL` | `http://127.0.0.1:8000` | where events go and the blocklist comes from |
| `--names` | | off | send each phone's DHCP hostname as `client_name`. Off: phones are reported by address only |
| `--leases` | `LEASES_FILE` | `/var/lib/NetworkManager/dnsmasq-tattle0.leases` | where `--names` reads hostnames from; unreadable or missing means no names. The file is named after the interface the hotspot runs on, which is not always `tattle0`: `box-up.sh` prints the right path |
| `--max-ttl` | `SENSOR_MAX_TTL` | `10` | cut the lifetime (TTL) of every relayed answer to this many seconds; `0` leaves answers as they are |
| `--debug` | | off | print one line per query. Development only |
| `--record FILE` | | off | append events to a JSONL replay. Only with our own phones, only on purpose |

If `9.9.9.9` is unreachable from your network (some networks only allow their own resolver), pass `--upstream` with the resolver from `/etc/resolv.conf`.

## Behaviour worth knowing

- **Guard list** (always NXDOMAIN, suffix match): the list at the top of `tattle_sensor.py`. These are the phone's ways around us (encrypted DNS, iCloud Private Relay); the backend counts them as "hidden-traffic attempts".
- **Short answer lifetimes.** A phone reuses a DNS answer until its lifetime (TTL) runs out, and only a new lookup can be blocked. So the sensor cuts every answer's lifetime to 10 s (`--max-ttl`): phones ask again within seconds, and a block or unblock takes hold at the app's next connection. Nothing else in the answer is changed. A connection that is already open is not affected by a block; that needs the app to reconnect.
- **Names are untrusted.** A phone can look up anything, and DNS allows any bytes in a name. The sensor resolves and reports plain host names only (letters, digits, `-`, `_`, dots; 253 characters at most). Anything else is answered `REFUSED`, never forwarded, never printed, and counted; the count reaches the backend as `malformed`.
- **Backend down:** lookups keep working with the last blocklist. Up to 5000 events wait in memory, oldest dropped first, and are delivered when the backend is back.
- **Privacy:** query names are never printed or written unless `--debug` or `--record` is given. Normal output is two start lines and "backend connected / unreachable".
- **Device names are off by default.** Without `--names` the sensor never opens the lease file, and the backend shows "Device 1", "Device 2". Use `--names` for our own phones only.
- **`--record`** replaces device names with `Test iPhone A`, `B`, … before writing. Host names are written as they are, so the file has to be looked over before it joins the repo: use a `.raw.jsonl` name (git-ignored) until then. The whole procedure is in `box/README.md`, "Recording a replay from our own phone".

## Tests

```sh
sensor/.venv/bin/python -m pytest sensor/tests    # about 35 s; uses a fake upstream and a fake backend on loopback
```
