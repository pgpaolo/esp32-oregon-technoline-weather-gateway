Import("env")
from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def replace_once(path, old, new, label, required=True):
    text = read(path)
    if new in text:
        return True
    if old not in text:
        if required:
            raise RuntimeError(f"SD safe format patch anchor missing: {label} in {path}")
        print(f"SD safe format: skipped {label} (already transformed/compatible)")
        return False
    write(path, text.replace(old, new, 1))
    print(f"SD safe format: patched {path} ({label})")
    return True


def insert_before(path, anchor, block, marker, label, required=True):
    text = read(path)
    if marker in text:
        return True
    pos = text.find(anchor)
    if pos < 0:
        if required:
            raise RuntimeError(f"SD safe format insert anchor missing: {label} in {path}")
        print(f"SD safe format: skipped {label} (anchor unavailable)")
        return False
    write(path, text[:pos] + block + text[pos:])
    print(f"SD safe format: inserted {path} ({label})")
    return True


# ---------------------------------------------------------------------------
# sd_logger.h - diagnostics + public format API
# ---------------------------------------------------------------------------
h = read("src/sd_logger.h")
if "uint32_t spiFrequencyHz{0};" not in h:
    anchor = "    uint32_t mountAttempts{0};\n"
    if anchor not in h:
        raise RuntimeError("SD safe format: mountAttempts field missing in sd_logger.h")
    h = h.replace(anchor, anchor + "    uint32_t spiFrequencyHz{0};\n", 1)
if "uint8_t spiAttemptMask{0};" not in h:
    anchor = "    uint32_t spiFrequencyHz{0};\n"
    if anchor not in h:
        raise RuntimeError("SD safe format: spiFrequencyHz field missing in sd_logger.h")
    h = h.replace(anchor, anchor + "    uint8_t spiAttemptMask{0};\n    uint8_t spiBeginFailMask{0};\n    uint8_t initCode{0};\n", 1)
if "bool formatSdLogger();" not in h:
    anchor = "bool remountSdLogger();\n"
    if anchor not in h:
        raise RuntimeError("SD safe format: remount declaration missing in sd_logger.h")
    h = h.replace(anchor, anchor + "bool formatSdLogger();\n", 1)
write("src/sd_logger.h", h)


# ---------------------------------------------------------------------------
# sd_logger.cpp - diagnostics JSON + format action.
# The next pre-script (apply_sd_mount_regression_fix.py) owns mountSdAdaptive()
# and remountSdLogger(), so this script does not make assumptions about their
# current generated state.
# ---------------------------------------------------------------------------
cpp = read("src/sd_logger.cpp")

# Clear negotiated speed on unmount. Match only the unmount status block.
if "status.spiFrequencyHz = 0;" not in cpp:
    old = "    status.usedBytes = 0;\n    status.currentFile[0] = '\\0';\n"
    new = "    status.usedBytes = 0;\n    status.spiFrequencyHz = 0;\n    status.currentFile[0] = '\\0';\n"
    if old in cpp:
        cpp = cpp.replace(old, new, 1)
    else:
        print("SD safe format: unmount SPI reset anchor unavailable; continuing")

# Add compact diagnostics to status JSON independently, so a partially patched
# workspace can be completed without requiring an exact previous line shape.
mount_json = '    out += ",\\\"mount_attempts\\\":" + String(s.mountAttempts);\n'
if '\\\"spi_hz\\\"' not in cpp and mount_json in cpp:
    cpp = cpp.replace(mount_json, mount_json + '    out += ",\\\"spi_hz\\\":" + String(s.spiFrequencyHz);\n', 1)
spi_json = '    out += ",\\\"spi_hz\\\":" + String(s.spiFrequencyHz);\n'
if '\\\"spi_try\\\"' not in cpp and spi_json in cpp:
    cpp = cpp.replace(
        spi_json,
        spi_json
        + '    out += ",\\\"spi_try\\\":" + String(s.spiAttemptMask);\n'
        + '    out += ",\\\"spi_fail\\\":" + String(s.spiBeginFailMask);\n'
        + '    out += ",\\\"init_code\\\":" + String(s.initCode);\n',
        1,
    )

# Public format operation. clearSdTree() is supplied by the following
# apply_sd_clear_tree_guard.py and ends up textually before this public API.
if "bool formatSdLogger() {" not in cpp:
    format_fn = r'''bool formatSdLogger() {
#if !SDCARD_SUPPORTED
    return false;
#else
    // format_if_empty recreates FAT only when no valid filesystem exists.
    // On an already valid FAT volume, clear the complete tree instead.
    if (!mountSdAdaptive(true)) return false;
    queueHead = queueTail = 0;
    status.queueDepth = 0;
    const bool ok = clearSdTree("/");
    if (!ok) {
        status.writeErrors++;
        return false;
    }
    status.currentFile[0] = '\0';
    refreshCapacity();
    Serial.println(F("[SD] formato/azzeramento completato"));
    return true;
#endif
}

'''
    anchor = "void enqueueSdOregon("
    pos = cpp.find(anchor)
    if pos < 0:
        raise RuntimeError("SD safe format: enqueueSdOregon anchor missing in sd_logger.cpp")
    cpp = cpp[:pos] + format_fn + cpp[pos:]

write("src/sd_logger.cpp", cpp)


