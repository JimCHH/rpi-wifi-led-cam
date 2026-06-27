#!/usr/bin/env bash
# Teach the Pi another WiFi network so it auto-joins when in range. Run this for
# each place you'll take the Pi (home, office, phone hotspot, …) so you never
# get locked out when you move it.
#
# Usage:  ./add-wifi.sh "SSID" "PASSWORD"
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: $0 \"SSID\" \"PASSWORD\"" >&2
  exit 1
fi

SSID="$1"
PASS="$2"
CON="wifi-$SSID"

# Skip if a profile with this name already exists, otherwise create it.
if nmcli -t -f NAME connection show | grep -qxF "$CON"; then
  echo "==> Updating existing network '$SSID'…"
  sudo nmcli connection modify "$CON" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS"
else
  echo "==> Adding network '$SSID'…"
  sudo nmcli connection add type wifi con-name "$CON" ssid "$SSID" \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS" \
    connection.autoconnect yes >/dev/null
fi

echo "Done. The Pi will auto-join '$SSID' whenever it's in range."
echo "Saved WiFi networks:"
nmcli -t -f NAME,TYPE connection show \
  | awk -F: '$2=="802-11-wireless"{print "  - "$1}'
