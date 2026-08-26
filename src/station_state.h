#pragma once
#include "oregon_types.h"
#include "lacrosse_ws23xx.h"

struct OregonSensorStatus {
    uint16_t code{0};
    uint8_t channel{0};
    uint8_t channelRaw{0};
    uint8_t rollingCode{0};
    uint8_t flags{0};
    bool batteryKnown{false};
    bool batteryLow{false};
    uint32_t updatedMs{0};
};


struct LaCrosseStationState {
    uint8_t wsId{0};
    uint8_t sensorId{0};
    uint8_t lastDataFlags{0};
    uint8_t lastUpdateFlags{0};
    uint8_t nextUpdateCode{0};

    float temperatureC{NAN};
    float humidityPct{NAN};
    uint32_t temperatureUpdatedMs{0};
    uint32_t humidityUpdatedMs{0};
    bool temperatureValid{false};
    bool humidityValid{false};

    float rainTotalMm{NAN};
    float rainIncrementMm{NAN};
    uint32_t rainUpdatedMs{0};
    bool rainValid{false};
    bool rainIncrementValid{false};

    float windKmh{NAN};
    float gustKmh{NAN};
    float windDirectionDeg{NAN};
    uint8_t windDirectionIndex{0};
    uint32_t windUpdatedMs{0};
    uint32_t gustUpdatedMs{0};
    bool windValid{false};
    bool gustValid{false};
    bool directionValid{false};

    uint32_t validPacketCount{0};
    uint32_t rejectedPacketCount{0};
    uint32_t temperaturePacketCount{0};
    uint32_t humidityPacketCount{0};
    uint32_t rainPacketCount{0};
    uint32_t windPacketCount{0};
    uint32_t gustPacketCount{0};
    uint32_t lastPacketMs{0};
    float lastRssi{NAN};

};

struct StationState {
    // Sensore termo/igrometrico Oregon esterno.
    float temperatureC{NAN};
    float humidityPct{NAN};
    uint32_t thermoUpdatedMs{0};
    bool thermoValid{false};
    OregonSensorStatus thermoSensor{};

    // Valori derivati localmente dai sensori hardware.
    float heatIndexC{NAN};
    bool heatIndexValid{false};
    float dewPointC{NAN};
    bool dewPointValid{false};
    float windChillC{NAN};
    bool windChillValid{false};

    // WGR800.
    float windAverageKmh{NAN};
    float windGustKmh{NAN};
    uint8_t windDirectionIndex{0};
    float windDirectionDeg{NAN};
    uint32_t windUpdatedMs{0};
    bool windValid{false};
    OregonSensorStatus windSensor{};

    // PCR800 e accumuli derivati localmente dal contatore hardware.
    float rainTotalMm{NAN};
    float rainRateMmH{NAN};
    float rainIncrementMm{NAN};
    float rainLastHourMm{NAN};
    float rainLast24hMm{NAN};
    uint32_t rainUpdatedMs{0};
    bool rainValid{false};
    bool rainIncrementValid{false};
    bool rainLastHourValid{false};
    bool rainLast24hValid{false};
    OregonSensorStatus rainSensor{};

    // UVN800.
    int uvIndex{-1};
    uint32_t uvUpdatedMs{0};
    bool uvValid{false};
    OregonSensorStatus uvSensor{};

    // BME280 locale: pressione della stazione e altimetro derivato dalla quota.
    float pressureAbsoluteHpa{NAN};
    float pressureSeaLevelHpa{NAN};
    float pressureTrendHpa3h{NAN};
    uint16_t pressureTrendWindowMin{0};
    float indoorTemperatureC{NAN};
    float indoorHumidityPct{NAN};
    uint32_t pressureUpdatedMs{0};
    bool pressureValid{false};
    bool pressureTrendValid{false};
    bool indoorTemperatureValid{false};
    bool indoorHumidityValid{false};

    // Conteggi e diagnostica applicativa.
    uint32_t validPacketCount{0};
    uint32_t rejectedPacketCount{0};
    uint32_t thermoPacketCount{0};
    uint32_t windPacketCount{0};
    uint32_t rainPacketCount{0};
    uint32_t uvPacketCount{0};

    uint32_t lastPacketMs{0};
    uint8_t lastSensorId{0};
    SensorType lastSensorType{SensorType::Unknown};
    float lastRssi{NAN};

    // Stazione La Crosse WS-2305 / WS-23xx, separata dai valori Oregon.
    LaCrosseStationState lacrosse{};
};

void applyWeatherReading(StationState &state, const WeatherReading &reading, bool applyThermoToPrimary = true);
void applyLaCrosseReading(StationState &state, const LaCrosseReading &reading);
void refreshDerivedWeather(StationState &state);
bool sensorFresh(uint32_t updatedAtMs, uint32_t nowMs);
const char *sensorBatteryName(const OregonSensorStatus &sensor);
