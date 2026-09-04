from pathlib import Path

root = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (root / path).read_text(encoding="utf-8")


def require(haystack: str, needle: str, label: str) -> None:
    if needle not in haystack:
        raise SystemExit(f"FAIL: {label}: missing {needle!r}")


baro_cpp = text("src/barometer_manager.cpp")
baro_h = text("src/barometer_manager.h")
display = text("src/display_manager.cpp")
web = text("src/web_manager.cpp")
pio = text("platformio.ini")

require(pio, "pre:scripts/apply_bme280_i2c_main_hotfix.py", "PlatformIO hotfix pass")
require(display, "BME280_I2C_MAIN_HOTFIX_DISPLAY_V1", "shared I2C display patch")
require(display, "Wire.setTimeOut(80);", "I2C timeout")
require(display, "Wire.setClock(100000);", "I2C runtime clock")
require(display, "oled.setBusClock(100000);", "OLED runtime clock")

require(baro_h, "BME280_I2C_MAIN_HOTFIX_API_V1", "BME diagnostics API")
require(baro_cpp, "BME280_I2C_MAIN_HOTFIX_CORE_V1", "BME retry core")
require(baro_cpp, "BME_RETRY_5S_MS", "5 second retry")
require(baro_cpp, "BME_RETRY_15S_MS", "15 second retry")
require(baro_cpp, "BME_RETRY_60S_MS", "60 second retry")
require(baro_cpp, "BME_RETRY_5MIN_MS", "5 minute retry")
require(baro_cpp, "BME_READ_FAILURE_LIMIT = 6U", "read-failure recovery")
require(baro_cpp, "if (lastI2cAck77) ok = tryBme(0x77);", "0x77 preference")
require(baro_cpp, "if (!ok && lastI2cAck76) ok = tryBme(0x76);", "0x76 fallback")
require(baro_cpp, "configureI2cRuntimeBus();", "runtime bus restore")

require(web, "BME280_I2C_MAIN_HOTFIX_WEB_V1", "Web diagnostics patch")
require(web, 'server.on("/api/i2c/hardware", HTTP_GET, handleI2cHardware);', "I2C hardware route")
require(web, 'server.on("/api/i2c/scan", HTTP_POST, handleI2cScan);', "I2C scan route")
require(web, 'id="tabI2c"', "I2C configuration tab")
require(web, 'id="cfgI2c"', "I2C configuration page")
require(web, 'id="sysMcuTemp"', "MCU temperature Hardware line")
require(web, "hardware_temperature_c", "MCU temperature JSON")
require(web, "temperatureRead()", "ESP32 die temperature source")
require(web, "scanI2cAddresses(100000)", "100 kHz scan")
require(web, "scanI2cAddresses(400000)", "400 kHz stress scan")
require(web, "readBoschChipId(0x77)", "BME chip-ID probe")
require(web, "restoreI2cRuntimeBus();", "scanner runtime restore")

# Guard against accidentally importing unrelated RC4 subsystems into this
# selective main hotfix.
if (root / "src/lightning_manager.cpp").exists():
    raise SystemExit("FAIL: unrelated AS3935 manager was imported into main hotfix")
if (root / "src/mb_compatible_publisher.cpp").exists():
    raise SystemExit("FAIL: unrelated COMPATIBLE MB publisher was imported into main hotfix")

print("PASS: BME280/I2C main hotfix integration is present and selective")
