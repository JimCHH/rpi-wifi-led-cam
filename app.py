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
import json
import threading
import urllib.request
from flask import Flask, jsonify, request, Response

try:
    import ups  # Waveshare UPS HAT battery reader (best-effort)
except Exception:  # pragma: no cover - never let this break the app
    ups = None

# gpiozero is the modern, recommended GPIO library on Raspberry Pi OS.
# PWMLED lets us control brightness (0.0–1.0), not just on/off.
from gpiozero import PWMLED

# Safety floor for the max-intensity cap: 0.01 == 1% of full brightness
# (below this, software PWM can't reliably light the LED anyway).
CAP_MIN = 0.01

# Effects map to gpiozero's built-in background animations. "none" = solid.
EFFECTS = ("none", "blink", "breathe", "strobe")

# Configure lights from the environment. BCM pin numbers, comma-separated.
PINS = [int(p) for p in os.environ.get("LED_PINS", "18,23").split(",") if p.strip()]
_names = [n.strip() for n in os.environ.get("LED_NAMES", "").split(",")]

# PWM frequency (Hz). 1000 Hz is smooth and flicker-free. Override with PWM_HZ.
PWM_HZ = int(os.environ.get("PWM_HZ", "1000"))

# Build the light registry: id -> {led, name, pin, state}. `order` keeps the
# UI/JSON ordering stable (dicts preserve insertion order, but be explicit).
lights = {}
order = []
for i, pin in enumerate(PINS):
    lid = "light%d" % (i + 1)
    name = _names[i] if i < len(_names) and _names[i] else "Light %d" % (i + 1)
    lights[lid] = {
        "led": PWMLED(pin, frequency=PWM_HZ),
        "name": name,
        "pin": pin,
        # In-memory state so the UI can reflect values after a refresh.
        # cap = max-intensity ceiling (0.0001–1.0); brightness scales within it.
        "state": {"on": False, "brightness": 1.0, "effect": "none", "cap": 1.0},
        "lock": threading.Lock(),     # serialize apply_state per light
        "stop": threading.Event(),    # signal the running effect thread to stop
        "thread": None,               # the running effect thread, if any
    }
    order.append(lid)

app = Flask(__name__)


def _stop_effect(light):
    """Stop a running effect thread and arm a fresh stop signal."""
    t = light["thread"]
    if t and t.is_alive():
        light["stop"].set()
        t.join(timeout=1.5)
    light["stop"] = threading.Event()
    light["thread"] = None


def _effect_loop(light, stop):
    """Drive an effect in the background, peaking at the light's cap.

    Reads cap live each cycle so a cap change takes effect without a restart.
    """
    led = light["led"]
    s = light["state"]
    while not stop.is_set():
        cap = s["cap"]
        eff = s["effect"]
        if eff == "blink":
            led.value = cap
            if stop.wait(0.5):
                break
            led.value = 0.0
            if stop.wait(0.5):
                break
        elif eff == "strobe":
            led.value = cap
            if stop.wait(0.05):
                break
            led.value = 0.0
            if stop.wait(0.05):
                break
        elif eff == "breathe":
            n = 40
            broke = False
            for i in list(range(n + 1)) + list(range(n, -1, -1)):
                led.value = cap * i / n
                if stop.wait(0.025):
                    broke = True
                    break
            if broke:
                break
        else:
            break


