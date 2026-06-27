# rpi-wifi-led

Control one or more LEDs on a **Raspberry Pi Zero 2 W** GPIO from your **Mac or
PC over WiFi** — no internet required. The Pi runs a tiny web server; you open
its address in a browser to toggle each light, set brightness, and run effects
(blink / breathe / strobe). Each light is independent, with its own card.

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
lgpio's PWM, which is perfectly fine for LEDs. **Add more lights** by setting
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

It does four things: enables the systemd service (fills in your username/path
automatically), **disables WiFi power-save** (which otherwise drops the link
when idle), **pins a static IP** (`192.168.0.79` by default), and generates a
UTF-8 locale (silences SSH warnings). Override any of them:

```bash
STATIC_IP="" ./install-service.sh                # keep DHCP instead of static
LED_PINS=18,23,24 ./install-service.sh           # drive three lights
STATIC_IP=192.168.1.50/24 ./install-service.sh   # different fixed address
```

> The static IP defaults to `192.168.0.79/24` and auto-detects your gateway.
> If your network isn't `192.168.0.x`, pass your own `STATIC_IP`, or use
> `STATIC_IP=""` and instead set a DHCP reservation in your router. Revert to
> DHCP anytime: `sudo nmcli connection modify preconfigured ipv4.method auto`.

After reboot the server starts on every boot — just apply power and browse to
`http://192.168.0.79:5000`. Useful commands:

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

## API (if you want to script it)

Each light is addressed by id (`light1`, `light2`, …). Routes return that
light's state, e.g. `{"id": "light1", "name": "Light 1", "pin": 18,
"on": true, "brightness": 1.0, "effect": "none"}`.

| Method | Path                          | Body                       | Action            |
|--------|-------------------------------|----------------------------|-------------------|
| GET    | `/`                           | —                          | Control web page  |
| GET    | `/state`                      | —                          | Array of all lights |
| POST   | `/light/<id>/toggle`          | —                          | Flip on/off       |
| POST   | `/light/<id>/on`              | —                          | Turn on           |
| POST   | `/light/<id>/off`             | —                          | Turn off          |
| POST   | `/light/<id>/brightness`      | `{"value": 0.5}` (0.0–1.0) | Set brightness    |
| POST   | `/light/<id>/effect`          | `{"name": "blink"}`        | Run an effect     |

`effect` names: `none` (solid), `blink`, `breathe` (fade in/out), `strobe`.
Selecting an effect turns the light on; on/off/brightness return it to solid mode.

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
