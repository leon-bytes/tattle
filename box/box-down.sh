#!/usr/bin/env bash
# ============================================================================
# Ran on the real card as the cleanup after a failed box-up, and worked.
# Taking down a hotspot that actually started has not been tried yet.
# Read box/README.md first.
# ============================================================================
#
# Undoes box-up.sh: removes exactly its firewall chains, stops and deletes the
# hotspot profile, and removes the virtual interface. Safe to run twice: every
# step is attempted even if an earlier one finds nothing to remove. It works
# with or without the state file box-up.sh leaves under /run.
#
# Usage: sudo bash box/box-down.sh

set -u                                 # unset variables are errors; failing steps do not stop the script

AP_IFACE=tattle0                       # the virtual interface box-up.sh added to the card
CON_NAME=tattle-hotspot                # NetworkManager profile name of the hotspot
STATE_FILE="${STATE_FILE:-/run/tattle-box.state}"   # where box-up.sh wrote which interface got the hotspot

[ "$(id -u)" -eq 0 ] || { echo "run with sudo: removing interfaces and firewall rules needs root" >&2; exit 1; }

quiet() { "$@" >/dev/null 2>&1; }      # run a step, ignore "nothing to remove"

drop_jumps() {                         # $1 table, $2 built-in chain, $3 our chain: delete every rule there that jumps to ours, whatever interface it names
  iptables -w -t "$1" -S "$2" 2>/dev/null | grep -- "-j $3\$" | while read -r _ rule; do   # "-A INPUT -i x -j TATTLE-IN" becomes "INPUT -i x -j TATTLE-IN"
    quiet iptables -w -t "$1" -D $rule                                                     # unquoted on purpose: the rule is several words
  done
}

HOTSPOT_IFACE="$(sed -n 's/^HOTSPOT_IFACE=//p' "$STATE_FILE" 2>/dev/null)"   # the interface our rules name; empty if the file is missing

if [ -n "$HOTSPOT_IFACE" ]; then                                           # the normal case: remove exactly the three rules box-up.sh added
  quiet iptables -w -D INPUT -i "$HOTSPOT_IFACE" -j TATTLE-IN              # stop using the input chain
  quiet iptables -w -t nat -D PREROUTING -i "$HOTSPOT_IFACE" -j TATTLE-DNS # stop redirecting DNS to the sensor
  quiet iptables -w -D FORWARD -i "$HOTSPOT_IFACE" -j TATTLE-FWD           # stop rejecting port 853 and the VM network
fi
drop_jumps filter INPUT TATTLE-IN                                          # without the state file, or if anything is left:
drop_jumps nat PREROUTING TATTLE-DNS                                       #   find the rules that point at our chains
drop_jumps filter FORWARD TATTLE-FWD                                       #   and remove them, whichever interface they name

quiet iptables -w -F TATTLE-IN                                             # empty the input chain
quiet iptables -w -X TATTLE-IN                                             # delete it
quiet iptables -w -t nat -F TATTLE-DNS                                     # empty the redirect chain
quiet iptables -w -t nat -X TATTLE-DNS                                     # delete it
quiet iptables -w -F TATTLE-FWD                                            # empty the forward chain
quiet iptables -w -X TATTLE-FWD                                            # delete it

quiet nmcli connection down "$CON_NAME"                                    # stop the hotspot
quiet nmcli connection delete "$CON_NAME"                                  # delete its saved profile (it holds the password)
quiet iw dev "$AP_IFACE" del                                               # remove the virtual interface; if it carried the normal Wi-Fi, NetworkManager reconnects on the real one
rm -f "$STATE_FILE"                                                        # forget which interface had the hotspot

# Report anything that is still there.
left=0
iptables -w -S 2>/dev/null | grep -q TATTLE && { echo "filter rules still present: iptables -S | grep TATTLE" >&2; left=1; }
iptables -w -t nat -S 2>/dev/null | grep -q TATTLE && { echo "nat rules still present: iptables -t nat -S | grep TATTLE" >&2; left=1; }
iw dev "$AP_IFACE" info >/dev/null 2>&1 && { echo "$AP_IFACE still exists" >&2; left=1; }
[ "$left" -eq 0 ] && echo "box is down: firewall rules, hotspot profile and $AP_IFACE removed"
[ "$left" -eq 0 ] && [ -n "$HOTSPOT_IFACE" ] && [ "$HOTSPOT_IFACE" != "$AP_IFACE" ] && echo "the normal Wi-Fi was on $AP_IFACE: give NetworkManager a few seconds to reconnect it on $HOTSPOT_IFACE"
exit "$left"
