Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    p = root / path
    current = p.read_text(encoding="utf-8")
    if current != text:
        p.write_text(text, encoding="utf-8")


def replace_function(text, signature, replacement):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"BME280 main hotfix: missing function {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"BME280 main hotfix: missing opening brace {signature}")
    depth = 0
    end = brace
    while end < len(text):
        ch = text[end]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end += 1
                while end < len(text) and text[end] in "\r\n":
                    end += 1
                return text[:start] + replacement + text[end:]
        end += 1
    raise RuntimeError(f"BME280 main hotfix: missing closing brace {signature}")


# ---------------------------------------------------------------------------
# Shared I2C bus: validated runtime settings from develop/hardware tests.
# Keep OLED + BME280 on 100 kHz and use the same 80 ms Wire timeout used by
# the known-good standalone hardware test.
# ---------------------------------------------------------------------------
display = read("src/display_manager.cpp")
if "BME280_I2C_MAIN_HOTFIX_DISPLAY_V1" not in display:
    old = """    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);\n    oled.setBusClock(400000);\n    oled.begin();\n"""
    new = """    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);\n    // BME280_I2C_MAIN_HOTFIX_DISPLAY_V1\n    Wire.setTimeOut(80);\n    Wire.setClock(100000);\n    oled.setBusClock(100000);\n    oled.begin();\n"""
    if old not in display:
        raise RuntimeError("BME280 main hotfix: initDisplay I2C anchor missing")
    display = display.replace(old, new, 1)
    write("src/display_manager.cpp", display)


# ---------------------------------------------------------------------------
# BME280 diagnostics API.
# ---------------------------------------------------------------------------
header = read("src/barometer_manager.h")
if "BME280_I2C_MAIN_HOTFIX_API_V1" not in header:
    header += r'''

// BME280_I2C_MAIN_HOTFIX_API_V1
struct BarometerDetectionDiagnostics {
    uint32_t attempts{0};
    uint32_t lastAttemptMs{0};
    uint32_t nextRetryMs{0};
    uint32_t retryDelayMs{0};
    uint32_t readFailuresTotal{0};
    uint32_t lastGoodReadMs{0};
    uint8_t consecutiveReadFailures{0};
    bool i2cAck76{false};
    bool i2cAck77{false};
};

BarometerDetectionDiagnostics getBarometerDetectionDiagnostics();
'''
    write("src/barometer_manager.h", header)


