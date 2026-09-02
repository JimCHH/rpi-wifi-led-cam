#!/usr/bin/env micropython
"""
Pico 2 W WiFi LED control — MicroPython port of the Raspberry Pi Flask app.

The Pico is a microcontroller, not a Linux computer: there is no OS, no
systemd, no Flask. This one file IS the whole program. Flash MicroPython
firmware once, copy this file onto the board as `main.py`, and it auto-runs
on every power-up — connecting to WiFi and serving a tiny web page you open
from any browser on the same network. No internet required.

It mirrors the Pi app's LED features: several independent lights, on/off,
brightness, effects (blink / breathe / strobe), a max-intensity safety cap,
and master "all lights" controls. Camera and battery are Pi-only and have no
equivalent here.

Wiring (per LED): long leg (+) -> 330Ohm resistor -> its GP pin;
                  short leg (-) -> any GND pin.
    Light 1 default: GP15 (physical pin 20)
    Light 2 default: GP16 (physical pin 21)
    GND: physical pin 23 (or 3, 8, 13, 18, 28, 38).
Every GPxx pin on the Pico can do PWM, so brightness works on any of them.
"""
import network
import time
import json
import uasyncio as asyncio
from machine import Pin, PWM

# --- Config ------------------------------------------------------------------
WIFI_SSID = "YOUR_SSID"          # 2.4GHz only — the Pico 2 W has no 5GHz radio
WIFI_PASSWORD = "YOUR_PASSWORD"
LED_PINS = [15, 16]              # GPxx numbers, one per independent light
LED_NAMES = ["Light 1", "Light 2"]
PWM_HZ = 1000                    # smooth, flicker-free
CAP_MIN = 0.01                   # safety-cap floor (1% of full brightness)
EFFECTS = ("none", "blink", "breathe", "strobe")
# -----------------------------------------------------------------------------

# Build the light registry: id -> {pwm, name, pin, state, task}.
lights = {}
order = []
for _i, _gp in enumerate(LED_PINS):
    _pwm = PWM(Pin(_gp))
    _pwm.freq(PWM_HZ)
    _pwm.duty_u16(0)
    _lid = "light%d" % (_i + 1)
    _name = LED_NAMES[_i] if _i < len(LED_NAMES) and LED_NAMES[_i] else "Light %d" % (_i + 1)
    lights[_lid] = {
        "pwm": _pwm,
        "name": _name,
        "pin": _gp,
        # cap = max-intensity ceiling (CAP_MIN..1.0); brightness scales within it.
        "state": {"on": False, "brightness": 1.0, "effect": "none", "cap": 1.0},
        "task": None,   # the running asyncio effect task, if any
    }
    order.append(_lid)


def _duty(pwm, frac):
    """Write a 0.0-1.0 brightness fraction to a PWM channel (16-bit duty)."""
    if frac < 0:
        frac = 0.0
    elif frac > 1:
        frac = 1.0
    pwm.duty_u16(int(frac * 65535))


def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return lo if v < lo else hi if v > hi else v


async def _effect(light):
    """Drive an effect in the background, peaking at the light's cap.

    Reads cap live each cycle so a cap change takes effect without a restart.
    Cancelled by apply_state() whenever the light's state changes.
    """
    s = light["state"]
    pwm = light["pwm"]
    try:
        while True:
            cap = s["cap"]
            eff = s["effect"]
            if eff == "blink":
                _duty(pwm, cap)
                await asyncio.sleep_ms(500)
                _duty(pwm, 0.0)
                await asyncio.sleep_ms(500)
            elif eff == "strobe":
                _duty(pwm, cap)
                await asyncio.sleep_ms(50)
                _duty(pwm, 0.0)
                await asyncio.sleep_ms(50)
            elif eff == "breathe":
                n = 40
                for i in list(range(n + 1)) + list(range(n, -1, -1)):
                    _duty(pwm, cap * i / n)
                    await asyncio.sleep_ms(25)
            else:
                break
    except asyncio.CancelledError:
        pass


def apply_state(light):
    """Push one light's state to its PWM channel, restarting any effect."""
    t = light["task"]
    if t:
        t.cancel()
        light["task"] = None
    s = light["state"]
    pwm = light["pwm"]
    if not s["on"]:
        _duty(pwm, 0.0)
    elif s["effect"] == "none":
        _duty(pwm, s["brightness"] * s["cap"])
    else:
        light["task"] = asyncio.create_task(_effect(light))


def payload(lid):
    light = lights[lid]
    return {"id": lid, "name": light["name"], "pin": light["pin"], **light["state"]}


def all_payloads():
    return [payload(lid) for lid in order]


