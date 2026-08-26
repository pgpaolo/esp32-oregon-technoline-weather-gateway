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


def replace_if_present(path, old, new, label):
    p = root / path
    text = p.read_text(encoding="utf-8")
    if new in text:
        return True
    if old not in text:
        return False
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"SD format tools: upgraded {path} ({label})")
    return True


# ---- sd_logger.h: expose negotiated SPI speed, diagnostics and format action ----
patch_once(
    "src/sd_logger.h",
    "    uint32_t mountAttempts{0};\n",
    "    uint32_t mountAttempts{0};\n    uint32_t spiFrequencyHz{0};\n",
    "status SPI frequency",
)
patch_once(
    "src/sd_logger.h",
    "    uint32_t spiFrequencyHz{0};\n",
    "    uint32_t spiFrequencyHz{0};\n    uint8_t spiAttemptMask{0};\n    uint8_t spiBeginFailMask{0};\n    uint8_t initCode{0};\n",
    "compact mount diagnostics",
)
patch_once(
    "src/sd_logger.h",
    "bool remountSdLogger();\n",
    "bool remountSdLogger();\nbool formatSdLogger();\n",
    "format API",
)


# ---- sd_logger.cpp: LILYGO-style HSPI + adaptive 4/2/1/0.4 MHz mount ----
patch_once(
    "src/sd_logger.cpp",
    "    status.usedBytes = 0;\n    status.currentFile[0] = '\\0';\n",
    "    status.usedBytes = 0;\n    status.spiFrequencyHz = 0;\n    status.currentFile[0] = '\\0';\n",
    "clear SPI frequency on unmount",
)

old_helpers_v1 = r'''bool mountSdAdaptive(bool formatIfEmpty) {
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
'''

helpers_v2 = r'''bool mountSdAdaptive(bool formatIfEmpty) {
#if !SDCARD_SUPPORTED
    status.supported = false;
    return false;
#else
    unmount();
    status.mountAttempts++;
    status.spiAttemptMask = 0;
    status.spiBeginFailMask = 0;
    status.initCode = 0;

    // Match the official LILYGO T3 V1.6.x sequence exactly: HSPI gets only
    // SCK/MISO/MOSI; CS remains owned by SD.begin(). Give old cards/socket
    // contacts a short settle time before issuing the first command.
    pinMode(SDCARD_CS_PIN, OUTPUT);
    digitalWrite(SDCARD_CS_PIN, HIGH);
    sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN, SDCARD_MOSI_PIN);
    spiStarted = true;
    delay(250);

    const uint32_t freq[] = {4000000U, 2000000U, 1000000U, 400000U};
    for (uint8_t i = 0; i < 4U; ++i) {
        const uint8_t bit = static_cast<uint8_t>(1U << i);
        status.spiAttemptMask |= bit;

        // First normal attempt intentionally uses the same overload as the
        // LILYGO Factory example. Formatting needs the extended overload.
        const bool beginOk = (i == 0U && !formatIfEmpty)
            ? SD.begin(SDCARD_CS_PIN, sdSpi)
            : SD.begin(SDCARD_CS_PIN, sdSpi, freq[i], "/sd", 5, formatIfEmpty);

        if (!beginOk) {
            status.spiBeginFailMask |= bit;
            status.initCode = 2; // SD.begin failed before a usable card existed.
            Serial.printf("[SD] %lu kHz: begin FAIL\n",
                          static_cast<unsigned long>(freq[i] / 1000UL));
            SD.end();
            digitalWrite(SDCARD_CS_PIN, HIGH);
            delay(60);
            continue;
        }

        if (SD.cardType() == CARD_NONE) {
            status.initCode = 3; // SPI/FAT path returned, but no card type.
            Serial.printf("[SD] %lu kHz: CARD_NONE\n",
                          static_cast<unsigned long>(freq[i] / 1000UL));
            SD.end();
            digitalWrite(SDCARD_CS_PIN, HIGH);
            delay(60);
            continue;
        }

        status.mounted = true;
        status.spiFrequencyHz = freq[i];
        status.initCode = 1;
        refreshCapacity();
        Serial.printf("[SD] OK %lu kHz, %lu MB\n",
                      static_cast<unsigned long>(freq[i] / 1000UL),
                      static_cast<unsigned long>(status.cardSizeBytes / (1024ULL * 1024ULL)));
        return true;
    }

    SD.end();
    sdSpi.end();
    spiStarted = false;
    Serial.printf("[SD] mount FAIL try=0x%02X beginFail=0x%02X code=%u\n",
                  static_cast<unsigned>(status.spiAttemptMask),
                  static_cast<unsigned>(status.spiBeginFailMask),
                  static_cast<unsigned>(status.initCode));
    return false;
#endif
}

bool clearSdTree(const char *path) {
'''

