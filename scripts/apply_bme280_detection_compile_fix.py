Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "barometer_manager.cpp"
text = path.read_text(encoding="utf-8")

marker = "// BME280_DETECTION_RETRY_V1\n"
prototype = "bool tryBme(uint8_t addr);\n"

if marker not in text:
    raise RuntimeError("BME280 detection compile fix: retry marker missing")

if prototype not in text:
    text = text.replace(marker, marker + prototype, 1)
    path.write_text(text, encoding="utf-8")
    print("Added BME280 tryBme forward declaration")
else:
    print("BME280 tryBme forward declaration already present")
