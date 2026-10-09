Import("env")
from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def replace_function(text, signature, replacement):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"SdFat backend: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"SdFat backend: opening brace missing: {signature}")
    depth = 0
    end = brace
    while end < len(text):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                end += 1
                while end < len(text) and text[end] in "\r\n":
                    end += 1
                return text[:start] + replacement + text[end:]
        end += 1
    raise RuntimeError(f"SdFat backend: closing brace missing: {signature}")


# The preceding SD scripts create the logger, Web API and format button. This
# final storage patch changes only their transport/filesystem implementation.
cpp = read("src/sd_logger.cpp")
cpp = cpp.replace("#include <FS.h>\n#include <SD.h>\n", "#include <SdFat.h>\n", 1)
if "#include <SdFat.h>" not in cpp:
    raise RuntimeError("SdFat backend: Arduino SD includes anchor missing")

if "SdFat32 sd;" not in cpp:
    cpp = cpp.replace("SPIClass sdSpi(HSPI);\n", "SPIClass sdSpi(HSPI);\nSdFat32 sd;\n", 1)

refresh = r'''void refreshCapacity() {
    if (!status.mounted || !sd.card()) return;
    status.cardSizeBytes = static_cast<uint64_t>(sd.card()->sectorCount()) * 512ULL;
    const uint64_t bytesPerCluster = sd.bytesPerCluster();
    status.totalBytes = static_cast<uint64_t>(sd.clusterCount()) * bytesPerCluster;
    const uint64_t freeBytes = static_cast<uint64_t>(sd.freeClusterCount()) * bytesPerCluster;
    status.usedBytes = status.totalBytes >= freeBytes ? status.totalBytes - freeBytes : 0;
    lastCapacityRefreshMs = millis();
}

'''
cpp = replace_function(cpp, "void refreshCapacity() {", refresh)

cpp = cpp.replace("SD.exists(", "sd.exists(")
cpp = cpp.replace("SD.mkdir(", "sd.mkdir(")
cpp = cpp.replace("File f = SD.open(path, FILE_APPEND);",
                  "File32 f = sd.open(path, O_WRONLY | O_CREAT | O_APPEND);")

# A previous environment build may already have generated this private helper.
# Remove all copies before replacing unmount() with the canonical pair below.
while "bool mountSdFat(bool formatRequested) {" in cpp:
    cpp = replace_function(cpp, "bool mountSdFat(bool formatRequested) {", "")

unmount = r'''void unmount() {
    sd.end();
    if (spiStarted) {
        sdSpi.end();
        spiStarted = false;
    }
    status.mounted = false;
    status.cardSizeBytes = 0;
    status.totalBytes = 0;
    status.usedBytes = 0;
    status.spiFrequencyHz = 0;
    status.currentFile[0] = '\0';
    queueHead = queueTail = 0;
    status.queueDepth = 0;
}

bool mountSdFat(bool formatRequested) {
    unmount();
    status.mountAttempts++;
    status.spiAttemptMask = 0;
    status.spiBeginFailMask = 0;
    status.initCode = 0;
    status.sdErrorCode = 0;
    status.sdErrorData = 0;

    // Official LILYGO T3 V1.6.1 HSPI pin order. CS is kept high while the
    // clock/data pins are configured, then SdFat owns it during transactions.
    constexpr uint32_t frequencies[] = {SD_SCK_MHZ(4), 400000UL};
    for (uint8_t i = 0; i < 2U; ++i) {
        const uint8_t bit = static_cast<uint8_t>(1U << i);
        status.spiAttemptMask |= bit;
        pinMode(SDCARD_CS_PIN, OUTPUT);
        digitalWrite(SDCARD_CS_PIN, HIGH);
        delay(10);
        sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN, SDCARD_MOSI_PIN);
        spiStarted = true;

        const SdSpiConfig spiConfig(SDCARD_CS_PIN, SHARED_SPI, frequencies[i], &sdSpi);
        bool mounted = sd.begin(spiConfig);
        status.sdErrorCode = sd.sdErrorCode();
        status.sdErrorData = sd.sdErrorData();

        // sdErrorCode()==0 with begin()==false means the card initialized but
        // no supported FAT volume exists. That is precisely the state in which
        // formatting must be allowed instead of aborting before the formatter.
        const bool cardReady = mounted || status.sdErrorCode == 0;
        if (formatRequested && cardReady) {
            Serial.println(F("[SD] formattazione FAT tramite SdFat..."));
            if (!sd.format(&Serial)) {
                status.sdErrorCode = sd.sdErrorCode();
                status.sdErrorData = sd.sdErrorData();
                status.initCode = 4;
                status.spiBeginFailMask |= bit;
                unmount();
                return false;
            }

            // Reinitialize from a clean bus after writing the partition/FAT.
            sd.end();
            sdSpi.end();
            spiStarted = false;
            delay(20);
            pinMode(SDCARD_CS_PIN, OUTPUT);
            digitalWrite(SDCARD_CS_PIN, HIGH);
            sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN, SDCARD_MOSI_PIN);
            spiStarted = true;
            mounted = sd.begin(spiConfig);
            status.sdErrorCode = sd.sdErrorCode();
            status.sdErrorData = sd.sdErrorData();
        }

        if (mounted) {
            status.mounted = true;
            status.spiFrequencyHz = frequencies[i];
            status.initCode = 1;
            status.sdErrorCode = 0;
            status.sdErrorData = 0;
            refreshCapacity();
            Serial.print(F("[SD] SdFat montata a "));
            Serial.print(frequencies[i] / 1000UL);
            Serial.print(F(" kHz: "));
            Serial.print(static_cast<unsigned long>(status.cardSizeBytes / (1024ULL * 1024ULL)));
            Serial.println(F(" MB"));
            return true;
        }

        status.spiBeginFailMask |= bit;
        status.initCode = cardReady ? 3 : 2;
        Serial.print(F("[SD] SdFat init fallita a "));
        Serial.print(frequencies[i] / 1000UL);
        Serial.print(F(" kHz, error 0x"));
        Serial.print(status.sdErrorCode, HEX);
        Serial.print(F(" data 0x"));
        Serial.println(status.sdErrorData, HEX);
        sd.end();
        sdSpi.end();
        spiStarted = false;

        // A valid card with an invalid FAT will not improve at a lower clock.
        // Preserve that state so the explicit FORMATTA action can repair it.
        if (cardReady) return false;
        delay(25);
    }

    Serial.println(F("[SD] scheda non inizializzata; gateway continua senza logging"));
    return false;
}

'''
cpp = replace_function(cpp, "void unmount() {", unmount)

