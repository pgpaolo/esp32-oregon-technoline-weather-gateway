#pragma once
#include <Arduino.h>
#include "oregon_types.h"
#include "station_state.h"

struct ThermoChannelConfig {
    uint8_t enabledMask{0x01};       // bit0=CH1, bit1=CH2, bit2=CH3
    uint8_t primaryChannel{1};       // feeds legacy weather fields/topics
    bool autoDiscover{true};         // detected channels join Web/MQTT automatically
};

struct ThermoChannelState {
    bool detected{false};
    bool valid{false};
    float temperatureC{NAN};
    float humidityPct{NAN};
    uint32_t updatedMs{0};
    uint32_t packetCount{0};
    float lastRssi{NAN};
    OregonSensorStatus sensor{};
};

void initThermoChannels();
void noteThermoChannelReading(const WeatherReading &reading);
ThermoChannelConfig getThermoChannelConfig();
ThermoChannelState getThermoChannelState(uint8_t channel);
uint8_t thermoDetectedMask();
uint8_t thermoEffectiveMask();
bool thermoChannelVisible(uint8_t channel);
bool thermoChannelIsPrimary(uint8_t channel);
bool saveThermoChannelConfig(const ThermoChannelConfig &cfg);
bool resetThermoChannelConfig();
void syncPrimaryThermoState(StationState &station);
