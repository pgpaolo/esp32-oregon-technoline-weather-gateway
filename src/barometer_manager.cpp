#include "barometer_manager.h"
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_BME280.h>
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
#if BAROMETER_ENABLE
    if (tryBme(0x76) || tryBme(0x77)) {
        Serial.print(F("[BARO] BME280 rilevato @0x"));
        Serial.print(address, HEX);
        Serial.print(F(" quota="));
        Serial.print(BAROMETER_ALTITUDE_M, 1);
        Serial.println(F(" m"));
    } else {
        Serial.println(F("[BARO] BME280 non rilevato su 0x76/0x77"));
    }
#else
    Serial.println(F("[BARO] supporto BME280 disabilitato"));
#endif
}

void serviceBarometer(StationState &state) {
#if BAROMETER_ENABLE
    if (!detected) return;
    const uint32_t now = millis();
    if (static_cast<uint32_t>(now - lastReadMs) < BAROMETER_READ_MS) return;
    lastReadMs = now;

    const float pressurePa = bme.readPressure();
    const float tempC = bme.readTemperature();
    const float humidity = bme.readHumidity();
    if (!isfinite(pressurePa) || pressurePa < 30000.0f || pressurePa > 120000.0f) return;

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

const char *barometerTrendName(const StationState &state) {
    if (!state.pressureTrendValid) return "in acquisizione";
    if (state.pressureTrendHpa3h >= 2.0f) return "in aumento";
    if (state.pressureTrendHpa3h <= -2.0f) return "in calo";
    return "stabile";
}

const char *barometerForecastName(const StationState &state) {
    if (!state.pressureValid) return "N/D";
    if (state.pressureTrendValid) {
        if (state.pressureTrendHpa3h >= 2.5f) return "Miglioramento";
        if (state.pressureTrendHpa3h <= -2.5f) return "Peggioramento";
    }
    if (state.pressureSeaLevelHpa >= 1022.0f) return "Stabile / sereno";
    if (state.pressureSeaLevelHpa <= 1000.0f) return "Instabile / pioggia";
    return "Variabile";
}
