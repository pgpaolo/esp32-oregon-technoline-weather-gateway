Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src/barometer_manager.cpp"
text = path.read_text(encoding="utf-8")

marker = "BME280_I2C_MAIN_HOTFIX_CORE_V1"
if marker not in text:
    raise RuntimeError("BME280 main compile fix: hotfix core marker missing")

# attemptBmeDetection() is generated before the existing tryBme() definition.
# Add a forward declaration in the same anonymous namespace so both clean and
# repeated PlatformIO builds compile deterministically.
decl = "bool tryBme(uint8_t addr);"
if decl not in text:
    anchor = "bool lastI2cAck77 = false;\n\n"
    if anchor not in text:
        raise RuntimeError("BME280 main compile fix: diagnostics state anchor missing")
    text = text.replace(anchor, anchor + decl + "\n\n", 1)
    path.write_text(text, encoding="utf-8")
    print("BME280 main hotfix: added tryBme forward declaration")
else:
    print("BME280 main hotfix: tryBme declaration already present")
