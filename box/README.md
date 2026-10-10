# The box: hotspot and sensor on the host laptop

> **Hardware test passed** (Saturday, about 14:00): with `box-up.sh` and the real sensor, a real iPhone on `Tattle-Demo` showed up live on `/debug`. It took three runs. Run 1: NetworkManager would not manage `tattle0` (fixed with its own MAC address and a wait). Run 2: forcing the normal Wi-Fi back onto the real interface failed (fixed by no longer forcing which interface does which job). Run 3 passed. Not confirmed yet on hardware: that a block visibly stops an app (the first try looked broken, see "Things to know"), `box-down.sh` after a hotspot that really ran, and the items under "Still unproven" at the end.

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
   Hotspot `Tattle-Demo` up and DNS redirected. Asks for the hotspot password, and takes up to half a minute while the interfaces settle. It prints NetworkManager's device table before and after, then two plain lines: `HOTSPOT: … runs on <interface>` (with `10.42.0.1/24`) and `INTERNET: the normal Wi-Fi … is on <interface>`. (`bash …` so it runs even if the copy lost the scripts' executable bit.)
8. `sensor/.venv/bin/python sensor/tattle_sensor.py --backend http://<vm-ip>:8000`
   Starts the sensor (leave it running). Expect `backend: connected`. OpenSnitch asks about the connection to the VM: allow.
9. `sensor/.venv/bin/python -c "from dnslib import DNSRecord; print(DNSRecord.parse(DNSRecord.question('example.com').send('127.0.0.1', 5300, timeout=5)).short())"`
   One lookup through the sensor, from a second terminal: expect IP addresses. OpenSnitch asks about DNS to `9.9.9.9`: allow. On `/debug` this lookup appears under "box self-test": it is the laptop asking itself, not a phone.
10. On the iPhone: join `Tattle-Demo`. If nothing shows up, turn cellular data off.
11. Open `http://<vm-ip>:8000/debug` in the host's browser.

**Pass: the iPhone on Tattle-Demo shows up live on /debug.**

Afterwards: Ctrl+C in the sensor's terminal, then `sudo bash box/box-down.sh` (removes the firewall rules, the hotspot and `tattle0`).

## Things to know

- **A block stops new connections, not open ones.** In the live test, blocking `discord.com` seemed to do nothing: the phone already had the answer and Discord keeps a connection open (and also uses `discord.gg` and `discordapp.net`). DNS blocking only acts on a new lookup. The sensor now makes phones ask again within 10 s (`--max-ttl`), and `/debug` says what each block covers. To see a block bite: block the **company**, then close the app on the phone and open it again.
- **Phones have no DNS between step 7 and step 8.** The redirect to the sensor goes in before the sensor runs.
- **Mullvad stays off.** `box-up.sh` prints a warning if `mullvad status` reports a connection, and carries on.
- **OpenSnitch on the host will prompt for the sensor.** It makes two kinds of outgoing connections: DNS to `9.9.9.9` port 53 (UDP and TCP), and HTTP to `<vm-ip>` port 8000. Both need an allow rule that lasts (at least "until reboot"). If a prompt times out into a deny, lookups stall for 3 s and phones look offline. Steps 8 and 9 trigger both prompts before a phone joins.
- **Device names are hidden.** The sensor reports phones by address and the page shows "Device 1", "Device 2". For our own phones, add `--names --leases /var/lib/NetworkManager/dnsmasq-<hotspot-interface>.leases` in step 8 to send DHCP hostnames (`box-up.sh` prints the exact path; the file usually needs root to read, so this may still give nothing), or rename the device on the page.
- **The VM's address can change** after a VM restart. Step 2 shows the current one. From the host, `virsh -c qemu:///system net-dhcp-leases default` lists it too. To stop it changing, see "A fixed address for the VM" below.
- **The short version** of this page, for the walk to the judges: `docs/RUNBOOK.md` in the repo.
- **Which interface is the hotspot is decided at run time.** Either `tattle0` or the real Wi-Fi interface, whichever NetworkManager leaves free; the other carries the internet. Both layouts work. `box-up.sh` says which is which at the end, and the firewall rules follow the hotspot interface. Wherever this page says `<hotspot-interface>`, use the name from the `HOTSPOT:` line.
- **`tattle0` gets its own MAC address,** `02:00:00:00:00:01` (a "locally administered" address, the kind reserved for made-up interfaces). With the card's own address, which it would inherit, NetworkManager refused to manage it. To use another one: `sudo AP_MAC=02:00:00:00:00:02 bash box/box-up.sh <wifi-interface>`.
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

