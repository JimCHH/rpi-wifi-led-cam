#!/usr/bin/env python3
"""Relay the NeuroSwift USB IMU over WiFi.

The IMU that the NS01-2 app normally reads on a Windows COM port is plugged into
the Pi's USB port instead. This program reads its serial lines and serves them,
unchanged, on a TCP port. On the PC, a virtual COM port driver connects a COM
port to that TCP port, and the app reads it exactly as it reads the USB IMU.

Line format (what the app's IMUData parser and IMU.TestPort accept):
    18 comma-separated decimal bytes, 0..255, ending in CR LF:
    accX hi,lo, accY hi,lo, accZ hi,lo, gyrX hi,lo, gyrY hi,lo, gyrZ hi,lo,
    magX hi,lo, magY hi,lo, magZ hi,lo
    (16-bit two's complement; 2048 LSB/g, 16.4 LSB per deg/s)
Any other line would become an all-zero sample in the app, so only lines in this
format are forwarded. Log output goes to stderr (the journal), never to clients.

Synchronized output (IMU_SYNC_PORT, default 4002), for receivers that need to
know when each sample was taken rather than when it arrived. The first line
names the format; every line after it is one IMU line with three fields before
the 18 tokens:
    # nsn-imu-sync 1 seq,mono_us,wall_us,<18 IMU tokens>
    seq      counts every line read from the IMU, including lines not forwarded,
             so a gap in seq means lines were skipped or dropped
    mono_us  Pi monotonic clock (CLOCK_MONOTONIC), microseconds; use it for the
             time between samples. It never jumps.
    wall_us  Pi wall clock (Unix time), microseconds; use it to line samples up
             with other streams. NTP can step it, so do not use it for dt.
Both are taken when the Pi reads the bytes from the USB serial device. Lines
that arrive in one read share one time stamp. Port 4001 is not changed by this.

Environment:
    IMU_DEV      serial device, "auto" (default) or "sim" (synthetic test data)
    IMU_BAUD     115200 (the app's rate)
    IMU_PORT     TCP port to serve on, default 4001
    IMU_SYNC_PORT  TCP port of the synchronized output, default 4002; 0 turns it off
    IMU_BIND     address to listen on, default 0.0.0.0
    IMU_SIM_HZ   sample rate of the synthetic source, default 145
"""
import glob
import math
import os
import queue
import select
import socket
import sys
import termios
import threading
import time

DEV = os.environ.get("IMU_DEV", "auto")
BAUD = int(os.environ.get("IMU_BAUD", "115200"))
PORT = int(os.environ.get("IMU_PORT", "4001"))
SYNC_PORT = int(os.environ.get("IMU_SYNC_PORT", "4002"))
BIND = os.environ.get("IMU_BIND", "0.0.0.0")
SIM_HZ = float(os.environ.get("IMU_SIM_HZ", "145"))

# About 2 s of samples per client. A client that falls further behind loses the
# oldest lines, so what it receives stays current.
CLIENT_QUEUE = 300
PROBE_SECONDS = 1.5          # how long auto-detect listens to each device
RESCAN_SECONDS = 2.0         # wait between scans while no IMU is connected

ACC_LSB_PER_G = 2048.0
GYRO_LSB_PER_DPS = 16.4

BAUD_CONST = {
    9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
    57600: termios.B57600, 115200: termios.B115200, 230400: termios.B230400,
}


_AXES = ["acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z", "mag_x", "mag_y", "mag_z"]
SYNC_HEADER = ("# nsn-imu-sync 1 seq,mono_us,wall_us,"
               + ",".join(f"{a}_{b}" for a in _AXES for b in ("hi", "lo")) + "\r\n").encode()


def stamp():
    """(monotonic us, wall-clock us), read together."""
    return time.monotonic_ns() // 1000, time.time_ns() // 1000


def log(msg):
    print(f"imu-bridge: {msg}", file=sys.stderr, flush=True)


# --- line format --------------------------------------------------------------

def valid_line(line):
    """True when `line` (bytes, no line ending) is 18 integers in 0..255."""
    parts = line.split(b",")
    if len(parts) != 18:
        return False
    for p in parts:
        if not p.isdigit() or int(p) > 255:
            return False
    return True


