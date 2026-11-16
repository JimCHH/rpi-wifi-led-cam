#!/usr/bin/env bash
# Relay the NeuroSwift USB IMU over WiFi (see README section 11).
# Plug the IMU into the Pi's USB port (through a hub if the camera is also
# connected), then run on the Pi from the repo dir:
#     ./setup-imu.sh
#
# Result: the IMU's lines are served, unchanged, on tcp://<pi>:4001. On the PC,
# a virtual COM port connected to that address gives the NS01-2 app a COM port
# that reads like the USB IMU.
#
# Optional overrides:
#   IMU_PORT=4001 ./setup-imu.sh                 # TCP port
#   IMU_DEV=/dev/ttyACM0 ./setup-imu.sh          # fixed device instead of auto-detect
#   IMU_DEV=sim ./setup-imu.sh                   # synthetic data, for testing without the IMU
set -euo pipefail

IMU_PORT="${IMU_PORT:-4001}"
IMU_DEV="${IMU_DEV:-auto}"
USER_NAME="$(id -un)"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT=/etc/systemd/system/imu-bridge.service

# The service user reads /dev/ttyACM* and /dev/ttyUSB*, which belong to dialout.
if ! id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx dialout; then
  echo "==> Adding '$USER_NAME' to the dialout group (serial devices)…"
  sudo usermod -aG dialout "$USER_NAME"
fi

chmod +x "$REPO_DIR/imu/imu-bridge.py"

echo "==> Installing imu-bridge.service (port $IMU_PORT, device $IMU_DEV)…"
sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Relay the NeuroSwift USB IMU over TCP (port $IMU_PORT)
After=network.target

[Service]
User=$USER_NAME
SupplementaryGroups=dialout
ExecStart=/usr/bin/python3 -u $REPO_DIR/imu/imu-bridge.py
Restart=always
RestartSec=3
Environment=IMU_PORT=$IMU_PORT
Environment=IMU_DEV=$IMU_DEV
# Serial reads and network writes ahead of the camera and web server.
Nice=-5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable imu-bridge.service >/dev/null
# restart (not just start) so re-running this after a git pull applies changes
sudo systemctl restart imu-bridge.service

# Add imu=<port> to the _nsn-cam._tcp announcement. Never fatal.
echo "==> Updating the DNS-SD announcement (imu=$IMU_PORT)…"
IMU_PORT="$IMU_PORT" "$REPO_DIR/setup-mdns.sh" >/dev/null \
  || echo "   (announcement not updated; run IMU_PORT=$IMU_PORT ./setup-mdns.sh later)"

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Done. The IMU stream is at  tcp://$IP:$IMU_PORT"
echo "On the PC, connect a virtual COM port to that address (README section 11),"
echo "then choose that COM port in the NS01-2 app."
echo
echo "Status:  systemctl status imu-bridge     Logs:  journalctl -u imu-bridge -f"
echo "Quick check from a Mac/PC:  nc $IP $IMU_PORT | head"