# ---------------------------------------------------------------------------
# Non-blocking BME280 discovery/recovery.
# 5 s -> 15 s -> 60 s -> 5 min after a failed discovery.
# Six consecutive invalid pressure reads mark the device offline and restart
# rediscovery. BME280 0x77 is preferred because it is the Waveshare default;
# 0x76 remains fully supported.
# ---------------------------------------------------------------------------
cpp = read("src/barometer_manager.cpp")
if "BME280_I2C_MAIN_HOTFIX_CORE_V1" not in cpp:
    anchor = "uint32_t lastReadMs = 0;\n"
    if anchor not in cpp:
        raise RuntimeError("BME280 main hotfix: barometer state anchor missing")

    state = r'''

// BME280_I2C_MAIN_HOTFIX_CORE_V1
constexpr uint32_t BME_RETRY_5S_MS = 5000UL;
constexpr uint32_t BME_RETRY_15S_MS = 15000UL;
constexpr uint32_t BME_RETRY_60S_MS = 60000UL;
constexpr uint32_t BME_RETRY_5MIN_MS = 300000UL;
constexpr uint8_t BME_READ_FAILURE_LIMIT = 6U;
constexpr uint32_t I2C_RUNTIME_CLOCK_HZ = 100000UL;
constexpr uint16_t I2C_RUNTIME_TIMEOUT_MS = 80U;

uint32_t detectionAttempts = 0;
uint32_t lastDetectionAttemptMs = 0;
uint32_t nextDetectionRetryMs = 0;
uint32_t currentRetryDelayMs = 0;
uint32_t readFailuresTotal = 0;
uint32_t lastGoodReadMs = 0;
uint8_t consecutiveReadFailures = 0;
uint8_t retryStage = 0;
bool lastI2cAck76 = false;
bool lastI2cAck77 = false;

void configureI2cRuntimeBus() {
    Wire.setTimeOut(I2C_RUNTIME_TIMEOUT_MS);
    Wire.setClock(I2C_RUNTIME_CLOCK_HZ);
}

bool i2cAddressResponds(uint8_t addr) {
    configureI2cRuntimeBus();
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
}

uint32_t retryDelayForStage(uint8_t stage) {
    switch (stage) {
        case 0: return BME_RETRY_5S_MS;
        case 1: return BME_RETRY_15S_MS;
        case 2: return BME_RETRY_60S_MS;
        default: return BME_RETRY_5MIN_MS;
    }
}

void scheduleDetectionRetry(uint32_t now) {
    currentRetryDelayMs = retryDelayForStage(retryStage);
    nextDetectionRetryMs = now + currentRetryDelayMs;
    if (retryStage < 3U) retryStage++;
}

bool attemptBmeDetection() {
    const uint32_t now = millis();
    detectionAttempts++;
    lastDetectionAttemptMs = now;
    configureI2cRuntimeBus();
    lastI2cAck76 = i2cAddressResponds(0x76);
    lastI2cAck77 = i2cAddressResponds(0x77);

    detected = false;
    address = 0;
    bool ok = false;
    if (lastI2cAck77) ok = tryBme(0x77);
    if (!ok && lastI2cAck76) ok = tryBme(0x76);

    if (ok) {
        retryStage = 0;
        nextDetectionRetryMs = 0;
        currentRetryDelayMs = 0;
        consecutiveReadFailures = 0;
        Serial.print(F("[BARO] BME280 rilevato @0x"));
        Serial.print(address, HEX);
        Serial.print(F(" tentativo="));
        Serial.println(detectionAttempts);
        return true;
    }

    scheduleDetectionRetry(now);
    Serial.print(F("[BARO] BME280 non rilevato: 0x76="));
    Serial.print(lastI2cAck76 ? F("ACK") : F("--"));
    Serial.print(F(" 0x77="));
    Serial.print(lastI2cAck77 ? F("ACK") : F("--"));
    Serial.print(F(" retry="));
    Serial.print(currentRetryDelayMs / 1000UL);
    Serial.println(F("s"));
    return false;
}
'''
    cpp = cpp.replace(anchor, anchor + state, 1)

    # Every driver transaction is forced back to the validated runtime bus.
    try_anchor = "bool tryBme(uint8_t addr) {\n    if (!bme.begin(addr, &Wire)) return false;"
    try_repl = "bool tryBme(uint8_t addr) {\n    configureI2cRuntimeBus();\n    if (!bme.begin(addr, &Wire)) return false;"
    if try_anchor not in cpp:
        raise RuntimeError("BME280 main hotfix: tryBme anchor missing")
    cpp = cpp.replace(try_anchor, try_repl, 1)

    init_replacement = r'''void initBarometer() {
#if BAROMETER_ENABLE
    retryStage = 0;
    nextDetectionRetryMs = 0;
    currentRetryDelayMs = 0;
    consecutiveReadFailures = 0;
    if (attemptBmeDetection()) {
        Serial.print(F("[BARO] quota="));
        Serial.print(BAROMETER_ALTITUDE_M, 1);
        Serial.println(F(" m"));
    }
#else
    Serial.println(F("[BARO] supporto BME280 disabilitato"));
#endif
}

'''
    cpp = replace_function(cpp, "void initBarometer() {", init_replacement)

    service_replacement = r'''void serviceBarometer(StationState &state) {
#if BAROMETER_ENABLE
    const uint32_t now = millis();

    if (!detected) {
        if (nextDetectionRetryMs == 0 ||
            static_cast<int32_t>(now - nextDetectionRetryMs) >= 0) {
            attemptBmeDetection();
        }
        return;
    }

    if (static_cast<uint32_t>(now - lastReadMs) < BAROMETER_READ_MS) return;
    lastReadMs = now;
    configureI2cRuntimeBus();

    const float pressurePa = bme.readPressure();
    const float tempC = bme.readTemperature();
    const float humidity = bme.readHumidity();
    const bool pressureOk = isfinite(pressurePa) && pressurePa >= 30000.0f && pressurePa <= 120000.0f;

    if (!pressureOk) {
        readFailuresTotal++;
        if (consecutiveReadFailures < 255U) consecutiveReadFailures++;
        if (consecutiveReadFailures >= BME_READ_FAILURE_LIMIT) {
            Serial.print(F("[BARO] BME280 perso dopo "));
            Serial.print(consecutiveReadFailures);
            Serial.println(F(" letture non valide: avvio rediscovery"));
            detected = false;
            address = 0;
            state.pressureValid = false;
            state.pressureTrendValid = false;
            state.indoorTemperatureValid = false;
            state.indoorHumidityValid = false;
            retryStage = 0;
            scheduleDetectionRetry(now);
        }
        return;
    }

    consecutiveReadFailures = 0;
    lastGoodReadMs = now;

    const float absoluteHpa = pressurePa / 100.0f;
    const float seaLevelHpa = seaLevelFromAltitude(absoluteHpa, BAROMETER_ALTITUDE_M);

    state.pressureAbsoluteHpa = absoluteHpa;
    state.pressureSeaLevelHpa = seaLevelHpa;
    state.pressureUpdatedMs = now;
    state.pressureValid = true;

    state.indoorTemperatureC = tempC;
    state.indoorTemperatureValid = isfinite(tempC) && tempC > -50.0f && tempC < 100.0f;
    state.indoorHumidityPct = humidity;
    state.indoorHumidityValid = isfinite(humidity) && humidity >= 0.0f && humidity <= 100.0f;

    addPressureTrendSample(state, now, seaLevelHpa);
#else
    (void)state;
#endif
}

'''
    cpp = replace_function(cpp, "void serviceBarometer(StationState &state) {", service_replacement)

    sleep_anchor = "void prepareBarometerForDeepSleep() {\n#if BAROMETER_ENABLE\n    if (!detected) return;\n    bme.setSampling"
    sleep_repl = "void prepareBarometerForDeepSleep() {\n#if BAROMETER_ENABLE\n    if (!detected) return;\n    configureI2cRuntimeBus();\n    bme.setSampling"
    if sleep_anchor not in cpp:
        raise RuntimeError("BME280 main hotfix: sleep anchor missing")
    cpp = cpp.replace(sleep_anchor, sleep_repl, 1)

    public_anchor = "uint8_t barometerAddress() { return address; }\n"
    if public_anchor not in cpp:
        raise RuntimeError("BME280 main hotfix: diagnostics public anchor missing")
    public_api = r'''

BarometerDetectionDiagnostics getBarometerDetectionDiagnostics() {
    BarometerDetectionDiagnostics d;
    d.attempts = detectionAttempts;
    d.lastAttemptMs = lastDetectionAttemptMs;
    d.nextRetryMs = nextDetectionRetryMs;
    d.retryDelayMs = currentRetryDelayMs;
    d.readFailuresTotal = readFailuresTotal;
    d.lastGoodReadMs = lastGoodReadMs;
    d.consecutiveReadFailures = consecutiveReadFailures;
    d.i2cAck76 = lastI2cAck76;
    d.i2cAck77 = lastI2cAck77;
    return d;
}
'''
    cpp = cpp.replace(public_anchor, public_anchor + public_api, 1)
    write("src/barometer_manager.cpp", cpp)


