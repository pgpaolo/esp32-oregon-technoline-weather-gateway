#include "barometer_manager.h"
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_BME280.h>
#include <Preferences.h>
#include <math.h>
#include "config.h"

namespace {
bool detected = false;
uint8_t address = 0;
Adafruit_BME280 bme;
uint32_t lastReadMs = 0;

constexpr uint8_t PRESSURE_HISTORY_SIZE = 20;
struct PressureSample {
    uint32_t ms{0};
    float seaLevelHpa{NAN};
};
PressureSample pressureHistory[PRESSURE_HISTORY_SIZE];
uint8_t pressureHead = 0;
uint8_t pressureCount = 0;
uint32_t lastTrendSampleMs = 0;

// BAROMETER_RUNTIME_V1
constexpr const char *BAROMETER_NVS_NS = "barocfg";
BarometerRuntimeConfig runtimeCfg{};


// BME280_DETECTION_RETRY_V1
bool tryBme(uint8_t addr);
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
    // I2C_SHARED_BUS_COMPAT_V2: prefer 0x77, retain 0x76 fallback.
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

float seaLevelFromAltitude(float pressureHpa, float altitudeM) {
    if (altitudeM <= 0.0f) return pressureHpa;
    const float ratio = 1.0f - (altitudeM / 44330.0f);
    if (ratio <= 0.0f) return pressureHpa;
    return pressureHpa / powf(ratio, 5.255f);
}

bool tryBme(uint8_t addr) {
    if (!bme.begin(addr, &Wire)) return false;
    detected = true;
    address = addr;
    bme.setSampling(Adafruit_BME280::MODE_NORMAL,
                    Adafruit_BME280::SAMPLING_X2,
                    Adafruit_BME280::SAMPLING_X16,
                    Adafruit_BME280::SAMPLING_X1,
                    Adafruit_BME280::FILTER_X4,
                    Adafruit_BME280::STANDBY_MS_500);
    return true;
}

void addPressureTrendSample(StationState &state, uint32_t now, float seaLevelHpa) {
    if (lastTrendSampleMs != 0 &&
        static_cast<uint32_t>(now - lastTrendSampleMs) < BAROMETER_TREND_SAMPLE_MS) return;
    lastTrendSampleMs = now;

    pressureHistory[pressureHead].ms = now;
    pressureHistory[pressureHead].seaLevelHpa = seaLevelHpa;
    pressureHead = static_cast<uint8_t>((pressureHead + 1U) % PRESSURE_HISTORY_SIZE);
    if (pressureCount < PRESSURE_HISTORY_SIZE) pressureCount++;

    if (pressureCount < 4) {
        state.pressureTrendValid = false;
        return;
    }

    const int newestIdx = (static_cast<int>(pressureHead) - 1 + PRESSURE_HISTORY_SIZE) % PRESSURE_HISTORY_SIZE;
    const int oldestIdx = (static_cast<int>(pressureHead) - pressureCount + PRESSURE_HISTORY_SIZE) % PRESSURE_HISTORY_SIZE;
    const PressureSample &newest = pressureHistory[newestIdx];
    const PressureSample &oldest = pressureHistory[oldestIdx];
    const uint32_t ageMs = static_cast<uint32_t>(newest.ms - oldest.ms);
    if (ageMs < 30UL * 60UL * 1000UL || !isfinite(oldest.seaLevelHpa)) {
        state.pressureTrendValid = false;
        return;
    }

    const float delta = newest.seaLevelHpa - oldest.seaLevelHpa;
    const float hours = static_cast<float>(ageMs) / 3600000.0f;
    state.pressureTrendHpa3h = delta * (3.0f / hours);
    state.pressureTrendWindowMin = static_cast<uint16_t>(ageMs / 60000UL);
    state.pressureTrendValid = true;
}
} // namespace

void initBarometer() {
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

void serviceBarometer(StationState &state) {
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

void prepareBarometerForDeepSleep() {
#if BAROMETER_ENABLE
    if (!detected) return;
    bme.setSampling(Adafruit_BME280::MODE_SLEEP);
    Serial.println(F("[BARO] BME280 -> sleep"));
#endif
}

bool barometerDetected() { return detected; }
const char *barometerName() { return detected ? "BME280" : "none"; }
uint8_t barometerAddress() { return address; }


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

BarometerRuntimeConfig getBarometerConfig() {
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

const char *barometerTrendName(const StationState &state) {
    if (!state.pressureTrendValid) return "in acquisizione";
    if (state.pressureTrendHpa3h >= 2.0f) return "in aumento";
    if (state.pressureTrendHpa3h <= -2.0f) return "in calo";
    return "stabile";
}

const char *barometerForecastName(const StationState &state) {
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

