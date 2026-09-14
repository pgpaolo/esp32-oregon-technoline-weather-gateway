Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "mb_compatible_publisher.cpp"
text = path.read_text(encoding="utf-8")

# Arduino Print.h defines HEX as the numeric base macro (16). Runtime Memory V3
# originally used HEX as the URL-encoder digit table identifier, which collides
# at preprocessing time. Rename only the generated V3 encoder symbols; runtime
# behavior and allocation sizing remain unchanged.
old_decl = 'static const char HEX[] = "0123456789ABCDEF";'
new_decl = 'static const char HEX_DIGITS[] = "0123456789ABCDEF";'

if old_decl in text:
    text = text.replace(old_decl, new_decl, 1)
    text = text.replace('out += HEX[(c >> 4) & 0x0FU];', 'out += HEX_DIGITS[(c >> 4) & 0x0FU];', 1)
    text = text.replace('out += HEX[c & 0x0FU];', 'out += HEX_DIGITS[c & 0x0FU];', 1)
elif new_decl not in text:
    raise RuntimeError("Runtime memory V3 compile fix: URL encoder table anchor missing")

path.write_text(text, encoding="utf-8")
print("Runtime memory V3 compile fix: Arduino HEX macro collision removed")
