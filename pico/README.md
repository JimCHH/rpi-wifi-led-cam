# Pico 2 W — WiFi LED control

A MicroPython port of this repo's LED control, sized for the Raspberry Pi
**Pico 2 W** (RP2350). The Pico is a microcontroller, not a Linux computer —
there's no OS, Flask, or systemd. `main.py` **is** the whole program: it
connects to WiFi and serves a web page you open from any browser on the same
network. No internet required.

It mirrors the Pi app's LED features: multiple independent lights, on/off,
brightness, effects (blink / breathe / strobe), a max-intensity safety cap,
and master "all lights" controls. (Camera and battery are Pi-only.)

## What to burn onto the board

There are two layers, and only the first is literally "burned":

1. **MicroPython firmware** (a `.uf2` file) — flashed once:
   - Hold **BOOTSEL** while plugging the Pico into USB. It mounts as a USB
     drive named `RP2350`.
   - Download the **Pico 2 W** MicroPython build from
     <https://micropython.org/download/RPI_PICO2_W/> (must be the `_W` /
     RP2350 build — a plain Pico or Pico W image won't work).
   - Drag the `.uf2` onto the `RP2350` drive. It reboots into MicroPython.

2. **`main.py`** (this app) — copied onto the board's filesystem:
   - Open [Thonny](https://thonny.org/) → interpreter "MicroPython (Raspberry
     Pi Pico)".
   - Edit the config block at the top of `main.py` (`WIFI_SSID`,
     `WIFI_PASSWORD`, `LED_PINS`, `LED_NAMES`).
   - Save it to the Pico **as `main.py`** (File → Save as → Raspberry Pi Pico).
     MicroPython auto-runs a file named `main.py` on every power-up.

Reset or replug the board. Watch Thonny's shell for
`LED control ready:  http://<ip>/`, then open that URL.

## Wiring (per LED)

```
long leg (+) --[ 330Ω ]-- GPxx pin
short leg (-) ----------- GND
```

Defaults in `main.py`:

| Light | GP  | Physical pin |
|-------|-----|--------------|
| 1     | 15  | 20           |
| 2     | 16  | 21           |
| GND   | —   | 23 (or 3, 8, 13, 18, 28, 38) |

Every `GPxx` pin can do PWM, so brightness works on any pin you choose. Add
more lights by extending `LED_PINS` (e.g. `[15, 16, 17]`).

## Notes vs. the Raspberry Pi version

- **2.4 GHz only** — the Pico 2 W has no 5 GHz radio (same as the Pi Zero 2 W).
- Serves on **port 80**, so the URL is just `http://<ip>/` (no `:5000`).
- No fixed hostname like `raspberrypi.local`; find the IP from Thonny's shell
  or your router. For a stable address, reserve a DHCP lease on your router.
- The Pico runs this one file directly — "restart the service" becomes
  "reset the board." There's nothing to `apt install` and no venv.
