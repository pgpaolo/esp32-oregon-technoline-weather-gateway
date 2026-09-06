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

# ---------------------------------------------------------------------------
# Oregon-specific follow-up to the Davis gzip/Base64 fix.
#
# The Oregon dashboard is materially larger than the Davis dashboard. The
# proven Davis implementation already avoids a second Base64 copy, but it kept
# LocalResp::body allocated until after the TLS/WSS write. Once the complete
# JSON frame has been assembled, the original gzip body is no longer needed.
# Release that vector before ws.sendTXT() so WiFiClientSecure/TCP has maximum
# contiguous heap available while transmitting the large frame.
# ---------------------------------------------------------------------------
remote_text = remote_path.read_text(encoding="utf-8")
old_sig = "void sendResp(const String&id,const LocalResp&r){"
new_sig = "void sendResp(const String&id,LocalResp&r){"
if old_sig in remote_text:
    remote_text = remote_text.replace(old_sig, new_sig, 1)
elif new_sig not in remote_text:
    raise RuntimeError("Remote heap release: sendResp signature anchor missing")

release_stmt = "std::vector<uint8_t>().swap(r.body);"
if release_stmt not in remote_text:
    release_anchor = (
        'if(o.length()!=finalLen){if(take()){st.lastError="Frame risposta remota incompleto";'
        'give();}return;}'
    )
    if release_anchor not in remote_text:
        raise RuntimeError("Remote heap release: final-frame anchor missing")
    remote_text = remote_text.replace(
        release_anchor,
        release_anchor + release_stmt,
        1,
    )
remote_path.write_text(remote_text, encoding="utf-8")
print("AdminSensor Remote heap: gzip body released before TLS/WSS frame write")

# ---------------------------------------------------------------------------
# Remote OTA image-type guard.
#
# Checking only byte 0 == 0xE9 is insufficient: ESP32 bootloader images also
# start with the ESP image magic and a merged/full-flash image can therefore be
# written into an OTA app slot. An application image carries the ESP app
# descriptor magic 0xABCD5432 at fixed offset 32 (24-byte image header + 8-byte
# first segment header). Reject anything else before the first flash write.
# This protects NVS/network configuration indirectly by preventing a bad OTA
# slot from being selected and making a healthy device appear to have lost IP.
# ---------------------------------------------------------------------------
ota_path = root / "src" / "remote_firmware_update.cpp"
ota_text = ota_path.read_text(encoding="utf-8")
helper_name = "looksLikeOtaApplication"
if helper_name not in ota_text:
    helper = '''constexpr size_t OTA_APP_DESC_OFFSET = 32U;\nconstexpr uint32_t OTA_APP_DESC_MAGIC = 0xABCD5432UL;\n\nbool looksLikeOtaApplication(const uint8_t *data, size_t len) {\n    if (!data || len < OTA_APP_DESC_OFFSET + sizeof(uint32_t)) return false;\n    if (data[0]!=0xE9U) return false;\n    const uint32_t magic =\n        static_cast<uint32_t>(data[OTA_APP_DESC_OFFSET]) |\n        (static_cast<uint32_t>(data[OTA_APP_DESC_OFFSET + 1U]) << 8) |\n        (static_cast<uint32_t>(data[OTA_APP_DESC_OFFSET + 2U]) << 16) |\n        (static_cast<uint32_t>(data[OTA_APP_DESC_OFFSET + 3U]) << 24);\n    return magic == OTA_APP_DESC_MAGIC;\n}\n\n'''
    anchor = "String shaHex(const unsigned char digest[32]) {"
    if anchor not in ota_text:
        raise RuntimeError("Remote OTA image guard: shaHex anchor missing")
    ota_text = ota_text.replace(anchor, helper + anchor, 1)

old_first_chunk = '''    if (firstChunk) {\n        firstChunk=false;\n        if (data[0]!=0xE9U) {\n            const bool r=failRemoteLocked("File non riconosciuto come immagine firmware ESP32",error);unlock();return r;\n        }\n    }'''
new_first_chunk = '''    if (firstChunk) {\n        firstChunk=false;\n        if (!looksLikeOtaApplication(data,len)) {\n            const bool r=failRemoteLocked("File OTA non valido: usare firmware.bin applicativo, non bootloader/partitions/merged",error);unlock();return r;\n        }\n    }'''
if old_first_chunk in ota_text:
    ota_text = ota_text.replace(old_first_chunk, new_first_chunk, 1)
elif new_first_chunk not in ota_text:
    raise RuntimeError("Remote OTA image guard: first-chunk anchor missing")

ota_path.write_text(ota_text, encoding="utf-8")
print("Remote OTA safety: application-image descriptor validation enabled")
