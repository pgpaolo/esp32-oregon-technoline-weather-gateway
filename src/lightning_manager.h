#pragma once

#include <Arduino.h>
#include <PubSubClient.h>

struct LightningConfig {
    bool enabled{true};
    bool indoor{true};
    uint8_t i2cAddress{0x03};
    int8_t irqPin{34};
    uint8_t noiseFloor{2};
    uint8_t watchdogThreshold{2};
    uint8_t spikeRejection{2};
    uint8_t minStrikes{1};
    bool maskDisturbers{false};
    uint8_t tuningCap{6};
    bool autoTune{false};
};

struct LightningState {
    bool enabled{false};
    bool detected{false};
    bool irqOk{false};
    bool calibrationOk{false};
    int32_t resonanceHz{0};
    uint32_t irqTotal{0};
    uint32_t noiseTotal{0};
    uint32_t disturberTotal{0};
    uint32_t lightningTotal{0};
    uint32_t lastEventMs{0};
    uint32_t lastLightningMs{0};
    uint8_t lastInterruptSource{0};
    uint8_t lastDistanceKm{0};
    bool distanceOutOfRange{false};
    uint32_t lastEnergy{0};
};

void initLightning();
void serviceLightning(PubSubClient &mqttClient);
void prepareLightningForDeepSleep();

LightningConfig getLightningConfig();
LightningState getLightningState();

bool validateLightningConfig(const LightningConfig &cfg);
bool saveLightningConfig(const LightningConfig &cfg, bool &changed);
bool resetLightningConfigToDefaults(bool &changed);
bool reinitializeLightning();

String lightningConfigJson();
String lightningStateJson();
const char *lightningInterruptName(uint8_t source);
