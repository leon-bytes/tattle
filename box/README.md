# The box: hotspot and sensor on the host laptop

> **UNTESTED.** `box-up.sh` and `box-down.sh` were written without access to the Wi-Fi hardware and have never been run. They follow the setup that worked by hand (a virtual AP interface next to the normal Wi-Fi), but the first run should be done with this page open. The sensor and the backend are tested, but only inside the dev VM.

## What runs where

| Where | What | Needs |
| --- | --- | --- |
| Host laptop | hotspot (`box-up.sh`) and the sensor | NetworkManager, `iw`, `iptables`, `python3`, a venv with `dnslib` |
| VM on the same laptop | backend (and the frontend it serves) | the whole repo; see `backend/README.md` there |

**The host only needs two folders: `sensor/` and `box/`.** Copy them anywhere, side by side. No checkout, no git, nothing else from the repo. All host commands below are run from the folder that holds the two.

The VM sits on libvirt's default network. The host reaches it directly at the VM's `192.168.122.x` address; nothing has to be forwarded. The sensor sends its events there (`--backend http://<vm-ip>:8000`), and the browser on the host opens the same address.

## Morning hardware checklist

In the VM, from the repo root:

1. `backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --no-access-log`
   Starts the backend where the host can reach it.
2. `ip -4 -brief addr`
   Shows the VM's addresses. The `192.168.122.x` one is `<vm-ip>` below.

On the host, in the folder that holds `sensor/` and `box/`:

3. `curl http://<vm-ip>:8000/api/health`
   Proves the host can reach the backend: expect a line of JSON.
4. `mullvad disconnect`
   VPN off, for tests and the demo.
5. `python3 -m venv sensor/.venv && sensor/.venv/bin/pip install -r sensor/requirements.txt`
   Once: a private Python environment with `dnslib`, the sensor's only dependency.
6. `iw dev`
   Lists Wi-Fi interfaces. The real one's name is `<wifi-interface>` below.
