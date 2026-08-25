from pathlib import Path

PATH = Path("src/weather_parser.cpp")
text = PATH.read_text(encoding="utf-8")

old_digits = """            uint8_t n[11];
            const uint8_t idx[] = {18,17,16,15,14,13,8,9,10,11,12};
            for (uint8_t i = 0; i < 11; ++i) if (!decimalNybble(packet, idx[i], n[i])) return false;
"""
new_digits = """            // PCR800/2914: total rain is nibbles 17..12 and rain rate is
            // nibbles 11..8 in the protocol payload. This legacy buffer has the
            // sync nibble at index 0, therefore the corresponding indexes are
            // 18..13 for total and 12..9 for rate. Both fields are BCD, LSD first.
            uint8_t n[10];
            const uint8_t idx[] = {18,17,16,15,14,13,12,11,10,9};
            for (uint8_t i = 0; i < 10; ++i) if (!decimalNybble(packet, idx[i], n[i])) return false;
"""

old_rate = """            const uint32_t rateRaw =
                static_cast<uint32_t>(n[6]) * 10000UL + static_cast<uint32_t>(n[7]) * 1000UL +
                static_cast<uint32_t>(n[8]) * 100UL + static_cast<uint32_t>(n[9]) * 10UL + n[10];
"""
new_rate = """            const uint32_t rateRaw =
                static_cast<uint32_t>(n[6]) * 1000UL + static_cast<uint32_t>(n[7]) * 100UL +
                static_cast<uint32_t>(n[8]) * 10UL + n[9];
"""

changed = False
if old_digits in text:
    text = text.replace(old_digits, new_digits, 1)
    changed = True
elif new_digits not in text:
    raise RuntimeError("PCR800 rain-rate fix: digit-layout anchor not found")

if old_rate in text:
    text = text.replace(old_rate, new_rate, 1)
    changed = True
elif new_rate not in text:
    raise RuntimeError("PCR800 rain-rate fix: rate formula anchor not found")

# Guard against the two regressions that caused the observed ~10x / reversed value:
# - flags nibble 8 must never be part of rain rate;
# - PCR800 rain rate is four BCD digits, not five.
if "{18,17,16,15,14,13,8,9,10,11,12}" in text:
    raise RuntimeError("PCR800 rain-rate fix: flags nibble still included")
if "static_cast<uint32_t>(n[6]) * 10000UL" in text:
    raise RuntimeError("PCR800 rain-rate fix: five-digit rate formula still present")

if changed:
    PATH.write_text(text, encoding="utf-8")
    print("[PCR800] corrected rain-rate BCD nibble order (12..9, four digits)")
else:
    print("[PCR800] rain-rate decoder already corrected")
