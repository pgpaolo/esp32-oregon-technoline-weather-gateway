Import("env")

from pathlib import Path
import gzip
import re

# SCons-safe entry point for the AdminSensor Remote integration.
# The implementation remains a normal Python module-like script and receives
# an explicit __file__ so its existing project-root logic works under both
# PlatformIO/SCons and normal Python inspection.
root = Path(env.subst("$PROJECT_DIR"))

# Size the transient tunnel buffers from the *actual* Web UI that will be
# embedded in this build. This avoids a fixed response ceiling becoming stale
# as dashboard.html grows, while keeping a bounded heap budget on classic ESP32.
#
# The local Web UI is always served gzip-compressed. Keep 8 KiB of response
# headroom above the deterministic gzip payload and 4 KiB above the Base64 JSON
# WebSocket expansion. Limits are rounded to 4 KiB boundaries. If the dashboard
# ever grows enough to require unsafe buffers, fail the build instead of
# silently shipping a tunnel that cannot serve the UI reliably.
dashboard_path = root / "web" / "dashboard.html"
dashboard_gz_len = len(gzip.compress(dashboard_path.read_bytes(), compresslevel=9, mtime=0))


def round_up(value, block=4096):
    return ((value + block - 1) // block) * block


max_req = 16384
max_resp = max(40960, round_up(dashboard_gz_len + 8192))
base64_resp = ((max_resp + 2) // 3) * 4
max_ws = max(57344, round_up(base64_resp + 4096))

if max_resp > 65536 or max_ws > 98304:
    raise RuntimeError(
        f"Remote tunnel buffers would be unsafe: gzip={dashboard_gz_len}, "
        f"response={max_resp}, websocket={max_ws}"
    )

remote_path = root / "src" / "remote_access.cpp"
remote_text = remote_path.read_text(encoding="utf-8")
limits_re = re.compile(
    r"constexpr size_t MAX_REQ=\d+U, MAX_RESP=\d+U, MAX_WS=\d+U;"
)
new_limits = (
    f"constexpr size_t MAX_REQ={max_req}U, "
    f"MAX_RESP={max_resp}U, MAX_WS={max_ws}U;"
)
remote_text, replacements = limits_re.subn(new_limits, remote_text, count=1)
if replacements != 1:
    raise RuntimeError("Remote memory limits: expected limits anchor missing")
remote_path.write_text(remote_text, encoding="utf-8")
print(
    "AdminSensor Remote limits: "
    f"dashboard gzip {dashboard_gz_len} B, request {max_req // 1024} KiB, "
    f"response {max_resp // 1024} KiB, WebSocket {max_ws // 1024} KiB"
)

impl = root / "scripts" / "apply_remote_access_ota_impl.py"
scope = {"__file__": str(impl), "__name__": "__main__"}
exec(compile(impl.read_text(encoding="utf-8"), str(impl), "exec"), scope, scope)

# Keep the Oregon-specific asynchronous HTTP worker and guarded OTA, but apply
# the WSS lifecycle proven on esp32-davis-weather-gateway/develop-optimized:
# shorter reconnect/enroll cadence, Wi-Fi sleep disabled while tunnelling,
# transport heartbeat plus application-level presence ping, and intentional
# disconnect tracking so planned reconnects do not look like failures.
reconnect = root / "scripts" / "apply_remote_reconnect_hardening.py"
reconnect_scope = {
    "__file__": str(reconnect),
    "__name__": "__main__",
    "env": env,
    # The pass is executed inside this already-imported SCons script. It has
    # the env object explicitly, so its standalone Import("env") can be a no-op.
    "Import": lambda *args: None,
}
exec(compile(reconnect.read_text(encoding="utf-8"), str(reconnect), "exec"), reconnect_scope, reconnect_scope)
