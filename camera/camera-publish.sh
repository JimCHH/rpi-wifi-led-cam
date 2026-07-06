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
RTSP="${CAM_RTSP:-rtsp://localhost:8554/cam}"

echo "camera-publish: waiting for $DEV …"
until [ -e "$DEV" ]; do sleep 2; done
echo "camera-publish: $DEV present."

# Ask the camera what it actually supports, so we never request an unsupported
# mode (which makes v4l2 deliver "corrupted data").
FMTS="$(v4l2-ctl -d "$DEV" --list-formats-ext 2>/dev/null || true)"
AVAIL_SIZES="$(printf '%s\n' "$FMTS" | grep -oE '[0-9]+x[0-9]+' | sort -u)"
echo "camera-publish: $DEV advertises sizes: $(printf '%s ' $AVAIL_SIZES)"

# Choose the frame size: explicit CAM_SIZE > project presets (1280x480/400 if
# the camera has them) > the largest size the camera actually advertises.
choose_size() {
  if [ -n "${CAM_SIZE:-}" ]; then echo "$CAM_SIZE"; return; fi
  for s in 1280x480 1280x400; do
    printf '%s\n' "$AVAIL_SIZES" | grep -qx "$s" && { echo "$s"; return; }
  done
  local best="" area=0 w h a
  while read -r s; do
    [ -z "$s" ] && continue
    w=${s%x*}; h=${s#*x}; a=$(( w * h ))
    [ "$a" -gt "$area" ] && { area=$a; best=$s; }
  done <<< "$AVAIL_SIZES"
  echo "${best:-640x480}"
}
SIZE="$(choose_size)"

# Pick an input pixel format the camera offers (MJPEG allows higher fps on USB2).
if [ -n "${CAM_INPUT_FORMAT:-}" ]; then
  INPUT_FMT="$CAM_INPUT_FORMAT"
elif printf '%s' "$FMTS" | grep -qiE 'MJPG|Motion-JPEG'; then
  INPUT_FMT="mjpeg"
else
  INPUT_FMT="yuyv422"
fi

echo "camera-publish: STREAMING ${SIZE} @ ${FPS}fps  format=${INPUT_FMT}  ->  $RTSP"

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
