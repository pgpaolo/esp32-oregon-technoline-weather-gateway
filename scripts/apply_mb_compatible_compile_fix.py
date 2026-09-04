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

# Fail if neither the source form nor the corrected form is recognizable.
required = [
    'static const char HEX_DIGITS[] = "0123456789ABCDEF";',
    'String(value, static_cast<unsigned int>(decimals))',
]
for marker in required:
    if marker not in text:
        raise RuntimeError(f"MB-compatible compile compatibility marker missing: {marker}")

path.write_text(text, encoding="utf-8")
print("MB-compatible Arduino compile compatibility:" + (" patched" if changed else " already clean"))
