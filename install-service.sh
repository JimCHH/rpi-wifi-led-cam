#!/usr/bin/env bash
# Install rpi-wifi-led as a systemd service AND apply the stability fixes so the
# Pi keeps a fixed address and stays connected. Run on the Pi:  ./install-service.sh
#
# Override any of these on the command line, e.g.:
#   STATIC_IP="" ./install-service.sh                 # keep DHCP (no static IP)
#   LED_PINS=18,23,24 ./install-service.sh            # drive three LEDs
#   STATIC_IP=192.168.0.79/24 WIFI_CONN=preconfigured ./install-service.sh
set -euo pipefail

# --- Config (override via environment) ---------------------------------------
LED_PINS="${LED_PINS:-18,23}"            # BCM pins, one per light
WIFI_CONN="${WIFI_CONN:-preconfigured}"  # NetworkManager connection name
STATIC_IP="${STATIC_IP:-192.168.0.79/24}" # set to "" to stay on DHCP
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

# --- Stability: pin a fixed IP so the address stops moving --------------------
if [ -n "$STATIC_IP" ]; then
  GW="$(ip route | awk '/default/{print $3; exit}')"
  echo "==> Setting static IP $STATIC_IP (gateway $GW) on '$WIFI_CONN'…"
  sudo nmcli connection modify "$WIFI_CONN" \
    ipv4.method manual ipv4.addresses "$STATIC_IP" \
    ipv4.gateway "$GW" ipv4.dns "$GW 8.8.8.8" || \
    echo "   (static IP not applied — revert anytime with: sudo nmcli connection modify $WIFI_CONN ipv4.method auto)"
fi

# --- Cosmetic: generate a UTF-8 locale so SSH stops warning -------------------
if ! locale -a 2>/dev/null | grep -qi 'en_US.utf8'; then
  echo "==> Generating en_US.UTF-8 locale…"
  sudo sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
  sudo locale-gen
  sudo update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
fi

echo
echo "Done. Reboot to apply the network changes:  sudo reboot"
echo "After reboot, open:  http://${STATIC_IP%%/*}:5000"
echo "Status:  systemctl status rpi-wifi-led   Logs:  journalctl -u rpi-wifi-led -f"