remount = r'''bool remountSdLogger() {
#if !SDCARD_SUPPORTED
    status.supported = false;
    return false;
#else
    return mountSdFat(false);
#endif
}

'''
cpp = replace_function(cpp, "bool remountSdLogger() {", remount)

format_fn = r'''bool formatSdLogger() {
#if !SDCARD_SUPPORTED
    return false;
#else
    const bool ok = mountSdFat(true);
    if (ok) Serial.println(F("[SD] formattazione e rimontaggio completati"));
    return ok;
#endif
}

'''
cpp = replace_function(cpp, "bool formatSdLogger() {", format_fn)

# Compact, stable diagnostics in the existing JSON status object.
init_json = '    out += ",\\\"init_code\\\":" + String(s.initCode);\n'
if '\\"sd_error\\"' not in cpp:
    if init_json not in cpp:
        raise RuntimeError("SdFat backend: init_code JSON anchor missing")
    cpp = cpp.replace(
        init_json,
        init_json
        + '    out += ",\\\"sd_error\\\":" + String(s.sdErrorCode);\n'
        + '    out += ",\\\"sd_error_data\\\":" + String(s.sdErrorData);\n',
        1,
    )

if "SD." in cpp or "FILE_APPEND" in cpp:
    raise RuntimeError("SdFat backend: residual Arduino SD API found")
write("src/sd_logger.cpp", cpp)


h = read("src/sd_logger.h")
if "uint8_t sdErrorCode{0};" not in h:
    anchor = "    uint8_t initCode{0};\n"
    if anchor not in h:
        raise RuntimeError("SdFat backend: initCode field missing")
    h = h.replace(anchor, anchor + "    uint8_t sdErrorCode{0};\n    uint8_t sdErrorData{0};\n", 1)
write("src/sd_logger.h", h)


# Replace stale Arduino-SD diagnostics in the final uncompressed dashboard.
d = read("web/dashboard.html")
sd_badge = '<span id="hdrSd" class="statusPill wait" title="Stato datalogger microSD">SD...</span>'
while sd_badge + sd_badge in d:
    d = d.replace(sd_badge + sd_badge, sd_badge, 1)
if 'id="hdrSd"' not in d:
    d = d.replace(
        '<span id="hdrMqtt" class="statusPill wait">MQTT...</span>',
        '<span id="hdrMqtt" class="statusPill wait">MQTT...</span>' + sd_badge,
        1,
    )
if "statusPill.write" not in d:
    css_anchor = ".statusPill.bad:before{background:var(--bad)}"
    css_write = ".statusPill.write{color:#8fdcff;border-color:#246584}.statusPill.write:before{background:#43c7ff;box-shadow:0 0 0 3px #43c7ff28}"
    if css_anchor in d:
        d = d.replace(css_anchor, css_anchor + css_write, 1)
    else:
        print("SdFat backend: status pill CSS anchor unavailable; continuing")

