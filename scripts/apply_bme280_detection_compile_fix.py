Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "barometer_manager.cpp"
text = path.read_text(encoding="utf-8")

# Compile-order guard only. The manual I2C scanner lives in the dedicated
# apply_i2c_hardware_diagnostics.py pass, not in the BME280 driver patch.
marker = "// BME280_DETECTION_RETRY_V1\n"
prototype = "bool tryBme(uint8_t addr);\n"

if marker not in text:
    raise RuntimeError("BME280 detection compile fix: retry marker missing")

if prototype not in text:
    text = text.replace(marker, marker + prototype, 1)
    print("Added BME280 tryBme forward declaration")
else:
    print("BME280 tryBme forward declaration already present")

path.write_text(text, encoding="utf-8")
