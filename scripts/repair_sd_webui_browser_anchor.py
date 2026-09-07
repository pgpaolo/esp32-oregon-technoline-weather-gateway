Import("env")
from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
d = path.read_text(encoding="utf-8")

# apply_sd_webui_browser.py is deliberately a late final-state pass. Earlier
# generators may reformat showCfgTab() and the I2C/HW pass intentionally adds
# executable statements before the historical configuration loop. Normalize
# the real loop semantically and provide a harmless compatibility loop only
# when that prelude prevents the downstream legacy anchor from matching.
func = re.search(r"function\s+showCfgTab\s*\(\s*t\s*\)\s*\{", d)
if not func:
    raise RuntimeError("SD browser anchor repair: showCfgTab function missing")

next_func = d.find("function setFresh", func.end())
end = next_func if next_func >= 0 else min(len(d), func.end() + 4096)
segment = d[func.end():end]
loop = re.search(
    r"for\s*\(\s*const\s+x\s+of\s+\[([^\]]*)\]\s*\)",
    segment,
)
if not loop:
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

between = d[func.end():abs_start]
if between.strip():
    # Keep the I2C/HW (or future) prelude exactly where it is. First normalize
    # the real configuration loop so MICROSD is actually toggled. Then insert a
    # no-op one-iteration loop directly after the function opener solely as a
    # compatibility anchor for the older final SD pass. It has no side effects
    # and avoids reordering executable dashboard logic.
    d = d[:abs_start] + canonical_loop + d[abs_end:]
    func2 = re.search(r"function\s+showCfgTab\s*\(\s*t\s*\)\s*\{", d)
    if not func2:
        raise RuntimeError("SD browser anchor repair: showCfgTab lost after normalization")
    sentinel = "for(const x of ['sd']){}"
    if d[func2.end():].startswith(sentinel):
        pass
    else:
        d = d[:func2.start()] + "function showCfgTab(t){" + sentinel + d[func2.end():]
    print("SD browser anchor repair: real SD loop fixed; I2C prelude preserved")
else:
    d = d[:func.start()] + "function showCfgTab(t){" + canonical_loop + d[abs_end:]
    print("SD browser anchor repair: showCfgTab loop canonicalized")

path.write_text(d, encoding="utf-8")
