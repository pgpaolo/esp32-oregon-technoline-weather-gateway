#!/usr/bin/env python3
"""Post-build guard for the reviewed I2C/HW diagnostics integration.

PlatformIO pre-scripts intentionally transform source/UI files in-place. Run
this after `pio run` so CI verifies the generated result, not only the patch
sources.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"I2C/HW guard: missing {label}: {needle}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise SystemExit(f"I2C/HW guard: forbidden {label}: {needle}")


dash = read("web/dashboard.html")
web = read("src/web_manager.cpp")
display = read("src/display_manager.cpp")
lightning = read("src/lightning_manager.cpp")
baro = read("src/barometer_manager.cpp")

# Dedicated UI and hardware temperature.
for needle, label in (
    ('id="tabHardwareDiag"', "I2C/HW configuration tab"),
    ('id="cfgHardwareDiag"', "I2C/HW configuration page"),
    ('id="hwScanBtn"', "manual I2C scanner button"),
    ('id="sysHwTemp"', "Hardware monitor MCU temperature"),
    ("async function scanHardwareI2c()", "I2C/HW scan JavaScript"),
):
    require(dash, needle, label)

# Scanner must no longer live inside BAROMETRO.
for needle, label in (
    ('id="baroScanBtn"', "legacy BAROMETRO scan button"),
    ('id="baroI2cScan"', "legacy BAROMETRO scan result"),
):
    forbid(dash, needle, label)

# Authenticated backend endpoints and state telemetry.
for needle, label in (
    ('server.on("/api/hardware/info"', "hardware-info route"),
    ('server.on("/api/hardware/i2c-scan"', "hardware I2C-scan route"),
    ('"hardware_temperature_c"', "MCU temperature JSON field"),
    ('String runHardwareI2cScanJson()', "hardware I2C scanner implementation"),
):
    require(web, needle, label)

# The physical fix established a conservative runtime bus. 400 kHz is only
# present inside the manual diagnostic stress scan.
require(display, "I2C_SHARED_BUS_COMPAT_V2", "validated shared-bus marker")
require(display, "Wire.setTimeOut(80);", "80 ms I2C timeout")
require(display, "Wire.setClock(100000);", "100 kHz runtime I2C clock")
require(display, "oled.setBusClock(100000);", "100 kHz OLED bus clock")
require(web, "constexpr uint32_t RUNTIME_I2C_HZ = 100000UL;", "scanner runtime speed")
require(web, "constexpr uint32_t STRESS_I2C_HZ = 400000UL;", "scanner stress speed")
require(web, "for (uint8_t addr = 1; addr < 0x7FU; ++addr)", "standard scanner address range")
forbid(web, "for (uint8_t addr = 0; addr < 0x7FU; ++addr)", "I2C general-call scan")

# AS3935 returns to deterministic configured-address startup; BME retry remains.
forbid(lightning, "Auto-detect the complete AS3935", "experimental AS3935 address auto-scan")
require(lightning, "new AS3935I2C(cfg.i2cAddress", "configured AS3935 address")
require(baro, "BME_RETRY_5S_MS", "BME280 retry/recovery")
require(baro, "if (lastI2cAck77) ok = tryBme(0x77);", "BME280 0x77 preferred probe")
require(baro, "if (!ok && lastI2cAck76) ok = tryBme(0x76);", "BME280 0x76 fallback")

print("I2C/HW generated integration guard: PASS")
