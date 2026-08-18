#include "station_state.h"
#include <Arduino.h>
#include <math.h>
#include "config.h"

namespace {

// 2048 campioni coprono oltre 24 ore con un PCR800 che trasmette circa ogni 45-50 s.
constexpr uint16_t RAIN_HISTORY_SIZE = 2048;
struct RainHistorySample {
    uint32_t ms{0};
    float totalMm{0.0f};
};
RainHistorySample rainHistory[RAIN_HISTORY_SIZE];
uint16_t rainHistoryHead = 0;
uint16_t rainHistoryCount = 0;

void clearRainHistory() {
    rainHistoryHead = 0;
    rainHistoryCount = 0;
}

void addRainHistory(uint32_t nowMs, float totalMm) {
    rainHistory[rainHistoryHead].ms = nowMs;
    rainHistory[rainHistoryHead].totalMm = totalMm;
    rainHistoryHead = static_cast<uint16_t>((rainHistoryHead + 1U) % RAIN_HISTORY_SIZE);
    if (rainHistoryCount < RAIN_HISTORY_SIZE) rainHistoryCount++;
}

bool rainBaseline(uint32_t nowMs, uint32_t targetAgeMs, float &baselineMm) {
    if (rainHistoryCount < 2) return false;

    // Si parte dal campione immediatamente precedente all'ultimo e si torna indietro.
    for (uint16_t n = 1; n < rainHistoryCount; ++n) {
        const int idx = (static_cast<int>(rainHistoryHead) - 1 - n + RAIN_HISTORY_SIZE) % RAIN_HISTORY_SIZE;
        const RainHistorySample &s = rainHistory[idx];
        if (static_cast<uint32_t>(nowMs - s.ms) >= targetAgeMs) {
            baselineMm = s.totalMm;
            return true;
        }
    }
    return false;
}

void updateRainDerived(StationState &state, float newTotalMm, uint32_t nowMs) {
    // Incremento fra due telegrammi consecutivi. Se il sensore viene resettato e il
    // totale torna indietro, ripartiamo con una nuova storia senza produrre pioggia falsa.
    if (state.rainValid && isfinite(state.rainTotalMm)) {
        const float delta = newTotalMm - state.rainTotalMm;
        if (delta >= -0.001f && delta < 500.0f) {
            state.rainIncrementMm = delta > 0.0f ? delta : 0.0f;
            state.rainIncrementValid = true;
        } else {
            clearRainHistory();
            state.rainIncrementMm = 0.0f;
            state.rainIncrementValid = true;
            state.rainLastHourValid = false;
            state.rainLast24hValid = false;
        }
    } else {
        state.rainIncrementMm = 0.0f;
        state.rainIncrementValid = true;
    }

    addRainHistory(nowMs, newTotalMm);

    float baseline = 0.0f;
    if (rainBaseline(nowMs, 60UL * 60UL * 1000UL, baseline)) {
        state.rainLastHourMm = max(0.0f, newTotalMm - baseline);
        state.rainLastHourValid = true;
    }
    if (rainBaseline(nowMs, 24UL * 60UL * 60UL * 1000UL, baseline)) {
        state.rainLast24hMm = max(0.0f, newTotalMm - baseline);
        state.rainLast24hValid = true;
    }
}

float calculateDewPoint(float tempC, float humidity) {
    if (!isfinite(tempC) || !isfinite(humidity) || humidity <= 0.0f || humidity > 100.0f) return NAN;
    // Magnus, adatto all'intervallo meteorologico del sensore.
    constexpr float a = 17.62f;
    constexpr float b = 243.12f;
    const float gamma = logf(humidity / 100.0f) + (a * tempC) / (b + tempC);
    return (b * gamma) / (a - gamma);
}

float calculateHeatIndex(float tempC, float humidity) {
    // Rothfusz in Fahrenheit: sotto la zona di applicabilita' non mostriamo un
    // numero artificiale, ma N/A.
    if (tempC < 26.7f || humidity < 40.0f) return NAN;
    const float t = tempC * 9.0f / 5.0f + 32.0f;
    const float r = humidity;
    const float hi = -42.379f + 2.04901523f * t + 10.14333127f * r
        - 0.22475541f * t * r - 0.00683783f * t * t
        - 0.05481717f * r * r + 0.00122874f * t * t * r
        + 0.00085282f * t * r * r - 0.00000199f * t * t * r * r;
    return (hi - 32.0f) * 5.0f / 9.0f;
}

float calculateWindChill(float tempC, float windKmh) {
    if (tempC > 10.0f || windKmh < 4.8f) return NAN;
    const float p = powf(windKmh, 0.16f);
    return 13.12f + 0.6215f * tempC - 11.37f * p + 0.3965f * tempC * p;
}

void updateSensorStatus(OregonSensorStatus &dst, const WeatherReading &reading) {
    dst.code = reading.sensorCode;
    dst.channel = reading.channel;
    dst.channelRaw = reading.channelRaw;
    dst.rollingCode = reading.rollingCode;
    dst.flags = reading.flags;
    dst.batteryKnown = reading.batteryStatusValid;
    dst.batteryLow = reading.batteryLow;
    dst.updatedMs = reading.receivedAtMs;
}

} // namespace

void refreshDerivedWeather(StationState &state) {
    state.dewPointC = calculateDewPoint(state.temperatureC, state.humidityPct);
    state.dewPointValid = state.thermoValid && isfinite(state.dewPointC);

    state.heatIndexC = calculateHeatIndex(state.temperatureC, state.humidityPct);
    state.heatIndexValid = state.thermoValid && isfinite(state.heatIndexC);

    state.windChillC = calculateWindChill(state.temperatureC, state.windAverageKmh);
    state.windChillValid = state.thermoValid && state.windValid && isfinite(state.windChillC);
}

