"""Final, idempotent MBFIX2 TLS / TASK_WDT risk guard.

Late PlatformIO generators canonicalize MB performHttp on every build.
This pass MUST be last and works on pristine and previously-built checkouts.
No changes to radio decoders, rain data, NVS, or OTA behavior.
"""
Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))

def update(path, pairs):
    f = root / path
    s = f.read_text(encoding="utf-8")
    original = s
    for old, new in pairs:
        if new in s:
            continue
        count = s.count(old)
        if count != 1:
            raise RuntimeError(f"MBFIX2 TLS guard: {path} missing/duplicate anchor {count}: {old[:64]}")
        s = s.replace(old, new, 1)
    if s != original:
        f.write_text(s, encoding="utf-8")
        print(f"MBFIX2 TLS guard updated {path}")
    else:
        print(f"MBFIX2 TLS guard already applied {path}")

update("src/remote_access.cpp", [
    ("    bool active=false;\n    if(take()){active=st.transportActive;give();}\n    if(!active)return false;\n", "    // MBFIX2_TLS_WDT_GUARD_V2: no WSS task -> no competing TLS transport.\n    // If it exists, coordinate even when disconnected: it may be connecting.\n    if(!taskHandle)return true;\n"),
])
update("src/mb_compatible_publisher.cpp", [
    ("        const bool remotePaused = blockInitial < MB_TLS_HEAP_PAUSE_THRESHOLD &&\n                                  remoteAccessPauseForExternalTls(2000U);\n        // LILYGO_STABILITY_TLS_GUARD_V1: prefer an omitted report to MCU reset.\n        if(blockInitial < MB_TLS_HEAP_PAUSE_THRESHOLD && !remotePaused){\n            setStatusError(\"HTTPS deferred: insufficient contiguous heap for a second TLS session\");\n            gBusy=false;\n            return;\n        }\n", "        // MBFIX2_TLS_WDT_GUARD_V2: serialize WSS and MB HTTPS handshakes.\n        // A false pause return used to mean \"remote not connected\"; the Remote\n        // API now returns true in that case, but still blocks during OTA.\n        const bool remotePaused = remoteAccessPauseForExternalTls(2000U);\n        // LILYGO_STABILITY_TLS_GUARD_V1: never force TLS into a fragmented heap.\n        if (!remotePaused) {\n            setStatusError(\"HTTPS deferred: remote TLS arbitration unavailable\");\n            gBusy = false;\n            return;\n        }\n        const uint32_t heapAfterPause = ESP.getFreeHeap();\n        const uint32_t blockAfterPause = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);\n        // Heap figures are a preflight, not a guarantee that mbedTLS will fit.\n        // Do not lower the proven 32 KiB contiguous threshold after a TASK_WDT.\n        constexpr uint32_t MB_TLS_MIN_FREE_HEAP = 49152U;\n        if (blockAfterPause < MB_TLS_HEAP_PAUSE_THRESHOLD ||\n            heapAfterPause < MB_TLS_MIN_FREE_HEAP) {\n            setStatusError(\"HTTPS deferred: insufficient heap after TLS arbitration\");\n            remoteAccessResumeAfterExternalTls();\n            gBusy = false;\n            return;\n        }\n"),
    ("        setStatusError(\"endpoint URL missing or invalid\");\n        gForceTest = false;\n        return;", "        setStatusError(\"endpoint URL missing or invalid\");\n        // MBFIX2_TLS_WDT_GUARD_V2: prevent a config error retrying each loop.\n        gLastScheduleMs = now;\n        gForceTest = false;\n        return;"),
    ("    if (!buildPayload(snapshot, cfg, payload, error)) {\n        setStatusError(error);\n        if (error.startsWith(\"no fresh meteorological measurements\")) {", "    if (!buildPayload(snapshot, cfg, payload, error)) {\n        setStatusError(error);\n        // MBFIX2_TLS_WDT_GUARD_V2: bounded retry for NTP/UTC failures.\n        if (!error.startsWith(\"no fresh meteorological measurements\")) {\n            gLastScheduleMs = now;\n            gForceTest = false;\n        }\n        if (error.startsWith(\"no fresh meteorological measurements\")) {"),
    ("        gLastError = error;\n        xSemaphoreGive(gMutex);", "        gLastError = error;\n        // Deferred HTTPS is not the stale HTTP 200 from a previous attempt.\n        if (error.startsWith(\"HTTPS deferred:\")) {\n            gLastHttpCode = 0;\n            gLastResponse = \"\";\n        }\n        xSemaphoreGive(gMutex);"),
])
