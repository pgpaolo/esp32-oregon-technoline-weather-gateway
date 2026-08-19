#include "firmware_info.h"
#include <esp_system.h>
#include "config.h"

#if __has_include("git_version_generated.h")
#include "git_version_generated.h"
#else
#define GIT_COMMIT_HASH "source-archive"
#endif

const char *firmwareVersion() { return FIRMWARE_VERSION; }
const char *firmwareGitCommit() { return GIT_COMMIT_HASH; }

String firmwareBuildTimestamp() {
    return String(__DATE__) + " " + String(__TIME__);
}

const char *firmwareResetReason() {
    switch (esp_reset_reason()) {
        case ESP_RST_POWERON:   return "POWERON";
        case ESP_RST_EXT:       return "EXTERNAL";
        case ESP_RST_SW:        return "SOFTWARE";
        case ESP_RST_PANIC:     return "PANIC";
        case ESP_RST_INT_WDT:   return "INT_WDT";
        case ESP_RST_TASK_WDT:  return "TASK_WDT";
        case ESP_RST_WDT:       return "OTHER_WDT";
        case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
        case ESP_RST_BROWNOUT:  return "BROWNOUT";
        case ESP_RST_SDIO:      return "SDIO";
        default:                return "UNKNOWN";
    }
}
