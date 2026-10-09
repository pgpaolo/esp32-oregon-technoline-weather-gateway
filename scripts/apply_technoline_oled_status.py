#!/usr/bin/env python3
"""Unify Technoline OLED RF status with Oregon sensor-health notation.

Runs after apply_uv_outputs.py, which defines oledRssiGrade(). WS23xx exposes
RSSI but does not transmit battery state, therefore the compact OLED meta line
uses B- (battery N/D). No decoder or station-state logic is changed.
"""

from pathlib import Path

Import("env")
ROOT = Path(env.subst("$PROJECT_DIR"))
DISPLAY_CPP = ROOT / "src" / "display_manager.cpp"

text = DISPLAY_CPP.read_text(encoding="utf-8")
marker = '''    if (displayCfg.technolineFields & DISPLAY_TECH_META) {
        snprintf(line, sizeof(line), "ID %02X pkt %lu", lc.sensorId, static_cast<unsigned long>(lc.validPacketCount));
        drawLine(line, y);
    }'''
replacement = '''    if (displayCfg.technolineFields & DISPLAY_TECH_META) {
        if (isfinite(lc.lastRssi)) {
            int rssi = static_cast<int>(lroundf(lc.lastRssi));
            if (rssi < -126) rssi = -126;
            if (rssi > 0) rssi = 0;
            snprintf(line, sizeof(line), "ID%02X %ddBm %c B-", lc.sensorId, rssi,
                     oledRssiGrade(static_cast<int8_t>(rssi)));
        } else {
            snprintf(line, sizeof(line), "ID%02X RSSI-- B-", lc.sensorId);
        }
        drawLine(line, y);
    }'''

if replacement in text:
    print("Technoline OLED status: already patched")
elif text.count(marker) == 1:
    DISPLAY_CPP.write_text(text.replace(marker, replacement, 1), encoding="utf-8")
    print("Technoline OLED status: patched display_manager.cpp")
else:
    raise RuntimeError(f"Technoline OLED status marker count={text.count(marker)}")