void applyWeatherReading(StationState &state, const WeatherReading &reading) {
    state.validPacketCount++;
    state.lastPacketMs = reading.receivedAtMs;
    state.lastSensorId = reading.sensorId;
    state.lastSensorType = reading.type;
    state.lastRssi = reading.rssi;

    switch (reading.type) {
        case SensorType::ThermoHygro:
            state.thermoPacketCount++;
            updateSensorStatus(state.thermoSensor, reading);
            break;
        case SensorType::Wind:
            state.windPacketCount++;
            updateSensorStatus(state.windSensor, reading);
            break;
        case SensorType::Rain:
            state.rainPacketCount++;
            updateSensorStatus(state.rainSensor, reading);
            break;
        case SensorType::UV:
            state.uvPacketCount++;
            updateSensorStatus(state.uvSensor, reading);
            break;
        default: break;
    }

    if (reading.temperatureValid || reading.humidityValid) {
        if (reading.temperatureValid) state.temperatureC = reading.temperatureC;
        if (reading.humidityValid) state.humidityPct = reading.humidityPct;
        state.thermoUpdatedMs = reading.receivedAtMs;
        state.thermoValid = true;
    }

    if (reading.windAverageValid || reading.windGustValid || reading.windDirectionValid) {
        if (reading.windAverageValid) state.windAverageKmh = reading.windAverageKmh;
        if (reading.windGustValid) state.windGustKmh = reading.windGustKmh;
        if (reading.windDirectionValid) {
            state.windDirectionIndex = reading.windDirectionIndex;
            state.windDirectionDeg = reading.windDirectionDeg;
        }
        state.windUpdatedMs = reading.receivedAtMs;
        state.windValid = true;
    }

    if (reading.rainTotalValid || reading.rainRateValid) {
        if (reading.rainTotalValid) {
            updateRainDerived(state, reading.rainTotalMm, reading.receivedAtMs);
            state.rainTotalMm = reading.rainTotalMm;
        }
        if (reading.rainRateValid) state.rainRateMmH = reading.rainRateMmH;
        state.rainUpdatedMs = reading.receivedAtMs;
        state.rainValid = true;
    }

    if (reading.uvValid) {
        state.uvIndex = reading.uvIndex;
        state.uvUpdatedMs = reading.receivedAtMs;
        state.uvValid = true;
    }

    refreshDerivedWeather(state);
}

bool sensorFresh(uint32_t updatedAtMs, uint32_t nowMs) {
    return updatedAtMs != 0 && static_cast<uint32_t>(nowMs - updatedAtMs) <= SENSOR_STALE_MS;
}

const char *sensorBatteryName(const OregonSensorStatus &sensor) {
    if (!sensor.batteryKnown) return "N/D";
    return sensor.batteryLow ? "LOW" : "OK";
}

void applyLaCrosseReading(StationState &state, const LaCrosseReading &reading) {
    LaCrosseStationState &lc = state.lacrosse;
    lc.validPacketCount++;
    lc.lastPacketMs = reading.receivedAtMs;
    lc.lastRssi = reading.rssi;
    lc.wsId = reading.wsId;
    lc.sensorId = reading.sensorId;
    lc.lastDataFlags = reading.dataFlags;
    lc.lastUpdateFlags = reading.updateFlags;
    lc.nextUpdateCode = reading.nextUpdateCode;

    switch (reading.type) {
        case LaCrosseType::Temperature:
            lc.temperaturePacketCount++;
            if (reading.temperatureValid) {
                lc.temperatureC = reading.temperatureC;
                lc.temperatureValid = true;
                lc.temperatureUpdatedMs = reading.receivedAtMs;
            }
            break;
        case LaCrosseType::Humidity:
            lc.humidityPacketCount++;
            if (reading.humidityValid) {
                lc.humidityPct = reading.humidityPct;
                lc.humidityValid = true;
                lc.humidityUpdatedMs = reading.receivedAtMs;
            }
            break;
        case LaCrosseType::Rain:
            lc.rainPacketCount++;
            if (reading.rainValid) {
                if (lc.rainValid && isfinite(lc.rainTotalMm)) {
                    const float delta = reading.rainTotalMm - lc.rainTotalMm;
                    lc.rainIncrementMm = (delta >= 0.0f && delta < 500.0f) ? delta : 0.0f;
                    lc.rainIncrementValid = delta >= 0.0f && delta < 500.0f;
                } else {
                    lc.rainIncrementMm = 0.0f;
                    lc.rainIncrementValid = true;
                }
                lc.rainTotalMm = reading.rainTotalMm;
                lc.rainValid = true;
                lc.rainUpdatedMs = reading.receivedAtMs;
            }
            break;
        case LaCrosseType::Wind:
            lc.windPacketCount++;
            if (reading.windValid) {
                lc.windKmh = reading.windKmh;
                lc.windValid = true;
                lc.windUpdatedMs = reading.receivedAtMs;
            }
            if (reading.directionValid) {
                lc.windDirectionIndex = reading.directionIndex;
                lc.windDirectionDeg = reading.directionDeg;
                lc.directionValid = true;
            }
            break;
        case LaCrosseType::Gust:
            lc.gustPacketCount++;
            if (reading.gustValid) {
                lc.gustKmh = reading.gustKmh;
                lc.gustValid = true;
                lc.gustUpdatedMs = reading.receivedAtMs;
            }
            if (reading.directionValid) {
                lc.windDirectionIndex = reading.directionIndex;
                lc.windDirectionDeg = reading.directionDeg;
                lc.directionValid = true;
            }
            break;
        default:
            lc.rejectedPacketCount++;
            break;
    }
}