def apply_state(light):
    """Push one light's state to its physical LED.

    Output is gated by `cap` (the safety ceiling): solid output = brightness×cap,
    and effects peak at cap. Stops any running effect thread first.
    """
    with light["lock"]:
        _stop_effect(light)
        s = light["state"]
        led = light["led"]
        if not s["on"]:
            led.value = 0.0
        elif s["effect"] == "none":
            led.value = s["brightness"] * s["cap"]
        else:
            t = threading.Thread(
                target=_effect_loop, args=(light, light["stop"]), daemon=True)
            light["thread"] = t
            t.start()


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
  .master { border: 2px solid #2d7ff9; border-radius: 16px; padding: 12px 20px;
            max-width: 340px; margin: 0 auto 24px; }
  .master strong { display: block; margin-bottom: 6px; }
  .dash { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;
          margin: 0 auto 22px; }
  .stat { border: 1px solid #8884; border-radius: 12px; padding: 8px 16px;
          min-width: 90px; }
  .stat .k { font-size: .75rem; opacity: .6; text-transform: uppercase;
             letter-spacing: .04em; }
  .stat .v { font-size: 1.25rem; font-weight: 600; }
  .stat .v.warn { color: #e08a00; }
  .stat .v.crit { color: #e02d2d; }
  .camera { margin-top: 28px; }
  #camwrap { display: none; margin: 12px auto 6px; max-width: 640px; }
  #camframe { width: 100%; height: 380px; border: 0; border-radius: 12px;
              background: #000; }
  small { opacity: .6; }
</style>
</head>
<body>
  <h1>Raspberry Pi WiFi LED</h1>
  <div class="dash">
    <div class="stat"><div class="k">CPU</div><div class="v" id="s-cpu">–</div></div>
    <div class="stat"><div class="k">Temp</div><div class="v" id="s-temp">–</div></div>
    <div class="stat"><div class="k">Battery</div><div class="v" id="s-batt">–</div></div>
  </div>
  <div class="dash">
    <div class="stat"><div class="k">HLS</div><div class="v" id="s-hls">–</div></div>
    <div class="stat"><div class="k">WebRTC</div><div class="v" id="s-webrtc">–</div></div>
    <div class="stat"><div class="k">RTSP</div><div class="v" id="s-rtsp">–</div></div>
  </div>
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
  <div class="camera">
    <button id="camtoggle">📹 Show camera</button>
    <div id="camwrap"><iframe id="camframe" allow="autoplay; fullscreen"></iframe></div>
    <p><a id="camlink" target="_blank" rel="noopener">Open stream in new tab ↗</a></p>
  </div>
<script>
// Camera stream served by MediaMTX on the same host, port 8888 (HLS player).
const camBase = location.protocol + '//' + location.hostname + ':8888/cam';
document.getElementById('camlink').href = camBase;
const camtoggle = document.getElementById('camtoggle');
const camwrap = document.getElementById('camwrap');
const camframe = document.getElementById('camframe');
camtoggle.onclick = () => {
  const showing = camwrap.style.display === 'block';
  if (showing) {
    camframe.src = 'about:blank';           // stop the stream when hidden
    camwrap.style.display = 'none';
    camtoggle.textContent = '📹 Show camera';
  } else {
    camframe.src = camBase;                 // load only when the user asks
    camwrap.style.display = 'block';
    camtoggle.textContent = '📹 Hide camera';
  }
};

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

// Master controls: act on every light at once, then refresh all cards.
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

// System dashboard: poll CPU / temp / battery every 2s.
function setStat(id, text, cls) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = 'v' + (cls ? ' ' + cls : '');
}
async function pollStats() {
  let s;
  try { s = await (await fetch('/stats')).json(); } catch (e) { return; }
  setStat('s-cpu', s.cpu_percent == null ? '–' : s.cpu_percent + '%',
          s.cpu_percent >= 90 ? 'crit' : s.cpu_percent >= 70 ? 'warn' : '');
  setStat('s-temp', s.temp_c == null ? '–' : s.temp_c + '°C',
          s.temp_c >= 80 ? 'crit' : s.temp_c >= 70 ? 'warn' : '');
  const b = s.battery || {};
  const battEl = document.getElementById('s-batt');
  if (b.present) {
    setStat('s-batt', `${b.percent}%${b.charging ? ' ⚡' : ''} · ${b.voltage}V`,
            (!b.charging && b.percent <= 15) ? 'crit'
              : (!b.charging && b.percent <= 30) ? 'warn' : '');
    battEl.title = `${b.voltage} V, ${b.current_ma} mA`;
  } else {
    setStat('s-batt', 'n/a');
    battEl.title = b.reason || '';   // hover shows why (e.g. I2C off, no HAT)
  }
  // Per-protocol stream fps + viewer counts (same encoded stream on all three).
  const st = s.stream || {};
  const label = (n) => !st.publishing ? '–'
    : (st.fps != null ? st.fps + ' fps' : 'live') + (n ? ` · ${n}▸` : '');
  const p = st.protocols || {};
  setStat('s-hls', label(p.hls));
  setStat('s-webrtc', label(p.webrtc));
  setStat('s-rtsp', label(p.rtsp));
}
setInterval(pollStats, 2000);
pollStats();

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


# --- System dashboard (CPU / thermal / battery) ------------------------------
_prev_cpu = None


def cpu_percent():
    """CPU busy % since the previous call (from /proc/stat deltas)."""
    global _prev_cpu
    try:
        with open("/proc/stat") as f:
            vals = [int(x) for x in f.readline().split()[1:]]
    except Exception:
        return None
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
    total = sum(vals)
    prev = _prev_cpu
    _prev_cpu = (idle, total)
    if prev is None:
        return None
    d_total = total - prev[1]
    d_idle = idle - prev[0]
    if d_total <= 0:
        return None
    return round((1 - d_idle / d_total) * 100, 1)


def cpu_temp():
    """CPU temperature in °C, or None."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        return None


# Camera-publish writes the chosen mode here; MediaMTX's local API reports readers.
CAM_INFO = os.environ.get("CAM_INFO", "/dev/shm/rpi-cam-info")
MTX_API = os.environ.get("MTX_API", "http://127.0.0.1:9997")


def stream_stats():
    """Published fps + per-protocol viewer counts, from metadata only (no probing
    of the stream itself, so it doesn't affect video)."""
    info = {}
    try:
        with open(CAM_INFO) as f:
            info = json.load(f)
    except Exception:
        pass
    out = {
        "publishing": False,
        "fps": info.get("fps"),
        "size": info.get("size"),
        "codec": info.get("codec"),
        "protocols": {"hls": 0, "webrtc": 0, "rtsp": 0},
    }
    try:
        with urllib.request.urlopen(MTX_API + "/v3/paths/get/cam", timeout=0.5) as r:
            data = json.load(r)
        out["publishing"] = bool(data.get("ready"))
        for reader in data.get("readers", []):
            t = reader.get("type", "")
            if t == "hlsMuxer":
                out["protocols"]["hls"] += 1
            elif t == "webRTCSession":
                out["protocols"]["webrtc"] += 1
            elif t in ("rtspSession", "rtspsSession"):
                out["protocols"]["rtsp"] += 1
    except Exception:
        pass  # MediaMTX API off/unreachable — leave publishing False
    return out


@app.route("/stats")
def stats():
    battery = ups.read() if ups else {"present": False, "reason": "module missing"}
    return jsonify({
        "cpu_percent": cpu_percent(),
        "temp_c": cpu_temp(),
        "battery": battery,
        "stream": stream_stats(),
    })


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


@app.route("/light/<lid>/cap", methods=["POST"])
def cap(lid):
    light = _get(lid)
    if not light:
        return jsonify({"error": "unknown light"}), 404
    data = request.get_json(silent=True) or {}
    try:
        value = float(data.get("value"))
    except (TypeError, ValueError):
        return jsonify({"error": "value must be a number %s–1.0" % CAP_MIN}), 400
    light["state"]["cap"] = max(CAP_MIN, min(1.0, value))
    apply_state(light)
    return jsonify(payload(lid))


@app.route("/all/<action>", methods=["POST"])
def all_action(action):
    """Apply one action to every light at once (master controls)."""
    data = request.get_json(silent=True) or {}
    if action == "on":
        for lid in order:
            lights[lid]["state"].update(on=True, effect="none")
    elif action == "off":
        for lid in order:
            lights[lid]["state"].update(on=False, effect="none")
    elif action == "brightness":
        try:
            value = max(0.0, min(1.0, float(data.get("value"))))
        except (TypeError, ValueError):
            return jsonify({"error": "value must be a number 0.0–1.0"}), 400
        for lid in order:
            lights[lid]["state"].update(brightness=value, effect="none", on=value > 0)
    elif action == "effect":
        name = data.get("name")
        if name not in EFFECTS:
            return jsonify({"error": "name must be one of %s" % (EFFECTS,)}), 400
        for lid in order:
            lights[lid]["state"].update(effect=name, on=True)
    elif action == "cap":
        try:
            value = max(CAP_MIN, min(1.0, float(data.get("value"))))
        except (TypeError, ValueError):
            return jsonify({"error": "value must be a number %s–1.0" % CAP_MIN}), 400
        for lid in order:
            lights[lid]["state"].update(cap=value)
    else:
        return jsonify({"error": "unknown action"}), 404
    for lid in order:
        apply_state(lights[lid])
    return jsonify(all_payloads())


if __name__ == "__main__":
    # host=0.0.0.0 makes the server reachable from other devices on the
    # network (your Mac/PC), not just localhost on the Pi itself.
    for lid in order:
        apply_state(lights[lid])
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
