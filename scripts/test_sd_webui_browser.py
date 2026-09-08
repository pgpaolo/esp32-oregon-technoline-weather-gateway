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
require(pio, "pre:scripts/apply_sd_header_indicator.py", "stable SD header pass")
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

# The runtime V2 final pass removes the dedicated remote /api/sd badge poll.
# Before that final pass, the browser layer uses a staggered 15 s remote poll.
if "ADMIN_SENSOR_REMOTE_POLL_V3" in dash:
    require(dash, "if(!remoteUi){refreshSdHeader();setInterval(refreshSdHeader,4000);}", "local-only SD header poll")
    forbid(dash, "remoteUi?15000:4000", "remote SD badge polling after runtime V2")
else:
    require(dash, "remoteUi?15000:4000", "reduced remote SD poll")
    require(dash, "remoteUi?3500:0", "staggered remote SD startup")

# Fixed-width SD header indicator: state is colour-only, visible text never
# changes, so header/tile geometry cannot reflow when a write is observed.
require(dash, "SD_HEADER_STABLE_V2", "stable SD header marker")
require(dash, 'class="statusPill sdPill wait"', "fixed SD pill class")
require(dash, ".statusPill.sdPill{width:72px;min-width:72px;flex:0 0 72px", "fixed SD pill width")
require(dash, "e.textContent='SD';", "constant SD label")
require(dash, "cls='write';state='scrittura in corso'", "write colour state")
for legacy in ("SD SCRIVE", "SD ON", "SD PRONTA", "SD KO", "SD OFF", "SD ERR"):
    forbid(dash, legacy, f"variable-width SD label {legacy}")

print("MicroSD final Web UI + stable fixed-width header + authenticated remote-safe CSV browser: OK")
