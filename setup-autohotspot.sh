#!/usr/bin/env bash
# Make the Pi fall back to its OWN WiFi hotspot when no known network is in
# range, so you can always reach it anywhere:
#     ssh pi@10.42.0.1        http://10.42.0.1:5000
#
# At every boot/check: if a known WiFi is in range it joins it (normal); if not,
# it starts a hotspot you can connect your Mac/PC to directly.
#
# Override the hotspot name/password:
#     HOTSPOT_SSID=PiLED HOTSPOT_PASS=raspberry ./setup-autohotspot.sh
set -euo pipefail

HOTSPOT_SSID="${HOTSPOT_SSID:-PiLED}"
HOTSPOT_PASS="${HOTSPOT_PASS:-raspberry}"   # must be >= 8 characters
HOTSPOT="Hotspot"

if [ "${#HOTSPOT_PASS}" -lt 8 ]; then
  echo "HOTSPOT_PASS must be at least 8 characters." >&2
  exit 1
fi

echo "==> Creating hotspot connection '$HOTSPOT' (SSID: $HOTSPOT_SSID)…"
if ! nmcli -t -f NAME connection show | grep -qxF "$HOTSPOT"; then
  sudo nmcli connection add type wifi ifname wlan0 con-name "$HOTSPOT" \
    autoconnect no ssid "$HOTSPOT_SSID" >/dev/null
fi
sudo nmcli connection modify "$HOTSPOT" \
  802-11-wireless.mode ap 802-11-wireless.band bg \
  ipv4.method shared \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$HOTSPOT_PASS" \
  802-11-wireless.ssid "$HOTSPOT_SSID" \
  connection.autoconnect no

echo "==> Installing decision script /usr/local/bin/pi-autohotspot.sh…"
sudo tee /usr/local/bin/pi-autohotspot.sh >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
# Join a known WiFi if one is in range; otherwise bring up our own hotspot.
set -uo pipefail
HOTSPOT="Hotspot"
IFACE="wlan0"

active=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null \
         | awk -F: -v i="$IFACE" '$2==i{print $1}')

# On a real network already (not the hotspot)? Nothing to do.
[ -n "$active" ] && [ "$active" != "$HOTSPOT" ] && exit 0

# Already serving the hotspot? Leave it up so connected clients aren't dropped.
# (To switch back to WiFi: `sudo systemctl restart pi-autohotspot` or reboot
# near a known network — we avoid scanning while the AP is live.)
[ "$active" = "$HOTSPOT" ] && exit 0

# Not connected to anything: is a known network in range?
nmcli device wifi rescan >/dev/null 2>&1 || true
sleep 3
visible=$(nmcli -t -f SSID device wifi list 2>/dev/null | sort -u)
known=$(nmcli -t -f NAME,TYPE connection show \
        | awk -F: '$2=="802-11-wireless"{print $1}' | grep -v "^${HOTSPOT}$")

match=""
while IFS= read -r conn; do
  [ -z "$conn" ] && continue
  ssid=$(nmcli -t -g 802-11-wireless.ssid connection show "$conn" 2>/dev/null)
  [ -z "$ssid" ] && ssid="$conn"
  if printf '%s\n' "$visible" | grep -qxF "$ssid"; then match="$conn"; break; fi
done <<< "$known"

if [ -n "$match" ]; then
  nmcli connection up "$match" >/dev/null 2>&1 || \
    nmcli connection up "$HOTSPOT" >/dev/null 2>&1 || true
else
  nmcli connection up "$HOTSPOT" >/dev/null 2>&1 || true
fi
SCRIPT
sudo chmod +x /usr/local/bin/pi-autohotspot.sh

echo "==> Installing systemd service + timer…"
sudo tee /etc/systemd/system/pi-autohotspot.service >/dev/null <<'EOF'
[Unit]
Description=Fall back to a WiFi hotspot when no known network is available
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 15
ExecStart=/usr/local/bin/pi-autohotspot.sh
EOF

sudo tee /etc/systemd/system/pi-autohotspot.timer >/dev/null <<'EOF'
[Unit]
Description=Periodic WiFi / hotspot fallback check

[Timer]
OnBootSec=25
OnUnitActiveSec=3min

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pi-autohotspot.timer

echo
echo "Done. From now on, at each boot/check:"
echo "  • Known WiFi in range -> joins it (normal operation)."
echo "  • No known WiFi       -> starts hotspot '$HOTSPOT_SSID' (password: $HOTSPOT_PASS)."
echo
echo "On the hotspot, connect your Mac to '$HOTSPOT_SSID', then:"
echo "  ssh pi@10.42.0.1      http://10.42.0.1:5000"
