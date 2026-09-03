#pragma once
#include <Arduino.h>
#include "station_state.h"

enum class MbCompatibleTlsMode : uint8_t {
    CaVerified = 0,
    Insecure = 1
};

struct MbCompatibleConfig {
    bool enabled{false};
    String url;
    uint16_t intervalSec{60};
    uint16_t timeoutMs{2500};
    MbCompatibleTlsMode tlsMode{MbCompatibleTlsMode::CaVerified};
    String caCertificate;
    uint8_t sourcePriority{0}; // exclusive source: 0 Oregon, 1 Technoline/La Crosse
};

void initMbCompatiblePublisher(StationState &state);
void serviceMbCompatiblePublisher();
void prepareMbCompatibleForDeepSleep();

MbCompatibleConfig getMbCompatibleConfig();
bool validateMbCompatibleConfig(const MbCompatibleConfig &cfg, bool replaceCaCertificate);
bool saveMbCompatibleConfig(const MbCompatibleConfig &cfg, bool replaceCaCertificate);
bool resetMbCompatibleConfig();
void requestMbCompatibleTest();
String mbCompatibleConfigStatusJson();
const char *mbCompatibleTlsModeName(MbCompatibleTlsMode mode);
