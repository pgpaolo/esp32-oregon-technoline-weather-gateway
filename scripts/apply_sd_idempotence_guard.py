Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def remove_following_duplicate(path, marker, anchor, label):
    """Keep the first generated section and remove later copies before anchor.

    PlatformIO pre-scripts patch source files in-place. The SD format patch
    intentionally changes the first SD section, so the base datalogger patch
    can otherwise insert the original section again on a later local build.
    Clean that generated duplicate before compilation.
    """
    p = root / path
    text = p.read_text(encoding="utf-8")
    changed = False

    while text.count(marker) > 1:
        first = text.find(marker)
        duplicate = text.find(marker, first + len(marker))
        end = text.find(anchor, duplicate)
        if duplicate < 0 or end < 0:
            raise RuntimeError(f"SD idempotence guard cannot delimit {label} in {path}")
        text = text[:duplicate] + text[end:]
        changed = True

    if changed:
        p.write_text(text, encoding="utf-8")
        print(f"SD idempotence guard: removed duplicate {label} from {path}")


# C++ endpoint block: the preserved first copy contains the FORMAT handler
# added by apply_sd_format_tools.py; repeated base copies are just before the
# thermo handlers.
remove_following_duplicate(
    "src/web_manager.cpp",
    "void handleSdConfigGet() {",
    "void handleThermoConfigGet() {",
    "Web handlers",
)

# Dashboard SD page: keep the first (format-enabled) page and remove any base
# page reinserted immediately before the Lightning configuration page.
remove_following_duplicate(
    "web/dashboard.html",
    '<div id="cfgSd" class="cfgPage">',
    '<div id="cfgLightning" class="cfgPage">',
    "dashboard page",
)

# Dashboard JavaScript: keep the first SD implementation (which includes
# formatSd()) and remove a reinserted base block before the display helpers.
remove_following_duplicate(
    "web/dashboard.html",
    "function sdBytes(v){",
    "function dSet(attr,mask){",
    "dashboard JavaScript",
)
