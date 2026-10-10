#!/usr/bin/env bash
# ============================================================================
# NOT YET PROVEN ON HARDWARE. Two runs on the real card so far, both stopped
# before the hotspot was up (the story is in box/README.md). This version no
# longer forces which interface does which job. It has not run on the card yet.
# Read box/README.md first.
# ============================================================================
#
# Brings the Tattle hotspot up on the box (Linux + NetworkManager + iptables).
# A second, virtual Wi-Fi interface is added to the card. NetworkManager keeps
# the normal Wi-Fi on one of the two interfaces (it chooses which); the hotspot
# runs on the other, and DNS from hotspot clients is steered to the sensor.
# Nothing here survives a reboot. box-down.sh undoes all of it.
#
# Usage: sudo bash box/box-up.sh <wifi-interface> [ssid]
#        IFACE, SSID, PASSWORD, VM_NET and AP_MAC are also read from the environment.
#        Without PASSWORD the script asks for it, which keeps it out of the shell history.

set -euo pipefail                      # stop at the first failing command or unset variable

IFACE="${1:-${IFACE:-}}"               # the laptop's real Wi-Fi interface ("iw dev" lists it)
SSID="${2:-${SSID:-Tattle-Demo}}"      # network name the phones see
PASSWORD="${PASSWORD:-}"               # WPA2 password: env only, an argument would show up in "ps"
AP_IFACE=tattle0                       # the virtual interface this script adds to the card
CON_NAME=tattle-hotspot                # NetworkManager profile name of the hotspot
SENSOR_PORT=5300                       # where sensor/tattle_sensor.py listens
VM_NET="${VM_NET:-192.168.122.0/24}"   # network of the VM that runs the backend (libvirt's default network)
AP_MAC="${AP_MAC:-02:00:00:00:00:01}"  # MAC address for the virtual interface: locally administered, not the card's own
STATE_FILE="${STATE_FILE:-/run/tattle-box.state}"   # remembers which interface got the hotspot, for box-down.sh; /run is emptied at boot

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

echo "--- network devices before:"
nmcli device status                                                # NetworkManager's view before anything is touched

# From here on, a failure cleans up after itself.
trap 'echo "box-up failed, cleaning up" >&2; bash "$(dirname "$0")/box-down.sh"' ERR

# --- interfaces: add one, then let NetworkManager choose which of the two keeps the normal Wi-Fi ---

dev_state() {                                                      # NetworkManager's state number for an interface: 100 connected, 30 idle and usable, 10 unmanaged; empty if not listed
  nmcli -g GENERAL.STATE device show "$1" 2>/dev/null | cut -d' ' -f1 || true
}
dev_connection() {                                                 # name of the profile active (or being activated) on an interface; empty if none
  local name
  name="$(nmcli -g GENERAL.CONNECTION device show "$1" 2>/dev/null || true)"
  [ "$name" = "--" ] && name=""                                    # some nmcli versions print "--" for "none"
  echo "$name"
}
at_least() {                                                       # is the interface's state number at least $2?
  local state
  state="$(dev_state "$1")"
  case "$state" in ''|*[!0-9]*) return 1 ;; *) [ "$state" -ge "$2" ] ;; esac
}
has_wifi() {                                                       # is the interface connected to a normal Wi-Fi (anything but our own hotspot)?
  local name
  name="$(dev_connection "$1")"
  [ "$(dev_state "$1")" = "100" ] && [ -n "$name" ] && [ "$name" != "$CON_NAME" ]
}

UPLINK_CON="$(dev_connection "$IFACE")"                            # the Wi-Fi the card is on right now (empty if none)

# Create the virtual access-point interface on the same card, with a MAC address of its own. With the
# card's own address (what it gets by default), NetworkManager refused it as "strictly unmanaged".
iw dev "$IFACE" interface add "$AP_IFACE" type __ap addr "$AP_MAC"

ap_managed() {                                                     # wait up to 10 s until NetworkManager manages the new interface
  for _ in $(seq 1 20); do
    at_least "$AP_IFACE" 11 && return 0                            # anything above 10 (unmanaged) means managed
    sleep 0.5
  done
  return 1
}

if ! ap_managed; then                                              # still unmanaged after 10 s
  nmcli device set "$AP_IFACE" managed yes || true                 # ask NetworkManager to take it, then wait once more
  if ! ap_managed; then
    echo "NetworkManager still lists $AP_IFACE as unmanaged, so the hotspot cannot start on it. Look at: nmcli device status" >&2
    false                                                          # stop here; the trap above cleans up
  fi
fi

# A new interface makes NetworkManager reshuffle: on our card it moves the normal Wi-Fi onto the new
# interface and frees the old one. Both layouts work, so we do not fight it. We wait until one of the
# two holds the normal Wi-Fi and has held it for 3 s while the other is free, and then use the other.
INET_IFACE=""                                                      # the interface that carries the normal Wi-Fi (the internet); decided here
if [ -n "$UPLINK_CON" ]; then
  steady=0
  for _ in $(seq 1 40); do                                         # up to 20 s
    holder=""; other="$AP_IFACE"
    if has_wifi "$IFACE"; then holder="$IFACE"; elif has_wifi "$AP_IFACE"; then holder="$AP_IFACE"; other="$IFACE"; fi
    if [ -n "$holder" ] && [ "$holder" = "$INET_IFACE" ] && at_least "$other" 30; then steady=$((steady + 1)); else steady=0; fi
    INET_IFACE="$holder"
    [ "$steady" -ge 6 ] && break                                   # same holder for 3 s, the other one usable: settled
    sleep 0.5
  done
  if [ -z "$INET_IFACE" ]; then
    echo "WARNING: after 20 s neither $IFACE nor $AP_IFACE is connected to the normal Wi-Fi (\"$UPLINK_CON\")." >&2
    echo "         Carrying on, but phones on the hotspot will have NO internet unless this laptop has another uplink." >&2
  fi
