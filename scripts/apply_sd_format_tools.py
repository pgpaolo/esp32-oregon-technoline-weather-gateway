Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def patch_once(path, old, new, label):
    p = root / path
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"SD format patch anchor missing: {label} in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"SD format tools: patched {path} ({label})")


# ---- sd_logger.h: expose negotiated SPI speed and format action ----
patch_once(
    "src/sd_logger.h",
    "    uint32_t mountAttempts{0};\n",
    "    uint32_t mountAttempts{0};\n    uint32_t spiFrequencyHz{0};\n",
    "status SPI frequency",
)
patch_once(
    "src/sd_logger.h",
    "bool remountSdLogger();\n",
    "bool remountSdLogger();\nbool formatSdLogger();\n",
    "format API",
)


# ---- sd_logger.cpp: adaptive 4/2/1 MHz mount + guarded FAT init/erase ----
patch_once(
    "src/sd_logger.cpp",
    "    status.usedBytes = 0;\n    status.currentFile[0] = '\\0';\n",
    "    status.usedBytes = 0;\n    status.spiFrequencyHz = 0;\n    status.currentFile[0] = '\\0';\n",
    "clear SPI frequency on unmount",
)

helpers = r'''bool mountSdAdaptive(bool formatIfEmpty) {
#if !SDCARD_SUPPORTED
    status.supported = false;
    return false;
#else
    unmount();
    status.mountAttempts++;
    pinMode(SDCARD_CS_PIN, OUTPUT);
    digitalWrite(SDCARD_CS_PIN, HIGH);
    const uint32_t freq[] = {4000000U, 2000000U, 1000000U};

    for (uint8_t i = 0; i < 3U; ++i) {
        sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN, SDCARD_MOSI_PIN, SDCARD_CS_PIN);
        spiStarted = true;
        if (SD.begin(SDCARD_CS_PIN, sdSpi, freq[i], "/sd", 5, formatIfEmpty) && SD.cardType() != CARD_NONE) {
            status.mounted = true;
            status.spiFrequencyHz = freq[i];
            refreshCapacity();
            Serial.printf("[SD] OK %lu MHz, %lu MB\n",
                          static_cast<unsigned long>(freq[i] / 1000000UL),
                          static_cast<unsigned long>(status.cardSizeBytes / (1024ULL * 1024ULL)));
            return true;
        }
        SD.end();
        sdSpi.end();
        spiStarted = false;
    }
    Serial.println(F("[SD] mount fallito a 4/2/1 MHz"));
    return false;
#endif
}

bool clearSdTree(const char *path) {
    while (true) {
        File dir = SD.open(path);
        if (!dir || !dir.isDirectory()) {
            if (dir) dir.close();
            return false;
        }
        File entry = dir.openNextFile();
        if (!entry) {
            dir.close();
            return true;
        }
        const String child = entry.path();
        const bool isDir = entry.isDirectory();
        entry.close();
        dir.close();
        if (isDir) {
            if (!clearSdTree(child.c_str()) || !SD.rmdir(child)) return false;
        } else if (!SD.remove(child)) {
            return false;
        }
        delay(0);
    }
}

'''
patch_once(
    "src/sd_logger.cpp",
    "} // namespace\n\nvoid initSdLogger() {\n",
    helpers + "} // namespace\n\nvoid initSdLogger() {\n",
    "adaptive mount helpers",
)

