Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def replace_function(source, signature, replacement):
    start = source.find(signature)
    if start < 0:
        raise RuntimeError(f"BME280 diagnostics fix: missing function {signature}")
    brace = source.find("{", start)
    if brace < 0:
        raise RuntimeError(f"BME280 diagnostics fix: missing opening brace {signature}")
    depth = 0
    end = brace
    while end < len(source):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if depth == 0:
                end += 1
                while end < len(source) and source[end] in "\r\n":
                    end += 1
                return source[:start] + replacement + source[end:]
        end += 1
    raise RuntimeError(f"BME280 diagnostics fix: missing closing brace {signature}")


# ---------------------------------------------------------------------------
# Deep I2C diagnostics.
#
# The normal BME280 retry path only probes 0x76/0x77 and must stay lightweight.
# This extension adds a cached full-bus scan at 400 kHz and 100 kHz plus a
# direct read of Bosch chip-id register 0xD0. One scan is performed after the
# first failed boot discovery; later scans are user-triggered from BAROMETRO.
# The shared Wire bus is always restored to 400 kHz afterwards.
# ---------------------------------------------------------------------------
header = read("src/barometer_manager.h")
if "struct BarometerI2cDeepDiagnostics" not in header:
    header += r'''

// BME280_I2C_DEEP_SCAN_V1
struct BarometerI2cDeepDiagnostics {
    bool scanCompleted{false};
    uint32_t scanAtMs{0};
    uint8_t count400{0};
    uint8_t count100{0};
    uint8_t addresses400[32]{};
    uint8_t addresses100[32]{};
    int16_t chipId76_400{-1};
    int16_t chipId77_400{-1};
    int16_t chipId76_100{-1};
    int16_t chipId77_100{-1};
};

BarometerI2cDeepDiagnostics getBarometerI2cDeepDiagnostics();
void runBarometerI2cDeepScan();
'''
    write("src/barometer_manager.h", header)

cpp = read("src/barometer_manager.cpp")
if "BME280_I2C_DEEP_SCAN_V1" not in cpp:
    attempt_anchor = "bool attemptBmeDetection() {"
    if attempt_anchor not in cpp:
        raise RuntimeError("BME280 deep scan: retry pass must run first")

    deep_block = r'''
// BME280_I2C_DEEP_SCAN_V1
BarometerI2cDeepDiagnostics deepI2cDiag{};

bool readI2cRegister(uint8_t addr, uint8_t reg, uint8_t &value) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    const uint8_t got = Wire.requestFrom(static_cast<int>(addr), 1);
    if (got != 1U || !Wire.available()) return false;
    value = static_cast<uint8_t>(Wire.read());
    return true;
}

void scanI2cAtClock(uint32_t clockHz, uint8_t *addresses, uint8_t &count,
                    int16_t &chip76, int16_t &chip77) {
    Wire.setClock(clockHz);
    delay(2);
    count = 0;
    for (uint8_t addr = 1; addr < 0x7F; ++addr) {
        Wire.beginTransmission(addr);
        const uint8_t rc = Wire.endTransmission();
        if (rc == 0 && count < 32U) addresses[count++] = addr;
    }

    uint8_t chip = 0;
    chip76 = readI2cRegister(0x76, 0xD0, chip) ? static_cast<int16_t>(chip) : -1;
    chip77 = readI2cRegister(0x77, 0xD0, chip) ? static_cast<int16_t>(chip) : -1;
}

void performDeepI2cScan() {
    deepI2cDiag = BarometerI2cDeepDiagnostics{};
    deepI2cDiag.scanAtMs = millis();

    scanI2cAtClock(400000UL, deepI2cDiag.addresses400, deepI2cDiag.count400,
                   deepI2cDiag.chipId76_400, deepI2cDiag.chipId77_400);
    scanI2cAtClock(100000UL, deepI2cDiag.addresses100, deepI2cDiag.count100,
                   deepI2cDiag.chipId76_100, deepI2cDiag.chipId77_100);

    // OLED/AS3935 and the normal gateway configuration use fast-mode I2C.
    Wire.setClock(400000UL);
    deepI2cDiag.scanCompleted = true;

    Serial.print(F("[I2C-DEEP] 400k:"));
    for (uint8_t i = 0; i < deepI2cDiag.count400; ++i) {
        Serial.print(F(" 0x"));
        if (deepI2cDiag.addresses400[i] < 0x10) Serial.print('0');
        Serial.print(deepI2cDiag.addresses400[i], HEX);
    }
    Serial.print(F(" | 100k:"));
    for (uint8_t i = 0; i < deepI2cDiag.count100; ++i) {
        Serial.print(F(" 0x"));
        if (deepI2cDiag.addresses100[i] < 0x10) Serial.print('0');
        Serial.print(deepI2cDiag.addresses100[i], HEX);
    }
    Serial.println();

    Serial.print(F("[I2C-DEEP] CHIP_ID 0x76 400k="));
    if (deepI2cDiag.chipId76_400 >= 0) Serial.print(deepI2cDiag.chipId76_400, HEX); else Serial.print(F("--"));
    Serial.print(F(" 0x77 400k="));
    if (deepI2cDiag.chipId77_400 >= 0) Serial.print(deepI2cDiag.chipId77_400, HEX); else Serial.print(F("--"));
    Serial.print(F(" 0x76 100k="));
    if (deepI2cDiag.chipId76_100 >= 0) Serial.print(deepI2cDiag.chipId76_100, HEX); else Serial.print(F("--"));
    Serial.print(F(" 0x77 100k="));
    if (deepI2cDiag.chipId77_100 >= 0) Serial.print(deepI2cDiag.chipId77_100, HEX); else Serial.print(F("--"));
    Serial.println();
}

'''
    cpp = cpp.replace(attempt_anchor, deep_block + attempt_anchor, 1)

    retry_anchor = "    scheduleDetectionRetry(now);\n    Serial.print(F(\"[BARO] BME280 non rilevato: 0x76=\"));"
    if retry_anchor not in cpp:
        raise RuntimeError("BME280 deep scan: failed-discovery anchor missing")
    cpp = cpp.replace(
        retry_anchor,
        "    if (detectionAttempts == 1U && !deepI2cDiag.scanCompleted) performDeepI2cScan();\n" + retry_anchor,
        1,
    )

    cpp += r'''

BarometerI2cDeepDiagnostics getBarometerI2cDeepDiagnostics() {
    return deepI2cDiag;
}

void runBarometerI2cDeepScan() {
    performDeepI2cScan();
}
'''
    write("src/barometer_manager.cpp", cpp)


