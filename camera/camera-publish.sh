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
#   CAM_SENSOR_FPS=210           MJPEG transcode only: run the camera at this rate but stream CAM_FPS
#                                (see "Sensor rate above the stream rate" below). Default: off.
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

# Will we re-encode, or stream-copy? (copy = camera-native H.264, or MJPEG
# passthrough). Transcoding goes through the Pi's H.264 encoder, which has a
# hard throughput ceiling; copy does not.
MODE="${CAM_MODE:-transcode}"
if [ "$CODEC" = h264 ] || { [ "$CODEC" = mjpeg ] && [ "$MODE" = copy ]; }; then
  TRANSCODE=0
else
  TRANSCODE=1
fi

# The camera's max advertised fps (e.g. 210) can far exceed what the Pi can
# *transcode* — feeding that to the H.264 encoder makes VIDIOC_STREAMON fail.
# So cap the transcode path to a stable rate. Passthrough/copy is never capped
# (it doesn't re-encode). Force any rate with CAM_FPS; raise the cap with
# CAM_FPS_MAX.
if [ "$TRANSCODE" = 1 ] && [ -z "${CAM_FPS:-}" ]; then
  FPS_MAX="${CAM_FPS_MAX:-30}"
  if [ "$FPS" -gt "$FPS_MAX" ]; then
    echo "camera-publish: capping transcode fps ${FPS} -> ${FPS_MAX} (encoder limit; CAM_FPS/CAM_FPS_MAX to override)"
    FPS="$FPS_MAX"
  fi
fi

# Decide the encode strategy (build VENC with the possibly-capped FPS).
if [ "$CODEC" = h264 ]; then
  STRATEGY="copy (H.264 passthrough — no Pi transcode)"
  VENC=(-c:v copy)
elif [ "$CODEC" = mjpeg ] && [ "$MODE" = copy ]; then
  STRATEGY="copy (MJPEG passthrough — RTSP only, not HLS/WebRTC)"
  VENC=(-c:v copy)
elif [ "${CAM_ENC:-hw}" != "sw" ] && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_v4l2m2m; then
  # Hardware encoder (low CPU). The Pi's h264_v4l2m2m emits non-monotonic DTS
  # that the RTSP muxer rejects, so we output a raw H.264 elementary stream
  # (no timestamps) and re-timestamp it in a 2nd ffmpeg (HW_PIPE below).
  STRATEGY="transcode -> H.264 (hardware, re-timestamped)"
  VENC=(-c:v h264_v4l2m2m -b:v "$BITRATE" -pix_fmt yuv420p -g "$FPS")
  HW_PIPE=1
else
  STRATEGY="transcode -> H.264 (software libx264)"
  VENC=(-c:v libx264 -preset ultrafast -tune zerolatency -b:v "$BITRATE" -pix_fmt yuv420p -g "$FPS")
fi

# Frame times for the app (CAM_FRAME_STAMP=1, the default; only when this Pi re-encodes, since a copied
# stream cannot be drawn on): the capture ffmpeg keeps the kernel's CLOCK_MONOTONIC frame times
# (-copyts), logs each frame's number and time (showinfo, no checksum, to frame-stamps.py, which hands
# them to imu-bridge) and draws the same number into the frame: a 16 px column at the picture's left
# edge (keep a receiver's own picture analysis clear of it), a white start block then 24 bits,
# 12 px each, least significant first, white = 1. Survives H.264 at the stream's bitrate (measured
# 2026-11-21: 337 of 337 frames decoded, ffmpeg CPU unchanged).
STAMP_VF=""
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "${CAM_FRAME_STAMP:-1}" = 1 ] && [ "${VENC[1]}" != copy ] && [ "$W" -ge 160 ] && [ "$H" -ge 312 ] \
   && [ -f "$DIR/frame-stamps.py" ]; then
  STAMP_VF="showinfo=checksum=0,drawbox=x=0:y=0:w=16:h=312:color=black:t=fill,drawbox=x=0:y=0:w=16:h=12:color=white:t=fill"
  k=0
  while [ $k -lt 24 ]; do
    STAMP_VF="$STAMP_VF,drawbox=x=0:y=$(( 12 + k * 12 )):w=16:h=12:color=white:t=fill:enable='mod(floor(n/pow(2\,$k))\,2)'"
    k=$((k+1))
  done
  STRATEGY="$STRATEGY, frame times"
