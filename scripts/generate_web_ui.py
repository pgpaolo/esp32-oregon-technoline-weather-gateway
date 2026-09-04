Import("env")

from pathlib import Path
import gzip


project_dir = Path(env.subst("$PROJECT_DIR"))
pioenv = env.subst("$PIOENV")
build_root = Path(env.subst("$BUILD_DIR"))
generated_dir = build_root / pioenv / "generated"
generated_dir.mkdir(parents=True, exist_ok=True)

source_path = project_dir / "web" / "dashboard.html"
payload = gzip.compress(source_path.read_bytes(), compresslevel=9, mtime=0)

rows = []
for offset in range(0, len(payload), 16):
    chunk = payload[offset : offset + 16]
    rows.append("    " + ", ".join(f"0x{value:02X}" for value in chunk) + ",")

header_content = (
    "#pragma once\n"
    "// Auto-generated from web/dashboard.html; deterministic gzip (mtime=0).\n"
    "static const uint8_t WEB_UI_GZ[] PROGMEM = {\n"
    + "\n".join(rows)
    + "\n};\n"
    + f"static constexpr size_t WEB_UI_GZ_LEN = {len(payload)}U;\n"
)

header_path = generated_dir / "web_ui_generated.h"
if not header_path.exists() or header_path.read_text(encoding="ascii") != header_content:
    header_path.write_text(header_content, encoding="ascii", newline="\n")

env.Append(CPPPATH=[str(generated_dir)])
print(f"Compressed Web UI: {source_path.stat().st_size} -> {len(payload)} bytes")
