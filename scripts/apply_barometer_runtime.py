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
        raise RuntimeError(f"Barometer runtime: missing function {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Barometer runtime: missing opening brace {signature}")
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
    raise RuntimeError(f"Barometer runtime: missing closing brace {signature}")


# ---------------------------------------------------------------------------
# BME280 runtime configuration. Internal meteorological values remain in hPa.
# ---------------------------------------------------------------------------
header = read("src/barometer_manager.h")
if "struct BarometerRuntimeConfig" not in header:
    header += r'''
// BAROMETER_RUNTIME_V1
enum class PressureDisplayUnit : uint8_t {
    Hpa = 0,
    Mbar = 1,
    InHg = 2,
    MmHg = 3,
    Kpa = 4
};

enum class BarometerForecastCode : uint8_t {
    PartlyCloudy = 0,
    Rainy = 1,
    Cloudy = 2,
    Sunny = 3,
    ClearNight = 4,
    Snowy = 5,
    PartlyCloudyNight = 6,
    Unknown = 7
};

struct BarometerRuntimeConfig {
    float altitudeM{0.0f};
    PressureDisplayUnit displayUnit{PressureDisplayUnit::Hpa};
};

BarometerRuntimeConfig getBarometerConfig();
bool validateBarometerConfig(const BarometerRuntimeConfig &cfg);
bool saveBarometerConfig(const BarometerRuntimeConfig &cfg, bool &changed);
bool resetBarometerConfigToDefaults(bool &changed);
float barometerAltitudeM();
const char *pressureUnitName(PressureDisplayUnit unit);
float pressureDisplayValue(float pressureHpa, PressureDisplayUnit unit);
BarometerForecastCode barometerForecastCode(const StationState &state);
'''
    write("src/barometer_manager.h", header)

