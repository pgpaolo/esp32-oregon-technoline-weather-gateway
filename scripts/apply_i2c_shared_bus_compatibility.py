Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))

# ---------------------------------------------------------------------------
# Shared I2C compatibility pass.
#
# Hardware validation showed that long I2C wiring can remove the BME280 from
# the bus even while SDA/SCL read HIGH at idle. Keep the normal shared bus at a
# conservative 100 kHz with an 80 ms timeout. The dedicated I2C/HW diagnostic
# pass can still run a manual 400 kHz margin test.
# ---------------------------------------------------------------------------

# 1) Own the shared bus once from initDisplay() and keep OLED/BME280/AS3935 at
#    the validated 100 kHz runtime speed.
display_path = root / "src" / "display_manager.cpp"
display = display_path.read_text(encoding="utf-8")
if "I2C_SHARED_BUS_COMPAT_V2" not in display:
    old_v1 = '''void initDisplay() {
    // I2C_SHARED_BUS_COMPAT_V1
    // Conservative shared bus: OLED + BME280 + AS3935.
    // This matches the known-good sensor project on the same ESP32 wiring.
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    Wire.setTimeOut(80);
    Wire.setClock(100000);

    // Probe BME280 before U8g2 touches the bus. This is intentionally only a
    // boot diagnostic; normal discovery remains in barometer_manager.
    Wire.beginTransmission(0x76);
    const bool bootBme76 = Wire.endTransmission(true) == 0;
    Wire.beginTransmission(0x77);
    const bool bootBme77 = Wire.endTransmission(true) == 0;
    Serial.print(F("[I2C] pre-OLED BME 0x76="));
    Serial.print(bootBme76 ? F("ACK") : F("--"));
    Serial.print(F(" 0x77="));
    Serial.println(bootBme77 ? F("ACK") : F("--"));

    oled.setBusClock(100000);
    oled.begin();
    Wire.setClock(100000);
'''
    old_base = '''void initDisplay() {
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    oled.setBusClock(400000);
    oled.begin();
'''
    new = '''void initDisplay() {
    // I2C_SHARED_BUS_COMPAT_V2
    // OLED + BME280 + AS3935 share one conservative bus. Hardware testing
    // confirmed that cable capacitance, not the BME280 driver, was the source
    // of intermittent/missing ACKs with long leads.
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    Wire.setTimeOut(80);
    Wire.setClock(100000);
    oled.setBusClock(100000);
    oled.begin();
    Wire.setClock(100000);
'''
    if old_v1 in display:
        display = display.replace(old_v1, new, 1)
    elif old_base in display:
        display = display.replace(old_base, new, 1)
    else:
        raise RuntimeError("I2C compatibility: initDisplay anchor missing")
    display_path.write_text(display, encoding="utf-8")
    print("I2C compatibility: shared runtime bus fixed at 100 kHz / 80 ms")
else:
    print("I2C compatibility: display/shared bus already patched")

# 2) Keep the AS3935 configured-address behaviour deterministic. The two-bit
#    address range is 0x00..0x03; default remains 0x03. Do not auto-scan or
#    rewrite a working address during boot.
lightning_path = root / "src" / "lightning_manager.cpp"
lightning = lightning_path.read_text(encoding="utf-8")
if "I2C_SHARED_BUS_COMPAT_V2" not in lightning:
    old_norm = '    if (c.i2cAddress < 0x01 || c.i2cAddress > 0x03) c.i2cAddress = 0x03;\n'
    old_v1_norm = '    // I2C_SHARED_BUS_COMPAT_V1: AS3935 A1/A0 can resolve to 0x00..0x03.\n    if (c.i2cAddress > 0x03) c.i2cAddress = 0x03;\n'
    new_norm = '    // I2C_SHARED_BUS_COMPAT_V2: valid AS3935 A1/A0 range is 0x00..0x03.\n    if (c.i2cAddress > 0x03) c.i2cAddress = 0x03;\n'
    if old_v1_norm in lightning:
        lightning = lightning.replace(old_v1_norm, new_norm, 1)
    elif old_norm in lightning:
        lightning = lightning.replace(old_norm, new_norm, 1)
    else:
        raise RuntimeError("I2C compatibility: AS3935 normalize anchor missing")

    # A reused workspace may still contain the experimental V1 auto-detect
    # block. Canonicalize it back to the stable configured-address path.
    auto_start = lightning.find('    // Auto-detect the complete AS3935 two-bit I2C address range.')
    if auto_start >= 0:
        auto_end_marker = '    state.detected = true;\n'
        auto_end = lightning.find(auto_end_marker, auto_start)
        if auto_end < 0:
            raise RuntimeError("I2C compatibility: AS3935 V1 auto-detect end missing")
        auto_end += len(auto_end_marker)
        stable = '''    sensor = new AS3935I2C(cfg.i2cAddress, static_cast<uint8_t>(cfg.irqPin));
    if (!sensor) {
        Serial.println(F("[AS3935] allocazione sensore fallita"));
        return false;
    }

    if (!sensor->begin() || !sensor->checkConnection()) {
        Serial.print(F("[AS3935] non rilevato su I2C 0x"));
        Serial.println(cfg.i2cAddress, HEX);
        delete sensor;
        sensor = nullptr;
        return false;
    }

    Wire.setClock(100000);
    state.detected = true;
'''
        lightning = lightning[:auto_start] + stable + lightning[auto_end:]
    else:
        stable_anchor = '    state.detected = true;\n'
        stable_pos = lightning.find(stable_anchor)
        if stable_pos < 0:
            raise RuntimeError("I2C compatibility: AS3935 stable detection anchor missing")
        before = lightning[max(0, stable_pos - 1000):stable_pos]
        if 'Wire.setClock(100000);' not in before:
            lightning = lightning[:stable_pos] + '    Wire.setClock(100000);\n' + lightning[stable_pos:]

    lightning_path.write_text(lightning, encoding="utf-8")
    print("I2C compatibility: AS3935 uses deterministic configured address at 100 kHz")
else:
    print("I2C compatibility: AS3935 already patched")

# 3) Prefer the Waveshare/common 0x77 BME280 address while retaining 0x76
#    fallback. Detection/retry remains non-blocking and address-specific.
baro_path = root / "src" / "barometer_manager.cpp"
baro = baro_path.read_text(encoding="utf-8")
if "I2C_SHARED_BUS_COMPAT_V2" not in baro:
    old = '''    bool ok = false;
    if (lastI2cAck76) ok = tryBme(0x76);
    if (!ok && lastI2cAck77) ok = tryBme(0x77);
'''
    old_v1 = '''    // I2C_SHARED_BUS_COMPAT_V1: Waveshare default is 0x77; retain 0x76 fallback.
    bool ok = false;
    if (lastI2cAck77) ok = tryBme(0x77);
    if (!ok && lastI2cAck76) ok = tryBme(0x76);
'''
    new = '''    // I2C_SHARED_BUS_COMPAT_V2: prefer 0x77, retain 0x76 fallback.
    bool ok = false;
    if (lastI2cAck77) ok = tryBme(0x77);
    if (!ok && lastI2cAck76) ok = tryBme(0x76);
'''
    if old_v1 in baro:
        baro = baro.replace(old_v1, new, 1)
    elif old in baro:
        baro = baro.replace(old, new, 1)
    else:
        raise RuntimeError("I2C compatibility: BME retry detection block missing")
    baro_path.write_text(baro, encoding="utf-8")
    print("I2C compatibility: BME280 prefers 0x77 with 0x76 fallback")
else:
    print("I2C compatibility: barometer already patched")
