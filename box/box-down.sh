#!/usr/bin/env bash
# ============================================================================
# UNTESTED. Written without access to the Wi-Fi hardware; never run so far.
# Read box/README.md first.
# ============================================================================
#
# Undoes box-up.sh: removes exactly its firewall chains, stops and deletes the
# hotspot profile, and removes the virtual interface. Safe to run twice: every
# step is attempted even if an earlier one finds nothing to remove.
#
# Usage: sudo bash box/box-down.sh

set -u                                 # unset variables are errors; failing steps do not stop the script

AP_IFACE=tattle0                       # virtual interface that carries the hotspot
CON_NAME=tattle-hotspot                # NetworkManager profile name of the hotspot

[ "$(id -u)" -eq 0 ] || { echo "run with sudo: removing interfaces and firewall rules needs root" >&2; exit 1; }

quiet() { "$@" >/dev/null 2>&1; }      # run a step, ignore "nothing to remove"

quiet iptables -w -D INPUT -i "$AP_IFACE" -j TATTLE-IN                 # stop using the input chain
quiet iptables -w -F TATTLE-IN                                         # empty it
quiet iptables -w -X TATTLE-IN                                         # delete it

quiet iptables -w -t nat -D PREROUTING -i "$AP_IFACE" -j TATTLE-DNS    # stop redirecting DNS to the sensor
quiet iptables -w -t nat -F TATTLE-DNS                                 # empty the chain
quiet iptables -w -t nat -X TATTLE-DNS                                 # delete it

quiet iptables -w -D FORWARD -i "$AP_IFACE" -j TATTLE-FWD              # stop rejecting port 853
quiet iptables -w -F TATTLE-FWD                                        # empty the chain
quiet iptables -w -X TATTLE-FWD                                        # delete it

quiet nmcli connection down "$CON_NAME"                                # stop the hotspot
quiet nmcli connection delete "$CON_NAME"                              # delete its saved profile (it holds the password)
quiet iw dev "$AP_IFACE" del                                           # remove the virtual interface

# Report anything that is still there.
left=0
iptables -w -S 2>/dev/null | grep -q TATTLE && { echo "filter rules still present: iptables -S | grep TATTLE" >&2; left=1; }
iptables -w -t nat -S 2>/dev/null | grep -q TATTLE && { echo "nat rules still present: iptables -t nat -S | grep TATTLE" >&2; left=1; }
iw dev "$AP_IFACE" info >/dev/null 2>&1 && { echo "$AP_IFACE still exists" >&2; left=1; }
[ "$left" -eq 0 ] && echo "box is down: firewall rules, hotspot profile and $AP_IFACE removed"
exit "$left"