cpp = read("src/barometer_manager.cpp")
if "BAROMETER_RUNTIME_V1" not in cpp:
    if "#include <Preferences.h>" not in cpp:
        cpp = cpp.replace("#include <Adafruit_BME280.h>\n", "#include <Adafruit_BME280.h>\n#include <Preferences.h>\n", 1)

    anchor = "uint32_t lastTrendSampleMs = 0;\n\n"
    if anchor not in cpp:
        raise RuntimeError("Barometer runtime: pressure-history anchor missing")
    block = r'''// BAROMETER_RUNTIME_V1
constexpr const char *BAROMETER_NVS_NS = "barocfg";
BarometerRuntimeConfig runtimeCfg{};

BarometerRuntimeConfig defaultBarometerConfig() {
    BarometerRuntimeConfig c;
    c.altitudeM = BAROMETER_ALTITUDE_M;
    c.displayUnit = PressureDisplayUnit::Hpa;
    return c;
}

void normalizeBarometerConfig(BarometerRuntimeConfig &c) {
    if (!isfinite(c.altitudeM) || c.altitudeM < 0.0f || c.altitudeM > 9000.0f)
        c.altitudeM = BAROMETER_ALTITUDE_M;
    if (static_cast<uint8_t>(c.displayUnit) > static_cast<uint8_t>(PressureDisplayUnit::Kpa))
        c.displayUnit = PressureDisplayUnit::Hpa;
}

bool sameBarometerConfig(const BarometerRuntimeConfig &a, const BarometerRuntimeConfig &b) {
    return fabsf(a.altitudeM - b.altitudeM) < 0.05f && a.displayUnit == b.displayUnit;
}

void resetPressureHistory() {
    for (uint8_t i = 0; i < PRESSURE_HISTORY_SIZE; ++i)
        pressureHistory[i] = PressureSample{};
    pressureHead = 0;
    pressureCount = 0;
    lastTrendSampleMs = 0;
}

void loadBarometerConfig() {
    runtimeCfg = defaultBarometerConfig();
    Preferences p;
    if (!p.begin(BAROMETER_NVS_NS, true)) {
        Serial.println(F("[BARO] NVS barocfg non disponibile: uso default firmware"));
        return;
    }
    runtimeCfg.altitudeM = p.getFloat("alt_m", runtimeCfg.altitudeM);
    runtimeCfg.displayUnit = static_cast<PressureDisplayUnit>(
        p.getUChar("unit", static_cast<uint8_t>(runtimeCfg.displayUnit)));
    p.end();
    normalizeBarometerConfig(runtimeCfg);
}

'''
    cpp = cpp.replace(anchor, anchor + block, 1)

    init_anchor = "void initBarometer() {\n#if BAROMETER_ENABLE\n"
    if init_anchor not in cpp:
        raise RuntimeError("Barometer runtime: init anchor missing")
    cpp = cpp.replace(init_anchor, "void initBarometer() {\n    loadBarometerConfig();\n#if BAROMETER_ENABLE\n", 1)
    cpp = cpp.replace("Serial.print(BAROMETER_ALTITUDE_M, 1);", "Serial.print(runtimeCfg.altitudeM, 1)")
    cpp = cpp.replace("seaLevelFromAltitude(absoluteHpa, BAROMETER_ALTITUDE_M)", "seaLevelFromAltitude(absoluteHpa, runtimeCfg.altitudeM)")

    forecast = r'''const char *barometerForecastName(const StationState &state) {
    switch (barometerForecastCode(state)) {
        case BarometerForecastCode::PartlyCloudy: return "Parzialmente nuvoloso";
        case BarometerForecastCode::Rainy: return "Pioggia";
        case BarometerForecastCode::Cloudy: return "Nuvoloso";
        case BarometerForecastCode::Sunny: return "Sereno";
        case BarometerForecastCode::ClearNight: return "Sereno notte";
        case BarometerForecastCode::Snowy: return "Neve";
        case BarometerForecastCode::PartlyCloudyNight: return "Poco nuvoloso notte";
        default: return "N/D";
    }
}

'''
    cpp = replace_function(cpp, "const char *barometerForecastName(const StationState &state) {", forecast)

    public_anchor = 'uint8_t barometerAddress() { return address; }\n\n'
    if public_anchor not in cpp:
        raise RuntimeError("Barometer runtime: public API anchor missing")
    public = r'''BarometerRuntimeConfig getBarometerConfig() {
    return runtimeCfg;
}

bool validateBarometerConfig(const BarometerRuntimeConfig &cfg) {
    const uint8_t unit = static_cast<uint8_t>(cfg.displayUnit);
    return isfinite(cfg.altitudeM) && cfg.altitudeM >= 0.0f && cfg.altitudeM <= 9000.0f &&
           unit <= static_cast<uint8_t>(PressureDisplayUnit::Kpa);
}

bool saveBarometerConfig(const BarometerRuntimeConfig &input, bool &changed) {
    BarometerRuntimeConfig cfg = input;
    normalizeBarometerConfig(cfg);
    if (!validateBarometerConfig(cfg)) {
        changed = false;
        return false;
    }

    changed = !sameBarometerConfig(cfg, runtimeCfg);
    if (!changed) return true;

    Preferences p;
    if (!p.begin(BAROMETER_NVS_NS, false)) return false;
    p.putFloat("alt_m", cfg.altitudeM);
    p.putUChar("unit", static_cast<uint8_t>(cfg.displayUnit));
    p.end();

    Preferences verify;
    if (!verify.begin(BAROMETER_NVS_NS, true)) return false;
    const float storedAltitude = verify.getFloat("alt_m", NAN);
    const uint8_t storedUnit = verify.getUChar("unit", 0xFFU);
    verify.end();
    if (!isfinite(storedAltitude) || fabsf(storedAltitude - cfg.altitudeM) >= 0.05f ||
        storedUnit != static_cast<uint8_t>(cfg.displayUnit)) return false;

    const bool altitudeChanged = fabsf(runtimeCfg.altitudeM - cfg.altitudeM) >= 0.05f;
    runtimeCfg = cfg;
    if (altitudeChanged) resetPressureHistory();
    return true;
}

bool resetBarometerConfigToDefaults(bool &changed) {
    return saveBarometerConfig(defaultBarometerConfig(), changed);
}

float barometerAltitudeM() {
    return runtimeCfg.altitudeM;
}

const char *pressureUnitName(PressureDisplayUnit unit) {
    switch (unit) {
        case PressureDisplayUnit::Mbar: return "mbar";
        case PressureDisplayUnit::InHg: return "inHg";
        case PressureDisplayUnit::MmHg: return "mmHg";
        case PressureDisplayUnit::Kpa: return "kPa";
        default: return "hPa";
    }
}

float pressureDisplayValue(float pressureHpa, PressureDisplayUnit unit) {
    if (!isfinite(pressureHpa)) return NAN;
    switch (unit) {
        case PressureDisplayUnit::Mbar: return pressureHpa;
        case PressureDisplayUnit::InHg: return pressureHpa * 0.0295299830714f;
        case PressureDisplayUnit::MmHg: return pressureHpa * 0.750061683f;
        case PressureDisplayUnit::Kpa: return pressureHpa / 10.0f;
        default: return pressureHpa;
    }
}

BarometerForecastCode barometerForecastCode(const StationState &state) {
    if (!state.pressureValid || !isfinite(state.pressureSeaLevelHpa))
        return BarometerForecastCode::Unknown;

    const float pressure = state.pressureSeaLevelHpa;
    const bool trendValid = state.pressureTrendValid && isfinite(state.pressureTrendHpa3h);
    const float trend = trendValid ? state.pressureTrendHpa3h : 0.0f;

    // La WMR200 espone il codice forecast gia calcolato dalla console ma il
    // protocollo non contiene la formula proprietaria. Qui replichiamo le
    // stesse categorie grafiche usando pressione al livello del mare + trend 3 h.
    float outsideTemp = NAN;
    const uint32_t now = millis();
    if (state.thermoValid && sensorFresh(state.thermoUpdatedMs, now))
        outsideTemp = state.temperatureC;
    else if (state.lacrosse.temperatureValid && sensorFresh(state.lacrosse.temperatureUpdatedMs, now))
        outsideTemp = state.lacrosse.temperatureC;

    if (isfinite(outsideTemp) && outsideTemp <= 1.5f && pressure <= 1015.0f &&
        trendValid && trend <= -0.7f)
        return BarometerForecastCode::Snowy;

    if (trendValid) {
        if (trend <= -2.5f) return BarometerForecastCode::Rainy;
        if (trend <= -0.8f)
            return pressure <= 1008.0f ? BarometerForecastCode::Rainy : BarometerForecastCode::Cloudy;
        if (trend >= 2.5f) return BarometerForecastCode::Sunny;
        if (trend >= 0.8f)
            return pressure >= 1015.0f ? BarometerForecastCode::Sunny : BarometerForecastCode::PartlyCloudy;
    }

    if (pressure >= 1022.0f) return BarometerForecastCode::Sunny;
    if (pressure <= 1000.0f) return BarometerForecastCode::Rainy;
    if (pressure <= 1010.0f) return BarometerForecastCode::Cloudy;
    return BarometerForecastCode::PartlyCloudy;
}

'''
    cpp = cpp.replace(public_anchor, public_anchor + public, 1)
    write("src/barometer_manager.cpp", cpp)


