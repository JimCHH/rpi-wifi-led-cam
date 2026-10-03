#!/usr/bin/env bash
# Announce the Pi on the network as a NeuroSwift camera + fixation light, so the
# NeuroSwift app can find it with one multicast question instead of knowing its
# name or address (DNS-SD service type _nsn-cam._tcp, via Avahi).
# Run on the Pi from the repo dir:  ./setup-mdns.sh   (install-service.sh runs it too)
#
# What it publishes (TXT record, version 1):
#   txtvers=1            format version of these keys
#   product=NeuroSwift
#   rtsp=8554            camera RTSP port   (see camera/mediamtx.yml)
#   stream=cam           camera stream name (see camera/mediamtx.yml)
#   hw=xx:xx:xx:xx:xx:xx hardware address of the WiFi interface
# The service port is the LED control server's port (PORT, default 5000).
#
# Optional overrides:
#   PORT=5000 RTSP_PORT=8554 STREAM=cam NET_IF=wlan0 ./setup-mdns.sh
#
# Check it from the Pi:   avahi-browse -rt _nsn-cam._tcp
# Check it from a Mac:    dns-sd -B _nsn-cam._tcp local.
set -euo pipefail

PORT="${PORT:-5000}"
RTSP_PORT="${RTSP_PORT:-8554}"
STREAM="${STREAM:-cam}"
NET_IF="${NET_IF:-wlan0}"
SERVICE_FILE=/etc/avahi/services/nsn-cam.service

# Hardware address of the interface the Pi normally uses; fall back to the first
# non-loopback interface if that one is absent (e.g. a wired-only Pi).
HW=""
if [ -r "/sys/class/net/$NET_IF/address" ]; then
  HW="$(cat "/sys/class/net/$NET_IF/address")"
else
  for d in /sys/class/net/*; do
    n="$(basename "$d")"
    [ "$n" = "lo" ] && continue
    HW="$(cat "$d/address" 2>/dev/null || true)"
    [ -n "$HW" ] && break
  done
fi
HW="$(printf '%s' "$HW" | tr 'A-F' 'a-f')"
case "$HW" in
  [0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]) ;;
  *) echo "   (no usable hardware address found; announcing without hw=)"; HW="" ;;
esac

echo "==> Installing Avahi (usually already present on Raspberry Pi OS)…"
sudo apt install -y avahi-daemon >/dev/null

echo "==> Announcing _nsn-cam._tcp on port $PORT (rtsp=$RTSP_PORT stream=$STREAM${HW:+ hw=$HW})"
HW_LINE=""
[ -n "$HW" ] && HW_LINE="    <txt-record>hw=$HW</txt-record>"
sudo tee "$SERVICE_FILE" >/dev/null <<EOF
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<!-- Written by setup-mdns.sh. Lets the NeuroSwift app find this Pi. -->
<service-group>
  <name replace-wildcards="yes">%h</name>
  <service>
    <type>_nsn-cam._tcp</type>
    <port>$PORT</port>
    <txt-record>txtvers=1</txt-record>
    <txt-record>product=NeuroSwift</txt-record>
    <txt-record>rtsp=$RTSP_PORT</txt-record>
    <txt-record>stream=$STREAM</txt-record>
$HW_LINE
  </service>
</service-group>
EOF

sudo systemctl enable --now avahi-daemon >/dev/null 2>&1 || true
# Avahi re-reads /etc/avahi/services on reload; restart if reload is not supported.
sudo systemctl reload avahi-daemon 2>/dev/null || sudo systemctl restart avahi-daemon

echo "Done. Check with:  avahi-browse -rt _nsn-cam._tcp"
