#!/usr/bin/env python3
"""Integration guard for AdminSensor Remote and local/remote OTA arbitration."""
from pathlib import Path

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

require(pio, 'FIRMWARE_VERSION=\\"6.4.0-dev3\\"', "develop firmware identity")
require(pio, "links2004/WebSockets@2.6.1", "WebSockets dependency")
require(pio, "bblanchon/ArduinoJson@7.4.2", "ArduinoJson dependency")
require(pio, "pre:scripts/apply_remote_access_ota.py", "late remote integration pass")

require(main, '#include "remote_access.h"', "remote main include")
require(main, "initRemoteAccess();", "remote initialization")
require(main, "serviceRemoteFirmwareUpdate();", "remote OTA reboot service")
require(webh, "bool webStarted();", "Web readiness API")
require(web, "bool webStarted() { return webStartedFlag; }", "Web readiness implementation")
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
require(ota, "SHA-256 firmware non corrispondente", "remote SHA-256 verification")
require(ota, "sequence!=expectedSequence", "strict remote sequence")
require(ota, "data[0]!=0xE9U", "ESP32 image magic validation")
require(ota, "prepareSdLoggerForDeepSleep();", "SD shutdown before remote OTA")
require(dash, 'id="tabRemote"', "Remote config tab")
require(dash, 'id="cfgRemote"', "Remote config page")
require(dash, "AdminSensor Remote", "Remote UI label")
require(dash, "loadRemoteAccess()", "Remote UI state loader")
forbid(dash, "device_token", "device token exposure in dashboard")

print("AdminSensor Remote + guarded WSS OTA integration: OK")
