#!/usr/bin/env bash
# Wait for the camera, then publish it to MediaMTX at the highest STABLE frame
# rate the hardware allows. Strategy (this is what makes high fps possible on a
# weak Pi):
#
#   * Camera outputs H.264 (onboard ISP)  -> STREAM-COPY it. No decode/encode on
#     the Pi, so fps is limited only by the camera + USB2 + WiFi, not the Pi's
#     CPU or hardware encoder. Best case for high fps, and browser-playable.
#   * Camera outputs MJPEG                 -> transcode to H.264 with the hardware
#     encoder (browser-playable, but capped by the encoder ~62 Mpix/s). Set
#     CAM_MODE=copy to pass MJPEG through untouched (higher fps, but RTSP-only —
#     browsers can't play MJPEG over HLS/WebRTC).
#   * Camera outputs only YUYV             -> transcode; USB2-bandwidth-limited.
#
# It auto-selects the highest fps the camera advertises for the chosen size.
#
# Overrides (Environment= in the service, or export before running):
#   CAM_DEV=/dev/video0
#   CAM_SIZE=1280x480            default: 1280x480/400 preset, else largest
#   CAM_FPS=60                   default: the camera's max at that size/codec
#   CAM_CODEC=h264|mjpeg|yuyv    default: auto (prefers h264, then mjpeg)
#   CAM_MODE=transcode|copy      mjpeg only; copy = passthrough (RTSP-only)
#   CAM_BITRATE=6M               transcode bitrate
#   CAM_RTSP=rtsp://localhost:8554/cam
set -uo pipefail

DEV="${CAM_DEV:-/dev/video0}"
RTSP="${CAM_RTSP:-rtsp://localhost:8554/cam}"
BITRATE="${CAM_BITRATE:-6M}"

echo "camera-publish: waiting for $DEV …"
until [ -e "$DEV" ]; do sleep 2; done
echo "camera-publish: $DEV present."

FMTS="$(v4l2-ctl -d "$DEV" --list-formats-ext 2>/dev/null || true)"
AVAIL_SIZES="$(printf '%s\n' "$FMTS" | grep -oE '[0-9]+x[0-9]+' | sort -u)"
echo "camera-publish: $DEV advertises sizes: $(printf '%s ' $AVAIL_SIZES)"

has_fmt() { printf '%s' "$FMTS" | grep -qiE "$1"; }

# Choose codec — auto prefers camera-native H.264 (zero-CPU passthrough).
CODEC="${CAM_CODEC:-auto}"
if [ "$CODEC" = auto ]; then
  if   has_fmt 'H264|H\.264';      then CODEC=h264
  elif has_fmt 'MJPG|Motion-JPEG'; then CODEC=mjpeg
  else                                  CODEC=yuyv
  fi
fi
case "$CODEC" in
  h264)  INPUT_FMT=h264;    PIXFMT=H264 ;;
  mjpeg) INPUT_FMT=mjpeg;   PIXFMT=MJPG ;;
  yuyv)  INPUT_FMT=yuyv422; PIXFMT=YUYV ;;
  *) echo "camera-publish: unknown CAM_CODEC=$CODEC"; exit 1 ;;
esac

# Choose size: explicit CAM_SIZE > presets (1280x480/400) > largest advertised.
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
W=${SIZE%x*}; H=${SIZE#*x}

# Choose fps: explicit CAM_FPS > the camera's max for this size+codec > 30.
choose_fps() {
  if [ -n "${CAM_FPS:-}" ]; then echo "$CAM_FPS"; return; fi
  local m
  m="$(v4l2-ctl -d "$DEV" --list-frameintervals=width="$W",height="$H",pixelformat="$PIXFMT" 2>/dev/null \
       | grep -oE '[0-9.]+ fps' | grep -oE '^[0-9.]+' | sort -nr | head -1)"
  [ -z "$m" ] && { echo 30; return; }
  printf '%.0f' "$m"
}
FPS="$(choose_fps)"

# Decide the encode strategy.
MODE="${CAM_MODE:-transcode}"
if [ "$CODEC" = h264 ]; then
  STRATEGY="copy (H.264 passthrough — no Pi transcode)"
  VENC=(-c:v copy)
elif [ "$CODEC" = mjpeg ] && [ "$MODE" = copy ]; then
  STRATEGY="copy (MJPEG passthrough — RTSP only, not HLS/WebRTC)"
  VENC=(-c:v copy)
elif ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_v4l2m2m; then
  STRATEGY="transcode -> H.264 (hardware)"
  VENC=(-c:v h264_v4l2m2m -b:v "$BITRATE" -pix_fmt yuv420p -g "$FPS")
else
  STRATEGY="transcode -> H.264 (software libx264)"
  VENC=(-c:v libx264 -preset ultrafast -tune zerolatency -b:v "$BITRATE" -pix_fmt yuv420p -g "$FPS")
fi

# --- Audio (microphone) ------------------------------------------------------
# CAM_AUDIO=auto|on|off (default auto: on if a capture device is found).
# CAM_ACODEC=aac (RTSP/HLS) | opus (also plays on the WebRTC player).
# CAM_ADEV overrides the ALSA device (e.g. plughw:1); else auto-detected.
AUDIO="${CAM_AUDIO:-auto}"
ACODEC="${CAM_ACODEC:-aac}"
ABITRATE="${CAM_ABITRATE:-128k}"
ADEV="${CAM_ADEV:-}"

if [ "$AUDIO" != "off" ] && [ -z "$ADEV" ]; then
  # arecord -l lists capture cards; take the first (usually the USB cam's mic).
  CARD="$(arecord -l 2>/dev/null | grep -oE '^card [0-9]+' | head -1 | grep -oE '[0-9]+')"
  [ -n "$CARD" ] && ADEV="plughw:${CARD}"
fi

if [ "$AUDIO" = "off" ] || [ -z "$ADEV" ]; then
  AUDIO_IN=(); MAP=(-map 0:v:0); AENC=(-an); ASTATE="off"
  echo "camera-publish: audio off (no capture device / CAM_AUDIO=off)"
else
  AUDIO_IN=(-f alsa -thread_queue_size 1024 -i "$ADEV")
  MAP=(-map 0:v:0 -map 1:a:0)
  case "$ACODEC" in
    opus) AENC=(-c:a libopus -b:a "$ABITRATE") ;;
    *)    AENC=(-c:a aac -b:a "$ABITRATE"); ACODEC="aac" ;;
  esac
  ASTATE="$ACODEC@$ADEV"
  echo "camera-publish: audio $ADEV -> $ACODEC @ $ABITRATE"
fi

echo "camera-publish: STREAMING ${SIZE} @ ${FPS}fps  codec=${CODEC}  audio=${ASTATE}  ${STRATEGY}  ->  $RTSP"

# Record the chosen mode so the LED dashboard can show the stream's fps/size.
printf '{"size":"%s","fps":%s,"codec":"%s","audio":"%s"}\n' "$SIZE" "$FPS" "$CODEC" "$ASTATE" \
  > "${CAM_INFO:-/dev/shm/rpi-cam-info}" 2>/dev/null || true

exec ffmpeg -hide_banner -loglevel warning -nostdin \
  -f v4l2 -input_format "$INPUT_FMT" -video_size "$SIZE" -framerate "$FPS" -i "$DEV" \
  "${AUDIO_IN[@]}" \
  "${MAP[@]}" "${VENC[@]}" "${AENC[@]}" \
  -f rtsp -rtsp_transport tcp "$RTSP"
