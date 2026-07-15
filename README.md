# rpi-wifi-led-cam

Control one or more LEDs on a **Raspberry Pi Zero 2 W** GPIO from your **Mac or
PC over WiFi** — no internet required — **and stream a connected camera** over
the network. The Pi runs a tiny web server; you open its address in a browser to
toggle each light, set brightness, and run effects (blink / breathe / strobe).
Each light is independent, with its own card. A connected camera is streamed via
[MediaMTX](https://github.com/bluenviron/mediamtx) (see [§9](#9-camera-streaming-mediamtx)).

> "Regardless the internet is available" → you don't need the *internet*, only a
> shared *local network* between the Pi and your computer. Two ways to get that
> are below (join your router, or make the Pi its own hotspot).

---

## 1. Hardware — where to attach the LED(s)

Per LED you need: 1 LED, 1 resistor (**220 Ω – 330 Ω**), 2 jumper wires (and
ideally a breadboard). The app drives **two independent lights by default**
(GPIO18 and GPIO23) — wire one or both.

The Pi Zero 2 W has the standard 40-pin header:

```
 Light 1: GPIO18 (pin 12) ──[ 330Ω ]──►|── GND (pin 14)
 Light 2: GPIO23 (pin 16) ──[ 330Ω ]──►|── GND (pin 20, or share a GND)
```

For each LED:
- **Long leg (anode, +)** → through the **resistor** → its **GPIO pin**
- **Short leg (cathode, –, flat side)** → **GND** (any ground pin; LEDs can
  share a common ground)

The resistor can go on either leg; it just limits current so the LED doesn't burn out.

Pin reference (the corner with pin 1 is nearest the SD-card / micro-USB edge):

```
        3V3  (1) (2)  5V
      GPIO2  (3) (4)  5V
      GPIO3  (5) (6)  GND
      GPIO4  (7) (8)  GPIO14
        GND  (9) (10) GPIO15
     GPIO17 (11) (12) GPIO18   ← Light 1 via resistor (pin 12)
     GPIO27 (13) (14) GND      ← Light 1 ground (pin 14)
     GPIO22 (15) (16) GPIO23   ← Light 2 via resistor (pin 16)
        3V3 (17) (18) GPIO24
     GPIO10 (19) (20) GND      ← Light 2 ground (pin 20)
      ...
```

GPIO18 supports **hardware PWM** (smoothest brightness); the other pins use
lgpio's PWM, which is perfectly fine for LEDs. PWM runs at **1000 Hz** by default
for flicker-free dimming — tune it with `PWM_HZ`. (Note: software PWM has a
minimum pulse width, so it can't render brightness much below ~1%; lower `PWM_HZ`
to reach dimmer, or use a larger series resistor to cap brightness in hardware.)
**Add more lights** by setting
`LED_PINS` (e.g. `LED_PINS=18,23,24`) and optional `LED_NAMES="Desk,Shelf,Lamp"`
— each gets its own card in the web UI. See `install-service.sh` to bake the
pin list into the autostart service.

---

## 2. First boot — get a terminal on the Pi (headless, from a Mac)

The Pi Zero 2 W has no easy keyboard/monitor port, so set it up **headless**
(over WiFi) and connect with SSH. You configure SSH + WiFi *while flashing the
SD card*, so the Pi joins your network and is reachable the moment it boots.

**a. Flash the card with Raspberry Pi Imager** (download from
raspberrypi.com/software):

1. **Choose Device:** Raspberry Pi Zero 2 W
2. **Choose OS:** Raspberry Pi OS (Lite is fine — no desktop needed)
3. **Choose Storage:** your SD card
4. Click **Next → "Edit Settings"** and set:
   - **Hostname:** `raspberrypi`
   - **Enable SSH** → *Use password authentication*
   - **Username:** `pi` · **Password:** something you'll remember
   - **Configure wireless LAN:** your WiFi **SSID + password**
   - **Wireless LAN country:** your country (the radio stays off until this is set)
5. **Save → Write**, then wait for it to finish and verify.

**b. Boot the Pi:** insert the card, plug power into the **PWR** micro-USB port
(the outer one). Wait **~60–90 seconds** on first boot (it expands the
filesystem and joins WiFi).

**c. SSH in from your Mac's Terminal:**

```bash
ssh pi@raspberrypi.local
```

Type `yes` to accept the host key the first time, then enter your password. The
prompt `pi@raspberrypi:~ $` means you're on the Pi. Run everything below here.

**If `raspberrypi.local` doesn't resolve**, the Pi probably isn't on WiFi yet,
or you need its IP. Find it from your router's device list, or scan:

```bash
ping raspberrypi.local        # works → name is fine
arp -a | grep -iE 'b8:27:eb|dc:a6:32|d8:3a:dd|e4:5f:01'   # common Pi MAC prefixes
```

Then `ssh pi@<that-ip>`.

---

## 3. Software — set up the Pi

Once you're SSH'd in, install everything with the helper script:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/jimchh/rpi-wifi-led.git
cd rpi-wifi-led
./setup.sh          # installs Flask + GPIO libs from apt (prebuilt)
python3 app.py
```

<details>
<summary>…or do it manually instead of <code>setup.sh</code></summary>

```bash
sudo apt update
sudo apt install -y git python3-flask python3-gpiozero python3-lgpio
git clone https://github.com/jimchh/rpi-wifi-led.git
cd rpi-wifi-led
python3 app.py
```

We use the **apt** packages (`python3-flask`, `python3-gpiozero`,
`python3-lgpio`) rather than `pip install` because they're prebuilt for the Pi —
no compiler, no virtualenv, nothing to build. `requirements.txt` is kept only
for reference / non-Pi setups; on the Pi, prefer apt.
</details>

You'll see `Running on http://0.0.0.0:5000`. Leave it running.

---

## 4. Connect from your Mac / PC

Find the Pi's IP address (run on the Pi):

```bash
hostname -I        # e.g. 192.168.1.42
```

On your Mac/PC (on the **same network**), open a browser to:

```
http://192.168.1.42:5000
```

You get a control page with an **on/off button** and a **brightness slider**.
That's it — clicking toggles the physical LED.

> Tip: if your network supports mDNS (Macs do by default), you can also use
> `http://raspberrypi.local:5000` instead of the IP.

---

## 5. Networking: make sure Pi + computer share a network

### Option A — Join your home WiFi router (simplest)

Put the Pi on the same WiFi as your Mac/PC. Easiest is to set this during
imaging with **Raspberry Pi Imager** (gear icon → enter WiFi SSID/password), or
edit it later with `sudo raspi-config` → *System Options* → *Wireless LAN*.

This works **even if the router has no internet** — only the LAN matters.

### Option B — Pi as its own WiFi hotspot (truly standalone, no router)

If there's no router at all, turn the Pi into an access point. Your Mac/PC then
connect directly to the Pi's WiFi, then browse to `http://10.42.0.1:5000`.

On Bookworm (which uses NetworkManager) this is a one-liner:

```bash
sudo nmcli device wifi hotspot ssid PiLED password ledled123 ifname wlan0
# Show/confirm the password later with:
sudo nmcli device wifi show-password
```

To make the hotspot come up automatically on boot:

```bash
sudo nmcli connection modify Hotspot connection.autoconnect yes
```

The Pi's address on its own hotspot is typically `10.42.0.1`, so browse to
`http://10.42.0.1:5000`. (Note: in hotspot mode the Pi's single WiFi radio
can't also be on your home WiFi — it's one or the other.)

---

## 6. Run automatically on boot + stay reachable

The helper installs the autostart service **and** applies the stability fixes
so the Pi keeps a fixed address and doesn't drop off WiFi:

```bash
./install-service.sh
sudo reboot          # applies the network changes
```

It does three things by default: enables the systemd service (fills in your
username/path automatically), **disables WiFi power-save** on your active
connection (which otherwise drops the link when idle), and generates a UTF-8
locale (silences SSH warnings). It **stays on DHCP** — roaming-friendly, so it's
safe to run at any location. Override anything:

```bash
LED_PINS=18,23,24 ./install-service.sh           # drive three lights
WIFI_CONN="MyWiFi" ./install-service.sh          # force a connection profile
STATIC_IP=192.168.1.50/24 ./install-service.sh   # opt in to a fixed IP (advanced)
```

> **Static IP is off by default on purpose.** A fixed address only works on the
> subnet it was set for, so pinning one and then moving the Pi to another network
> makes it unreachable. For a Pi that travels, stay on DHCP and find it via
> `raspberrypi.local`, your router's device list, or the `PiLED` hotspot. If you
> *do* want a fixed address on a permanent network, pass `STATIC_IP` (and prefer
> a DHCP reservation in your router). Revert anytime:
> `sudo nmcli connection modify <conn> ipv4.method auto`.

After reboot the server starts on every boot — just apply power and browse to
the Pi. Useful commands:

```bash
systemctl status rpi-wifi-led        # is it running?
journalctl -u rpi-wifi-led -f        # live logs
sudo systemctl restart rpi-wifi-led  # after editing app.py
sudo systemctl disable --now rpi-wifi-led   # turn autostart off
```

<details>
<summary>…or install it manually</summary>

```bash
sudo cp rpi-wifi-led.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rpi-wifi-led
```
Edit the `User=`/paths in the `.service` file if you didn't clone into
`/home/pi/rpi-wifi-led`.
</details>

---

## 7. Powering from a battery

The Pi Zero 2 W draws roughly (measured at 5 V):

| State | Current | Power |
|-------|---------|-------|
| Idle, headless, WiFi on | ~100–130 mA | ~0.5–0.65 W |
| This project (server idle + LED) | ~120–180 mA | ~0.6–0.9 W |
| Busy / WiFi active | ~200–300 mA | ~1.0–1.5 W |
| All 4 cores maxed | ~400–500 mA | ~2.0–2.5 W |

The LED through the 330 Ω resistor adds only ~4–10 mA. Plan around **~150 mA
average** for this project.

**Runtime estimate.** Power banks are rated at the 3.7 V cell, but you draw at
5 V through a ~85–90% efficient converter, so usable capacity at 5 V ≈
`rated mAh × ~0.65`. Runtime ≈ that ÷ average mA:

| Power bank | Usable @5 V | Runtime @~150 mA |
|------------|-------------|------------------|
| 5,000 mAh  | ~3,300 mAh  | ~22 h (≈1 day)   |
| 10,000 mAh | ~6,500 mAh  | ~43 h (≈2 days)  |
| 20,000 mAh | ~13,000 mAh | ~87 h (≈3.5 days)|

**Two gotchas:**

- Many power banks **auto-shut-off** when draw drops below ~50–100 mA — right
  where an idle Zero 2 W sits — so it may switch off on its own. Choose a bank
  with a "low-current / always-on" mode.
- Power the **PWR** micro-USB port (outer one) with a good-quality cable; thin
  cables sag and trigger low-voltage warnings.

For an always-on setup that recharges while running, use a UPS/battery HAT made
for the Zero footprint (e.g. **PiSugar 2/3**, **Waveshare UPS HAT**) instead of a
plain power bank — it powers the Pi, charges the cell, and cuts over cleanly.
Li-ion cells last ~300–500 charge cycles, so recharging every couple of days
gives years of service.

---

## 8. Take it anywhere: roaming + hotspot fallback

Moving the Pi to a new place with different WiFi does **not** require re-flashing
— you just teach it the new network, and it remembers all of them. Two helpers
make this painless.

### Add networks it should auto-join

Run this for each place (home, office, **your phone's hotspot**, …) while the Pi
is reachable. It then auto-joins whichever is in range:

```bash
./add-wifi.sh "NEW_SSID" "NEW_PASSWORD"
```

> Tip: add your **phone hotspot** as one of them. Anywhere you go, enable the
> hotspot, connect your Mac to it too, and `ssh pi@raspberrypi.local` — your
> phone becomes the shared network, so you're never locked out.

### Fall back to the Pi's own hotspot when no known WiFi exists

```bash
./setup-autohotspot.sh                                   # default SSID PiLED / pass raspberry
HOTSPOT_SSID=MyPi HOTSPOT_PASS=supersecret ./setup-autohotspot.sh   # custom
```

After this, at every boot/check:

- **A known WiFi is in range** → it joins normally.
- **No known WiFi** → it starts its **own hotspot**. Connect your Mac to that
  SSID, then reach it at **`ssh pi@10.42.0.1`** / **`http://10.42.0.1:5000`** —
  no router, no internet, works literally anywhere.

To switch back from hotspot mode to a known WiFi, reboot near that network (or
`sudo systemctl restart pi-autohotspot`) — the script avoids scanning while the
hotspot is live so it doesn't drop connected clients.

> Note on access while you're *away* from the Pi (different building): SSH/HTTP
> only need a **shared local network**, not the internet. To reach it remotely
> over the internet you'd add a VPN/tunnel such as Tailscale — out of scope here.

### WiFi setup page (onboard a network from your browser)

Instead of SSHing in to run `add-wifi.sh`, you can save networks from a web page —
ideal in **hotspot mode**: connect to the Pi's hotspot, open the page, and enter
the local WiFi's SSID + password for the Pi to join later.

```bash
./install-portal.sh                 # serves on port 8080 (override PORTAL_PORT)
```

Then browse to **`http://<pi>:8080`** (or `http://10.42.0.1:8080` on the hotspot).
It lists visible/saved networks, and **Save** adds the SSID+password as an
auto-connect profile — the Pi switches to it on the next auto-hotspot check or
reboot (or SSH in and `sudo nmcli connection up "wifi-<SSID>"` to switch now).

> It runs on its **own port (8080)**, separate from the LED app (5000). It runs
> as **root** (to change NetworkManager), so only expose it on your **hotspot /
> trusted network** — anyone who can reach it can change the Pi's WiFi. Stop it
> with `sudo systemctl disable --now wifi-portal` when not needed.

---

## 9. Camera streaming (MediaMTX)

Stream a connected camera (e.g. a USB stereo cam that outputs **1280×480** or
**1280×400** at **30 fps**) over the network using
[MediaMTX](https://github.com/bluenviron/mediamtx). Install it on the Pi:

```bash
cd ~/rpi-wifi-led
./setup-camera.sh
```

This installs MediaMTX + ffmpeg and two services:

- **`mediamtx`** — the media server (RTSP/HLS/WebRTC).
- **`camera-stream`** — waits for a camera, then publishes it. It **streams
  whenever a camera is connected**: if none is present it waits; if the camera is
  unplugged, ffmpeg stops and it goes back to waiting; replug and it resumes.

Then view the stream from your Mac/PC:

| Protocol | URL | Notes |
|----------|-----|-------|
| **HLS** | `http://<pi>:8888/cam` | Browser, most reliable on a LAN (~few s latency) |
| **WebRTC** | `http://<pi>:8889/cam` | Browser, low latency |
| **RTSP** | `rtsp://<pi>:8554/cam` | VLC / OBS / apps |

The LED control page has a **📹 Show camera** button that embeds the live stream
inline (plus an "open in new tab" link). The player loads only when you show it.

**Resolution / frame rate / codec.** It picks the size (presets **1280×480 →
1280×400**, else the camera's largest), then the **highest fps the camera
advertises** for that size, and a codec strategy tuned for **max stable fps**:

- **Camera outputs H.264** (onboard ISP) → **stream-copy, no transcode**. The Pi
  doesn't decode or encode, so fps is limited only by the camera + USB2 + WiFi —
  not the Pi's CPU or hardware encoder. This is how you get high fps on a Zero.
- **Camera outputs MJPEG** → transcode to H.264 with the hardware encoder
  (browser-playable, but capped by the encoder). `CAM_MODE=copy` passes MJPEG
  through untouched (higher fps, but RTSP-only — not HLS/WebRTC).
- **YUYV only** → transcode; limited by USB2 bandwidth.

The service log shows what it chose:

```
camera-publish: /dev/video0 advertises sizes: 320x240 640x480 1280x480
camera-publish: STREAMING 1280x480 @ 60fps  codec=h264  copy (H.264 passthrough — no Pi transcode)  ->  ...
```

Force any of it with `CAM_SIZE`, `CAM_FPS`, `CAM_CODEC` (`h264`/`mjpeg`/`yuyv`),
`CAM_MODE`, `CAM_BITRATE`.

Override per the `camera-stream.service` (or export before running the script):

```bash
sudo systemctl edit camera-stream      # add, e.g.:
# [Service]
# Environment=CAM_SIZE=1280x400
# Environment=CAM_FPS=30
sudo systemctl restart camera-stream
```

Encoding uses the Pi's **hardware H.264** (`h264_v4l2m2m`) when available, falling
back to software `libx264`. Useful commands:

```bash
systemctl status mediamtx camera-stream   # are they running?
journalctl -u camera-stream -f            # live camera/ffmpeg logs
v4l2-ctl --list-devices                   # confirm the camera is detected
v4l2-ctl -d /dev/video0 --list-formats-ext   # see supported sizes/rates
```

> **USB vs CSI:** this targets a **USB (UVC)** camera at `/dev/video0` (typical for
> 1280×480 stereo cams). For a **CSI ribbon** camera, capture with `rpicam-vid`
> piped into ffmpeg instead — ask and we'll add that variant.

---

## 10. Dashboard (CPU / thermal / battery)

The control page shows a small live dashboard (polled every 2 s) with:

- **CPU** — busy % (turns amber ≥70%, red ≥90%),
- **Temp** — SoC temperature in °C (amber ≥70 °C, red ≥80 °C — watch for throttling),
- **Battery** — from a **Waveshare UPS HAT** (INA219 over I2C): percentage, ⚡ when
  charging, and pack voltage. Shows `n/a` if no HAT / I2C is present (hover the
  tile to see why).
- **HLS / WebRTC / RTSP** — the stream's **fps** and live **viewer count** (`▸N`)
  per protocol. All three carry the *same* encoded stream, so the fps is the
  published source rate; they differ in latency/overhead, not frame rate. This is
  read from the encoder's chosen mode + MediaMTX's local API (metadata only) —
  **no probing of the video**, so it doesn't affect the stream.

`GET /stats` returns the same data as JSON:
```json
{"cpu_percent": 12.5, "temp_c": 54.2,
 "battery": {"present": true, "percent": 87, "voltage": 4.05, "current_ma": -320, "charging": false},
 "stream": {"publishing": true, "fps": 60, "size": "1280x480", "codec": "h264",
            "protocols": {"hls": 1, "webrtc": 0, "rtsp": 0}}}
```

> The per-protocol counts need the MediaMTX API (enabled in `camera/mediamtx.yml`);
> re-run `./setup-camera.sh` (or recopy the config and `sudo systemctl restart
> mediamtx`) after updating.

**Battery setup.** Tuned for the **Waveshare UPS HAT (C)** (the Pi Zero-sized
UPS, single Li-ion cell, INA219 @ `0x43`) — the defaults match its reference
driver, so it works out of the box. `./setup.sh` installs
`python3-smbus`/`i2c-tools` and enables I2C (reboot once to apply). Override via
env for other INA219 HATs:

```bash
sudo systemctl edit rpi-wifi-led     # add, e.g.:
# [Service]
# Environment=UPS_I2C_ADDR=0x42
# Environment=UPS_V_FULL=4.2
# Environment=UPS_V_EMPTY=3.0
# Environment=UPS_CURRENT_SIGN=-1   # if charging/discharging shows inverted
```

Confirm the HAT is on the bus with `i2cdetect -y 1` (look for `43`). CPU and temp
work with no extra hardware.

**Battery still `n/a`?** Hover the tile or `curl http://<pi>:5000/stats` to read
`battery.reason`, then:
- `smbus not installed` → run `./setup.sh` (installs `python3-smbus`).
- `[Errno 2] No such file or directory: '/dev/i2c-1'` → I2C not enabled; run
  `sudo raspi-config nonint do_i2c 0 && sudo reboot`.
- `[Errno 121] Remote I/O error` / wrong values → wrong address; check
  `i2cdetect -y 1` and set `UPS_I2C_ADDR`.
- `[Errno 13] Permission denied` → add the service user to the group:
  `sudo usermod -aG i2c $USER` then reboot.
- Restart after changes: `sudo systemctl restart rpi-wifi-led`.

---

## API (if you want to script it)

Each light is addressed by id (`light1`, `light2`, …). Routes return that
light's state, e.g. `{"id": "light1", "name": "Light 1", "pin": 18,
"on": true, "brightness": 1.0, "effect": "none"}`.

| Method | Path                          | Body                       | Action            |
|--------|-------------------------------|----------------------------|-------------------|
| GET    | `/`                           | —                          | Control web page  |
| GET    | `/state`                      | —                          | Array of all lights |
| GET    | `/stats`                      | —                          | CPU / temp / battery |
| POST   | `/light/<id>/toggle`          | —                          | Flip on/off       |
| POST   | `/light/<id>/on`              | —                          | Turn on           |
| POST   | `/light/<id>/off`             | —                          | Turn off          |
| POST   | `/light/<id>/brightness`      | `{"value": 0.5}` (0.0–1.0) | Set brightness    |
| POST   | `/light/<id>/effect`          | `{"name": "blink"}`        | Run an effect     |
| POST   | `/light/<id>/cap`             | `{"value": 0.5}` (0.01–1)  | Set max-intensity cap |
| POST   | `/all/on`                     | —                          | All lights on     |
| POST   | `/all/off`                    | —                          | All lights off    |
| POST   | `/all/brightness`             | `{"value": 0.5}` (0.0–1.0) | All brightness    |
| POST   | `/all/effect`                 | `{"name": "blink"}`        | Effect on all     |
| POST   | `/all/cap`                    | `{"value": 0.5}` (0.01–1)  | Cap on all        |

`effect` names: `none` (solid), `blink`, `breathe` (fade in/out), `strobe`.
Selecting an effect turns the light on; on/off/brightness return it to solid mode.
The `/all/*` routes apply to every light at once (the **All lights** bar in the
UI) and return the full array.

**Max-intensity cap (eye-safety).** Each light has a `cap` (0.01–1.0) that
ceilings its output: solid output = `brightness × cap`, and **effects also peak
at `cap`**. The UI exposes it as a **slider from 1% to 100%**, so you can dial the
maximum down (e.g. ~1%) when the LED is close to the eyes. Default is `1.0`
(100%, no limit).

Example from your Mac/PC:

```bash
curl -X POST http://192.168.0.79:5000/light/light1/on
curl -X POST http://192.168.0.79:5000/light/light2/brightness -H 'Content-Type: application/json' -d '{"value":0.3}'
curl -X POST http://192.168.0.79:5000/light/light1/effect -H 'Content-Type: application/json' -d '{"name":"breathe"}'
```

---

## Troubleshooting

- **Page won't load from Mac/PC:** confirm both devices are on the same network
  and you used the Pi's real IP (`hostname -I`). Port is `5000`.
- **`gpiozero`/`lgpio` errors:** make sure you're on Raspberry Pi OS and
  installed `requirements.txt` inside the venv. On older OS versions use
  `RPi.GPIO` or `pigpio` as the backend instead.
- **`error: command 'swig' failed` building `lgpio`:** on newer Raspberry Pi OS
  (Trixie / Python 3.13) `lgpio` compiles from source and needs build tools.
  Install them and retry:
  `sudo apt install -y swig python3-dev build-essential && pip install -r requirements.txt`
  (`setup.sh` already does this for you.)
- **LED never lights:** check the LED isn't reversed (long leg toward the
  resistor/GPIO18), and that the resistor is in series.
- **Change the pin:** set `LED_PIN` (BCM number), e.g. `LED_PIN=23 python app.py`.
