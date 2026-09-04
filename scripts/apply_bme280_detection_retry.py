Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def replace_function(text, signature, replacement):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"BME280 retry: missing function {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"BME280 retry: missing opening brace {signature}")
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
    raise RuntimeError(f"BME280 retry: missing closing brace {signature}")


# ---------------------------------------------------------------------------
# Public diagnostics API. This pass intentionally runs after
# apply_barometer_runtime.py, which adds the runtime barometer structures.
# ---------------------------------------------------------------------------
header = read("src/barometer_manager.h")
if "struct BarometerDetectionDiagnostics" not in header:
    header += r'''

// BME280_DETECTION_RETRY_V1
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
# Non-blocking BME280 detection/recovery.
# Retry sequence after a failed discovery: 5 s, 15 s, 60 s, then 5 min.
# If a previously working sensor stops returning valid pressure for six
# consecutive reads, it is marked offline and rediscovery restarts at 5 s.
# ---------------------------------------------------------------------------
cpp = read("src/barometer_manager.cpp")
if "BME280_DETECTION_RETRY_V1" not in cpp:
    runtime_anchor = 'BarometerRuntimeConfig runtimeCfg{};\n'
    if runtime_anchor not in cpp:
        raise RuntimeError("BME280 retry: BAROMETER_RUNTIME_V1 must run first")

    state_block = r'''

// BME280_DETECTION_RETRY_V1
constexpr uint32_t BME_RETRY_5S_MS = 5000UL;
constexpr uint32_t BME_RETRY_15S_MS = 15000UL;
constexpr uint32_t BME_RETRY_60S_MS = 60000UL;
constexpr uint32_t BME_RETRY_5MIN_MS = 300000UL;
constexpr uint8_t BME_READ_FAILURE_LIMIT = 6U;

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

bool i2cAddressResponds(uint8_t addr) {
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
    lastI2cAck76 = i2cAddressResponds(0x76);
    lastI2cAck77 = i2cAddressResponds(0x77);

    detected = false;
    address = 0;
    bool ok = false;
    if (lastI2cAck76) ok = tryBme(0x76);
    if (!ok && lastI2cAck77) ok = tryBme(0x77);

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
    cpp = cpp.replace(runtime_anchor, runtime_anchor + state_block, 1)

    init_replacement = r'''void initBarometer() {
    loadBarometerConfig();
#if BAROMETER_ENABLE
    retryStage = 0;
    nextDetectionRetryMs = 0;
    currentRetryDelayMs = 0;
    consecutiveReadFailures = 0;
    if (attemptBmeDetection()) {
        Serial.print(F("[BARO] quota="));
        Serial.print(runtimeCfg.altitudeM, 1);
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
    const float seaLevelHpa = seaLevelFromAltitude(absoluteHpa, runtimeCfg.altitudeM);

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

    public_anchor = 'uint8_t barometerAddress() { return address; }\n'
    if public_anchor not in cpp:
        raise RuntimeError("BME280 retry: public diagnostics anchor missing")
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
# Authenticated barometer configuration API diagnostics.
# ---------------------------------------------------------------------------
web = read("src/web_manager.cpp")
if '\"detection_attempts\"' not in web:
    anchor = r'''    out += ",\"address\":" + String(barometerAddress());
'''
    if anchor not in web:
        raise RuntimeError("BME280 retry: barometer config JSON anchor missing")
    extra = r'''    const BarometerDetectionDiagnostics d = getBarometerDetectionDiagnostics();
    const uint32_t diagNow = millis();
    const uint32_t retryInMs = (d.nextRetryMs != 0 && static_cast<int32_t>(d.nextRetryMs - diagNow) > 0)
        ? static_cast<uint32_t>(d.nextRetryMs - diagNow) : 0UL;
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
'''
    web = web.replace(anchor, anchor + extra, 1)
    write("src/web_manager.cpp", web)


# ---------------------------------------------------------------------------
# BAROMETRO Web tab diagnostics. It reuses the existing authenticated config
# fetch; no new poll or background timer is introduced.
# ---------------------------------------------------------------------------
path = root / "web" / "dashboard.html"
html = path.read_text(encoding="utf-8")

if 'id="baroDiag"' not in html:
    start = html.find('id="cfgBarometer"')
    if start < 0:
        raise RuntimeError("BME280 retry: cfgBarometer page missing; compact sensor pass must run first")
    pos = html.find('<div class="cfgActions">', start)
    if pos < 0:
        raise RuntimeError("BME280 retry: BAROMETRO cfgActions anchor missing")
    diag = '<div id="baroDiag" class="cfgNote">Diagnostica BME280 in acquisizione...</div>\n'
    html = html[:pos] + diag + html[pos:]

if "function updateBarometerDiagnostics(" not in html:
    helper = r'''function updateBarometerDiagnostics(c){const e=E('baroDiag');if(!e||!c)return;const a76=c.i2c_ack_0x76?'ACK':'--',a77=c.i2c_ack_0x77?'ACK':'--',tries=Number(c.detection_attempts||0),fails=Number(c.read_failures_total||0),retry=Math.ceil(Number(c.retry_in_ms||0)/1000);let s='I2C SDA '+String(c.i2c_sda??'--')+' / SCL '+String(c.i2c_scl??'--')+' · 0x76 '+a76+' · 0x77 '+a77+' · tentativi '+tries;if(c.detected){s+=' · BME280 OK @0x'+Number(c.address||0).toString(16).toUpperCase();}else if(c.i2c_ack_0x76||c.i2c_ack_0x77){s+=' · dispositivo I2C presente ma non riconosciuto come BME280: verificare BME280/BMP280';}else{s+=' · BME280 assente';if(retry>0)s+=' · nuovo tentativo tra '+retry+' s';}if(fails>0)s+=' · errori lettura '+fails;e.textContent=s;}
'''
    anchor = "async function loadBarometer()"
    if anchor not in html:
        raise RuntimeError("BME280 retry: loadBarometer JS anchor missing")
    html = html.replace(anchor, helper + anchor, 1)

summary_anchor = "E('barometerSummary').textContent=(c.detected?'BME280 rilevato':'BME280 non rilevato')+' · quota '+Number(c.altitude_m||0).toFixed(0)+' m · '+(c.pressure_unit_name||'hPa');"
if "updateBarometerDiagnostics(c);" not in html:
    if summary_anchor not in html:
        raise RuntimeError("BME280 retry: barometer summary JS anchor missing")
    html = html.replace(summary_anchor, summary_anchor + "updateBarometerDiagnostics(c);", 1)

path.write_text(html, encoding="utf-8")
print("Applied BME280 non-blocking detection retry, recovery and diagnostics")