# ---------------------------------------------------------------------------
# Web API. This script runs after Web auth, so newly inserted routes include
# the same authentication guard as the rest of the configuration endpoints.
# ---------------------------------------------------------------------------
web = read("src/web_manager.cpp")
web = web.replace(
    'String(BAROMETER_ALTITUDE_M, static_cast<unsigned int>(1))',
    'String(barometerAltitudeM(), static_cast<unsigned int>(1))',
)

forecast_line = '    out += ",\\\"forecast\\\":\\\"" + String(barometerForecastName(*station)) + "\\\"";'
if '\\"forecast_code\\"' not in web:
    if forecast_line not in web:
        raise RuntimeError("Barometer runtime: forecast JSON anchor missing")
    web = web.replace(
        forecast_line,
        forecast_line + '\n    out += ",\\\"forecast_code\\\":" + String(static_cast<uint8_t>(barometerForecastCode(*station)));',
    )

bme_anchor = (
    '    out += ",\\\"altitude_m\\\":" + String(barometerAltitudeM(), static_cast<unsigned int>(1));\n'
    '    out += ",\\\"age_s\\\":" + String(ageSeconds(station->pressureUpdatedMs, now));'
)
if '\\"display_unit\\"' not in web:
    if bme_anchor not in web:
        raise RuntimeError("Barometer runtime: BME JSON anchor missing")
    extra = (
        '    out += ",\\\"display_unit\\\":\\\"" + String(pressureUnitName(getBarometerConfig().displayUnit)) + "\\\"";\n'
        '    out += ",\\\"display_unit_id\\\":" + String(static_cast<uint8_t>(getBarometerConfig().displayUnit));\n'
        '    out += ",\\\"pressure_station_display\\\":" + jsonFloat(pressureDisplayValue(station->pressureAbsoluteHpa, getBarometerConfig().displayUnit), 3);\n'
        '    out += ",\\\"altimeter_display\\\":" + jsonFloat(pressureDisplayValue(station->pressureSeaLevelHpa, getBarometerConfig().displayUnit), 3);\n'
        '    out += ",\\\"trend_display\\\":" + jsonFloat(pressureDisplayValue(station->pressureTrendHpa3h, getBarometerConfig().displayUnit), 3);\n'
    )
    web = web.replace(
        bme_anchor,
        '    out += ",\\\"altitude_m\\\":" + String(barometerAltitudeM(), static_cast<unsigned int>(1));\n'
        + extra
        + '    out += ",\\\"age_s\\\":" + String(ageSeconds(station->pressureUpdatedMs, now));',
        1,
    )

