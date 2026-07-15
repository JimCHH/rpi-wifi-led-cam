#!/usr/bin/env bash
# Install the WiFi-provisioning portal as a systemd service. It serves a page on
# PORTAL_PORT (default 8080) where you enter an SSID + password to save a network
# the Pi will join later — handy in hotspot mode to onboard a new location.
#
# Runs as root so nmcli can modify NetworkManager. It's protected by a shared
# passphrase (HTTP Basic Auth); still prefer to expose it only on your hotspot /
# trusted network.
#
# Overrides:  PORTAL_PORT=8081 PORTAL_PASSWORD=secret ./install-portal.sh
set -euo pipefail

PORTAL_PORT="${PORTAL_PORT:-8080}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENVFILE=/etc/rpi-wifi-portal.env

# Ask for a passphrase if not provided and we have a terminal.
if [ -z "${PORTAL_PASSWORD:-}" ] && [ -t 0 ]; then
  read -rsp "Set a portal passphrase (blank = no gate, not recommended): " PORTAL_PASSWORD
  echo
fi
if [ -z "${PORTAL_PASSWORD:-}" ]; then
  echo "!! No passphrase set — the portal will be UNPROTECTED."
fi

echo "==> Writing $ENVFILE (root-only)…"
sudo tee "$ENVFILE" >/dev/null <<EOF
PORTAL_PORT=$PORTAL_PORT
PORTAL_PASSWORD=$PORTAL_PASSWORD
EOF
sudo chmod 600 "$ENVFILE"   # keep the passphrase out of the world-readable unit

echo "==> Installing wifi-portal service (port $PORTAL_PORT, runs as root)…"
sudo tee /etc/systemd/system/wifi-portal.service >/dev/null <<EOF
[Unit]
Description=Pi WiFi provisioning portal
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
User=root
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENVFILE
ExecStart=/usr/bin/python3 $REPO_DIR/wifi_portal.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now wifi-portal

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Done. Open the WiFi setup page at:"
echo "  http://$IP:$PORTAL_PORT       (or http://10.42.0.1:$PORTAL_PORT in hotspot mode)"
echo "Log in with any username and your passphrase."
echo "Change the passphrase later: edit $ENVFILE then 'sudo systemctl restart wifi-portal'."
