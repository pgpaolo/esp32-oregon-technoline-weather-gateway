Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))

# ---------------------------------------------------------------------------
# Shared I2C compatibility pass.
#
# A second validated ESP32 project using the same external sensor stack runs
# the shared bus at 100 kHz, with an 80 ms timeout, detects the Waveshare
# BME280 at 0x77 and allows the AS3935 address range 0x00..0x03.  Keep this
# gateway aligned with that proven electrical/software setup while preserving
# the existing OLED/BME280/AS3935 architecture.
# ---------------------------------------------------------------------------

# 1) Own the shared bus once from initDisplay(), but use conservative 100 kHz.
#    U8g2 must not leave the bus at 400 kHz before BME280 discovery.
display_path = root / "src" / "display_manager.cpp"
display = display_path.read_text(encoding="utf-8")
if "I2C_SHARED_BUS_COMPAT_V1" not in display:
    old = '''void initDisplay() {
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    oled.setBusClock(400000);
    oled.begin();
'''
    new = '''void initDisplay() {
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
    if old not in display:
        raise RuntimeError("I2C compatibility: initDisplay anchor missing")
    display = display.replace(old, new, 1)
    display_path.write_text(display, encoding="utf-8")
    print("I2C compatibility: shared bus set to 100 kHz / 80 ms timeout")
else:
    print("I2C compatibility: display/shared bus already patched")


# 2) The working sensor project can detect the AS3935 at 0x00. The current
#    gateway previously normalized 0x00 back to 0x03 and never tried it.
lightning_path = root / "src" / "lightning_manager.cpp"
lightning = lightning_path.read_text(encoding="utf-8")
if "I2C_SHARED_BUS_COMPAT_V1" not in lightning:
    old_norm = '    if (c.i2cAddress < 0x01 || c.i2cAddress > 0x03) c.i2cAddress = 0x03;\n'
    new_norm = '    // I2C_SHARED_BUS_COMPAT_V1: AS3935 A1/A0 can resolve to 0x00..0x03.\n    if (c.i2cAddress > 0x03) c.i2cAddress = 0x03;\n'
    if old_norm not in lightning:
        raise RuntimeError("I2C compatibility: AS3935 normalize anchor missing")
    lightning = lightning.replace(old_norm, new_norm, 1)

    old_detect = '''    sensor = new AS3935I2C(cfg.i2cAddress, static_cast<uint8_t>(cfg.irqPin));
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

    state.detected = true;
'''
    new_detect = '''    // Auto-detect the complete AS3935 two-bit I2C address range. The preferred
    // configured address is tried first, then the remaining addresses including
    // 0x00 (used by the known-good external sensor assembly).
    const uint8_t candidates[] = {cfg.i2cAddress, 0x03, 0x02, 0x01, 0x00};
    uint8_t tried[5] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    uint8_t triedCount = 0;
    uint8_t detectedAddress = 0xFF;

    for (uint8_t a : candidates) {
        bool duplicate = false;
        for (uint8_t i = 0; i < triedCount; ++i) {
            if (tried[i] == a) { duplicate = true; break; }
        }
        if (duplicate) continue;
        tried[triedCount++] = a;

        AS3935I2C *candidate = new AS3935I2C(a, static_cast<uint8_t>(cfg.irqPin));
        if (!candidate) continue;
        if (candidate->begin() && candidate->checkConnection()) {
            sensor = candidate;
            detectedAddress = a;
            break;
        }
        delete candidate;
    }

    if (!sensor) {
        Serial.println(F("[AS3935] non rilevato su I2C 0x00..0x03"));
        return false;
    }

    cfg.i2cAddress = detectedAddress;
    Wire.setClock(100000);
    state.detected = true;
'''
    if old_detect not in lightning:
        raise RuntimeError("I2C compatibility: AS3935 detection block missing")
    lightning = lightning.replace(old_detect, new_detect, 1)
    lightning_path.write_text(lightning, encoding="utf-8")
    print("I2C compatibility: AS3935 auto-detect extended to 0x00..0x03")
else:
    print("I2C compatibility: AS3935 already patched")


# 3) BME280: prefer the Waveshare default 0x77, while retaining 0x76 fallback.
#    The retry pass has already generated attemptBmeDetection() by this point.
baro_path = root / "src" / "barometer_manager.cpp"
baro = baro_path.read_text(encoding="utf-8")
if "I2C_SHARED_BUS_COMPAT_V1" not in baro:
    old_bme = '''    bool ok = false;
    if (lastI2cAck76) ok = tryBme(0x76);
    if (!ok && lastI2cAck77) ok = tryBme(0x77);
'''
    new_bme = '''    // I2C_SHARED_BUS_COMPAT_V1: Waveshare default is 0x77; retain 0x76 fallback.
    bool ok = false;
    if (lastI2cAck77) ok = tryBme(0x77);
    if (!ok && lastI2cAck76) ok = tryBme(0x76);
'''
    if old_bme not in baro:
        raise RuntimeError("I2C compatibility: BME retry detection block missing")
    baro = baro.replace(old_bme, new_bme, 1)

    # The manual scanner still exercises both 400 and 100 kHz, but the normal
    # runtime bus must be restored to the validated 100 kHz baseline afterwards.
    scanner_marker = "// BME280_I2C_DEEP_SCAN_V1"
    if scanner_marker not in baro:
        raise RuntimeError("I2C compatibility: deep scanner marker missing")
    scan_pos = baro.find(scanner_marker)
    restore_pos = baro.find("    Wire.setClock(NORMAL_I2C_HZ);", scan_pos)
    if restore_pos < 0:
        raise RuntimeError("I2C compatibility: scanner clock restore anchor missing")
    restore_end = restore_pos + len("    Wire.setClock(NORMAL_I2C_HZ);")
    baro = baro[:restore_pos] + "    Wire.setClock(100000UL);" + baro[restore_end:]

    # Include address 0x00 in the diagnostic scan so the AS3935 configuration
    # shown by the known-good project can be verified directly.
    loop_old = "        for (uint8_t addr = 1; addr < 0x7FU; ++addr) {"
    loop_new = "        for (uint8_t addr = 0; addr < 0x7FU; ++addr) {"
    if loop_old not in baro:
        raise RuntimeError("I2C compatibility: scanner address loop anchor missing")
    baro = baro.replace(loop_old, loop_new, 1)

    baro_path.write_text(baro, encoding="utf-8")
    print("I2C compatibility: BME280 prefers 0x77; scanner restores 100 kHz and includes 0x00")
else:
    print("I2C compatibility: barometer already patched")
