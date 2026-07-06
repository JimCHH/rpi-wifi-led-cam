#!/usr/bin/env bash
# Wait for the camera to be connected, then publish it to MediaMTX as H.264.
# Runs under systemd (camera-stream.service) with Restart=always, so:
#   - at boot it waits until the camera appears, then streams;
#   - if the camera is unplugged, ffmpeg exits, systemd restarts us, and we go
#     back to waiting — i.e. it streams whenever a camera is connected.
#
# Overrides (set as Environment= in the service, or export before running):
#   CAM_DEV=/dev/video0     camera device
#   CAM_SIZE=1280x480       frame size (default auto: prefer 1280x480 else 1280x400)
#   CAM_FPS=30              frame rate (30 or above)
#   CAM_INPUT_FORMAT=mjpeg  UVC pixel format (mjpeg gives 30fps at this size on USB2)
#   CAM_RTSP=rtsp://localhost:8554/cam   where to publish
set -uo pipefail

DEV="${CAM_DEV:-/dev/video0}"
FPS="${CAM_FPS:-30}"
INPUT_FMT="${CAM_INPUT_FORMAT:-mjpeg}"
RTSP="${CAM_RTSP:-rtsp://localhost:8554/cam}"

echo "camera-publish: waiting for $DEV …"
until [ -e "$DEV" ]; do sleep 2; done
echo "camera-publish: $DEV present."

# Pick the frame size: honour CAM_SIZE, else prefer 1280x480, fall back to
# 1280x400, based on what the camera actually advertises.
SIZE="${CAM_SIZE:-auto}"
if [ "$SIZE" = "auto" ]; then
  FMTS="$(v4l2-ctl -d "$DEV" --list-formats-ext 2>/dev/null || true)"
  SIZE="1280x480"
  for s in 1280x480 1280x400; do
    if printf '%s' "$FMTS" | grep -q "$s"; then SIZE="$s"; break; fi
  done
fi
echo "camera-publish: streaming $SIZE @ ${FPS}fps ($INPUT_FMT) -> $RTSP"

# Prefer the Pi's hardware H.264 encoder (offloads the CPU); fall back to
# software libx264 if it isn't available.
if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_v4l2m2m; then
  VENC=(-c:v h264_v4l2m2m -b:v 4M)
else
  VENC=(-c:v libx264 -preset ultrafast -tune zerolatency -b:v 4M)
fi

exec ffmpeg -hide_banner -loglevel warning -nostdin \
  -f v4l2 -input_format "$INPUT_FMT" -video_size "$SIZE" -framerate "$FPS" -i "$DEV" \
  "${VENC[@]}" -pix_fmt yuv420p -g "$FPS" \
  -f rtsp -rtsp_transport tcp "$RTSP"
