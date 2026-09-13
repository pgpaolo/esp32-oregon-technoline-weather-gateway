#pragma once

#include <Arduino.h>
#include <stdint.h>

enum class BootCheckpoint : uint8_t {
    Start = 0,
    DisplayInit,
    BarometerInit,
    LightningInit,
    NetworkInit,
    MqttInit,
    MbInit,
    WebInit,
    RemoteInit,
    LacrosseInit,
    RfInit,
    ThermoInit,
    SdInit,
    Ready,
};

enum class BootNetworkState : uint8_t {
    Unknown = 0,
    StaPending,
    StaConnected,
    RecoveryAp,
    Lost,
};

// RTC-only diagnostics: no NVS/flash write is performed during boot.
void bootDiagnosticsBegin();
void bootDiagnosticsCheckpoint(BootCheckpoint checkpoint);
void bootDiagnosticsNetwork(BootNetworkState state);
void bootDiagnosticsPrintSummary();

BootCheckpoint bootDiagnosticsCurrentCheckpoint();
BootCheckpoint bootDiagnosticsPreviousCheckpoint();
BootNetworkState bootDiagnosticsCurrentNetworkState();
BootNetworkState bootDiagnosticsPreviousNetworkState();
bool bootDiagnosticsPreviousComplete();
uint32_t bootDiagnosticsRtcBootCount();
const char *bootDiagnosticsResetReasonName();
const char *bootCheckpointName(BootCheckpoint checkpoint);
const char *bootNetworkStateName(BootNetworkState state);
