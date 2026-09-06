Import("env")

from pathlib import Path

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