# Upgrade a workspace already patched by the previous SD tool; otherwise insert
# the current helper into a clean checkout. This keeps repeated local builds safe.
if not replace_if_present(
    "src/sd_logger.cpp",
    old_helpers_v1,
    helpers_v2,
    "LILYGO HSPI mount sequence",
):
    helpers_insert = helpers_v2.rsplit("bool clearSdTree(const char *path) {\n", 1)[0]
    patch_once(
        "src/sd_logger.cpp",
        "} // namespace\n\nvoid initSdLogger() {\n",
        helpers_insert + "} // namespace\n\nvoid initSdLogger() {\n",
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
patch_once(
    "src/sd_logger.cpp",
    '    out += ",\\\"spi_hz\\\":" + String(s.spiFrequencyHz);\n',
    '    out += ",\\\"spi_hz\\\":" + String(s.spiFrequencyHz);\n    out += ",\\\"spi_try\\\":" + String(s.spiAttemptMask);\n    out += ",\\\"spi_fail\\\":" + String(s.spiBeginFailMask);\n    out += ",\\\"init_code\\\":" + String(s.initCode);\n',
    "status compact diagnostics JSON",
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


# ---- Dashboard: format button, double confirmation, speed + compact diagnostics ----
patch_once(
    "web/dashboard.html",
    '<button class="modeBtn" onclick="remountSd()">Rimonta scheda</button><button class="modeBtn" onclick="resetSd()">Default firmware</button>',
    '<button class="modeBtn" onclick="remountSd()">Rimonta scheda</button><button class="modeBtn" style="border-color:#a44;color:#ff8f8f" onclick="formatSd()">FORMATTA SD</button><button class="modeBtn" onclick="resetSd()">Default firmware</button>',
    "format button",
)
patch_once(
    "web/dashboard.html",
    "sdBytes(s.card_size)+' · usati '+sdBytes(s.used_bytes)",
    "sdBytes(s.card_size)+' · usati '+sdBytes(s.used_bytes)+' · SPI '+((s.spi_hz||0)>=1000000?((s.spi_hz||0)/1000000).toFixed(0)+' MHz':((s.spi_hz||0)/1000).toFixed(0)+' kHz')",
    "show negotiated SPI",
)
patch_once(
    "web/dashboard.html",
    "E('sdSummary').textContent=(c.enabled?'logger ON':'logger OFF')+' · mount tentativi '+(s.mount_attempts||0);",
    "E('sdSummary').textContent=(c.enabled?'logger ON':'logger OFF')+' · mount '+(s.mount_attempts||0)+' · init '+({0:'--',1:'OK',2:'BEGIN FAIL',3:'CARD NONE'}[s.init_code]||s.init_code)+' · try 0x'+Number(s.spi_try||0).toString(16).toUpperCase()+' / fail 0x'+Number(s.spi_fail||0).toString(16).toUpperCase();",
    "show compact mount diagnostics",
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

# Handle both a clean datalogger page and a workspace already patched by v1.
if not replace_if_present(
    "web/dashboard.html",
    "Mount adattivo 4/2/1 MHz. FORMATTA ricrea FAT se non valido oppure azzera il contenuto se gia FAT. La scrittura e differita: il decoder RF non scrive mai direttamente sulla SD.",
    "Mount LILYGO HSPI ufficiale + fallback 4/2/1 MHz/400 kHz. Diagnostica try/fail esposta in Web. FORMATTA ricrea FAT se non valido oppure azzera il contenuto se gia FAT. La scrittura e differita: il decoder RF non scrive mai direttamente sulla SD.",
    "mount note v2",
):
    patch_once(
        "web/dashboard.html",
        "La scrittura e differita: il decoder RF non scrive mai direttamente sulla SD.",
        "Mount LILYGO HSPI ufficiale + fallback 4/2/1 MHz/400 kHz. Diagnostica try/fail esposta in Web. FORMATTA ricrea FAT se non valido oppure azzera il contenuto se gia FAT. La scrittura e differita: il decoder RF non scrive mai direttamente sulla SD.",
        "mount note",
    )
