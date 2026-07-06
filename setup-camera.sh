#!/usr/bin/env bash
# Install MediaMTX + a camera publisher so the Pi streams a connected camera.
# Run on the Pi from the repo dir:  ./setup-camera.sh
#
# Result: whenever a camera is connected, the video is served at
#   HLS    (browser, reliable):  http://<pi>:8888/cam
#   WebRTC (browser, low-lat.):  http://<pi>:8889/cam
#   RTSP   (VLC / apps):         rtsp://<pi>:8554/cam
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing ffmpeg + v4l-utils…"
sudo apt update
sudo apt install -y ffmpeg v4l-utils curl tar

echo "==> Detecting CPU architecture for MediaMTX…"
case "$(uname -m)" in
  aarch64|arm64) MTX_ARCH=linux_arm64 ;;
  armv7l)        MTX_ARCH=linux_armv7 ;;
  armv6l)        MTX_ARCH=linux_armv6 ;;
  x86_64)        MTX_ARCH=linux_amd64 ;;
  *) echo "Unsupported arch $(uname -m)"; exit 1 ;;
esac

if ! command -v mediamtx >/dev/null 2>&1; then
  echo "==> Fetching MediaMTX ($MTX_ARCH)…"
  VER="$(curl -fsSL https://api.github.com/repos/bluenviron/mediamtx/releases/latest \
         | grep -oP '"tag_name":\s*"\K[^"]+' || true)"
  VER="${VER:-v1.11.3}"
  URL="https://github.com/bluenviron/mediamtx/releases/download/${VER}/mediamtx_${VER}_${MTX_ARCH}.tar.gz"
  echo "    $URL"
  curl -fsSL "$URL" -o /tmp/mediamtx.tar.gz
  sudo tar -xzf /tmp/mediamtx.tar.gz -C /usr/local/bin mediamtx
  sudo chmod +x /usr/local/bin/mediamtx
  rm -f /tmp/mediamtx.tar.gz
else
  echo "==> MediaMTX already installed ($(command -v mediamtx))."
fi

echo "==> Installing config + publisher script…"
sudo mkdir -p /usr/local/etc
sudo cp "$REPO_DIR/camera/mediamtx.yml" /usr/local/etc/mediamtx.yml
sudo cp "$REPO_DIR/camera/camera-publish.sh" /usr/local/bin/camera-publish.sh
sudo chmod +x /usr/local/bin/camera-publish.sh

echo "==> Installing systemd services…"
sudo tee /etc/systemd/system/mediamtx.service >/dev/null <<'EOF'
[Unit]
Description=MediaMTX media server
After=network.target

[Service]
ExecStart=/usr/local/bin/mediamtx /usr/local/etc/mediamtx.yml
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/camera-stream.service >/dev/null <<'EOF'
[Unit]
Description=Publish the camera to MediaMTX whenever it is connected
After=mediamtx.service
Wants=mediamtx.service

[Service]
ExecStart=/usr/local/bin/camera-publish.sh
Restart=always
RestartSec=3
# Optional overrides:
# Environment=CAM_DEV=/dev/video0
# Environment=CAM_SIZE=1280x480
# Environment=CAM_FPS=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now mediamtx.service camera-stream.service

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Done. Connect a camera, then view the stream:"
echo "  HLS    (reliable):  http://$IP:8888/cam"
echo "  WebRTC (low-lat.):  http://$IP:8889/cam"
echo "  RTSP   (VLC/apps):  rtsp://$IP:8554/cam"
echo
echo "Status:  systemctl status mediamtx camera-stream"
echo "Logs:    journalctl -u camera-stream -f"
