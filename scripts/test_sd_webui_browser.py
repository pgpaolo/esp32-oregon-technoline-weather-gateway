#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def require(haystack, needle, label):
    if needle not in haystack:
        raise SystemExit(f"SD WEBUI GUARD FAILED: missing {label}: {needle}")


def forbid(haystack, needle, label):
    if needle in haystack:
        raise SystemExit(f"SD WEBUI GUARD FAILED: forbidden {label}: {needle}")


pio = text("platformio.ini")
h = text("src/sd_logger.h")
cpp = text("src/sd_logger.cpp")
web = text("src/web_manager.cpp")
dash = text("web/dashboard.html")

require(pio, "pre:scripts/apply_sd_webui_browser.py", "late SD browser pass")
require(h, "ADMIN_SENSOR_SD_BROWSER_V1", "SD public API marker")
require(h, "sdLoggerFilesJson", "file list declaration")
require(h, "sdLoggerReadFileChunk", "chunk reader declaration")

require(cpp, "ADMIN_SENSOR_SD_BROWSER_V1", "SdFat browser implementation")
require(cpp, "SD_BROWSER_FILE_LIMIT = 48U", "bounded file list")
require(cpp, "SD_BROWSER_CHUNK_MAX = 6144U", "remote-safe read chunk")
require(cpp, 'path.startsWith("/weather/")', "weather-only path guard")
require(cpp, 'path.indexOf("..") < 0', "path traversal guard")
require(cpp, "entry.openNext(&dir, O_RDONLY)", "recursive SdFat listing")

require(web, "ADMIN_SENSOR_SD_BROWSER_V1", "Web SD browser handlers")
require(web, 'server.on("/api/sd/files", HTTP_GET, handleSdFiles);', "file list route")
require(web, 'server.on("/api/sd/read", HTTP_GET, handleSdRead);', "chunk read route")
require(web, "if (!requireWebAuth()) return;", "authenticated SD browser")
require(web, "limit > 6144U", "Web chunk ceiling")

require(dash, 'id="tabSd"', "MICROSD tab")
require(dash, 'id="cfgSd"', "MICROSD page")
require(dash, "'sd'", "SD config-loop token")
require(dash, "t==='sd')loadSdPanel()", "SD page loader")
require(dash, 'id="sdBrowserPanel"', "SD archive panel")
require(dash, "async function loadSdFiles()", "file-list loader")
require(dash, "async function downloadSdPath", "chunked browser download")
require(dash, "step=6144", "browser chunk size")
require(dash, "remoteUi?15000:4000", "reduced remote SD poll")
require(dash, "remoteUi?3500:0", "staggered remote SD startup")
forbid(dash, "refreshSdHeader();setInterval(refreshSdHeader,4000);", "old competing SD poll")

print("MicroSD final Web UI + authenticated remote-safe CSV browser: OK")