# ---------------------------------------------------------------------------
# web_manager.cpp - format endpoint. Tolerant of previous partial builds.
# ---------------------------------------------------------------------------
wm = read("src/web_manager.cpp")
if "void handleSdFormat() {" not in wm:
    handler = r'''void handleSdFormat() {
    if (!server.hasArg("confirm") || server.arg("confirm") != "FORMATTA") {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"confirmation required\"}");
        return;
    }
    const bool ok = formatSdLogger();
    String out = "{\"ok\":";
    out += ok ? "true" : "false";
    out += ",\"status\":" + sdLoggerStatusJson() + "}";
    sendNoCache();
    server.send(ok ? 200 : 500, "application/json", out);
}

'''
    pos = wm.find("void handleSdRemount() {")
    if pos < 0:
        raise RuntimeError("SD safe format: handleSdRemount anchor missing in web_manager.cpp")
    wm = wm[:pos] + handler + wm[pos:]

route = '    server.on("/api/sd/format", HTTP_POST, handleSdFormat);\n'
if route not in wm:
    anchor = '    server.on("/api/sd/remount", HTTP_POST, handleSdRemount);\n'
    if anchor not in wm:
        raise RuntimeError("SD safe format: SD remount route missing in web_manager.cpp")
    wm = wm.replace(anchor, anchor + route, 1)
write("src/web_manager.cpp", wm)


# ---------------------------------------------------------------------------
# dashboard.html - best-effort UI enrichment. None of these cosmetic changes
# is allowed to stop a firmware build. Functional format JS/route are inserted
# whenever their stable anchors are present.
# ---------------------------------------------------------------------------
d = read("web/dashboard.html")

# Button
if 'onclick="formatSd()"' not in d:
    anchor = '<button class="modeBtn" onclick="remountSd()">Rimonta scheda</button>'
    button = '<button class="modeBtn" style="border-color:#a44;color:#ff8f8f" onclick="formatSd()">FORMATTA SD</button>'
    if anchor in d:
        d = d.replace(anchor, anchor + button, 1)
        print("SD safe format: added FORMATTA SD button")
    else:
        print("SD safe format: remount button anchor unavailable; format UI button skipped")

# Negotiated SPI display. Use the stable used-bytes expression rather than the
# complete generated loadSd() line, which is frequently changed by other UI patches.
if "s.spi_hz" not in d:
    old = "sdBytes(s.used_bytes)"
    new = "sdBytes(s.used_bytes)+' · SPI '+((s.spi_hz||0)>=1000000?((s.spi_hz||0)/1000000).toFixed(0)+' MHz':((s.spi_hz||0)/1000).toFixed(0)+' kHz')"
    if old in d:
        d = d.replace(old, new, 1)
        print("SD safe format: added negotiated SPI display")
    else:
        print("SD safe format: used-bytes UI anchor unavailable; SPI display skipped")

# Compact diagnostics summary. Replace only the sdSummary assignment, whatever
# wording an earlier generated version used.
if "s.init_code" not in d:
    pattern = re.compile(r"E\('sdSummary'\)\.textContent=\(c\.enabled\?'logger ON':'logger OFF'\)\+[^;]+;")
    replacement = "E('sdSummary').textContent=(c.enabled?'logger ON':'logger OFF')+' · mount '+(s.mount_attempts||0)+' · init '+({0:'--',1:'OK',2:'BEGIN FAIL',3:'CARD NONE'}[s.init_code]||s.init_code)+' · try 0x'+Number(s.spi_try||0).toString(16).toUpperCase()+' / fail 0x'+Number(s.spi_fail||0).toString(16).toUpperCase();"
    d2, n = pattern.subn(replacement, d, count=1)
    if n:
        d = d2
        print("SD safe format: added compact mount diagnostics")
    else:
        print("SD safe format: sdSummary UI anchor unavailable; diagnostics display skipped")

# Format JS
if "async function formatSd()" not in d:
    format_js = r'''async function formatSd(){
 if(!confirm('ATTENZIONE: la formattazione cancella tutti i dati presenti sulla microSD. Continuare?'))return;
 if(!confirm('Conferma definitiva: cancellare TUTTO il contenuto della microSD?'))return;
 const q=new URLSearchParams();q.set('confirm','FORMATTA');
 const r=await fetch('/api/sd/format',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});
 if(!r.ok){alert('Formattazione microSD fallita: '+await r.text());await loadSd();return}
 alert('microSD inizializzata/azzerata correttamente');await loadSd();
}
'''
    anchor = "async function resetSd(){"
    pos = d.find(anchor)
    if pos >= 0:
        d = d[:pos] + format_js + d[pos:]
        print("SD safe format: added formatSd javascript")
    else:
        print("SD safe format: resetSd JS anchor unavailable; format JS skipped")

# Informational note only; deliberately non-fatal.
if "8/4/2/1 MHz/400 kHz" not in d:
    note_anchor = "La scrittura e differita: il decoder RF non scrive mai direttamente sulla SD."
    if note_anchor in d:
        d = d.replace(
            note_anchor,
            "Mount T3 V1.6.1 HSPI con retry 8/4/2/1 MHz/400 kHz. Diagnostica try/fail esposta in Web. FORMATTA ricrea FAT se non valido oppure azzera il contenuto se gia FAT. La scrittura e differita: il decoder RF non scrive mai direttamente sulla SD.",
            1,
        )

write("web/dashboard.html", d)
print("SD safe format: completed")