def encode(values):
    """Nine physical-unit raw counts -> the 18-token line the app expects.

    Counts are clamped to +-32767: the app treats only values above 32768 as
    negative, so -32768 (0x8000) would decode as +32768.
    """
    out = []
    for v in values:
        r = max(-32767, min(32767, int(round(v)))) & 0xFFFF
        out.append(str(r >> 8))
        out.append(str(r & 0xFF))
    return ",".join(out).encode()


# --- clients ------------------------------------------------------------------

class Clients:
    def __init__(self, name, header=None):
        self.name = name
        self._header = header          # sent once to each client on connect
        self._lock = threading.Lock()
        self._queues = {}

    def add(self, conn, addr):
        q = queue.Queue(maxsize=CLIENT_QUEUE)
        if self._header:
            q.put_nowait(self._header)
        with self._lock:
            self._queues[conn] = q
            n = len(self._queues)
        threading.Thread(target=self._writer, args=(conn, addr, q), daemon=True).start()
        log(f"{self.name} client connected: {addr[0]}:{addr[1]} ({n} total)")

    def _writer(self, conn, addr, q):
        dropped = 0
        try:
            while True:
                # One line per write (with TCP_NODELAY, one segment per line):
                # the app reads one line per serial receive event, so lines
                # that arrive together wait in its buffer.
                conn.sendall(q.get())
        except OSError:
            pass
        finally:
            with self._lock:
                self._queues.pop(conn, None)
                n = len(self._queues)
            try:
                conn.close()
            except OSError:
                pass
            log(f"{self.name} client disconnected: {addr[0]}:{addr[1]} ({n} left)")

    def send(self, line):
        with self._lock:
            targets = list(self._queues.values())
        for q in targets:
            try:
                q.put_nowait(line)
            except queue.Full:
                try:
                    q.get_nowait()          # drop the oldest line
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(line)
                except queue.Full:
                    pass

    def count(self):
        with self._lock:
            return len(self._queues)


class Outputs:
    """The app-compatible output and the synchronized output, fed together."""

    def __init__(self):
        self.raw = Clients("raw")
        self.sync = Clients("sync", SYNC_HEADER) if SYNC_PORT else None

    def publish(self, seq, line, mono_us, wall_us):
        self.raw.send(line + b"\r\n")
        if self.sync:
            self.sync.send(b"%d,%d,%d," % (seq, mono_us, wall_us) + line + b"\r\n")

    def count(self):
        return self.raw.count() + (self.sync.count() if self.sync else 0)


def serve(clients, port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((BIND, port))
    srv.listen(4)
    log(f"serving {clients.name} lines on tcp {BIND}:{port}")
    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)   # no batching delay
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        clients.add(conn, addr)


# --- serial source ------------------------------------------------------------

def open_serial(path):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        speed = BAUD_CONST.get(BAUD)
        if speed is None:
            raise ValueError(f"unsupported IMU_BAUD {BAUD}")
        attrs[0] = 0                                        # iflag: raw input
        attrs[1] = 0                                        # oflag: raw output
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL   # 8N1, no flow control
        attrs[3] = 0                                        # lflag: no echo, no canonical mode
        attrs[4] = speed
        attrs[5] = speed
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIFLUSH)
    except Exception:
        os.close(fd)
        raise
    return fd


def read_lines(fd, timeout=None):
    """Yield (line, mono_us, wall_us) for each complete line read from fd.

    The line is bytes without CR/LF. The time stamps are taken as soon as the
    read that completed the line returns. Stops when `timeout` seconds pass with
    no data. The first, possibly partial, line is discarded.
    """
    buf = b""
    synced = False
    while True:
        r, _, _ = select.select([fd], [], [], timeout if timeout is not None else 1.0)
        if not r:
            if timeout is not None:
                return
            continue
        chunk = os.read(fd, 4096)
        mono_us, wall_us = stamp()
        if not chunk:
            raise OSError("device closed")
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not synced:
                synced = True
                continue
            yield line.rstrip(b"\r"), mono_us, wall_us
        if len(buf) > 4096:              # no line ending in a long run: resync
            buf = b""
            synced = False


def candidates():
    found = sorted(glob.glob("/dev/serial/by-id/*"))
    real = {os.path.realpath(p) for p in found}
    for p in sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")):
        if p not in real:
            found.append(p)
    return found


