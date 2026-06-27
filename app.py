#!/usr/bin/env python3
"""
rpi-wifi-led — control one or more LEDs on a Raspberry Pi GPIO over WiFi.

Runs a tiny web server on the Pi. Open the Pi's IP address in any browser on
your Mac/PC (on the same network) to toggle each LED, set brightness, and run
effects. No internet connection is required — only a shared local network.

Lights are configured with the LED_PINS env var (comma-separated BCM pins);
default "18,23" drives two independent LEDs. Optional LED_NAMES gives them
friendly labels, e.g. LED_NAMES="Desk,Shelf".

Wiring (per LED): long leg (+) → 330Ω resistor → its GPIO pin; short leg (–) → GND.
    Light 1 default: GPIO18 (physical pin 12), GND pin 14.
    Light 2 default: GPIO23 (physical pin 16), GND pin 20 (or any GND).
GPIO18 supports hardware PWM; the others use lgpio's PWM, which is fine for LEDs.
"""
import os
from flask import Flask, jsonify, request, Response

# gpiozero is the modern, recommended GPIO library on Raspberry Pi OS.
# PWMLED lets us control brightness (0.0–1.0), not just on/off.
from gpiozero import PWMLED

# Effects map to gpiozero's built-in background animations. "none" = solid.
EFFECTS = ("none", "blink", "breathe", "strobe")

# Configure lights from the environment. BCM pin numbers, comma-separated.
PINS = [int(p) for p in os.environ.get("LED_PINS", "18,23").split(",") if p.strip()]
_names = [n.strip() for n in os.environ.get("LED_NAMES", "").split(",")]

# Build the light registry: id -> {led, name, pin, state}. `order` keeps the
# UI/JSON ordering stable (dicts preserve insertion order, but be explicit).
lights = {}
order = []
for i, pin in enumerate(PINS):
    lid = "light%d" % (i + 1)
    name = _names[i] if i < len(_names) and _names[i] else "Light %d" % (i + 1)
    lights[lid] = {
        "led": PWMLED(pin),
        "name": name,
        "pin": pin,
        # In-memory state so the UI can reflect values after a refresh.
        "state": {"on": False, "brightness": 1.0, "effect": "none"},
    }
    order.append(lid)

app = Flask(__name__)


def apply_state(light):
    """Push one light's state to its physical LED.

    For solid output we set led.value directly — its setter cancels any running
    blink/pulse thread. For effects we hand off to gpiozero's background
    animations (each call also stops the previous one).
    """
    led = light["led"]
    s = light["state"]
    if not s["on"] or s["effect"] == "none":
        led.value = s["brightness"] if s["on"] else 0.0
    elif s["effect"] == "blink":
        led.blink(on_time=0.5, off_time=0.5, background=True)
    elif s["effect"] == "strobe":
        led.blink(on_time=0.05, off_time=0.05, background=True)
    elif s["effect"] == "breathe":
        led.pulse(fade_in_time=1.0, fade_out_time=1.0, background=True)


def payload(lid):
    """JSON-serializable view of one light."""
    light = lights[lid]
    return {"id": lid, "name": light["name"], "pin": light["pin"], **light["state"]}


def all_payloads():
    return [payload(lid) for lid in order]


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pi WiFi LED</title>
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
  small { opacity: .6; }
</style>
</head>
<body>
  <h1>Raspberry Pi WiFi LED</h1>
  <div class="lights" id="lights"></div>
<script>
const container = document.getElementById('lights');
const EFFECTS = ['none', 'blink', 'breathe', 'strobe'];
const LABELS = {none: 'Solid', blink: 'Blink', breathe: 'Breathe', strobe: 'Strobe'};

function cardHtml(l) {
  return `
  <div class="card" data-id="${l.id}">
    <h2>${l.name} <small>GPIO ${l.pin}</small></h2>
    <div class="bulb">&#128161;</div>
    <div class="row"><button class="toggle">…</button></div>
    <div class="row">
      <label>Brightness</label>
      <input type="range" class="bright" min="0" max="100" value="100">
      <div><span class="pct">100</span>%</div>
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
  const solid = (l.effect || 'none') === 'none';
  br.disabled = !solid;
  const bulb = c.querySelector('.bulb');
  bulb.style.opacity = l.on ? (0.25 + 0.75 * l.brightness) : 0.15;
  bulb.style.filter = l.on ? 'none' : 'grayscale(1)';
  c.querySelectorAll('.effects button').forEach(b =>
    b.classList.toggle('active', l.on && b.dataset.fx === (l.effect || 'none')));
}

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
"""


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.route("/state")
def get_state():
    return jsonify(all_payloads())


def _get(lid):
    """Return the light or None (so routes can 404 cleanly)."""
    return lights.get(lid)


@app.route("/light/<lid>/toggle", methods=["POST"])
def toggle(lid):
    light = _get(lid)
    if not light:
        return jsonify({"error": "unknown light"}), 404
    light["state"]["on"] = not light["state"]["on"]
    light["state"]["effect"] = "none"
    apply_state(light)
    return jsonify(payload(lid))


@app.route("/light/<lid>/on", methods=["POST"])
def on(lid):
    light = _get(lid)
    if not light:
        return jsonify({"error": "unknown light"}), 404
    light["state"]["on"] = True
    light["state"]["effect"] = "none"
    apply_state(light)
    return jsonify(payload(lid))


@app.route("/light/<lid>/off", methods=["POST"])
def off(lid):
    light = _get(lid)
    if not light:
        return jsonify({"error": "unknown light"}), 404
    light["state"]["on"] = False
    light["state"]["effect"] = "none"
    apply_state(light)
    return jsonify(payload(lid))


@app.route("/light/<lid>/brightness", methods=["POST"])
def brightness(lid):
    light = _get(lid)
    if not light:
        return jsonify({"error": "unknown light"}), 404
    data = request.get_json(silent=True) or {}
    try:
        value = float(data.get("value"))
    except (TypeError, ValueError):
        return jsonify({"error": "value must be a number 0.0–1.0"}), 400
    s = light["state"]
    s["brightness"] = max(0.0, min(1.0, value))
    s["effect"] = "none"  # adjusting brightness implies solid output
    if s["brightness"] > 0:
        s["on"] = True
    apply_state(light)
    return jsonify(payload(lid))


@app.route("/light/<lid>/effect", methods=["POST"])
def effect(lid):
    light = _get(lid)
    if not light:
        return jsonify({"error": "unknown light"}), 404
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if name not in EFFECTS:
        return jsonify({"error": "name must be one of %s" % (EFFECTS,)}), 400
    light["state"]["effect"] = name
    light["state"]["on"] = True  # selecting an effect turns the light on
    apply_state(light)
    return jsonify(payload(lid))


if __name__ == "__main__":
    # host=0.0.0.0 makes the server reachable from other devices on the
    # network (your Mac/PC), not just localhost on the Pi itself.
    for lid in order:
        apply_state(lights[lid])
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