# ---------------------------------------------------------------------------
# Canonical Web handler. Rebuilding the complete function on every build keeps
# the pre-script idempotent even when PlatformIO reuses a modified workspace.
# deep_scan=1 runs the full cached diagnostic only on explicit request.
# ---------------------------------------------------------------------------
web = read("src/web_manager.cpp")
handler = r'''void handleBarometerConfigGet() {
    if (server.hasArg("deep_scan") && server.arg("deep_scan") == "1")
        runBarometerI2cDeepScan();

    const BarometerRuntimeConfig c = getBarometerConfig();
    const BarometerDetectionDiagnostics d = getBarometerDetectionDiagnostics();
    const BarometerI2cDeepDiagnostics deep = getBarometerI2cDeepDiagnostics();
    const uint32_t diagNow = millis();
    const uint32_t retryInMs = (d.nextRetryMs != 0 && static_cast<int32_t>(d.nextRetryMs - diagNow) > 0)
        ? static_cast<uint32_t>(d.nextRetryMs - diagNow) : 0UL;

    String out;
    out.reserve(1100);
    out = "{\"altitude_m\":" + String(c.altitudeM, 1);
    out += ",\"pressure_unit\":" + String(static_cast<uint8_t>(c.displayUnit));
    out += ",\"pressure_unit_name\":\"" + String(pressureUnitName(c.displayUnit)) + "\"";
    out += ",\"detected\":"; out += barometerDetected() ? "true" : "false";
    out += ",\"address\":" + String(barometerAddress());
    out += ",\"detection_attempts\":" + String(d.attempts);
    out += ",\"last_attempt_ms\":" + String(d.lastAttemptMs);
    out += ",\"retry_in_ms\":" + String(retryInMs);
    out += ",\"retry_delay_ms\":" + String(d.retryDelayMs);
    out += ",\"i2c_sda\":" + String(I2C_SDA_PIN);
    out += ",\"i2c_scl\":" + String(I2C_SCL_PIN);
    out += ",\"i2c_ack_0x76\":"; out += d.i2cAck76 ? "true" : "false";
    out += ",\"i2c_ack_0x77\":"; out += d.i2cAck77 ? "true" : "false";
    out += ",\"read_failures_total\":" + String(d.readFailuresTotal);
    out += ",\"consecutive_read_failures\":" + String(d.consecutiveReadFailures);
    out += ",\"last_good_read_ms\":" + String(d.lastGoodReadMs);

    out += ",\"deep_scan_completed\":"; out += deep.scanCompleted ? "true" : "false";
    out += ",\"deep_scan_at_ms\":" + String(deep.scanAtMs);
    out += ",\"scan_400khz\":[";
    for (uint8_t i = 0; i < deep.count400; ++i) {
        if (i) out += ',';
        out += String(deep.addresses400[i]);
    }
    out += "]";
    out += ",\"scan_100khz\":[";
    for (uint8_t i = 0; i < deep.count100; ++i) {
        if (i) out += ',';
        out += String(deep.addresses100[i]);
    }
    out += "]";
    out += ",\"chip_id_0x76_400khz\":" + String(deep.chipId76_400);
    out += ",\"chip_id_0x77_400khz\":" + String(deep.chipId77_400);
    out += ",\"chip_id_0x76_100khz\":" + String(deep.chipId76_100);
    out += ",\"chip_id_0x77_100khz\":" + String(deep.chipId77_100);
    out += "}";
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", out);
}

'''
web = replace_function(web, "void handleBarometerConfigGet() {", handler)
write("src/web_manager.cpp", web)