fi
run_capture() {
  # The capture ffmpeg; with frame times, its stderr goes through frame-stamps.py.
  if [ -n "$STAMP_VF" ]; then
    ffmpeg -hide_banner -loglevel level+info -nostdin -copyts "$@" 2> >(python3 "$DIR/frame-stamps.py" >&2)
  else
    ffmpeg -hide_banner -loglevel warning -nostdin "$@"
  fi
}
VF=()
[ -n "$STAMP_VF" ] && VF=(-vf "$STAMP_VF")

# Sensor rate above the stream rate (CAM_SENSOR_FPS, off by default). Some cameras clock other hardware
# from their sensor's frame rate (a sensor on the same board samples once per exposure), so the stream's
# rate also sets that hardware's rate. With CAM_SENSOR_FPS the camera runs at that rate and a first
# ffmpeg keeps one compressed frame in every N (N = sensor rate / stream rate, rounded) BEFORE anything
# is decoded, so the decode and encode load stays that of the stream rate. MJPEG frames stand alone, so
# any of them can be left out. The kept frames keep their own capture times (nut carries them to the
# second ffmpeg), and the frame number counts kept frames only. Needs the MJPEG transcode path and an
# ffmpeg whose noise bitstream filter has the drop expression (5.1 or later); otherwise it is not used,
# with one line saying why. Not yet measured on a Pi: check CPU and temperature when turning it on.
SENSOR_FPS="${CAM_SENSOR_FPS:-}"
KEEP_EVERY=1
if [ -n "$SENSOR_FPS" ]; then
  if [ "$CODEC" != mjpeg ] || [ "$TRANSCODE" != 1 ]; then
    echo "camera-publish: CAM_SENSOR_FPS not used: it needs the MJPEG transcode path (codec=$CODEC)"
  elif ! ffmpeg -hide_banner -h bsf=noise 2>/dev/null | grep -q -- '-drop '; then
    echo "camera-publish: CAM_SENSOR_FPS not used: this ffmpeg's noise filter has no drop expression"
  else
    KEEP_EVERY=$(( (SENSOR_FPS + FPS / 2) / FPS ))
    if [ "$KEEP_EVERY" -lt 2 ]; then
      echo "camera-publish: CAM_SENSOR_FPS=$SENSOR_FPS is not above the stream's $FPS fps; not used"
      KEEP_EVERY=1
    else
      STRATEGY="$STRATEGY, sensor ${SENSOR_FPS}fps (1 frame in ${KEEP_EVERY} streamed)"
    fi
  fi
fi
# The capture's input: the camera itself, or (sensor rate above the stream rate) the thinned frames.
if [ "$KEEP_EVERY" -gt 1 ]; then
  # The thinned stream still declares the sensor's rate; without this the second ffmpeg would pad it back up
  # to that rate (measured on a synthetic 210 fps source: 629 frames encoded instead of 90).
  SRC=(-f nut -i - -fps_mode passthrough)
  thin_frames() {
    ffmpeg -hide_banner -loglevel warning -nostdin -copyts \
      -f v4l2 -input_format "$INPUT_FMT" -video_size "$SIZE" -framerate "$SENSOR_FPS" -i "$DEV" \
      -c:v copy -bsf:v "noise=drop='mod(n\,$KEEP_EVERY)'" -f nut -
  }
else
  SRC=(-f v4l2 -input_format "$INPUT_FMT" -video_size "$SIZE" -framerate "$FPS" -i "$DEV")
  thin_frames() { :; }
fi

echo "camera-publish: STREAMING ${SIZE} @ ${FPS}fps  codec=${CODEC}  ${STRATEGY}  ->  $RTSP"

# Record the chosen mode so the LED dashboard can show the stream's fps/size.
printf '{"size":"%s","fps":%s,"codec":"%s"}\n' "$SIZE" "$FPS" "$CODEC" \
  > "${CAM_INFO:-/dev/shm/rpi-cam-info}" 2>/dev/null || true

if [ "${HW_PIPE:-0}" = 1 ]; then
  # Stage 1: capture + hardware-encode to a raw H.264 stream (no container, so
  # the encoder's bad timestamps are dropped). Stage 2: assign fresh monotonic
  # timestamps at $FPS and copy (no re-encode) into RTSP. systemd's cgroup kill
  # stops both; `pipefail` (set above) surfaces either stage's failure.
  thin_frames | run_capture \
    "${SRC[@]}" \
    "${VF[@]}" "${VENC[@]}" -f h264 - \
  | ffmpeg -hide_banner -loglevel warning \
    -use_wallclock_as_timestamps 1 -f h264 -i - \
    -c:v copy -f rtsp -rtsp_transport tcp "$RTSP"
else
  thin_frames | run_capture \
    "${SRC[@]}" \
    "${VF[@]}" "${VENC[@]}" \
    -f rtsp -rtsp_transport tcp "$RTSP"
fi
