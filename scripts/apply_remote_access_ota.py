Import("env")

from pathlib import Path
import re

# SCons-safe entry point for the AdminSensor Remote integration.
# The implementation remains a normal Python module-like script and receives
# an explicit __file__ so its existing project-root logic works under both
# PlatformIO/SCons and normal Python inspection.
root = Path(env.subst("$PROJECT_DIR"))

# Give the remote tunnel a little more transient headroom without changing the
# flash partition table (important: existing devices must remain OTA-compatible
# with the current min_spiffs layout). The pass is idempotent for same-workspace
# rebuilds performed by CI.
remote_path = root / "src" / "remote_access.cpp"
remote_text = remote_path.read_text(encoding="utf-8")
old_limits = "constexpr size_t MAX_REQ=12288U, MAX_RESP=24576U, MAX_WS=38000U;"
new_limits = "constexpr size_t MAX_REQ=16384U, MAX_RESP=28672U, MAX_WS=42000U;"
if old_limits in remote_text:
    remote_text = remote_text.replace(old_limits, new_limits, 1)
elif new_limits not in remote_text:
    raise RuntimeError("Remote memory limits: expected limits anchor missing")
remote_path.write_text(remote_text, encoding="utf-8")
print("AdminSensor Remote limits: request 16 KiB, response 28 KiB, WebSocket 42 kB")

impl = root / "scripts" / "apply_remote_access_ota_impl.py"
scope = {"__file__": str(impl), "__name__": "__main__"}
exec(compile(impl.read_text(encoding="utf-8"), str(impl), "exec"), scope, scope)

# Keep the pre-existing SD dashboard pass idempotent on PlatformIO's mandatory
# second build. The Remote implementation originally appended 'remote' to the
# shared cfg-page loop, which changed the exact semantic anchor used by the SD
# pass on the next build. Handle the Remote page independently instead: the
# normal loop remains unchanged, while this toggle activates/deactivates the
# Remote page and the existing remote loader still runs only when selected.
dash_path = root / "web" / "dashboard.html"
dash = dash_path.read_text(encoding="utf-8")
dash = re.sub(
    r"(for\(const x of \[[^\]]*),\s*'remote'(\]\))",
    r"\1\2",
    dash,
    count=1,
)
remote_toggle = "const rp=E('cfgRemote');if(rp)rp.classList.toggle('active',t==='remote');"
if remote_toggle not in dash:
    anchor = "function showCfgTab(t){"
    if anchor not in dash:
        raise RuntimeError("Remote integration: showCfgTab anchor missing for idempotence bridge")
    dash = dash.replace(anchor, anchor + remote_toggle, 1)
dash_path.write_text(dash, encoding="utf-8")