# ---------------------------------------------------------------------------
# BAROMETRO UI. The cached boot scan is displayed immediately. A manual button
# reruns the full scan at 400/100 kHz through the existing authenticated GET
# endpoint, so no new route and no new background poll are introduced.
# ---------------------------------------------------------------------------
html = read("web/dashboard.html")

start = html.find('id="cfgBarometer"')
if start < 0:
    raise RuntimeError("BME280 deep scan: cfgBarometer page missing")

if 'id="baroDeepScanBtn"' not in html:
    diag_pos = html.find('<div id="baroDiag"', start)
    if diag_pos < 0:
        raise RuntimeError("BME280 deep scan: baroDiag anchor missing")
    button = '<div class="cfgActions"><button type="button" class="modeBtn" id="baroDeepScanBtn" onclick="deepScanBarometer()">Scansione I2C completa</button><span class="muted">400 kHz + 100 kHz · CHIP_ID 0xD0</span></div>\n'
    html = html[:diag_pos] + button + html[diag_pos:]

helper_start = html.find("function updateBarometerDiagnostics(c){")
load_anchor = html.find("async function loadBarometer()", helper_start)
if helper_start < 0 or load_anchor < 0:
    raise RuntimeError("BME280 deep scan: diagnostics JS anchors missing")

helper = r'''function updateBarometerDiagnostics(c){const e=E('baroDiag');if(!e||!c)return;const hx=v=>'0x'+Number(v).toString(16).toUpperCase().padStart(2,'0'),list=a=>Array.isArray(a)&&a.length?a.map(hx).join(', '):'nessun dispositivo',chip=v=>Number(v)>=0?hx(v):'--';const a76=c.i2c_ack_0x76?'ACK':'--',a77=c.i2c_ack_0x77?'ACK':'--',tries=Number(c.detection_attempts||0),fails=Number(c.read_failures_total||0),retry=Math.ceil(Number(c.retry_in_ms||0)/1000);let s='I2C SDA '+String(c.i2c_sda??'--')+' / SCL '+String(c.i2c_scl??'--')+' · 0x76 '+a76+' · 0x77 '+a77+' · tentativi '+tries;if(c.detected){s+=' · BME280 OK @0x'+Number(c.address||0).toString(16).toUpperCase();}else if(c.i2c_ack_0x76||c.i2c_ack_0x77){s+=' · dispositivo I2C presente ma non riconosciuto come BME280';}else{s+=' · BME280 assente';if(retry>0)s+=' · nuovo tentativo tra '+retry+' s';}if(fails>0)s+=' · errori lettura '+fails;if(c.deep_scan_completed){s+='\nScan 400 kHz: '+list(c.scan_400khz)+' · Scan 100 kHz: '+list(c.scan_100khz);s+='\nCHIP_ID 0xD0 · 0x76: '+chip(c.chip_id_0x76_400khz)+' @400k / '+chip(c.chip_id_0x76_100khz)+' @100k';s+=' · 0x77: '+chip(c.chip_id_0x77_400khz)+' @400k / '+chip(c.chip_id_0x77_100khz)+' @100k';if([c.chip_id_0x76_400khz,c.chip_id_0x77_400khz,c.chip_id_0x76_100khz,c.chip_id_0x77_100khz].some(v=>Number(v)===0x60))s+=' · BME280 CHIP_ID 0x60 confermato';}e.textContent=s;e.style.whiteSpace='pre-line';}
async function deepScanBarometer(){const b=E('baroDeepScanBtn');if(b){b.disabled=true;b.textContent='Scansione I2C...';}try{const r=await fetch('/api/barometer/config?deep_scan=1',{cache:'no-store'});const c=await r.json();if(!r.ok)throw new Error(c.error||('HTTP '+r.status));updateBarometerDiagnostics(c);}catch(err){alert('Scansione I2C fallita: '+err.message);}finally{if(b){b.disabled=false;b.textContent='Scansione I2C completa';}}}
'''
html = html[:helper_start] + helper + html[load_anchor:]
write("web/dashboard.html", html)

print("Applied BME280 deep I2C 400/100 kHz scan, Bosch chip-ID probe and Web diagnostics")
