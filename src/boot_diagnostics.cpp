#include "boot_diagnostics.h"

#include <esp_attr.h>
#include <esp_system.h>

namespace {
constexpr uint32_t RTC_MAGIC = 0x42544431UL; // "BTD1"
constexpr uint8_t RTC_LAYOUT_VERSION = 1U;

struct BootRtcState {
    uint32_t magic;
    uint32_t bootCount;
    uint8_t layoutVersion;
    uint8_t currentCheckpoint;
    uint8_t previousCheckpoint;
    uint8_t currentNetwork;
    uint8_t previousNetwork;
    uint8_t resetReason;
    uint8_t reserved[2];
};

RTC_DATA_ATTR BootRtcState rtcState{};

BootCheckpoint checkedCheckpoint(uint8_t raw) {
    if (raw > static_cast<uint8_t>(BootCheckpoint::Ready)) return BootCheckpoint::Start;
    return static_cast<BootCheckpoint>(raw);
}

BootNetworkState checkedNetwork(uint8_t raw) {
    if (raw > static_cast<uint8_t>(BootNetworkState::Lost)) return BootNetworkState::Unknown;
    return static_cast<BootNetworkState>(raw);
}

const char *resetReasonName(esp_reset_reason_t reason) {
    switch (reason) {
        case ESP_RST_POWERON: return "POWERON";
        case ESP_RST_EXT: return "EXTERNAL";
        case ESP_RST_SW: return "SOFTWARE";
        case ESP_RST_PANIC: return "PANIC";
        case ESP_RST_INT_WDT: return "INT_WDT";
        case ESP_RST_TASK_WDT: return "TASK_WDT";
        case ESP_RST_WDT: return "WDT";
        case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
        case ESP_RST_BROWNOUT: return "BROWNOUT";
        case ESP_RST_SDIO: return "SDIO";
        case ESP_RST_UNKNOWN:
        default: return "UNKNOWN";
    }
}
} // namespace

void bootDiagnosticsBegin() {
    const esp_reset_reason_t reason = esp_reset_reason();
    const bool valid = rtcState.magic == RTC_MAGIC && rtcState.layoutVersion == RTC_LAYOUT_VERSION;

    if (!valid) {
        rtcState = BootRtcState{};
        rtcState.magic = RTC_MAGIC;
        rtcState.layoutVersion = RTC_LAYOUT_VERSION;
        rtcState.bootCount = 1U;
        rtcState.previousCheckpoint = static_cast<uint8_t>(BootCheckpoint::Start);
        rtcState.previousNetwork = static_cast<uint8_t>(BootNetworkState::Unknown);
    } else {
        rtcState.previousCheckpoint = rtcState.currentCheckpoint;
        rtcState.previousNetwork = rtcState.currentNetwork;
        if (rtcState.bootCount != UINT32_MAX) rtcState.bootCount++;
    }

    rtcState.currentCheckpoint = static_cast<uint8_t>(BootCheckpoint::Start);
    rtcState.currentNetwork = static_cast<uint8_t>(BootNetworkState::Unknown);
    rtcState.resetReason = static_cast<uint8_t>(reason);
}

void bootDiagnosticsCheckpoint(BootCheckpoint checkpoint) {
    rtcState.currentCheckpoint = static_cast<uint8_t>(checkpoint);
}

void bootDiagnosticsNetwork(BootNetworkState state) {
    rtcState.currentNetwork = static_cast<uint8_t>(state);
}

BootCheckpoint bootDiagnosticsCurrentCheckpoint() {
    return checkedCheckpoint(rtcState.currentCheckpoint);
}

BootCheckpoint bootDiagnosticsPreviousCheckpoint() {
    return checkedCheckpoint(rtcState.previousCheckpoint);
}

BootNetworkState bootDiagnosticsCurrentNetworkState() {
    return checkedNetwork(rtcState.currentNetwork);
}

BootNetworkState bootDiagnosticsPreviousNetworkState() {
    return checkedNetwork(rtcState.previousNetwork);
}

bool bootDiagnosticsPreviousComplete() {
    return bootDiagnosticsPreviousCheckpoint() == BootCheckpoint::Ready;
}

uint32_t bootDiagnosticsRtcBootCount() {
    return rtcState.bootCount;
}

const char *bootDiagnosticsResetReasonName() {
    return resetReasonName(static_cast<esp_reset_reason_t>(rtcState.resetReason));
}

const char *bootCheckpointName(BootCheckpoint checkpoint) {
    switch (checkpoint) {
        case BootCheckpoint::Start: return "START";
        case BootCheckpoint::DisplayInit: return "DISPLAY_INIT";
        case BootCheckpoint::BarometerInit: return "BAROMETER_INIT";
        case BootCheckpoint::LightningInit: return "LIGHTNING_INIT";
        case BootCheckpoint::NetworkInit: return "NETWORK_INIT";
        case BootCheckpoint::MqttInit: return "MQTT_INIT";
        case BootCheckpoint::MbInit: return "MB_INIT";
        case BootCheckpoint::WebInit: return "WEB_INIT";
        case BootCheckpoint::RemoteInit: return "REMOTE_INIT";
        case BootCheckpoint::LacrosseInit: return "LACROSSE_INIT";
        case BootCheckpoint::RfInit: return "RF_INIT";
        case BootCheckpoint::ThermoInit: return "THERMO_INIT";
        case BootCheckpoint::SdInit: return "SD_INIT";
        case BootCheckpoint::Ready: return "READY";
        default: return "UNKNOWN";
    }
}

const char *bootNetworkStateName(BootNetworkState state) {
    switch (state) {
        case BootNetworkState::Unknown: return "UNKNOWN";
        case BootNetworkState::StaPending: return "STA_PENDING";
        case BootNetworkState::StaConnected: return "STA_CONNECTED";
        case BootNetworkState::RecoveryAp: return "RECOVERY_AP";
        case BootNetworkState::Lost: return "LOST";
        default: return "UNKNOWN";
    }
}

void bootDiagnosticsPrintSummary() {
    Serial.print(F("[BOOT-DIAG] reset="));
    Serial.print(bootDiagnosticsResetReasonName());
    Serial.print(F(" rtc_boot="));
    Serial.print(bootDiagnosticsRtcBootCount());
    Serial.print(F(" previous_checkpoint="));
    Serial.print(bootCheckpointName(bootDiagnosticsPreviousCheckpoint()));
    Serial.print(F(" previous_network="));
    Serial.print(bootNetworkStateName(bootDiagnosticsPreviousNetworkState()));
    Serial.print(F(" previous_complete="));
    Serial.println(bootDiagnosticsPreviousComplete() ? F("yes") : F("no"));
}
