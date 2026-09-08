#!/usr/bin/env python3
"""Integration guard for AdminSensor Remote and local/remote OTA arbitration."""
from pathlib import Path
import gzip

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def require(haystack, needle, label):
    if needle not in haystack:
        raise SystemExit(f"REMOTE GUARD FAILED: missing {label}: {needle}")


def forbid(haystack, needle, label):
    if needle in haystack:
        raise SystemExit(f"REMOTE GUARD FAILED: forbidden {label}: {needle}")


pio = text("platformio.ini")
main = text("src/main.cpp")
web = text("src/web_manager.cpp")
webh = text("src/web_manager.h")
security = text("src/web_security.cpp")
remote = text("src/remote_access.cpp")
ota = text("src/remote_firmware_update.cpp")
dash = text("web/dashboard.html")

require(pio, 'FIRMWARE_VERSION=\\"6.4.0-rc6\\"', "RC6 firmware identity")
require(pio, "links2004/WebSockets@2.6.1", "WebSockets dependency")
require(pio, "bblanchon/ArduinoJson@7.4.2", "ArduinoJson dependency")
require(pio, "pre:scripts/repair_remote_heap_pre.py", "repeat-build remote heap repair pass")
require(pio, "pre:scripts/apply_remote_access_ota.py", "late remote integration pass")
require(pio, "pre:scripts/apply_remote_dynamic_response_fix.py", "Oregon dynamic response heap pass")
require(pio, "pre:scripts/apply_remote_ui_polling.py", "remote UI polling/JSON pass")

require(main, '#include "remote_access.h"', "remote main include")
require(main, "initRemoteAccess();", "remote initialization")
require(main, "serviceRemoteFirmwareUpdate();", "remote OTA reboot service")
require(webh, "bool webStarted();", "Web readiness API")
require(webh, "const uint8_t *webUiGzipData();", "flash Web UI data accessor")
require(webh, "size_t webUiGzipSize();", "flash Web UI size accessor")
require(web, "bool webStarted() { return webStartedFlag; }", "Web readiness implementation")
require(web, "webUiGzipData() { return WEB_UI_GZ; }", "flash Web UI data implementation")
require(web, "webUiGzipSize() { return WEB_UI_GZ_LEN; }", "flash Web UI size implementation")
require(web, 'server.on("/api/remote/config"', "remote config route")
require(web, 'server.on("/api/remote/status"', "remote status route")
require(web, 'server.on("/api/firmware/remote-status"', "remote firmware status route")
require(web, "firmwareLocalBeginGuard", "local OTA arbitration begin")
require(web, "firmwareLocalReleaseGuard", "local OTA arbitration release")
require(security, "webSecurityInternalAuthorizationHeader", "internal loopback auth")

require(remote, 'ws.setExtraHeaders(wsAuth.c_str())', "Bearer WSS authentication")
require(remote, 'c.setCACert(REMOTE_TRUST_CA)', "TLS CA validation")
require(remote, 'q["firmware_version"]=FIRMWARE_VERSION', "enrollment firmware version")
require(remote, 'type=="firmware_begin"', "remote OTA begin protocol")
require(remote, 'type=="firmware_chunk"', "remote OTA chunk protocol")
require(remote, 'type=="firmware_end"', "remote OTA end protocol")
require(remote, 'firmwareRemoteAbort("Connessione AdminSensor interrotta durante OTA")', "disconnect abort")

