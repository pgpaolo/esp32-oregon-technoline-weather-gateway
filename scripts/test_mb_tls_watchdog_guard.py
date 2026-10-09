"""Source safety checks: no direct hardware reset guarantee."""
from pathlib import Path
root=Path(__file__).resolve().parent.parent
mb=(root/"src/mb_compatible_publisher.cpp").read_text(encoding="utf-8")
remote=(root/"src/remote_access.cpp").read_text(encoding="utf-8")
ini=(root/"platformio.ini").read_text(encoding="utf-8")
workflow=(root/".github/workflows/mbfix2-stablebase.yml").read_text(encoding="utf-8")
checks={
    "single TLS arbiter even when WSS connected": "const bool remotePaused = remoteAccessPauseForExternalTls(2000U);" in mb,
    "never initiate TLS after refused pause": 'setStatusError("HTTPS deferred: remote TLS arbitration unavailable");' in mb,
    "32KiB threshold kept": "MB_TLS_HEAP_PAUSE_THRESHOLD = 32768U;" in mb and "blockAfterPause < MB_TLS_HEAP_PAUSE_THRESHOLD" in mb,
    "total free heap guard": "MB_TLS_MIN_FREE_HEAP = 49152U;" in mb,
    "remote pause released on preflight error": 'setStatusError("HTTPS deferred: insufficient heap after TLS arbitration");\n            remoteAccessResumeAfterExternalTls();' in mb,
    "remote task absent is not pause failure": "if(!taskHandle)return true;" in remote,
    "remote OTA protected": "if(firmwareUpdateInProgress())return false;" in remote,
    "remote task pause handshake acknowledged": "while(!externalTlsPaused" in remote,
    "insecure/CA mode unchanged": "client.setInsecure();" in mb and "client.setCACert(REMOTE_TRUST_CA);" in mb,
    "NTP error throttled": "MBFIX2_TLS_WDT_GUARD_V2: bounded retry for NTP/UTC failures" in mb,
    "bad URL throttled": "MBFIX2_TLS_WDT_GUARD_V2: prevent a config error retrying each loop" in mb,
    "stale HTTP200 cleared on deferred": 'if (error.startsWith("HTTPS deferred:"))' in mb,
    "original 192 fields": "constexpr size_t MB_FIELD_COUNT = 192;" in mb,
    "selected station unchanged": "v.rainTodayMm = rainAccumulatorTodayMm(!useTechnoline, dayKey);" in mb,
    "late generator registered": "pre:scripts/apply_mb_tls_watchdog_guard.py" in ini and ini.index("apply_mb_tls_watchdog_guard.py") > ini.index("apply_mb_measurement_diagnostics.py"),
    "CI test registered": "python scripts/test_mb_tls_watchdog_guard.py" in workflow,
}
for name,yes in checks.items():
    print(("PASS" if yes else "FAIL")+": "+name)
assert all(checks.values()),"MBFIX2 TLS guard regression"
print("PASS: static TLS/WDT risk checks; physical watchdog test remains necessary")
