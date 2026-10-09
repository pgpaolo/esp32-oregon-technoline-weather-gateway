#pragma once
#include "station_state.h"

void initBarometer();
void serviceBarometer(StationState &state);
void prepareBarometerForDeepSleep();
bool barometerDetected();
const char *barometerName();
uint8_t barometerAddress();
const char *barometerTrendName(const StationState &state);
const char *barometerForecastName(const StationState &state);

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
