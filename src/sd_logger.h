#pragma once

#include <Arduino.h>
#include "oregon_types.h"
#include "lacrosse_ws23xx.h"
#include "station_state.h"

struct SdLoggerConfig {
    // Fail-safe default: installing the SD-capable firmware without a card
    // must not alter the normal gateway path. Enable explicitly from Web.
    bool enabled{false};
    bool logOregon{true};
    bool logTechnoline{true};
    bool logBme280{true};
    bool logAs3935{true};
    // Calendar rainfall accumulation is independent from raw packet CSV logging.
    bool rainOregon{true};
    bool rainTechnoline{true};
    bool rainPersist{false};
    uint16_t snapshotIntervalSec{300};
};

struct SdLoggerStatus {
    bool supported{false};
    bool mounted{false};
    bool timeSynced{false};
    uint64_t cardSizeBytes{0};
    uint64_t totalBytes{0};
    uint64_t usedBytes{0};
    uint32_t mountAttempts{0};
    uint32_t spiFrequencyHz{0};
    uint8_t spiAttemptMask{0};
    uint8_t spiBeginFailMask{0};
    uint8_t initCode{0};
    uint8_t sdErrorCode{0};
    uint8_t sdErrorData{0};
    uint32_t recordsQueued{0};
    uint32_t recordsWritten{0};
    uint32_t recordsDropped{0};
    uint32_t writeErrors{0};
    uint32_t lastWriteMs{0};
    uint8_t queueDepth{0};
    char currentFile[72]{};
};

void initSdLogger();
void serviceSdLogger(const StationState &station);
void prepareSdLoggerForDeepSleep();

void enqueueSdOregon(const WeatherReading &reading, const OregonPacket &packet);
void enqueueSdTechnoline(const LaCrosseReading &reading, const LaCrossePacket &packet);

SdLoggerConfig getSdLoggerConfig();
SdLoggerStatus getSdLoggerStatus();
bool validateSdLoggerConfig(const SdLoggerConfig &cfg);
bool saveSdLoggerConfig(const SdLoggerConfig &cfg, bool &changed);
bool resetSdLoggerConfigToDefaults(bool &changed);
bool remountSdLogger();
bool formatSdLogger();

String sdLoggerConfigJson();
String sdLoggerStatusJson();

// ADMIN_SENSOR_SD_BROWSER_V1
String sdLoggerFilesJson();
bool sdLoggerReadFileChunk(const String &path, uint32_t offset, size_t maxBytes, String &data, uint32_t &totalBytes);

// Small alternating CRC-protected checkpoints. Only accessed from the main task.
bool sdRainStorageReady();
bool sdRainReadSlot(uint8_t slot, void *buffer, size_t size);
bool sdRainWriteSlot(uint8_t slot, const void *buffer, size_t size);