# Classic ESP32 heap safety. The root dashboard is zero-copy from flash. Normal
# dynamic replies retain the 24 KiB cap and are sent as 2 KiB raw chunks. The
# large Oregon /api/state loopback body is now segmented into independent 2 KiB
# allocations, so opening the remote dashboard no longer requires a second
# contiguous ~9 KiB vector while WSS/MQTT/RF/SD are resident.
require(remote, "constexpr size_t MAX_REQ=16384U, MAX_RESP=24576U, MAX_WS=38000U;", "bounded tunnel limits")
require(remote, "constexpr UBaseType_t HTTP_QUEUE_LEN=2;", "bounded HTTP queue")
require(remote, "ADMIN_SENSOR_HTTP_CHUNK_V2", "2 KiB dynamic response chunker")
require(remote, "HTTP_RESP_CHUNK_RAW=2048U", "2 KiB dynamic raw chunk")
require(remote, "ADMIN_SENSOR_STATE_SEGMENTED_V1", "segmented /api/state loopback fastpath")
require(remote, "segmentedBody", "segmented state body storage")
require(remote, "STATE_SEGMENT_RAW=2048U", "2 KiB state body segments")
require(remote, 'path=="/api/state" || path.startsWith("/api/state?")', "state-only segmented path")
require(remote, "ADMIN_SENSOR_FLASH_UI_V2", "zero-copy flash Web UI sender")
require(remote, "ADMIN_SENSOR_FLASH_UI_WORKER_V2", "zero-copy Web UI worker path")
require(remote, "ADMIN_SENSOR_FLASH_UI_DRAIN_V2", "zero-copy Web UI reply drain")
require(remote, "FLASH_CHUNK_RAW=2048U", "2 KiB flash Web UI raw chunk")
require(remote, "webUiGzipData()", "flash Web UI data use")
require(remote, "webUiGzipSize()", "flash Web UI size use")
require(remote, "ADMIN_SENSOR_DYNAMIC_HEAP_V4", "Oregon post-reserve heap marker")
require(remote, "Heap contiguo insufficiente per risposta locale", "repeat-build heap compatibility sentinel")
require(remote, "HTTP_POST_RESERVE_CONTIGUOUS=4096U", "4 KiB measured post-reserve block")
require(remote, "HTTP_TOTAL_HEADROOM=16384U", "16 KiB total runtime headroom")
require(remote, "postLargestBlock=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT)", "post-reserve contiguous measurement")
require(remote, "postFreeHeap=ESP.getFreeHeap()", "post-reserve total heap measurement")
require(remote, "std::vector<uint8_t>().swap(r.body);", "release rejected dynamic reserve")
require(remote, "Heap frammentato dopo reserve: need=", "post-reserve diagnostic failure path")
require(remote, 'q->path=="/"||q->path.startsWith("/?")', "root Web UI flash bypass")
forbid(remote, "MAX_RESP=45056U", "old dashboard-sized dynamic response buffer")
forbid(remote, "HTTP_RESP_CHUNK_RAW=4096U", "old 4 KiB transient response chunks")
forbid(remote, "largestBlock-reserveLen<8192U", "old 8 KiB pre-reserve headroom")
forbid(remote, "largestBlock-reserveLen<HTTP_CONTIGUOUS_HEADROOM", "V3 inferred post-reserve fragmentation")

require(ota, "SHA-256 firmware non corrispondente", "remote SHA-256 verification")
require(ota, "sequence!=expectedSequence", "strict remote sequence")
require(ota, "looksLikeOtaApplication", "ESP32 application image validation")
require(ota, "prepareSdLoggerForDeepSleep();", "SD shutdown before remote OTA")
require(dash, 'id="tabRemote"', "Remote config tab")
require(dash, 'id="cfgRemote"', "Remote config page")
require(dash, "AdminSensor Remote", "Remote UI label")
require(dash, "loadRemoteAccess()", "Remote UI state loader")
require(dash, "ADMIN_SENSOR_REMOTE_POLL_V3", "adaptive remote-aware polling")
require(dash, "ADMIN_SENSOR_REMOTE_BOOT_SERIAL_V1", "serialized first remote state load")
require(dash, "safeRefresh(true).finally", "first state before secondary API timers")
require(dash, "ADMIN_SENSOR_FETCH_JSON_V3", "checked JSON transport")
require(dash, "fetchJsonChecked('/api/state')", "checked state fetch")
require(dash, "fetchJsonChecked('/api/mqtt')", "checked MQTT fetch")
require(dash, "fetchJsonChecked('/api/as3935/state')", "checked lightning fetch")
forbid(dash, "device_token", "device token exposure in dashboard")
forbid(dash, "const s=await (await fetch('/api/state'", "unchecked state JSON parsing")

# The dashboard is intentionally larger than the normal dynamic response cap.
# That is safe because root GET is served from flash without an intermediate
# heap allocation; this assertion prevents regression to full buffering.
dash_gz_len = len(gzip.compress((ROOT / "web" / "dashboard.html").read_bytes(), compresslevel=9, mtime=0))
if dash_gz_len <= 24576:
    raise SystemExit("REMOTE GUARD FAILED: test no longer exercises flash-streaming path")

print(
    "AdminSensor Remote + guarded WSS OTA integration: OK "
    f"(dashboard gzip {dash_gz_len} B streamed from flash, /api/state segmented 2 KiB, "
    "dynamic response cap 24 KiB, OTA guarded)"
)
