#!/usr/bin/env bash
# ============================================================================
# UNTESTED. Written without access to the Wi-Fi hardware; never run so far.
# Read box/README.md first and run it line by line the first time.
# ============================================================================
#
# Brings the Tattle hotspot up on the box (Linux + NetworkManager + iptables):
# a second, virtual Wi-Fi interface carries the hotspot, the normal Wi-Fi
# interface is left alone, and DNS from hotspot clients is steered to the sensor.
# Nothing here survives a reboot. box-down.sh undoes all of it.
#
# Usage: sudo bash box/box-up.sh <wifi-interface> [ssid]
#        IFACE, SSID, PASSWORD and VM_NET are also read from the environment.
#        Without PASSWORD the script asks for it, which keeps it out of the shell history.

set -euo pipefail                      # stop at the first failing command or unset variable

IFACE="${1:-${IFACE:-}}"               # the laptop's real Wi-Fi interface ("iw dev" lists it)
SSID="${2:-${SSID:-Tattle-Demo}}"      # network name the phones see
PASSWORD="${PASSWORD:-}"               # WPA2 password: env only, an argument would show up in "ps"
AP_IFACE=tattle0                       # virtual interface that carries the hotspot
CON_NAME=tattle-hotspot                # NetworkManager profile name of the hotspot
SENSOR_PORT=5300                       # where sensor/tattle_sensor.py listens
VM_NET="${VM_NET:-192.168.122.0/24}"   # network of the VM that runs the backend (libvirt's default network)

[ "$(id -u)" -eq 0 ] || { echo "run with sudo: creating interfaces and firewall rules needs root" >&2; exit 1; }
[ -n "$IFACE" ] || { echo "set IFACE to the Wi-Fi interface (see: iw dev)" >&2; exit 1; }
iw dev "$IFACE" info >/dev/null || { echo "$IFACE is not a Wi-Fi interface" >&2; exit 1; }

if [ -z "$PASSWORD" ]; then            # no password in the environment: ask without echoing it
  read -r -s -p "Hotspot password (8-63 characters): " PASSWORD; echo
fi
if [ "${#PASSWORD}" -lt 8 ] || [ "${#PASSWORD}" -gt 63 ]; then   # WPA2 limits; also means never an open network
  echo "the password must be 8-63 characters" >&2; exit 1
fi

if iw dev "$AP_IFACE" info >/dev/null 2>&1 || iptables -w -S TATTLE-IN >/dev/null 2>&1; then
  echo "the box looks already up: run box-down.sh first" >&2; exit 1   # keeps reruns predictable
fi

# The VPN must be off for tests and the demo: warn, but carry on.
MULLVAD="$(command -v mullvad >/dev/null 2>&1 && mullvad status 2>/dev/null || true)"   # empty if Mullvad is not installed
if grep -qiE '(^|[^s])connect(ed|ing)' <<<"$MULLVAD"; then                              # "Connected"/"Connecting", but not "Disconnected"
  echo "WARNING: Mullvad VPN is connected. Hotspot phones may get no internet and the sensor's DNS may fail." >&2
  echo "         Turn it off with: mullvad disconnect" >&2
fi

# From here on, a failure cleans up after itself.
trap 'echo "box-up failed, cleaning up" >&2; bash "$(dirname "$0")/box-down.sh"' ERR

# --- interfaces: pin the jobs so NetworkManager cannot swap them ---

UPLINK_CON="$(nmcli -g GENERAL.CONNECTION device show "$IFACE")"   # profile now active on the real interface (empty if none)
[ "$UPLINK_CON" = "--" ] && UPLINK_CON=""                          # some nmcli versions print "--" for "none"

iw dev "$IFACE" interface add "$AP_IFACE" type __ap                # create the virtual access-point interface on the same card

for _ in 1 2 3 4 5 6 7 8 9 10; do                                  # wait up to 5 s for NetworkManager to notice it
  nmcli -g GENERAL.DEVICE device show "$AP_IFACE" >/dev/null 2>&1 && break
  sleep 0.5
done

nmcli device set "$AP_IFACE" autoconnect no                        # NetworkManager may never auto-pick this interface for a known Wi-Fi
nmcli device disconnect "$AP_IFACE" >/dev/null 2>&1 || true        # if it already grabbed one in the meantime, drop it

if [ -n "$UPLINK_CON" ] && [ "$(nmcli -g GENERAL.CONNECTION device show "$IFACE")" != "$UPLINK_CON" ]; then
  nmcli connection up "$UPLINK_CON" ifname "$IFACE"                # put the normal Wi-Fi back on the real interface
fi

# --- firewall: three own chains, so box-down.sh can remove exactly these rules ---

iptables -w -N TATTLE-IN                                                       # filter chain: what hotspot clients may send to the box itself
iptables -w -A TATTLE-IN -p udp --dport 67 -j ACCEPT                           # DHCP, so phones get an address
iptables -w -A TATTLE-IN -p udp --dport 53 -j ACCEPT                           # DNS to NetworkManager's own dnsmasq (only reached if the redirect below is removed)
iptables -w -A TATTLE-IN -p tcp --dport 53 -j ACCEPT                           # same, over TCP
iptables -w -A TATTLE-IN -p udp --dport "$SENSOR_PORT" -j ACCEPT               # DNS to the sensor
iptables -w -A TATTLE-IN -p tcp --dport "$SENSOR_PORT" -j ACCEPT               # same, over TCP
iptables -w -I INPUT 1 -i "$AP_IFACE" -j TATTLE-IN                             # use that chain for everything arriving on the hotspot interface

iptables -w -t nat -N TATTLE-DNS                                               # nat chain: steer DNS to the sensor
iptables -w -t nat -A TATTLE-DNS -p udp --dport 53 -j REDIRECT --to-ports "$SENSOR_PORT"   # any UDP DNS, whatever server the phone aimed at
iptables -w -t nat -A TATTLE-DNS -p tcp --dport 53 -j REDIRECT --to-ports "$SENSOR_PORT"   # same for TCP DNS
iptables -w -t nat -I PREROUTING 1 -i "$AP_IFACE" -j TATTLE-DNS                # apply it to everything arriving on the hotspot interface

iptables -w -N TATTLE-FWD                                                      # filter chain: what hotspot clients may not reach on the internet
iptables -w -A TATTLE-FWD -p tcp --dport 853 -j REJECT --reject-with tcp-reset # DNS-over-TLS: refuse fast, so phones fall back to plain DNS
iptables -w -A TATTLE-FWD -p udp --dport 853 -j REJECT                         # DNS-over-QUIC: same
iptables -w -A TATTLE-FWD -d "$VM_NET" -j REJECT                               # phones may not reach the VM network: the backend's API listens there
iptables -w -I FORWARD 1 -i "$AP_IFACE" -j TATTLE-FWD                          # apply it to everything forwarded from the hotspot interface

# --- hotspot ---

# Start the hotspot on the virtual interface: 2.4 GHz (band bg), WPA2 password, DHCP and NAT by NetworkManager.
nmcli device wifi hotspot ifname "$AP_IFACE" con-name "$CON_NAME" ssid "$SSID" password "$PASSWORD" band bg
nmcli connection modify "$CON_NAME" connection.autoconnect no      # the saved profile must not start by itself; box-down.sh deletes it

trap - ERR
echo "hotspot \"$SSID\" is up on $AP_IFACE:"
ip -4 -brief addr show "$AP_IFACE"                                 # expected: 10.42.0.1/24
echo "next: start the sensor (box/README.md). Phones have no DNS until the sensor runs."
