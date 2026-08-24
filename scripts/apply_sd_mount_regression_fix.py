Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
p = root / "src/sd_logger.cpp"
text = p.read_text(encoding="utf-8")

# Regression fix for T3 V1.6.1 microSD mounting.
# apply_sd_format_tools.py adds the format API and diagnostics, but its newer
# LILYGO-style mount sequence changed the SPI ownership/retry behaviour that was
# already proven on this board. Keep all format/UI features and replace only
# mountSdAdaptive() after the format patch has run.
marker = "SD_MOUNT_REGRESSION_FIX_V3"
if marker not in text:
    start_marker = "bool mountSdAdaptive(bool formatIfEmpty) {"
    end_marker = "bool clearSdTree(const char *path) {"
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker)) if start >= 0 else -1
    if start < 0 or end < 0:
        raise RuntimeError("SD mount regression fix: mountSdAdaptive block not found")

    helper = r'''// SD_MOUNT_REGRESSION_FIX_V3
bool mountSdAdaptive(bool formatIfEmpty) {
#if !SDCARD_SUPPORTED
    status.supported = false;
    return false;
#else
    unmount();
    status.mountAttempts++;
    status.spiAttemptMask = 0;
    status.spiBeginFailMask = 0;
    status.initCode = 0;

    // T3 V1.6.1 proven sequence: explicitly bind CS to HSPI, then let SD.begin
    // use the same bus. Recreate the SPI peripheral for every retry so a failed
    // card command cannot leave HSPI/CS in a stale state.
    pinMode(SDCARD_CS_PIN, OUTPUT);
    digitalWrite(SDCARD_CS_PIN, HIGH);
    delay(100);

    const uint32_t freq[] = {8000000U, 4000000U, 2000000U, 1000000U, 400000U};
    for (uint8_t i = 0; i < 5U; ++i) {
        const uint8_t bit = static_cast<uint8_t>(1U << i);
        status.spiAttemptMask |= bit;

        if (spiStarted) {
            sdSpi.end();
            spiStarted = false;
        }
        digitalWrite(SDCARD_CS_PIN, HIGH);
        delay(40);

        sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN, SDCARD_MOSI_PIN, SDCARD_CS_PIN);
        spiStarted = true;
        delay(80);

        const bool beginOk = formatIfEmpty
            ? SD.begin(SDCARD_CS_PIN, sdSpi, freq[i], "/sd", 5, true)
            : SD.begin(SDCARD_CS_PIN, sdSpi, freq[i]);

        if (!beginOk) {
            status.spiBeginFailMask |= bit;
            status.initCode = 2;
            Serial.printf("[SD] %lu kHz: begin FAIL\n",
                          static_cast<unsigned long>(freq[i] / 1000UL));
            SD.end();
            sdSpi.end();
            spiStarted = false;
            digitalWrite(SDCARD_CS_PIN, HIGH);
            delay(80);
            continue;
        }

        if (SD.cardType() == CARD_NONE) {
            status.initCode = 3;
            Serial.printf("[SD] %lu kHz: CARD_NONE\n",
                          static_cast<unsigned long>(freq[i] / 1000UL));
            SD.end();
            sdSpi.end();
            spiStarted = false;
            digitalWrite(SDCARD_CS_PIN, HIGH);
            delay(80);
            continue;
        }

        status.mounted = true;
        status.spiFrequencyHz = freq[i];
        status.initCode = 1;
        refreshCapacity();
        Serial.printf("[SD] OK %lu kHz, %lu MB\n",
                      static_cast<unsigned long>(freq[i] / 1000UL),
                      static_cast<unsigned long>(status.cardSizeBytes / (1024ULL * 1024ULL)));
        return true;
    }

    if (spiStarted) {
        sdSpi.end();
        spiStarted = false;
    }
    digitalWrite(SDCARD_CS_PIN, HIGH);
    Serial.printf("[SD] mount FAIL try=0x%02X beginFail=0x%02X code=%u\n",
                  static_cast<unsigned>(status.spiAttemptMask),
                  static_cast<unsigned>(status.spiBeginFailMask),
                  static_cast<unsigned>(status.initCode));
    return false;
#endif
}

'''

    p.write_text(text[:start] + helper + text[end:], encoding="utf-8")
    print("SD mount regression fix: restored explicit-CS HSPI + 8/4/2/1/0.4 MHz retries")
else:
    print("SD mount regression fix: source already patched")