def probe(path):
    """True when `path` sends IMU lines within PROBE_SECONDS."""
    try:
        fd = open_serial(path)
    except OSError as e:
        log(f"{path}: cannot open ({e})")
        return False
    try:
        deadline = time.monotonic() + PROBE_SECONDS
        for line, _, _ in read_lines(fd, timeout=PROBE_SECONDS):
            if valid_line(line):
                return True
            if time.monotonic() > deadline:
                return False
        return False
    except OSError:
        return False
    finally:
        os.close(fd)


def find_device():
    if DEV != "auto":
        return DEV if os.path.exists(DEV) else None
    for path in candidates():
        if probe(path):
            return path
    return None


def run_serial(out):
    waiting_logged = False
    seq = 0              # continues across reconnects, so receivers see one count
    while True:
        path = find_device()
        if not path:
            if not waiting_logged:
                log("waiting for the IMU" + ("" if DEV == "auto" else f" on {DEV}") + " ...")
                waiting_logged = True
            time.sleep(RESCAN_SECONDS)
            continue
        waiting_logged = False
        try:
            fd = open_serial(path)
        except OSError as e:
            log(f"{path}: cannot open ({e})")
            time.sleep(RESCAN_SECONDS)
            continue
        log(f"reading IMU on {path} at {BAUD} baud")
        seq = relay(fd, out, seq)
        os.close(fd)
        log(f"IMU on {path} stopped; scanning again")


class Stats:
    """Once a minute: line rate, skipped lines, and how fine the time stamps are."""

    def __init__(self):
        self.reset(time.monotonic())

    def reset(self, now):
        self.t0 = now
        self.good = self.bad = self.shared = 0
        self.max_gap_us = 0
        self.last_us = None

    def line(self, ok, mono_us):
        if ok:
            self.good += 1
        else:
            self.bad += 1
        if self.last_us is not None:
            gap = mono_us - self.last_us
            if gap == 0:
                self.shared += 1
            self.max_gap_us = max(self.max_gap_us, gap)
        self.last_us = mono_us

    def maybe_log(self, out):
        now = time.monotonic()
        if now - self.t0 < 60:
            return
        n = self.good + self.bad
        log(f"{self.good / (now - self.t0):.1f} lines/s, {self.bad} skipped, "
            f"time stamps: {100 * self.shared / max(n, 1):.0f}% shared with the previous line, "
            f"largest gap {self.max_gap_us / 1000:.1f} ms, {out.count()} client(s)")
        self.reset(now)


def relay(fd, out, seq=0):
    stats = Stats()
    try:
        # A connected IMU sends a line every few ms; 3 s of silence means it is gone.
        for line, mono_us, wall_us in read_lines(fd, timeout=3.0):
            seq += 1
            ok = valid_line(line)
            if ok:
                out.publish(seq, line, mono_us, wall_us)
            stats.line(ok, mono_us)
            stats.maybe_log(out)
    except OSError as e:
        log(f"read error: {e}")
    return seq


# --- synthetic source (testing without the IMU) -------------------------------

def run_sim(out):
    log(f"SIMULATED IMU at {SIM_HZ:g} Hz (IMU_DEV=sim); not for patient use")
    period = 1.0 / SIM_HZ
    nxt = time.monotonic()
    n = 0
    while True:
        t = n * period
        # Head still, gravity on +Z, a slow 20 deg/s yaw sway every 4 s.
        gyro_y = 20.0 * math.sin(2 * math.pi * t / 4.0)
        line = encode([0, 0, ACC_LSB_PER_G,
                       0, gyro_y * GYRO_LSB_PER_DPS, 0,
                       0, 0, 0])
        n += 1
        out.publish(n, line, *stamp())
        nxt += period
        delay = nxt - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        elif delay < -0.5:                # fell far behind: restart the clock
            nxt = time.monotonic()


def main():
    out = Outputs()
    threading.Thread(target=serve, args=(out.raw, PORT), daemon=True).start()
    if out.sync:
        threading.Thread(target=serve, args=(out.sync, SYNC_PORT), daemon=True).start()
    if DEV == "sim":
        run_sim(out)
    else:
        run_serial(out)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