7. `sudo bash box/box-up.sh <wifi-interface>`
   Hotspot `Tattle-Demo` up and DNS redirected. Asks for the hotspot password. Expect `tattle0 … 10.42.0.1/24`. (`bash …` so it runs even if the copy lost the scripts' executable bit.)
8. `sensor/.venv/bin/python sensor/tattle_sensor.py --backend http://<vm-ip>:8000`
   Starts the sensor (leave it running). Expect `backend: connected`. OpenSnitch asks about the connection to the VM: allow.
9. `sensor/.venv/bin/python -c "from dnslib import DNSRecord; print(DNSRecord.parse(DNSRecord.question('example.com').send('127.0.0.1', 5300, timeout=5)).short())"`
   One lookup through the sensor, from a second terminal: expect IP addresses. OpenSnitch asks about DNS to `9.9.9.9`: allow.
10. On the iPhone: join `Tattle-Demo`. If nothing shows up, turn cellular data off.
11. Open `http://<vm-ip>:8000/debug` in the host's browser.

**Pass: the iPhone on Tattle-Demo shows up live on /debug.**

Afterwards: Ctrl+C in the sensor's terminal, then `sudo bash box/box-down.sh` (removes the firewall rules, the hotspot and `tattle0`).

## Things to know

- **Phones have no DNS between step 7 and step 8.** The redirect to the sensor goes in before the sensor runs.
- **Mullvad stays off.** `box-up.sh` prints a warning if `mullvad status` reports a connection, and carries on.
- **OpenSnitch on the host will prompt for the sensor.** It makes two kinds of outgoing connections: DNS to `9.9.9.9` port 53 (UDP and TCP), and HTTP to `<vm-ip>` port 8000. Both need an allow rule that lasts (at least "until reboot"). If a prompt times out into a deny, lookups stall for 3 s and phones look offline. Steps 8 and 9 trigger both prompts before a phone joins.
- **Device names are hidden.** The sensor reports phones by address and the page shows "Device 1", "Device 2". For our own phones, add `--names` in step 8 to send DHCP hostnames (the lease file usually needs root to read, so this may still give nothing), or rename the device on the page.
- **The VM's address can change** after a VM restart. Step 2 shows the current one. From the host, `virsh -c qemu:///system net-dhcp-leases default` lists it too. To stop it changing, see "A fixed address for the VM" below.
- **The short version** of this page, for the walk to the judges: `docs/RUNBOOK.md` in the repo.
- **The password** is asked for by the script. `PASSWORD=…` in the environment also works but lands in the shell history.

## A fixed address for the VM (optional, once)

libvirt hands the VM its address by DHCP, so it can change after a restart. This one-time command on the host reserves the address the VM has right now for the VM's network card, and `<vm-ip>` stays the same from then on:

```sh
virsh -c qemu:///system net-update default add ip-dhcp-host "<host mac='<vm-mac>' ip='<vm-ip>'/>" --live --config
```

- `<vm-ip>`: the VM's current address. In the VM: `ip -4 -brief addr` (the `192.168.122.x` one). From the host: `virsh -c qemu:///system net-dhcp-leases default`, which lists address and MAC together.
- `<vm-mac>`: the hardware address of the VM's network card. In the VM: `ip -brief link` shows it on the line of the interface that has that address (it looks like `52:54:00:xx:xx:xx`). From the host: the same `net-dhcp-leases` line, or `virsh -c qemu:///system domiflist <vm-name>`.
- `-c qemu:///system`: talk to the system libvirt, where the `default` network lives.
- `net-update default add ip-dhcp-host`: add one DHCP reservation to the network named `default`.
- `--live` applies it to the running network, `--config` keeps it across host reboots.
- Nothing changes for the running VM: it already has this address.
- To undo: the same command with `delete` in place of `add`.

## What the scripts do

`box-up.sh`:

1. Creates a virtual access-point interface `tattle0` on the Wi-Fi card. The normal Wi-Fi interface keeps its internet connection.
2. Pins the jobs: `tattle0` is told never to auto-connect to a known Wi-Fi, and if NetworkManager already moved the normal connection over, it is moved back.
3. Adds three firewall chains (temporary, gone after a reboot):
   - `TATTLE-IN`: hotspot clients may reach DHCP (67), DNS (53) and the sensor (5300) on the box, nothing else.
   - `TATTLE-DNS`: every packet to port 53 arriving from the hotspot, **whatever server it was addressed to**, is redirected to the sensor on 5300. This also catches phones that still use a leftover DNS server (seen: a VPN's).
   - `TATTLE-FWD`: from the hotspot, port 853 (DNS-over-TLS and DNS-over-QUIC) is rejected so phones fall back to plain DNS, and the VM's network (`VM_NET`, default `192.168.122.0/24`) is rejected so phones cannot reach the backend's API.
4. Starts the NetworkManager hotspot on `tattle0`: 2.4 GHz, WPA2 password. NetworkManager provides DHCP (phones get `10.42.0.x`, the box is `10.42.0.1`) and NAT.

`box-down.sh` removes those three chains, stops and deletes the hotspot profile (it holds the password), and removes `tattle0`. It is safe to run twice, and `box-up.sh` calls it if anything fails halfway.

## If something goes wrong

- **Step 3 fails (host cannot reach the VM).** Is the backend started with `--host 0.0.0.0`? Is `<vm-ip>` current (step 2)? The VM's firewall already allows port 8000 on that interface; `firewall-cmd --list-ports` in the VM should show `1025-65535/tcp`.
- **iPhone stuck on "joining".** In the first hardware test this was the firewall dropping DHCP. `box-up.sh` allows DHCP, DNS and 5300 only; the setup that was actually tested allowed everything on the hotspot interface. To fall back to that: `sudo iptables -I TATTLE-IN 1 -j ACCEPT` (puts "accept everything" first in our chain; `box-down.sh` removes it with the chain).
- **Joined, but nothing on the page.** Is the sensor running and showing `backend: connected`? Does `sudo tcpdump -ni tattle0 port 53` show packets (`-n` no name lookups, `-i` the interface)? If the iPhone uses cellular instead of our Wi-Fi, turn cellular data off.
- **Names appear, but the phone has no internet, or every lookup takes 3 s.** The sensor cannot reach `9.9.9.9`: OpenSnitch denied it, or Mullvad is on. Step 9 tests exactly this.
- **Sensor says `backend: unreachable`.** Lookups still work and events queue up (5000 at most). Check step 3 and the OpenSnitch rule for port 8000.
- **iPhone shows "Private Relay is turned off for this network".** Expected: that is the guard list working. Tap "use without Private Relay".
- **`box-up.sh` says the box looks already up.** Run `sudo bash box/box-down.sh`, then try again.
- **The normal Wi-Fi dropped when the hotspot started.** `nmcli device status` shows which profile sits on which interface. `sudo bash box/box-down.sh` returns to the normal state.

Check what is in place at any time:

```sh
sudo iptables -S | grep TATTLE           # our filter rules
sudo iptables -t nat -S | grep TATTLE    # our DNS redirect
nmcli device status                      # which interface does what
```

## Assumptions that still need a real test

- `nmcli device set tattle0 autoconnect no` is enough to stop NetworkManager from swapping the two interfaces.
- The narrower input rules (DHCP, DNS, 5300) are enough for an iPhone to join.
- The hotspot hands out IPv4 only. The firewall rules are IPv4 only; if phones got IPv6 DNS, an `ip6tables` twin of the redirect would be needed.
- `iptables -I … 1` puts our chains ahead of the NixOS firewall's and NetworkManager's own rules.
- The host keeps reaching the VM while the Wi-Fi card runs the hotspot. The libvirt bridge is separate from the Wi-Fi card, so it should.
- The host and VM clocks may differ: the backend puts every batch of events on its own clock, so this should not matter.