PAGE = ("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pico W LED</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, -apple-system, sans-serif; max-width: 720px;
         margin: 32px auto; padding: 0 16px; text-align: center; }
  h1 { font-size: 1.4rem; }
  .lights { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }
  .card { border: 1px solid #8884; border-radius: 16px; padding: 16px 20px;
          width: 300px; box-sizing: border-box; }
  .card h2 { font-size: 1.1rem; margin: 0 0 8px; }
  .card h2 small { opacity: .55; font-weight: normal; }
  .bulb { font-size: 4rem; transition: opacity .15s, filter .15s; }
  button { font-size: 1.05rem; padding: 10px 22px; border: 0; border-radius: 12px;
           cursor: pointer; background: #2d7ff9; color: #fff; }
  button.off { background: #555; }
  input[type=range] { width: 100%; margin: 18px 0 4px; }
  .row { margin: 16px 0; }
  .effects { display: flex; gap: 6px; justify-content: center; flex-wrap: wrap; }
  .effects button { font-size: .85rem; padding: 7px 12px; background: #e6e6e6;
                    color: #222; }
  .effects button.active { background: #2d7ff9; color: #fff; }
  .master { border: 2px solid #2d7ff9; border-radius: 16px; padding: 12px 20px;
            max-width: 340px; margin: 0 auto 24px; }
  .master strong { display: block; margin-bottom: 6px; }
  small { opacity: .6; }
</style>
</head>
<body>
  <h1>Pico 2 W WiFi LED</h1>
  <div class="master">
    <strong>All lights</strong>
    <div class="row">
      <button id="all-on">All On</button>
      <button id="all-off" class="off">All Off</button>
    </div>
    <div class="row">
      <label>Brightness (all)</label>
      <input type="range" id="all-bright" min="0" max="100" value="100">
      <div><span id="all-pct">100</span>%</div>
    </div>
    <div class="row">
      <label>Max intensity (all)</label>
      <input type="range" id="all-cap" min="1" max="100" value="100">
      <div><span id="all-cappct">100</span>%</div>
    </div>
    <div class="row effects" id="all-effects">
      <button data-allfx="none">Solid</button>
      <button data-allfx="blink">Blink</button>
      <button data-allfx="breathe">Breathe</button>
      <button data-allfx="strobe">Strobe</button>
    </div>
  </div>
  <div class="lights" id="lights"></div>
<script>
const container = document.getElementById('lights');
const EFFECTS = ['none', 'blink', 'breathe', 'strobe'];
const LABELS = {none: 'Solid', blink: 'Blink', breathe: 'Breathe', strobe: 'Strobe'};

function cardHtml(l) {
  return `
  <div class="card" data-id="${l.id}">
    <h2>${l.name} <small>GP ${l.pin}</small></h2>
    <div class="bulb">&#128161;</div>
    <div class="row"><button class="toggle">…</button></div>
    <div class="row">
      <label>Brightness</label>
      <input type="range" class="bright" min="0" max="100" value="100">
      <div><span class="pct">100</span>%</div>
    </div>
    <div class="row">
      <label>Max intensity (safety cap)</label>
      <input type="range" class="cap" min="1" max="100" value="100">
      <div><span class="cappct">100</span>%</div>
    </div>
    <div class="row effects">
      ${EFFECTS.map(fx => `<button data-fx="${fx}">${LABELS[fx]}</button>`).join('')}
    </div>
  </div>`;
}

const card = id => container.querySelector(`.card[data-id="${id}"]`);

function bind(id) {
  const c = card(id);
  c.querySelector('.toggle').onclick = () => act(id, 'toggle');
  const br = c.querySelector('.bright');
  br.oninput = () => { c.querySelector('.pct').textContent = br.value; };
  br.onchange = () => act(id, 'brightness', {value: br.value / 100});
  const cap = c.querySelector('.cap');
  cap.oninput = () => { c.querySelector('.cappct').textContent = cap.value; };
  cap.onchange = () => act(id, 'cap', {value: cap.value / 100});
  c.querySelectorAll('.effects button').forEach(b =>
    b.onclick = () => act(id, 'effect', {name: b.dataset.fx}));
}

async function act(id, path, body) {
  const r = await fetch(`/light/${id}/${path}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined
  });
  update(await r.json());
}

function update(l) {
  const c = card(l.id);
  if (!c) return;
  const t = c.querySelector('.toggle');
  t.textContent = l.on ? 'Turn OFF' : 'Turn ON';
  t.className = 'toggle' + (l.on ? '' : ' off');
  const br = c.querySelector('.bright');
  br.value = Math.round(l.brightness * 100);
  c.querySelector('.pct').textContent = br.value;
  const cap = c.querySelector('.cap');
  cap.value = Math.round(l.cap * 100);
  c.querySelector('.cappct').textContent = cap.value;
  const solid = (l.effect || 'none') === 'none';
  br.disabled = !solid;
  const bulb = c.querySelector('.bulb');
  bulb.style.opacity = l.on ? (0.25 + 0.75 * l.brightness) : 0.15;
  bulb.style.filter = l.on ? 'none' : 'grayscale(1)';
  c.querySelectorAll('.effects button').forEach(b =>
    b.classList.toggle('active', l.on && b.dataset.fx === (l.effect || 'none')));
}

async function actAll(path, body) {
  const r = await fetch(`/all/${path}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined
  });
  (await r.json()).forEach(update);
}

document.getElementById('all-on').onclick = () => actAll('on');
document.getElementById('all-off').onclick = () => actAll('off');
const allBright = document.getElementById('all-bright');
allBright.oninput = () => { document.getElementById('all-pct').textContent = allBright.value; };
allBright.onchange = () => actAll('brightness', {value: allBright.value / 100});
const allCap = document.getElementById('all-cap');
allCap.oninput = () => { document.getElementById('all-cappct').textContent = allCap.value; };
allCap.onchange = () => actAll('cap', {value: allCap.value / 100});
document.querySelectorAll('#all-effects button').forEach(b =>
  b.onclick = () => actAll('effect', {name: b.dataset.allfx}));

async function load() {
  const states = await (await fetch('/state')).json();
  container.innerHTML = states.map(cardHtml).join('');
  states.forEach(l => bind(l.id));
  states.forEach(update);
}
load();
</script>
</body>
</html>
""").encode()


def _json(obj):
    return b"200 OK", b"application/json", json.dumps(obj).encode()


def route(method, path, body):
    """Return (status_bytes, content_type_bytes, body_bytes) for one request."""
    if path == "/":
        return b"200 OK", b"text/html", PAGE
    if path == "/state":
        return _json(all_payloads())

    data = {}
    if body:
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            data = {}
    seg = [p for p in path.split("/") if p]

    # /light/<id>/<action>
    if len(seg) == 3 and seg[0] == "light" and method == "POST":
        light = lights.get(seg[1])
        if not light:
            return b"404 Not Found", b"application/json", b'{"error":"unknown light"}'
        s = light["state"]
        action = seg[2]
        if action == "toggle":
            s["on"] = not s["on"]
            s["effect"] = "none"
        elif action == "on":
            s["on"] = True
            s["effect"] = "none"
        elif action == "off":
            s["on"] = False
            s["effect"] = "none"
        elif action == "brightness":
            s["brightness"] = _clamp(data.get("value"), 0.0, 1.0, s["brightness"])
            s["effect"] = "none"
            if s["brightness"] > 0:
                s["on"] = True
        elif action == "cap":
            s["cap"] = _clamp(data.get("value"), CAP_MIN, 1.0, s["cap"])
        elif action == "effect":
            name = data.get("name")
            if name not in EFFECTS:
                return b"400 Bad Request", b"application/json", b'{"error":"bad effect"}'
            s["effect"] = name
            s["on"] = True
        else:
            return b"404 Not Found", b"application/json", b'{"error":"unknown action"}'
        apply_state(light)
        return _json(payload(seg[1]))

    # /all/<action>
    if len(seg) == 2 and seg[0] == "all" and method == "POST":
        action = seg[1]
        if action == "on":
            for lid in order:
                lights[lid]["state"].update(on=True, effect="none")
        elif action == "off":
            for lid in order:
                lights[lid]["state"].update(on=False, effect="none")
        elif action == "brightness":
            v = _clamp(data.get("value"), 0.0, 1.0, None)
            if v is None:
                return b"400 Bad Request", b"application/json", b'{"error":"bad value"}'
            for lid in order:
                lights[lid]["state"].update(brightness=v, effect="none", on=v > 0)
        elif action == "cap":
            v = _clamp(data.get("value"), CAP_MIN, 1.0, None)
            if v is None:
                return b"400 Bad Request", b"application/json", b'{"error":"bad value"}'
            for lid in order:
                lights[lid]["state"].update(cap=v)
        elif action == "effect":
            name = data.get("name")
            if name not in EFFECTS:
                return b"400 Bad Request", b"application/json", b'{"error":"bad effect"}'
            for lid in order:
                lights[lid]["state"].update(effect=name, on=True)
        else:
            return b"404 Not Found", b"application/json", b'{"error":"unknown action"}'
        for lid in order:
            apply_state(lights[lid])
        return _json(all_payloads())

    return b"404 Not Found", b"text/plain", b"not found"


async def handle(reader, writer):
    """Serve one HTTP request (asyncio stream callback)."""
    try:
        line = await reader.readline()
        parts = line.split()
        if len(parts) < 2:
            return
        method = parts[0].decode()
        path = parts[1].decode().split("?", 1)[0]

        clen = 0
        while True:
            h = await reader.readline()
            if h == b"\r\n" or h == b"":
                break
            if h[:15].lower() == b"content-length:":
                try:
                    clen = int(h.split(b":", 1)[1].strip())
                except ValueError:
                    clen = 0
        body = await reader.readexactly(clen) if clen else b""

        status, ctype, resp = route(method, path, body)
        head = b"HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % (
            status, ctype, len(resp))
        writer.write(head)
        writer.write(resp)
        await writer.drain()
    except Exception as e:  # keep the server alive no matter what one client does
        print("request error:", e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("connecting to WiFi:", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(40):            # up to ~20 s
            if wlan.isconnected():
                break
            time.sleep(0.5)
    if not wlan.isconnected():
        raise RuntimeError("WiFi connect failed — check SSID/password (2.4GHz only)")
    return wlan.ifconfig()[0]


async def main():
    ip = connect_wifi()
    print("LED control ready:  http://%s/" % ip)
    for lid in order:
        apply_state(lights[lid])
    await asyncio.start_server(handle, "0.0.0.0", 80)
    while True:
        await asyncio.sleep(3600)


asyncio.run(main())
