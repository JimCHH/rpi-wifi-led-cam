# rpi-wifi-led

Control an LED on a **Raspberry Pi Zero 2 W** GPIO from your **Mac or PC over WiFi** —
no internet required. The Pi runs a tiny web server; you open its address in a
browser and toggle the LED / set brightness.

> "Regardless the internet is available" → you don't need the *internet*, only a
> shared *local network* between the Pi and your computer. Two ways to get that
> are below (join your router, or make the Pi its own hotspot).

---

## 1. Hardware — where to attach the LED

You need: 1 LED, 1 resistor (**220 Ω – 330 Ω**), 2 jumper wires (and ideally a
breadboard).

The Pi Zero 2 W has the standard 40-pin header. Wire the LED to **GPIO18**:

```
 GPIO18 (BCM)  ───[ 330Ω resistor ]───►|─── GND
 physical pin 12                       LED        physical pin 14 (or 6, 9, 20…)
```

- **LED long leg (anode, +)** → through the **resistor** → **GPIO18 (physical pin 12)**
- **LED short leg (cathode, –, flat side)** → **GND (physical pin 14)**

The resistor can go on either leg; it just limits current so the LED doesn't burn out.

Pin reference (the corner with pin 1 is nearest the SD-card / micro-USB edge):

```
        3V3  (1) (2)  5V
      GPIO2  (3) (4)  5V
      GPIO3  (5) (6)  GND
      GPIO4  (7) (8)  GPIO14
        GND  (9) (10) GPIO15
     GPIO17 (11) (12) GPIO18   ← LED via resistor here (pin 12)
     GPIO27 (13) (14) GND      ← LED ground here (pin 14)
      ...
```

Why GPIO18? It supports **hardware PWM**, giving smooth, flicker-free brightness
control. (On/off works on any GPIO, but brightness is nicest on GPIO18.)

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
./setup.sh          # creates venv, installs deps
source venv/bin/activate
python app.py
```

<details>
<summary>…or do it manually instead of <code>setup.sh</code></summary>

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git
git clone https://github.com/jimchh/rpi-wifi-led.git
cd rpi-wifi-led
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```
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

## 6. Run automatically on boot (optional)

So you don't have to start `app.py` by hand each time:

```bash
sudo cp rpi-wifi-led.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rpi-wifi-led
```

Check it: `systemctl status rpi-wifi-led`. Edit the `User=`/paths in the
`.service` file if you didn't clone into `/home/pi/rpi-wifi-led`.

---

## API (if you want to script it)

All return the current state as JSON: `{"on": true, "brightness": 1.0}`.

| Method | Path           | Body                       | Action                |
|--------|----------------|----------------------------|-----------------------|
| GET    | `/`            | —                          | Control web page      |
| GET    | `/state`       | —                          | Current state         |
| POST   | `/toggle`      | —                          | Flip on/off           |
| POST   | `/on`          | —                          | Turn on               |
| POST   | `/off`         | —                          | Turn off              |
| POST   | `/brightness`  | `{"value": 0.5}` (0.0–1.0) | Set brightness        |

Example from your Mac/PC:

```bash
curl -X POST http://192.168.1.42:5000/on
curl -X POST http://192.168.1.42:5000/brightness -H 'Content-Type: application/json' -d '{"value":0.3}'
```

---

## Troubleshooting

- **Page won't load from Mac/PC:** confirm both devices are on the same network
  and you used the Pi's real IP (`hostname -I`). Port is `5000`.
- **`gpiozero`/`lgpio` errors:** make sure you're on Raspberry Pi OS Bookworm and
  installed `requirements.txt` inside the venv. On older OS versions use
  `RPi.GPIO` or `pigpio` as the backend instead.
- **LED never lights:** check the LED isn't reversed (long leg toward the
  resistor/GPIO18), and that the resistor is in series.
- **Change the pin:** set `LED_PIN` (BCM number), e.g. `LED_PIN=23 python app.py`.
