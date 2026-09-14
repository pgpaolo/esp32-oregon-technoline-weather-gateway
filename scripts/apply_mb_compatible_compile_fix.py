Import("env")
from pathlib import Path

path = Path(env.subst("$PROJECT_DIR")) / "src/mb_compatible_publisher.cpp"
text = path.read_text(encoding="utf-8")
changed = False

replacements = [
    ('static const char HEX[] = "0123456789ABCDEF";', 'static const char HEX_DIGITS[] = "0123456789ABCDEF";'),
    ('out += HEX[(c >> 4) & 0x0FU];', 'out += HEX_DIGITS[(c >> 4) & 0x0FU];'),
    ('out += HEX[c & 0x0FU];', 'out += HEX_DIGITS[c & 0x0FU];'),
    ('String(value, decimals)', 'String(value, static_cast<unsigned int>(decimals))'),
]
for old, new in replacements:
    if old in text:
        text = text.replace(old, new)
        changed = True

# The historical generator used String(value, decimals), which needed an
# Arduino overload cast. Runtime Memory V3 deliberately removes that allocating
# helper entirely and appends formatted values directly into the reserved MB
# payload. Accept either representation so repeated PlatformIO builds remain
# compatible while still failing on an unknown/corrupt source shape.
if 'static const char HEX_DIGITS[] = "0123456789ABCDEF";' not in text:
    raise RuntimeError("MB-compatible compile compatibility marker missing: HEX_DIGITS")

legacy_float_builder = 'String(value, static_cast<unsigned int>(decimals))' in text
v3_float_builder = (
    'RUNTIME_MEMORY_V3_MB' in text
    and 'bool appendFloatField(String &out, float value, uint8_t decimals)' in text
    and 'bool appendFieldValue(String &out, size_t index' in text
)
if not legacy_float_builder and not v3_float_builder:
    raise RuntimeError("MB-compatible compile compatibility: neither legacy nor Runtime Memory V3 field builder found")

path.write_text(text, encoding="utf-8")
mode = "Runtime Memory V3" if v3_float_builder else "legacy"
print("MB-compatible Arduino compile compatibility:" + (" patched" if changed else " already clean") + f" ({mode})")