else
  echo "note: $IFACE was not connected to a Wi-Fi when this started. The hotspot's internet has to come from another" >&2
  echo "      uplink (for example a USB-tethered phone); without one, phones on the hotspot have no internet." >&2
fi

if [ "$INET_IFACE" = "$AP_IFACE" ]; then HOTSPOT_IFACE="$IFACE"; else HOTSPOT_IFACE="$AP_IFACE"; fi   # the hotspot goes on the one that does not hold the Wi-Fi
printf 'HOTSPOT_IFACE=%s\nINET_IFACE=%s\n' "$HOTSPOT_IFACE" "$INET_IFACE" > "$STATE_FILE"            # so box-down.sh knows which interface our rules name

# --- firewall: three own chains, so box-down.sh can remove exactly these rules ---

iptables -w -N TATTLE-IN                                                       # filter chain: what hotspot clients may send to the box itself
iptables -w -A TATTLE-IN -p udp --dport 67 -j ACCEPT                           # DHCP, so phones get an address
iptables -w -A TATTLE-IN -p udp --dport 53 -j ACCEPT                           # DNS to NetworkManager's own dnsmasq (only reached if the redirect below is removed)
iptables -w -A TATTLE-IN -p tcp --dport 53 -j ACCEPT                           # same, over TCP
iptables -w -A TATTLE-IN -p udp --dport "$SENSOR_PORT" -j ACCEPT               # DNS to the sensor
iptables -w -A TATTLE-IN -p tcp --dport "$SENSOR_PORT" -j ACCEPT               # same, over TCP
iptables -w -I INPUT 1 -i "$HOTSPOT_IFACE" -j TATTLE-IN                        # use that chain for everything arriving on the hotspot interface

iptables -w -t nat -N TATTLE-DNS                                               # nat chain: steer DNS to the sensor
iptables -w -t nat -A TATTLE-DNS -p udp --dport 53 -j REDIRECT --to-ports "$SENSOR_PORT"   # any UDP DNS, whatever server the phone aimed at
iptables -w -t nat -A TATTLE-DNS -p tcp --dport 53 -j REDIRECT --to-ports "$SENSOR_PORT"   # same for TCP DNS
iptables -w -t nat -I PREROUTING 1 -i "$HOTSPOT_IFACE" -j TATTLE-DNS           # apply it to everything arriving on the hotspot interface

iptables -w -N TATTLE-FWD                                                      # filter chain: what hotspot clients may not reach on the internet
iptables -w -A TATTLE-FWD -p tcp --dport 853 -j REJECT --reject-with tcp-reset # DNS-over-TLS: refuse fast, so phones fall back to plain DNS
iptables -w -A TATTLE-FWD -p udp --dport 853 -j REJECT                         # DNS-over-QUIC: same
iptables -w -A TATTLE-FWD -d "$VM_NET" -j REJECT                               # phones may not reach the VM network: the backend's API listens there
iptables -w -I FORWARD 1 -i "$HOTSPOT_IFACE" -j TATTLE-FWD                     # apply it to everything forwarded from the hotspot interface

# --- hotspot ---

# Start the hotspot on the free interface: 2.4 GHz (band bg), WPA2 password, DHCP and NAT by NetworkManager.
nmcli device wifi hotspot ifname "$HOTSPOT_IFACE" con-name "$CON_NAME" ssid "$SSID" password "$PASSWORD" band bg
nmcli connection modify "$CON_NAME" connection.autoconnect no      # the saved profile must not start by itself; box-down.sh deletes it

trap - ERR
echo "--- network devices after:"
nmcli device status                                                # NetworkManager's view now
echo
echo "HOTSPOT:  \"$SSID\" runs on $HOTSPOT_IFACE"
ip -4 -brief addr show "$HOTSPOT_IFACE"                            # expected: 10.42.0.1/24
if [ -n "$INET_IFACE" ] && has_wifi "$INET_IFACE"; then
  echo "INTERNET: the normal Wi-Fi (\"$(dev_connection "$INET_IFACE")\") is on $INET_IFACE"
elif [ -n "$INET_IFACE" ]; then
  echo "INTERNET: the normal Wi-Fi was on $INET_IFACE but is not connected at this moment. Look at the table above; it may need a few seconds."
else
  echo "INTERNET: neither $IFACE nor $AP_IFACE is on a Wi-Fi. Phones on the hotspot have NO internet unless this laptop has another uplink."
fi
echo "next: start the sensor (box/README.md). Phones have no DNS until the sensor runs."
echo "      (for the sensor's --names: --leases /var/lib/NetworkManager/dnsmasq-$HOTSPOT_IFACE.leases)"