d = d.replace(
    "Mount T3 V1.6.1 HSPI con retry 8/4/2/1 MHz/400 kHz. Diagnostica try/fail esposta in Web.",
    "Mount SdFat su HSPI a 4 MHz con fallback 400 kHz. Codice errore SD reale esposto in Web.",
)
d = d.replace(
    "Mount LILYGO HSPI ufficiale + fallback 4/2/1 MHz/400 kHz. Diagnostica try/fail esposta in Web.",
    "Mount SdFat su HSPI a 4 MHz con fallback 400 kHz. Codice errore SD reale esposto in Web.",
)

summary_pattern = re.compile(r"E\('sdSummary'\)\.textContent=\(c\.enabled\?'logger ON':'logger OFF'\)\+[^;]+;")
summary = "E('sdSummary').textContent=(c.enabled?'logger ON':'logger OFF')+' · mount '+(s.mount_attempts||0)+' · init '+({0:'--',1:'OK',2:'CARD INIT',3:'FAT INVALID',4:'FORMAT FAIL'}[s.init_code]||s.init_code)+' · SdFat 0x'+Number(s.sd_error||0).toString(16).toUpperCase().padStart(2,'0')+'/0x'+Number(s.sd_error_data||0).toString(16).toUpperCase().padStart(2,'0');"
d, count = summary_pattern.subn(summary, d, count=1)
if not count:
    print("SdFat backend: dashboard summary anchor unavailable; continuing")

failure_pattern = re.compile(r"if\(!r\.ok\)\{let msg='Formattazione microSD fallita\.';try\{.*?\}catch\(e\)\{\}alert\(msg\);await loadSd\(\);return\}")
failure = "if(!r.ok){let msg='Formattazione microSD fallita.';try{const j=await r.json(),s=j.status||{},ec=Number(s.sd_error||0),ed=Number(s.sd_error_data||0),hx=n=>'0x'+n.toString(16).toUpperCase().padStart(2,'0');if(Number(s.init_code)===2)msg='La scheda non completa l inizializzazione SdFat: errore '+hx(ec)+', dato '+hx(ed)+'.';else if(Number(s.init_code)===3)msg='Scheda inizializzata ma FAT assente/non valida: riprovare FORMATTA SD.';else if(Number(s.init_code)===4)msg='Formatter SdFat fallito: errore '+hx(ec)+', dato '+hx(ed)+'.';}catch(e){}alert(msg);await loadSd();return}"
d, count = failure_pattern.subn(failure, d, count=1)
if not count:
    print("SdFat backend: format failure UI anchor unavailable; continuing")

# Header indicator: one small request every four seconds. A rise in the
# cumulative write counter keeps "SD SCRIVE" visible until the next poll;
# otherwise the badge distinguishes ready, disabled and mount-failure states.
if "async function refreshSdHeader()" not in d:
    sd_header_js = r'''let sdHeaderWritten=null;
function updateSdHeader(c,s){const e=E('hdrSd');if(!e)return;const n=Number(s.written||0),wrote=sdHeaderWritten!==null&&n>sdHeaderWritten;sdHeaderWritten=n;if(s.mounted){e.className='statusPill '+(wrote?'write':'ok');e.textContent=wrote?'SD SCRIVE':(c.enabled?'SD ON':'SD PRONTA')}else{e.className='statusPill '+(c.enabled?'bad':'wait');e.textContent=c.enabled?'SD KO':'SD OFF'}e.title='microSD · scritture '+n+' · coda '+Number(s.queue_depth||0)+' · errori '+Number(s.write_errors||0)+(s.file?' · '+s.file:'')}
async function refreshSdHeader(){try{const j=await (await fetch('/api/sd',{cache:'no-store'})).json();updateSdHeader(j.config||{},j.status||{})}catch(e){const h=E('hdrSd');if(h){h.className='statusPill bad';h.textContent='SD ERR';h.title='Errore lettura stato microSD'}}}
'''
    anchor = "function sdBytes(v){"
    if anchor not in d:
        raise RuntimeError("SdFat backend: sdBytes javascript anchor missing")
    d = d.replace(anchor, sd_header_js + anchor, 1)

load_sd_anchor = "const j=await (await fetch('/api/sd',{cache:'no-store'})).json(),c=j.config||{},s=j.status||{};"
if "updateSdHeader(c,s);E('sdEnabled')" not in d:
    if load_sd_anchor not in d:
        raise RuntimeError("SdFat backend: loadSd response anchor missing")
    d = d.replace(load_sd_anchor, load_sd_anchor + "updateSdHeader(c,s);", 1)

timer_anchor = "bindDisplayFieldAutoPages();loadNetwork();loadMqtt();refreshLightning();refresh();"
if "setInterval(refreshSdHeader,4000)" not in d:
    if timer_anchor not in d:
        raise RuntimeError("SdFat backend: startup timers anchor missing")
    d = d.replace(timer_anchor, timer_anchor + "refreshSdHeader();setInterval(refreshSdHeader,4000);", 1)
write("web/dashboard.html", d)

print("SdFat backend: completed")
