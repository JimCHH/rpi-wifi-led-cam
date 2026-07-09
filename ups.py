"""Best-effort battery reader for Waveshare INA219-based UPS HATs.

Defaults are tuned for the Waveshare UPS HAT (C) — the Pi Zero-sized UPS with a
single Li-ion cell and an INA219 at 0x43 — matching its reference driver.

The common Waveshare UPS HATs expose an INA219 current/voltage monitor over I2C.
This reads battery voltage + current and estimates a percentage. It degrades
gracefully (returns {"present": False, ...}) when I2C is off, no HAT is present,
or the smbus library isn't installed — so the rest of the app is unaffected.

Env overrides (defaults suit most single-cell Waveshare UPS HATs):
    UPS_I2C_BUS=1
    UPS_I2C_ADDR=0x43        # some HATs use 0x40/0x41/0x42
    UPS_V_FULL=4.2           # single Li-ion cell full
    UPS_V_EMPTY=3.0          # cell empty
    UPS_CURRENT_SIGN=1       # set -1 if charging/discharging shows inverted
"""
import os

I2C_BUS = int(os.environ.get("UPS_I2C_BUS", "1"))
I2C_ADDR = int(os.environ.get("UPS_I2C_ADDR", "0x43"), 0)
V_FULL = float(os.environ.get("UPS_V_FULL", "4.2"))
V_EMPTY = float(os.environ.get("UPS_V_EMPTY", "3.0"))
CURRENT_SIGN = int(os.environ.get("UPS_CURRENT_SIGN", "1"))

try:
    from smbus2 import SMBus
except ImportError:
    try:
        from smbus import SMBus
    except ImportError:
        SMBus = None

_REG_CONFIG = 0x00
_REG_BUSVOLTAGE = 0x02
_REG_CURRENT = 0x04
_REG_CALIBRATION = 0x05


def _read_word(bus, reg):
    hi, lo = bus.read_i2c_block_data(I2C_ADDR, reg, 2)
    return (hi << 8) | lo


def _signed(val):
    return val - 0x10000 if val > 0x7FFF else val


def read():
    """Return a battery dict, or {'present': False, 'reason': ...} if unreadable."""
    if SMBus is None:
        return {"present": False, "reason": "smbus not installed"}
    try:
        with SMBus(I2C_BUS) as bus:
            # Calibrate for the Waveshare 32V/2A range (current LSB ~0.1 mA).
            # Bus voltage itself doesn't depend on this; current does.
            bus.write_i2c_block_data(I2C_ADDR, _REG_CALIBRATION, [0x10, 0x00])
            raw_bus = _read_word(bus, _REG_BUSVOLTAGE)
            voltage = (raw_bus >> 3) * 0.004  # 4 mV/LSB
            current_ma = _signed(_read_word(bus, _REG_CURRENT)) * 0.1 * CURRENT_SIGN
    except Exception as exc:  # I2C off, no HAT, wrong address, etc.
        return {"present": False, "reason": str(exc)}

    pct = (voltage - V_EMPTY) / (V_FULL - V_EMPTY) * 100.0
    pct = max(0.0, min(100.0, pct))
    return {
        "present": True,
        "voltage": round(voltage, 3),
        "current_ma": round(current_ma, 1),
        "percent": round(pct),
        # Positive current into the battery == charging (flip with UPS_CURRENT_SIGN).
        "charging": current_ma > 20,
    }
