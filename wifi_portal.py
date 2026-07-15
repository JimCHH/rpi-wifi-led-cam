#!/usr/bin/env python3
"""Tiny WiFi-provisioning page (separate from the LED app).

Enter an SSID + password to save a network the Pi will auto-join later. Handy in
hotspot/AP mode: connect to the Pi's hotspot, open this page, and onboard the
local WiFi so the Pi can switch to it (immediately, or on the next
auto-hotspot check / reboot).

Runs on its own port (default 8080) so it doesn't collide with the LED app (5000).
Needs privileges to change NetworkManager, so install it to run as root (see
install-portal.sh). Only expose it on a trusted/hotspot network — anyone who can
reach it can change the Pi's WiFi.
"""
import os
import subprocess
from flask import Flask, request, Response, jsonify

PORT = int(os.environ.get("PORTAL_PORT", "8080"))
app = Flask(__name__)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def con_name(ssid):
    return "wifi-" + ssid


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pi WiFi Setup</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, -apple-system, sans-serif; max-width: 440px;
         margin: 40px auto; padding: 0 20px; }
  h1 { font-size: 1.3rem; }
  label { display: block; margin: 14px 0 4px; font-size: .9rem; opacity: .8; }
  input { width: 100%; box-sizing: border-box; padding: 10px; font-size: 1rem;
          border: 1px solid #8886; border-radius: 10px; }
  button { font-size: 1rem; padding: 10px 20px; border: 0; border-radius: 10px;
           cursor: pointer; background: #2d7ff9; color: #fff; margin-top: 14px; }
  button.ghost { background: #e6e6e6; color: #222; }
  #msg { margin: 14px 0; min-height: 1.2em; }
  .ok { color: #1a9d4b; } .err { color: #e02d2d; }
  ul { list-style: none; padding: 0; }
  li { display: flex; justify-content: space-between; align-items: center;
       border-top: 1px solid #8883; padding: 8px 0; }
  li button { margin: 0; padding: 5px 10px; font-size: .8rem; background: #e0e0e0;
              color: #333; }
  small { opacity: .6; }
</style>
</head>
<body>
  <h1>Pi WiFi Setup</h1>
  <p><small>Save a network for the Pi to join. In hotspot mode, this onboards a
     new location's WiFi.</small></p>

  <label for="ssid">Network name (SSID)</label>
  <input id="ssid" list="ssids" autocomplete="off" placeholder="MyWiFi">
  <datalist id="ssids"></datalist>

  <label for="pass">Password</label>
  <input id="pass" type="password" placeholder="(leave blank for open network)">

  <div>
    <button id="save">Save network</button>
    <button id="rescan" class="ghost" type="button">Rescan</button>
  </div>
  <div id="msg"></div>

  <h2 style="font-size:1rem">Saved networks</h2>
  <ul id="saved"></ul>

<script>
const msg = document.getElementById('msg');
function say(text, cls) { msg.textContent = text; msg.className = cls || ''; }

async function scan() {
  try {
    const list = await (await fetch('/scan')).json();
    document.getElementById('ssids').innerHTML =
      list.map(s => `<option value="${s.replace(/"/g, '&quot;')}">`).join('');
  } catch (e) {}
}

async function loadSaved() {
  try {
    const list = await (await fetch('/saved')).json();
    document.getElementById('saved').innerHTML = list.length
      ? list.map(s => `<li><span>${s}</span><button data-del="${s}">Delete</button></li>`).join('')
      : '<li><small>none yet</small></li>';
    document.querySelectorAll('[data-del]').forEach(b =>
      b.onclick = () => del(b.dataset.del));
  } catch (e) {}
}

async function post(path, body) {
  const r = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  return r.json();
}

document.getElementById('save').onclick = async () => {
  const ssid = document.getElementById('ssid').value.trim();
  const password = document.getElementById('pass').value;
  if (!ssid) return say('Enter an SSID.', 'err');
  say('Saving…');
  const r = await post('/add', {ssid, password});
  if (r.ok) { say(`Saved "${r.ssid}". The Pi will join it when in range.`, 'ok');
              document.getElementById('pass').value = ''; loadSaved(); }
  else say('Error: ' + (r.error || 'failed'), 'err');
};

document.getElementById('rescan').onclick = () => { say('Scanning…'); scan().then(() => say('')); };

async function del(ssid) {
  say('Removing…');
  const r = await post('/delete', {ssid});
  say(r.ok ? `Removed "${ssid}".` : 'Error: ' + (r.error || 'failed'), r.ok ? 'ok' : 'err');
  loadSaved();
}

scan(); loadSaved();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.route("/scan")
def scan():
    """Best-effort list of visible SSIDs (may be empty while hosting the AP)."""
    run(["nmcli", "device", "wifi", "rescan"])
    r = run(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list"])
    ssids = sorted({
        line.replace("\\:", ":")
        for line in r.stdout.splitlines()
        if line.strip()
    })
    return jsonify(ssids)


@app.route("/saved")
def saved():
    """Names of saved WiFi connections (our wifi-* profiles first)."""
    r = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    names = [
        line.rsplit(":", 1)[0]
        for line in r.stdout.splitlines()
        if line.endswith(":802-11-wireless")
    ]
    return jsonify(sorted(names))


@app.route("/add", methods=["POST"])
def add():
    data = request.get_json(silent=True) or {}
    ssid = (data.get("ssid") or "").strip()
    password = data.get("password") or ""
    if not ssid:
        return jsonify({"ok": False, "error": "SSID required"}), 400
    name = con_name(ssid)
    # Replace any existing profile of the same name so re-saving updates it.
    run(["nmcli", "connection", "delete", name])
    cmd = ["nmcli", "connection", "add", "type", "wifi", "con-name", name,
           "ssid", ssid, "connection.autoconnect", "yes"]
    if password:
        cmd += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    r = run(cmd)
    if r.returncode != 0:
        return jsonify({"ok": False, "error": r.stderr.strip() or "nmcli failed"}), 500
    return jsonify({"ok": True, "ssid": ssid})


@app.route("/delete", methods=["POST"])
def delete():
    data = request.get_json(silent=True) or {}
    ssid = (data.get("ssid") or "").strip()
    # Accept either the SSID or the full connection name.
    name = ssid if ssid.startswith("wifi-") else con_name(ssid)
    r = run(["nmcli", "connection", "delete", name])
    if r.returncode != 0:
        # fall back to deleting by the given name verbatim
        r = run(["nmcli", "connection", "delete", ssid])
    if r.returncode != 0:
        return jsonify({"ok": False, "error": r.stderr.strip() or "not found"}), 500
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