old_remount = r'''bool remountSdLogger() {
#if !SDCARD_SUPPORTED
    status.supported = false;
    return false;
#else
    unmount();
    status.mountAttempts++;
    pinMode(SDCARD_CS_PIN, OUTPUT);
    digitalWrite(SDCARD_CS_PIN, HIGH);
    sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN, SDCARD_MOSI_PIN, SDCARD_CS_PIN);
    spiStarted = true;

    if (!SD.begin(SDCARD_CS_PIN, sdSpi, 8000000U)) {
        Serial.println(F("[SD] microSD non rilevata / mount fallito; gateway continua senza logging"));
        unmount();
        return false;
    }
    if (SD.cardType() == CARD_NONE) {
        Serial.println(F("[SD] nessuna scheda presente"));
        unmount();
        return false;
    }

    status.mounted = true;
    refreshCapacity();
    Serial.print(F("[SD] montata: "));
    Serial.print(static_cast<unsigned long>(status.cardSizeBytes / (1024ULL * 1024ULL)));
    Serial.println(F(" MB"));
    return true;
#endif
}
'''
new_remount = r'''bool remountSdLogger() {
    return mountSdAdaptive(false);
}

bool formatSdLogger() {
#if !SDCARD_SUPPORTED
    return false;
#else
    // format_if_empty ricrea FAT se il volume non e' valido. Se e' gia' FAT,
    // azzeriamo ricorsivamente il contenuto: nessuna libreria aggiuntiva.
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
patch_once(
    "src/sd_logger.cpp",
    old_remount,
    new_remount,
    "adaptive remount and format",
)
patch_once(
    "src/sd_logger.cpp",
    '    out += ",\\\"mount_attempts\\\":" + String(s.mountAttempts);\n',
    '    out += ",\\\"mount_attempts\\\":" + String(s.mountAttempts);\n    out += ",\\\"spi_hz\\\":" + String(s.spiFrequencyHz);\n',
    "status SPI JSON",
)


# ---- web_manager.cpp: destructive POST endpoint with explicit token ----
sd_format_handler = r'''void handleSdFormat() {
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
patch_once(
    "src/web_manager.cpp",
    "void handleSdRemount() {\n",
    sd_format_handler + "void handleSdRemount() {\n",
    "format handler",
)
patch_once(
    "src/web_manager.cpp",
    '    server.on("/api/sd/remount", HTTP_POST, handleSdRemount);\n',
    '    server.on("/api/sd/remount", HTTP_POST, handleSdRemount);\n    server.on("/api/sd/format", HTTP_POST, handleSdFormat);\n',
    "format route",
)


# ---- Dashboard: format button, double confirmation, negotiated speed ----
patch_once(
    "web/dashboard.html",
    '<button class="modeBtn" onclick="remountSd()">Rimonta scheda</button><button class="modeBtn" onclick="resetSd()">Default firmware</button>',
    '<button class="modeBtn" onclick="remountSd()">Rimonta scheda</button><button class="modeBtn" style="border-color:#a44;color:#ff8f8f" onclick="formatSd()">FORMATTA SD</button><button class="modeBtn" onclick="resetSd()">Default firmware</button>',
    "format button",
)
patch_once(
    "web/dashboard.html",
    "sdBytes(s.card_size)+' · usati '+sdBytes(s.used_bytes)",
    "sdBytes(s.card_size)+' · usati '+sdBytes(s.used_bytes)+' · SPI '+((s.spi_hz||0)/1000000).toFixed(0)+' MHz'",
    "show negotiated SPI",
)

format_js = r'''async function formatSd(){
 if(!confirm('ATTENZIONE: la formattazione cancella tutti i dati presenti sulla microSD. Continuare?'))return;
 if(!confirm('Conferma definitiva: cancellare TUTTO il contenuto della microSD?'))return;
 const q=new URLSearchParams();q.set('confirm','FORMATTA');
 const r=await fetch('/api/sd/format',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});
 if(!r.ok){alert('Formattazione microSD fallita: '+await r.text());await loadSd();return}
 alert('microSD inizializzata/azzerata correttamente');await loadSd();
}
'''
patch_once(
    "web/dashboard.html",
    "async function resetSd(){",
    format_js + "async function resetSd(){",
    "format javascript",
)
patch_once(
    "web/dashboard.html",
    "La scrittura e differita: il decoder RF non scrive mai direttamente sulla SD.",
    "Mount adattivo 4/2/1 MHz. FORMATTA ricrea FAT se non valido oppure azzera il contenuto se gia FAT. La scrittura e differita: il decoder RF non scrive mai direttamente sulla SD.",
    "format note",
)
