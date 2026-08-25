from pathlib import Path

MM_PER_COUNT = 0.254  # PCR800 rate LSD = 0.01 in/h = 0.254 mm/h


def decode_rate_mm_h(n9: int, n10: int, n11: int, n12: int) -> float:
    # Legacy parser indexes 9..12 correspond to protocol rate nibbles 8..11.
    # The field is transmitted LSD first, so numeric order is 12,11,10,9.
    raw = n12 * 1000 + n11 * 100 + n10 * 10 + n9
    return raw * MM_PER_COUNT


# 6.77 in/h = 171.958 mm/h, displayed by an Oregon console as about 172.0 mm/h.
# Transmitted BCD nibbles are LSD first: 7, 7, 6, 0.
rate = decode_rate_mm_h(7, 7, 6, 0)
assert abs(rate - 171.958) < 0.001, rate
assert round(rate, 1) == 172.0, rate

src = Path("src/weather_parser.cpp").read_text(encoding="utf-8")
assert "const uint8_t idx[] = {18,17,16,15,14,13,12,11,10,9};" in src
assert "static_cast<uint32_t>(n[6]) * 1000UL" in src
assert "{18,17,16,15,14,13,8,9,10,11,12}" not in src
assert "static_cast<uint32_t>(n[6]) * 10000UL" not in src

print(f"PCR800 rain-rate regression OK: {rate:.3f} mm/h -> {rate:.1f} mm/h")
