Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
p = root / "src/sd_logger.cpp"
text = p.read_text(encoding="utf-8")

# T3 V1.6.1 SD mount normalizer.
#
# PlatformIO pre-scripts patch the checkout in-place. Depending on whether the
# tree is clean or has already been built, apply_sd_format_tools.py can leave
# mountSdAdaptive() absent, present once, or (on a repeated build) reinsert an
# older generated copy. Normalize that state on every build instead of assuming
# a particular previous patch state.

FUNCTION_SIG = "bool mountSdAdaptive(bool formatIfEmpty) {"
INIT_SIG = "void initSdLogger() {"
REMOUNT_SIG = "bool remountSdLogger() {"


def function_end(src: str, start: int) -> int:
    """Return index immediately after a C/C++ function block starting at start."""
    brace = src.find("{", start)
    if brace < 0:
        raise RuntimeError("SD mount normalizer: function opening brace not found")
    depth = 0
    i = brace
    while i < len(src):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                i += 1
                while i < len(src) and src[i] in "\r\n":
                    i += 1
                return i
        i += 1
    raise RuntimeError("SD mount normalizer: unterminated function block")


helper = r'''// SD_MOUNT_REGRESSION_FIX_V4
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

    // Sequence already proven by the original SD datalogger on T3 V1.6.1:
    // bind CS explicitly to HSPI. For retries, completely recreate the SPI
    // peripheral so a failed card command cannot leave HSPI/CS in stale state.
    pinMode(SDCARD_CS_PIN, OUTPUT);
    digitalWrite(SDCARD_CS_PIN, HIGH);
    delay(100);

    const uint32_t freq[] = {8000000U, 4000000U, 2000000U, 1000000U, 400000U};
    for (uint8_t i = 0; i < 5U; ++i) {
        const uint8_t bit = static_cast<uint8_t>(1U << i);
        status.spiAttemptMask |= bit;

        // SD.end() is safe here even after a failed/partial begin and makes the
        // retry independent from the previous SD library state.
        SD.end();
        if (spiStarted) {
            sdSpi.end();
            spiStarted = false;
        }

        digitalWrite(SDCARD_CS_PIN, HIGH);
        delay(40);
        sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN,
                    SDCARD_MOSI_PIN, SDCARD_CS_PIN);
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
            if (spiStarted) {
                sdSpi.end();
                spiStarted = false;
            }
            digitalWrite(SDCARD_CS_PIN, HIGH);
            delay(80);
            continue;
        }

        if (SD.cardType() == CARD_NONE) {
            status.initCode = 3;
            Serial.printf("[SD] %lu kHz: CARD_NONE\n",
                          static_cast<unsigned long>(freq[i] / 1000UL));
            SD.end();
            if (spiStarted) {
                sdSpi.end();
                spiStarted = false;
            }
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

    SD.end();
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

# Remove every generated/previous mountSdAdaptive implementation. This is
# deliberate: apply_sd_format_tools.py executes immediately before this script
# and can re-add its older helper on a previously patched local checkout.
removed = 0
while True:
    start = text.find(FUNCTION_SIG)
    if start < 0:
        break
    # Include our marker comment if it directly precedes the function.
    line_start = text.rfind("\n", 0, start) + 1
    prev_line_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
    prefix = text[prev_line_start:line_start]
    if prefix.startswith("// SD_MOUNT_REGRESSION_FIX_"):
        start = prev_line_start
    end = function_end(text, text.find(FUNCTION_SIG, start))
    text = text[:start] + text[end:]
    removed += 1

# Insert exactly one canonical helper inside the anonymous namespace, directly
# before initSdLogger(). This works both on a clean source tree and on an
# in-place workspace left by an earlier PlatformIO build.
init_pos = text.find(INIT_SIG)
if init_pos < 0:
    raise RuntimeError("SD mount normalizer: initSdLogger() anchor not found")
namespace_end = text.rfind("} // namespace", 0, init_pos)
if namespace_end < 0:
    raise RuntimeError("SD mount normalizer: namespace end anchor not found")
text = text[:namespace_end] + helper + text[namespace_end:]

# Ensure the public remount API uses the normalized helper even if the format
# pre-script found an old baseline implementation in this checkout.
remount_pos = text.find(REMOUNT_SIG)
if remount_pos < 0:
    raise RuntimeError("SD mount normalizer: remountSdLogger() not found")
remount_end = function_end(text, remount_pos)
remount = "bool remountSdLogger() {\n    return mountSdAdaptive(false);\n}\n\n"
text = text[:remount_pos] + remount + text[remount_end:]

p.write_text(text, encoding="utf-8")
print(
    "SD mount normalizer: OK; removed %u old helper(s), "
    "installed explicit-CS HSPI 8/4/2/1/0.4 MHz" % removed
)