# ---------------------------------------------------------------------------
# Web diagnostics: dedicated CONFIGURAZIONE > I2C / HW tab, manual scanner,
# BME280 chip-ID probe and MCU die temperature. No periodic bus scan.
# ---------------------------------------------------------------------------
web = read("src/web_manager.cpp")
if "BME280_I2C_MAIN_HOTFIX_WEB_V1" not in web:
    if '#include <Wire.h>' not in web:
        inc = '#include <WiFi.h>\n'
        if inc not in web:
            raise RuntimeError("BME280 main hotfix: Web include anchor missing")
        web = web.replace(inc, inc + '#include <Wire.h>\n', 1)

    helper_anchor = "void handleState() {\n"
    if helper_anchor not in web:
        raise RuntimeError("BME280 main hotfix: handleState anchor missing")
    helpers = r'''
// BME280_I2C_MAIN_HOTFIX_WEB_V1
float hardwareTemperatureC() {
#if defined(ESP32)
    const float t = temperatureRead();
    return isfinite(t) ? t : NAN;
#else
    return NAN;
#endif
}

void restoreI2cRuntimeBus() {
    Wire.setTimeOut(80);
    Wire.setClock(100000);
}

String scanI2cAddresses(uint32_t clockHz) {
    Wire.setTimeOut(80);
    Wire.setClock(clockHz);
    String out = "[";
    bool first = true;
    for (uint8_t addr = 1; addr < 127; ++addr) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            if (!first) out += ',';
            out += String(addr);
            first = false;
        }
    }
    out += ']';
    return out;
}

int readBoschChipId(uint8_t addr) {
    restoreI2cRuntimeBus();
    Wire.beginTransmission(addr);
    Wire.write(static_cast<uint8_t>(0xD0));
    if (Wire.endTransmission(false) != 0) return -1;
    if (Wire.requestFrom(static_cast<int>(addr), 1) != 1) return -1;
    return static_cast<int>(Wire.read());
}

void handleI2cHardware() {
    const BarometerDetectionDiagnostics d = getBarometerDetectionDiagnostics();
    const uint32_t now = millis();
    const uint32_t retryInMs = (d.nextRetryMs != 0 && static_cast<int32_t>(d.nextRetryMs - now) > 0)
        ? static_cast<uint32_t>(d.nextRetryMs - now) : 0UL;
    const float mcuTemp = hardwareTemperatureC();

    String out;
    out.reserve(640);
    out += "{\"sda\":" + String(I2C_SDA_PIN);
    out += ",\"scl\":" + String(I2C_SCL_PIN);
    out += ",\"runtime_hz\":100000";
    out += ",\"timeout_ms\":80";
    out += ",\"oled_address\":60";
    out += ",\"bme_detected\":"; out += barometerDetected() ? "true" : "false";
    out += ",\"bme_address\":" + String(barometerAddress());
    out += ",\"ack_0x76\":"; out += d.i2cAck76 ? "true" : "false";
    out += ",\"ack_0x77\":"; out += d.i2cAck77 ? "true" : "false";
    out += ",\"detection_attempts\":" + String(d.attempts);
    out += ",\"retry_in_ms\":" + String(retryInMs);
    out += ",\"retry_delay_ms\":" + String(d.retryDelayMs);
    out += ",\"read_failures_total\":" + String(d.readFailuresTotal);
    out += ",\"consecutive_read_failures\":" + String(d.consecutiveReadFailures);
    out += ",\"last_good_read_ms\":" + String(d.lastGoodReadMs);
    out += ",\"hardware_temperature_c\":" + jsonFloat(mcuTemp, 1);
    out += "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleI2cScan() {
    const uint32_t started = millis();
    const int sdaBefore = digitalRead(I2C_SDA_PIN);
    const int sclBefore = digitalRead(I2C_SCL_PIN);
    const String a100 = scanI2cAddresses(100000);
    const String a400 = scanI2cAddresses(400000);
    restoreI2cRuntimeBus();
    const int chip76 = readBoschChipId(0x76);
    const int chip77 = readBoschChipId(0x77);
    restoreI2cRuntimeBus();
    const int sdaAfter = digitalRead(I2C_SDA_PIN);
    const int sclAfter = digitalRead(I2C_SCL_PIN);

    String out;
    out.reserve(520);
    out += "{\"addresses_100khz\":" + a100;
    out += ",\"addresses_400khz\":" + a400;
    out += ",\"chip_id_0x76\":" + String(chip76);
    out += ",\"chip_id_0x77\":" + String(chip77);
    out += ",\"sda_before\":" + String(sdaBefore);
    out += ",\"scl_before\":" + String(sclBefore);
    out += ",\"sda_after\":" + String(sdaAfter);
    out += ",\"scl_after\":" + String(sclAfter);
    out += ",\"duration_ms\":" + String(static_cast<uint32_t>(millis() - started));
    out += "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

'''
    web = web.replace(helper_anchor, helpers + helper_anchor, 1)

    # Expose MCU die temperature in the existing Hardware page state payload.
    state_anchor = '    out += ",\\\"cpu_mhz\\\":" + String(ESP.getCpuFreqMHz());\n'
    if state_anchor not in web:
        raise RuntimeError("BME280 main hotfix: system JSON CPU anchor missing")
    state_extra = '    out += ",\\\"hardware_temperature_c\\\":" + jsonFloat(hardwareTemperatureC(), 1);\n'
    web = web.replace(state_anchor, state_anchor + state_extra, 1)

    # Add the MCU temperature line to HARDWARE > CPU / SoC.
    hw_anchor = '<div class=\\"resourceLine\\"><span class=\\"name\\">Core</span><span class=\\"value\\" id=\\"sysCores\\">--</span></div><div class=\\"resourceLine\\"><span class=\\"name\\">Uptime</span>'
    hw_repl = '<div class=\\"resourceLine\\"><span class=\\"name\\">Core</span><span class=\\"value\\" id=\\"sysCores\\">--</span></div><div class=\\"resourceLine\\"><span class=\\"name\\">Temperatura MCU</span><span class=\\"value\\" id=\\"sysMcuTemp\\">--</span></div><div class=\\"resourceLine\\"><span class=\\"name\\">Uptime</span>'
    if hw_anchor not in web:
        raise RuntimeError("BME280 main hotfix: Hardware CPU card anchor missing")
    web = web.replace(hw_anchor, hw_repl, 1)

    # Dedicated configuration tab.
    tabs_anchor = '<button id=\\"tabDisplay\\" class=\\"cfgTab\\" onclick=\\"showCfgTab(\'display\')\\">DISPLAY</button><button id=\\"tabBackup\\"'
    tabs_repl = '<button id=\\"tabDisplay\\" class=\\"cfgTab\\" onclick=\\"showCfgTab(\'display\')\\">DISPLAY</button><button id=\\"tabI2c\\" class=\\"cfgTab\\" onclick=\\"showCfgTab(\'i2c\')\\">I2C / HW</button><button id=\\"tabBackup\\"'
    if tabs_anchor not in web:
        raise RuntimeError("BME280 main hotfix: configuration tab anchor missing")
    web = web.replace(tabs_anchor, tabs_repl, 1)

    page_anchor = '<div id=\\"cfgBackup\\" class=\\"cfgPage\\">'
    if page_anchor not in web:
        raise RuntimeError("BME280 main hotfix: cfgBackup anchor missing")
    page = r'''<div id=\"cfgI2c\" class=\"cfgPage\">
<div class=\"cfgGrid\">
<label><span>Bus I2C runtime</span><input id=\"i2cBus\" type=\"text\" readonly></label>
<label><span>Temperatura MCU</span><input id=\"i2cMcuTemp\" type=\"text\" readonly></label>
<label><span>BME280</span><input id=\"i2cBme\" type=\"text\" readonly></label>
<label><span>OLED</span><input id=\"i2cOled\" type=\"text\" readonly></label>
<label class=\"cfgWide\"><span>Rilevamento BME280</span><input id=\"i2cBmeDiag\" type=\"text\" readonly></label>
</div>
<div class=\"cfgActions\"><button class=\"modeBtn\" onclick=\"scanI2cBus()\">Scanner I2C</button><button class=\"modeBtn\" onclick=\"loadI2cHardware()\">Aggiorna</button><span id=\"i2cSummary\" class=\"muted\">Scanner manuale · nessun polling aggiuntivo</span></div>
<div class=\"diag\" id=\"i2cScanResult\">Premi Scanner I2C per verificare 100 kHz e 400 kHz.</div>
<div class=\"cfgNote\">Il runtime resta a 100 kHz con timeout 80 ms. Il test a 400 kHz e' solo diagnostico; al termine il bus viene sempre riportato a 100 kHz. Un BME280 Bosch valido risponde normalmente a 0x76/0x77 con chip ID 0x60.</div>
</div>
'''
    web = web.replace(page_anchor, page + page_anchor, 1)

    js_tabs = "function showCfgTab(t){for(const x of ['net','mqtt','display','backup'])"
    js_tabs_new = "function showCfgTab(t){for(const x of ['net','mqtt','display','i2c','backup'])"
    if js_tabs not in web:
        raise RuntimeError("BME280 main hotfix: showCfgTab list anchor missing")
    web = web.replace(js_tabs, js_tabs_new, 1)

    js_tail = "else if(t==='display')loadDisplay();}function setFresh"
    js_tail_new = "else if(t==='display')loadDisplay();else if(t==='i2c')loadI2cHardware();}function setFresh"
    if js_tail not in web:
        raise RuntimeError("BME280 main hotfix: showCfgTab dispatch anchor missing")
    web = web.replace(js_tail, js_tail_new, 1)

    js_anchor = "async function loadNetwork(){"
    if js_anchor not in web:
        raise RuntimeError("BME280 main hotfix: JS network anchor missing")
    js_helpers = r'''function i2cHex(v){const n=Number(v);return Number.isFinite(n)&&n>=0?'0x'+n.toString(16).toUpperCase().padStart(2,'0'):'--'}
function i2cAddressList(a){return Array.isArray(a)&&a.length?a.map(i2cHex).join(', '):'nessun dispositivo'}
async function loadI2cHardware(){try{const d=await (await fetch('/api/i2c/hardware',{cache:'no-store'})).json();E('i2cBus').value='SDA '+d.sda+' / SCL '+d.scl+' · '+Math.round(Number(d.runtime_hz||0)/1000)+' kHz · timeout '+d.timeout_ms+' ms';E('i2cMcuTemp').value=d.hardware_temperature_c==null?'N/D':Number(d.hardware_temperature_c).toFixed(1)+' °C';E('i2cBme').value=d.bme_detected?'OK @'+i2cHex(d.bme_address):'non rilevato';E('i2cOled').value=i2cHex(d.oled_address)+' atteso';const retry=Math.ceil(Number(d.retry_in_ms||0)/1000),a76=d.ack_0x76?'ACK':'--',a77=d.ack_0x77?'ACK':'--';let s='0x76 '+a76+' · 0x77 '+a77+' · tentativi '+Number(d.detection_attempts||0);if(!d.bme_detected&&retry>0)s+=' · retry '+retry+' s';if(Number(d.read_failures_total||0)>0)s+=' · errori '+Number(d.read_failures_total);E('i2cBmeDiag').value=s;E('i2cSummary').textContent=d.bme_detected?'BME280 operativo':'BME280 in rilevamento / retry';}catch(e){E('i2cSummary').textContent='Errore lettura diagnostica I2C';}}
async function scanI2cBus(){const box=E('i2cScanResult'),sum=E('i2cSummary');box.textContent='Scansione in corso...';sum.textContent='Scanner I2C attivo';try{const r=await fetch('/api/i2c/scan',{method:'POST',cache:'no-store'});if(!r.ok)throw new Error(await r.text());const d=await r.json(),c76=Number(d.chip_id_0x76),c77=Number(d.chip_id_0x77);let verdict='Nessun BME280 confermato';if(c76===96)verdict='BME280 confermato @0x76 · chip ID 0x60';if(c77===96)verdict='BME280 confermato @0x77 · chip ID 0x60';box.textContent='100 kHz: '+i2cAddressList(d.addresses_100khz)+'\n400 kHz: '+i2cAddressList(d.addresses_400khz)+'\nChip ID 0x76: '+i2cHex(c76)+' · 0x77: '+i2cHex(c77)+'\nSDA/SCL iniziali: '+d.sda_before+'/'+d.scl_before+' · finali: '+d.sda_after+'/'+d.scl_after+'\nDurata: '+d.duration_ms+' ms\n'+verdict;sum.textContent='Scansione completata · runtime ripristinato a 100 kHz';await loadI2cHardware();}catch(e){box.textContent='Scanner I2C fallito: '+e;sum.textContent='Errore scanner';}}
'''
    web = web.replace(js_anchor, js_helpers + js_anchor, 1)

    refresh_anchor = "E('sysCores').textContent=sys.cores??'--';E('sysUptime')"
    refresh_repl = "E('sysCores').textContent=sys.cores??'--';E('sysMcuTemp').textContent=sys.hardware_temperature_c==null?'N/D':Number(sys.hardware_temperature_c).toFixed(1)+' °C';E('sysUptime')"
    if refresh_anchor not in web:
        raise RuntimeError("BME280 main hotfix: Hardware refresh anchor missing")
    web = web.replace(refresh_anchor, refresh_repl, 1)

    route_anchor = '    server.on(\"/api/state\", HTTP_GET, handleState);\n'
    if route_anchor not in web:
        raise RuntimeError("BME280 main hotfix: route anchor missing")
    routes = '    server.on(\"/api/i2c/hardware\", HTTP_GET, handleI2cHardware);\n    server.on(\"/api/i2c/scan\", HTTP_POST, handleI2cScan);\n'
    web = web.replace(route_anchor, route_anchor + routes, 1)

    write("src/web_manager.cpp", web)

print("Applied main BME280/I2C reliability hotfix and diagnostics")
