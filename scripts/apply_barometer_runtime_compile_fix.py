Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "barometer_manager.cpp"
text = path.read_text(encoding="utf-8")

bad = "Serial.print(runtimeCfg.altitudeM, 1)\n"
good = "Serial.print(runtimeCfg.altitudeM, 1);\n"
if bad in text:
    text = text.replace(bad, good, 1)
    path.write_text(text, encoding="utf-8")
    print("Fixed generated BME280 altitude Serial.print syntax")
elif good in text:
    print("BME280 altitude Serial.print syntax already correct")
else:
    raise RuntimeError("Barometer compile fix: expected runtime altitude print not found")