if "void handleBarometerConfigGet()" not in web:
    handlers = r'''
void handleBarometerConfigGet() {
    const BarometerRuntimeConfig c = getBarometerConfig();
    String out;
    out.reserve(260);
    out = "{\"altitude_m\":" + String(c.altitudeM, 1);
    out += ",\"pressure_unit\":" + String(static_cast<uint8_t>(c.displayUnit));
    out += ",\"pressure_unit_name\":\"" + String(pressureUnitName(c.displayUnit)) + "\"";
    out += ",\"detected\":"; out += barometerDetected() ? "true" : "false";
    out += ",\"address\":" + String(barometerAddress());
    out += "}";
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", out);
}

void handleBarometerConfigPost() {
    BarometerRuntimeConfig c = getBarometerConfig();
    if (server.hasArg("altitude_m")) c.altitudeM = server.arg("altitude_m").toFloat();
    if (server.hasArg("pressure_unit")) {
        const long unit = server.arg("pressure_unit").toInt();
        if (unit < 0 || unit > static_cast<long>(PressureDisplayUnit::Kpa)) {
            server.send(400, "application/json", "{\"ok\":false,\"error\":\"pressure unit must be 0..4\"}");
            return;
        }
        c.displayUnit = static_cast<PressureDisplayUnit>(unit);
    }
    if (!validateBarometerConfig(c)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"altitude must be 0..9000 m\"}");
        return;
    }
    bool changed = false;
    if (!saveBarometerConfig(c, changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"barometer NVS verification failed\"}");
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":";
    out += changed ? "true" : "false";
    out += ",\"altitude_m\":" + String(barometerAltitudeM(), 1);
    out += ",\"pressure_unit\":" + String(static_cast<uint8_t>(getBarometerConfig().displayUnit));
    out += "}";
    server.send(200, "application/json; charset=utf-8", out);
}

void handleBarometerConfigReset() {
    bool changed = false;
    if (!resetBarometerConfigToDefaults(changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"barometer reset failed\"}");
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":";
    out += changed ? "true" : "false";
    out += "}";
    server.send(200, "application/json; charset=utf-8", out);
}

'''
    anchor = "void handleLightningState() {"
    if anchor not in web:
        raise RuntimeError("Barometer runtime: lightning handler anchor missing")
    web = web.replace(anchor, handlers + anchor, 1)

if 'server.on("/api/barometer/config"' not in web:
    pos = web.find('    server.on("/api/as3935/state"')
    if pos < 0:
        raise RuntimeError("Barometer runtime: route anchor missing")
    routes = (
        '    server.on("/api/barometer/config", HTTP_GET, [](){ if (!requireWebAuth()) return; handleBarometerConfigGet(); });\n'
        '    server.on("/api/barometer/config", HTTP_POST, [](){ if (!requireWebAuth()) return; handleBarometerConfigPost(); });\n'
        '    server.on("/api/barometer/reset", HTTP_POST, [](){ if (!requireWebAuth()) return; handleBarometerConfigReset(); });\n'
    )
    web = web[:pos] + routes + web[pos:]

write("src/web_manager.cpp", web)
print("Applied runtime BME280 altitude, pressure units and WMR-style forecast")
