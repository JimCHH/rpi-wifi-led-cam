#!/usr/bin/env bash
# Install rpi-wifi-led as a systemd service AND apply the stability fixes.
# Roaming-friendly by default: stays on DHCP and auto-detects your active WiFi
# connection, so it's safe to run at any location. Run on the Pi:
#     ./install-service.sh
#
# Optional overrides:
#   LED_PINS=18,23,24 ./install-service.sh           # drive more lights
#   WIFI_CONN="MyWiFi" ./install-service.sh          # force a connection profile
#   STATIC_IP=192.168.1.50/24 ./install-service.sh   # pin a fixed IP (advanced)
set -euo pipefail

# --- Config (override via environment) ---------------------------------------
LED_PINS="${LED_PINS:-18,23}"            # BCM pins, one per light
# Auto-detect the active wlan0 connection so power-save is disabled on the right
# profile. Falls back to "preconfigured" (the Imager default) if none is active.
WIFI_CONN="${WIFI_CONN:-$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null \
            | awk -F: '$2=="wlan0"{print $1; exit}')}"
WIFI_CONN="${WIFI_CONN:-preconfigured}"
STATIC_IP="${STATIC_IP:-}"               # empty = DHCP (recommended for roaming)
# -----------------------------------------------------------------------------

USER_NAME="$(id -un)"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT=/etc/systemd/system/rpi-wifi-led.service

echo "==> Installing service for user '$USER_NAME' from $REPO_DIR (LED_PINS=$LED_PINS)"
sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Raspberry Pi WiFi LED control server
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$REPO_DIR
ExecStart=/usr/bin/python3 $REPO_DIR/app.py
Restart=on-failure
RestartSec=3
Environment=LED_PINS=$LED_PINS
Environment=PORT=5000

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now rpi-wifi-led

# --- Stability: stop WiFi power-save dropping the link when idle --------------
echo "==> Disabling WiFi power-save on '$WIFI_CONN'…"
sudo nmcli connection modify "$WIFI_CONN" 802-11-wireless.powersave 2 || \
  echo "   (couldn't modify '$WIFI_CONN' — check name with: nmcli connection show)"

# --- Optional: pin a fixed IP (OFF by default) -------------------------------
# A static IP is only valid on the subnet it was set for, so moving the Pi to
# another network would make it unreachable. Left on DHCP unless you opt in.
if [ -n "$STATIC_IP" ]; then
  GW="$(ip route | awk '/default/{print $3; exit}')"
  echo "==> Setting static IP $STATIC_IP (gateway $GW) on '$WIFI_CONN'…"
  echo "    NOTE: revert anytime with: sudo nmcli connection modify '$WIFI_CONN' ipv4.method auto"
  sudo nmcli connection modify "$WIFI_CONN" \
    ipv4.method manual ipv4.addresses "$STATIC_IP" \
    ipv4.gateway "$GW" ipv4.dns "$GW 8.8.8.8" || echo "   (static IP not applied)"
else
  echo "==> Staying on DHCP (roaming-friendly). Find the Pi via 'raspberrypi.local'"
  echo "    or your router's device list."
fi

# --- Cosmetic: generate a UTF-8 locale so SSH stops warning -------------------
if ! locale -a 2>/dev/null | grep -qi 'en_US.utf8'; then
  echo "==> Generating en_US.UTF-8 locale…"
  sudo sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
  sudo locale-gen
  sudo update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
fi

IP_NOW="$(hostname -I | awk '{print $1}')"
echo
echo "Done. Reboot to apply the WiFi power-save change:  sudo reboot"
if [ -n "$STATIC_IP" ]; then
  echo "After reboot, open:  http://${STATIC_IP%%/*}:5000"
else
  echo "Open:  http://${IP_NOW}:5000   (or http://raspberrypi.local:5000)"
fi
echo "Status:  systemctl status rpi-wifi-led   Logs:  journalctl -u rpi-wifi-led -f"
