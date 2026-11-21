#!/usr/bin/env python3
"""Hand each camera frame's capture time to imu-bridge, so the app can time frames and IMU samples
on one clock (the Pi's CLOCK_MONOTONIC).

camera-publish.sh runs the capture ffmpeg with `-copyts` and `showinfo=checksum=0` ahead of the
frame-number strip it draws, and sends that ffmpeg's stderr here. With -copyts the v4l2 input keeps
the kernel's buffer time stamps, which are CLOCK_MONOTONIC (checked on the headset, 2026-11-21:
frame 0 at 418959.432 s between monotonic 418957.618 and 418961.953). For each showinfo line this
sends one UDP datagram "<n> <mono_us>" to imu-bridge (127.0.0.1:IMU_FRAME_PORT), which puts
"# frame <n> <mono_us>" in its synchronized output. n is showinfo's frame count, the number the strip
carries (the same filter chain counts both). Every other line is passed on to stderr (the journal).

Environment:
    IMU_FRAME_PORT  UDP port imu-bridge listens on, default 4003
"""
import os
import re
import socket
import sys

PORT = int(os.environ.get("IMU_FRAME_PORT", "4003"))
LINE = re.compile(rb"Parsed_showinfo.*?\bn:\s*(\d+)\s+pts:\s*-?\d+\s+pts_time:([0-9.]+)")
LOUD = re.compile(rb"\[(warning|error|fatal|panic)\]")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = ("127.0.0.1", PORT)
    sent = 0
    for raw in sys.stdin.buffer:
        m = LINE.search(raw)
        if m is None:
            # ffmpeg runs at info level for showinfo; only its warnings and errors go on to the
            # journal (showinfo's own per-frame detail lines would fill it at 30 lines a second).
            if LOUD.search(raw):
                sys.stderr.buffer.write(raw)
                sys.stderr.buffer.flush()
            continue
        n = int(m.group(1))
        mono_us = int(round(float(m.group(2)) * 1_000_000))
        try:
            sock.sendto(b"%d %d" % (n, mono_us), target)
            sent += 1
        except OSError:
            pass   # imu-bridge not running: the frames still stream


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
