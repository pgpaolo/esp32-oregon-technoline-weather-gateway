Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))

# ---------------------------------------------------------------------------
# C++ Web routes
# ---------------------------------------------------------------------------
path = root / "src/web_manager.cpp"
text = path.read_text(encoding="utf-8")

# A few older SD pre-scripts use the literal route declarations as idempotence
# anchors on the second PlatformIO build in the same workspace.  The generic
# Web-auth patch wraps routes in lambdas, which is functionally correct but
# hides those anchors.  Keep these selected declarations in their historical
# shape and enforce authentication inside their handlers instead.
routes = [
    ("/api/network/reset", "HTTP_POST", "handleNetworkConfigReset"),
    ("/api/sd", "HTTP_GET", "handleSdConfigGet"),
    ("/api/sd", "HTTP_POST", "handleSdConfigPost"),
    ("/api/sd/reset", "HTTP_POST", "handleSdConfigReset"),
    ("/api/sd/remount", "HTTP_POST", "handleSdRemount"),
    ("/api/sd/format", "HTTP_POST", "handleSdFormat"),
]

changed = False
for url, method, handler in routes:
    wrapped = (
        f'    server.on("{url}", {method}, [](){{ if (!requireWebAuth()) return; '
        f'{handler}(); }});\n'
    )
    direct = f'    server.on("{url}", {method}, {handler});\n'
    if wrapped in text:
        text = text.replace(wrapped, direct, 1)
        changed = True

    signature = f"void {handler}() {{\n"
    guarded = signature + "    if (!requireWebAuth()) return;\n"
    if signature in text and guarded not in text:
        text = text.replace(signature, guarded, 1)
        changed = True

path.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Dashboard configuration-tab loop
# ---------------------------------------------------------------------------
# apply_sd_datalogger.py also uses the literal configuration-tab loop as a
# second-build marker.  Keep its historical list intact and handle the new
# SYSTEM tab with two explicit class toggles outside that loop.  Functionality
# is identical, while a second PlatformIO invocation can still recognize the
# already-generated microSD UI.
dash_path = root / "web/dashboard.html"
dash = dash_path.read_text(encoding="utf-8")
with_system = "for(const x of ['net','thermo','mqtt','display','sd','lightning','backup','system'])"
stable_loop = "for(const x of ['net','thermo','mqtt','display','sd','lightning','backup'])"
if with_system in dash:
    dash = dash.replace(with_system, stable_loop, 1)
    changed = True

system_toggle = "E('cfgSystem').classList.toggle('active',t==='system');E('tabSystem').classList.toggle('active',t==='system');"
if "function showCfgTab(t){" in dash and system_toggle not in dash:
    anchor = "}if(t==='net')"
    if anchor not in dash:
        raise RuntimeError("Web auth idempotence: showCfgTab loader anchor missing")
    dash = dash.replace(anchor, "}" + system_toggle + "if(t==='net')", 1)
    changed = True

dash_path.write_text(dash, encoding="utf-8")
print("Web auth idempotence: SD/network anchors and config loop restored" + (" with changes" if changed else " (already stable)"))
