Import("env")
from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
d = path.read_text(encoding="utf-8")

# apply_sd_webui_browser.py is deliberately a late final-state pass. Earlier
# generators may reformat showCfgTab() (spaces/newlines and extra SYSTEM/I2C
# toggles), so normalize only the function/loop prefix that the late pass uses
# as an idempotence anchor. Do not change the loop body or any loader logic.
func = re.search(r"function\s+showCfgTab\s*\(\s*t\s*\)\s*\{", d)
if not func:
    raise RuntimeError("SD browser anchor repair: showCfgTab function missing")

# Bound the search to the showCfgTab function area. setFresh() is the stable
# next function in the dashboard; a 4 KiB fallback keeps accidental matches out.
next_func = d.find("function setFresh", func.end())
end = next_func if next_func >= 0 else min(len(d), func.end() + 4096)
segment = d[func.end():end]
loop = re.search(
    r"for\s*\(\s*const\s+x\s+of\s+\[([^\]]*)\]\s*\)",
    segment,
)
if not loop:
    # Fallback for generated dashboards where another small helper was inserted
    # before setFresh(): select the configuration loop by its canonical tokens.
    candidate = None
    for m in re.finditer(r"for\s*\(\s*const\s+x\s+of\s+\[([^\]]*)\]\s*\)", d):
        items = m.group(1)
        if all(tok in items for tok in ("'net'", "'thermo'", "'mqtt'", "'display'", "'lightning'")):
            candidate = m
            break
    if candidate is None:
        raise RuntimeError("SD browser anchor repair: configuration loop missing")
    abs_start, abs_end = candidate.start(), candidate.end()
    items = candidate.group(1)
else:
    abs_start = func.end() + loop.start()
    abs_end = func.end() + loop.end()
    items = loop.group(1)

if "'sd'" not in items:
    if "'display'" in items:
        items = items.replace("'display'", "'display','sd'", 1)
    else:
        items += ",'sd'"

canonical_loop = "for(const x of [" + items + "])"

# If only whitespace separates the function opening brace and loop, canonicalize
# that prefix too; this makes the downstream exact anchor deterministic. If a
# real statement exists before the loop, leave it in place and instead create a
# canonical function prefix by moving whitespace only -- never reorder code.
between = d[func.end():abs_start]
if between.strip():
    # The downstream script's old regex cannot consume a prelude. In that case
    # it is safer to normalize just the loop and let a compatibility sentinel
    # immediately after the function opener satisfy its semantic check.
    d = d[:abs_start] + canonical_loop + d[abs_end:]
    # A real prelude is unexpected in current generators; report clearly rather
    # than silently deleting or moving executable Javascript.
    print("SD browser anchor repair: showCfgTab has prelude; loop normalized without reordering")
else:
    d = d[:func.start()] + "function showCfgTab(t){" + canonical_loop + d[abs_end:]
    print("SD browser anchor repair: showCfgTab loop canonicalized")

path.write_text(d, encoding="utf-8")
