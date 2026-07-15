#!/usr/bin/env bash
# Install the WiFi-provisioning portal as a systemd service. It serves a page on
# PORTAL_PORT (default 8080) where you enter an SSID + password to save a network
# the Pi will join later — handy in hotspot mode to onboard a new location.
#
# Runs as root so nmcli can modify NetworkManager. Only expose it on a trusted /
# hotspot network: anyone who can reach the page can change the Pi's WiFi.
#
# Override the port:  PORTAL_PORT=8081 ./install-portal.sh
set -euo pipefail

PORTAL_PORT="${PORTAL_PORT:-8080}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing wifi-portal service (port $PORTAL_PORT, runs as root)…"
sudo tee /etc/systemd/system/wifi-portal.service >/dev/null <<EOF
[Unit]
Description=Pi WiFi provisioning portal
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
User=root
WorkingDirectory=$REPO_DIR
ExecStart=/usr/bin/python3 $REPO_DIR/wifi_portal.py
Restart=on-failure
RestartSec=3
Environment=PORTAL_PORT=$PORTAL_PORT

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now wifi-portal

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Done. Open the WiFi setup page at:"
echo "  http://$IP:$PORTAL_PORT       (or http://10.42.0.1:$PORTAL_PORT in hotspot mode)"
echo "Status:  systemctl status wifi-portal"
