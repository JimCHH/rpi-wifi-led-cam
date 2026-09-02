#!/usr/bin/env bash
# Wired backup: reach the LED web UI over a single USB cable, no WiFi needed.
#
# Puts the Pi Zero 2 W's OTG "USB" port into USB Ethernet gadget mode. Plug one
# data cable from your Mac/PC into the Pi's inner **USB** port (not PWR IN) and
# the Pi appears as a USB network adapter. The SAME app answers — open
#     http://10.55.0.1:5000
# The cable also powers the Pi, so no separate supply is needed.
#
#   ./setup-usb-gadget.sh          enable gadget mode  (disables the USB camera)
#   ./setup-usb-gadget.sh off      revert to host mode (re-enables the camera)
#
# NOTE: the Zero 2 W has ONE data port, which can be a USB *host* (camera) OR a
# USB *device* (this gadget) — never both at once. Toggling here swaps between
# them. A reboot is required for the change to take effect.
set -euo pipefail

MODE="${1:-on}"

# Boot config lives in /boot/firmware on Bookworm/Trixie, /boot on older images.
BOOT=/boot/firmware
[ -f "$BOOT/config.txt" ] || BOOT=/boot
CONFIG="$BOOT/config.txt"
CMDLINE="$BOOT/cmdline.txt"

# USB-link addressing: static gateway on the Pi + NetworkManager "shared" mode,
# which runs a small DHCP server on usb0 so the Mac auto-configures (and even
# gets internet via the Pi's WiFi when it's up). Pinned to 10.55.0.x so it can't
# collide with the auto-hotspot's 10.42.0.x network.
USB_IP="${USB_IP:-10.55.0.1/24}"
NM_CON="usb-gadget"

require_boot() {
  if [ ! -f "$CONFIG" ] || [ ! -f "$CMDLINE" ]; then
    echo "ERROR: can't find $CONFIG / $CMDLINE — is this a Raspberry Pi OS image?" >&2
    exit 1
  fi
}

set_overlay() {  # $1 = otg | host
  # Replace any existing dwc2 overlay line, then append the one we want.
  sudo sed -i '/^dtoverlay=dwc2/d' "$CONFIG"
  echo "dtoverlay=dwc2,dr_mode=$1" | sudo tee -a "$CONFIG" >/dev/null
}

add_gadget_module() {
  grep -q 'modules-load=dwc2,g_ether' "$CMDLINE" && return
  # cmdline.txt is a SINGLE line; insert right after rootwait, in place.
  sudo sed -i 's/\brootwait\b/rootwait modules-load=dwc2,g_ether/' "$CMDLINE"
}

remove_gadget_module() {
  sudo sed -i 's/ *modules-load=dwc2,g_ether//g' "$CMDLINE"
}

enable() {
  require_boot
  echo "==> Enabling USB Ethernet gadget mode (OTG) in $CONFIG …"
  set_overlay otg
  add_gadget_module

  echo "==> Configuring usb0 ($USB_IP, shared/DHCP) via NetworkManager …"
  if nmcli -t -f NAME connection show 2>/dev/null | grep -qx "$NM_CON"; then
    sudo nmcli connection modify "$NM_CON" \
      ipv4.method shared ipv4.addresses "$USB_IP" ipv6.method disabled
  else
    # ifname usb0 may not exist until the module loads at boot; NM stores the
    # profile and binds it when the interface appears (autoconnect).
    sudo nmcli connection add type ethernet ifname usb0 con-name "$NM_CON" \
      ipv4.method shared ipv4.addresses "$USB_IP" ipv6.method disabled \
      connection.autoconnect yes >/dev/null
  fi

  cat <<EOF

Done. Reboot to apply:  sudo reboot

After reboot, with WiFi off or unplugged:
  1. Connect a **data** USB cable: Mac  ->  Pi's inner **USB** port (not PWR IN).
     (That one cable also powers the Pi — leave PWR IN empty.)
  2. A new "Ethernet Gadget" appears in macOS System Settings > Network;
     leave it on DHCP (it auto-configures).
  3. Open:  http://${USB_IP%%/*}:5000

Camera note: gadget mode uses the data port as a USB *device*, so the USB
camera (which needs host mode) won't work until you switch back:
  ./setup-usb-gadget.sh off && sudo reboot
EOF
}

disable() {
  require_boot
  echo "==> Reverting to USB host mode (camera) in $CONFIG …"
  set_overlay host
  remove_gadget_module
  if nmcli -t -f NAME connection show 2>/dev/null | grep -qx "$NM_CON"; then
    echo "==> Removing the $NM_CON connection …"
    sudo nmcli connection delete "$NM_CON" >/dev/null || true
  fi
  cat <<EOF

Done. Reboot to apply:  sudo reboot
Host mode restored — the USB camera works again; USB LED control is off.
EOF
}

case "$MODE" in
  on|enable|"")  enable ;;
  off|disable|host) disable ;;
  *) echo "usage: $0 [on|off]" >&2; exit 1 ;;
esac