1. Creates a virtual access-point interface `tattle0` on the Wi-Fi card, with a MAC address of its own (`AP_MAC`). It then waits up to 10 s until NetworkManager lists `tattle0` as anything other than "unmanaged". If it is still unmanaged, it asks once (`nmcli device set tattle0 managed yes`) and waits again; if that fails too, it stops with a message and cleans up.
2. Lets NetworkManager settle, for up to 20 s. Adding an interface makes it reshuffle: on our card it moves the normal Wi-Fi onto `tattle0` and frees the real interface. The script does not fight that. It waits until one of the two has held the normal Wi-Fi for 3 s while the other is free, and uses **the other one** for the hotspot. If neither is on the normal Wi-Fi after 20 s, it carries on with a clear warning that the hotspot will have no internet. It writes the hotspot interface's name to `/run/tattle-box.state` (gone after a reboot).
3. Adds three firewall chains (temporary, gone after a reboot):
   - `TATTLE-IN`: hotspot clients may reach DHCP (67), DNS (53) and the sensor (5300) on the box, nothing else.
   - `TATTLE-DNS`: every packet to port 53 arriving from the hotspot, **whatever server it was addressed to**, is redirected to the sensor on 5300. This also catches phones that still use a leftover DNS server (seen: a VPN's).
   - `TATTLE-FWD`: from the hotspot, port 853 (DNS-over-TLS and DNS-over-QUIC) is rejected so phones fall back to plain DNS, and the VM's network (`VM_NET`, default `192.168.122.0/24`) is rejected so phones cannot reach the backend's API.
4. Starts the NetworkManager hotspot on that interface: 2.4 GHz, WPA2 password. NetworkManager provides DHCP (phones get `10.42.0.x`, the box is `10.42.0.1`) and NAT. Then it prints the device table again and says which interface is the hotspot and which carries the internet.

`box-down.sh` removes those three chains, stops and deletes the hotspot profile (it holds the password), and removes `tattle0`. It reads the hotspot interface's name from `/run/tattle-box.state`; if that file is missing it finds our rules by the chains they point at. If the normal Wi-Fi was on `tattle0`, it drops for a few seconds until NetworkManager reconnects it on the real interface. It is safe to run twice, and `box-up.sh` calls it if anything fails halfway.

## If something goes wrong

- **`box-up.sh` warns "neither … is connected to the normal Wi-Fi".** After adding `tattle0`, NetworkManager did not bring the laptop's Wi-Fi back within 20 s. The hotspot still comes up, but phones on it have no internet. Look at `nmcli device status`; connect the Wi-Fi by hand on the interface that is not the hotspot (`nmcli device wifi connect "<network>" ifname <the-other-interface>`), or run `sudo bash box/box-down.sh` and try again.
- **`box-up.sh` fails at the hotspot start in the swapped layout** ("… is not available on device …"). The real interface was not yet usable again when the hotspot was started on it. This is what broke run 2, in a different step. The script now waits for the free interface to be usable; if it still happens, run `sudo bash box/box-down.sh`, wait ten seconds, and run `box-up.sh` again.
- **`box-up.sh` stops with "NetworkManager still lists tattle0 as unmanaged".** This is what broke run 1, before the MAC address fix. Check by hand: `sudo iw dev <wifi-interface> interface add tattle0 type __ap addr 02:00:00:00:00:01`, wait 3 s, then `nmcli device status` should show `tattle0` as "disconnected" (that worked on our card). Remove it again with `sudo iw dev tattle0 del`. If it stays "unmanaged", NetworkManager on this machine is configured not to touch that interface name or address; try another `AP_MAC`.
- **Step 3 fails (host cannot reach the VM).** Is the backend started with `--host 0.0.0.0`? Is `<vm-ip>` current (step 2)? The VM's firewall already allows port 8000 on that interface; `firewall-cmd --list-ports` in the VM should show `1025-65535/tcp`.
- **iPhone stuck on "joining".** In the first hardware test this was the firewall dropping DHCP. `box-up.sh` allows DHCP, DNS and 5300 only; the setup that was actually tested allowed everything on the hotspot interface. To fall back to that: `sudo iptables -I TATTLE-IN 1 -j ACCEPT` (puts "accept everything" first in our chain; `box-down.sh` removes it with the chain).
- **Joined, but nothing on the page.** Is the sensor running and showing `backend: connected`? Does `sudo tcpdump -ni <hotspot-interface> port 53` show packets (`-n` no name lookups, `-i` the interface)? If the iPhone uses cellular instead of our Wi-Fi, turn cellular data off.
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

## Proven on hardware, and still unproven

Proven by the test that passed:

- `box-up.sh` completes on the real card: with its own MAC address NetworkManager manages `tattle0`, the interfaces settle, and the hotspot starts on the free one.
- An iPhone joins `Tattle-Demo` with the narrow input rules (DHCP, DNS, 5300) and has working internet.
- Its lookups reach the sensor through the redirect, and the sensor answers them.
- The sensor on the laptop reaches the backend in the VM while the hotspot is up, and `/debug` shows the phone live.

Still unproven:

- That a block visibly stops an app on the phone. The first try was before the answer-lifetime cap and looked broken.
- `box-down.sh` taking down a hotspot that really ran, and NetworkManager then reconnecting the normal Wi-Fi on the real interface.
- That port 853 is really rejected and that phones really cannot reach the VM's network (the rules are in place; nobody has tried to get past them).
- Device names from the lease file (`--names`).
- The hotspot hands out IPv4 only. The firewall rules are IPv4 only; if phones got IPv6 DNS, an `ip6tables` twin of the redirect would be needed.
- `iptables -I … 1` puts our chains ahead of the NixOS firewall's and NetworkManager's own rules.
- The host keeps reaching the VM while the Wi-Fi card runs the hotspot. The libvirt bridge is separate from the Wi-Fi card, so it should.
- The host and VM clocks may differ: the backend puts every batch of events on its own clock, so this should not matter.
