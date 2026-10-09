#include "sd_logger.h"
#include "rain_accumulator.h"

#include <Arduino.h>
#include <SdFat.h>
#include <SPI.h>
#include <Preferences.h>
#include <time.h>
#include <string.h>

#include "board_config.h"
#include "weather_parser.h"
#include "oregon_receiver.h"
#include "lightning_manager.h"

namespace {

constexpr const char *NVS_NS = "sdlog";
constexpr uint8_t QUEUE_SIZE = 16;
constexpr size_t LINE_SIZE = 320;
constexpr uint32_t WRITE_PERIOD_MS = 750UL;
constexpr uint8_t WRITE_BATCH_MAX = 6;
constexpr uint32_t CAPACITY_REFRESH_MS = 30000UL;
constexpr time_t VALID_EPOCH_MIN = 1700000000;

const char *CSV_HEADER =
    "timestamp_utc,uptime_ms,source,protocol,type,model,code,channel,rolling_id,rssi_dbm,battery,"
    "temperature_c,humidity_pct,wind_avg_kmh,wind_gust_kmh,wind_dir_deg,rain_total_mm,rain_rate_mmh,uv_index,"
    "pressure_abs_hpa,pressure_sl_hpa,pressure_trend_hpa3h,lightning_distance_km,lightning_energy,lightning_count,"
    "sensor_id,next_update,raw\n";

struct PendingLine {
    char text[LINE_SIZE]{};
};

SPIClass sdSpi(HSPI);
SdFat32 sd;
SdLoggerConfig cfg{};
SdLoggerStatus status{};
PendingLine queueBuf[QUEUE_SIZE];
uint8_t queueHead = 0;
uint8_t queueTail = 0;
uint32_t lastWriteServiceMs = 0;
uint32_t lastCapacityRefreshMs = 0;
uint32_t lastSnapshotMs = 0;
bool spiStarted = false;
constexpr uint32_t SD_MOUNT_RETRY_STEPS_MS[] = {5000UL, 15000UL, 60000UL, 300000UL};
uint8_t mountRetryStage = 0;
uint32_t nextMountRetryMs = 0;

void resetMountRetry() {
    mountRetryStage = 0;
    nextMountRetryMs = 0;
}

void scheduleMountRetry() {
    if (!cfg.enabled || !status.supported || status.mounted) {
        nextMountRetryMs = 0;
        return;
    }
    constexpr uint8_t stepCount = sizeof(SD_MOUNT_RETRY_STEPS_MS) / sizeof(SD_MOUNT_RETRY_STEPS_MS[0]);
    const uint8_t idx = mountRetryStage < stepCount ? mountRetryStage : static_cast<uint8_t>(stepCount - 1U);
    nextMountRetryMs = millis() + SD_MOUNT_RETRY_STEPS_MS[idx];
    if (mountRetryStage + 1U < stepCount) mountRetryStage++;
    Serial.print(F("[SD] nuovo tentativo mount tra "));
    Serial.print(SD_MOUNT_RETRY_STEPS_MS[idx] / 1000UL);
    Serial.println(F(" s"));
}

uint32_t mountRetryRemainingMs() {
    if (!nextMountRetryMs) return 0;
    const int32_t delta = static_cast<int32_t>(nextMountRetryMs - millis());
    return delta > 0 ? static_cast<uint32_t>(delta) : 0U;
}

SdLoggerConfig defaults() {
    return SdLoggerConfig{};
}

uint8_t queueDepth() {
    return queueHead >= queueTail
        ? static_cast<uint8_t>(queueHead - queueTail)
        : static_cast<uint8_t>(QUEUE_SIZE - queueTail + queueHead);
}

bool queueLine(const char *line) {
    // An absent/unmounted card is a normal optional-hardware state: do not
    // consume RAM or count artificial queue drops while storage is offline.
    if (!cfg.enabled || !status.mounted || !line || !line[0]) return false;
    const uint8_t next = static_cast<uint8_t>((queueHead + 1U) % QUEUE_SIZE);
    if (next == queueTail) {
        status.recordsDropped++;
        return false;
    }
    strncpy(queueBuf[queueHead].text, line, LINE_SIZE - 1U);
    queueBuf[queueHead].text[LINE_SIZE - 1U] = '\0';
    queueHead = next;
    status.recordsQueued++;
    status.queueDepth = queueDepth();
    return true;
}

bool boolFromPrefs(Preferences &p, const char *key, bool fallback) {
    return p.getBool(key, fallback);
}

void loadConfig() {
    cfg = defaults();
    Preferences p;
    if (!p.begin(NVS_NS, true)) return;
    cfg.enabled = boolFromPrefs(p, "enabled", cfg.enabled);
    cfg.logOregon = boolFromPrefs(p, "oregon", cfg.logOregon);
    cfg.logTechnoline = boolFromPrefs(p, "tech", cfg.logTechnoline);
    cfg.logBme280 = boolFromPrefs(p, "bme", cfg.logBme280);
    cfg.logAs3935 = boolFromPrefs(p, "as3935", cfg.logAs3935);
    cfg.rainOregon = boolFromPrefs(p, "r_oreg", cfg.rainOregon);
    cfg.rainTechnoline = boolFromPrefs(p, "r_tech", cfg.rainTechnoline);
    cfg.rainPersist = boolFromPrefs(p, "r_sd", cfg.rainPersist);
    cfg.snapshotIntervalSec = p.getUShort("snap_s", cfg.snapshotIntervalSec);
    p.end();
    if (!validateSdLoggerConfig(cfg)) cfg = defaults();
}

bool sameConfig(const SdLoggerConfig &a, const SdLoggerConfig &b) {
    return a.enabled == b.enabled &&
           a.logOregon == b.logOregon &&
           a.logTechnoline == b.logTechnoline &&
           a.logBme280 == b.logBme280 &&
           a.logAs3935 == b.logAs3935 &&
           a.rainOregon == b.rainOregon &&
           a.rainTechnoline == b.rainTechnoline &&
           a.rainPersist == b.rainPersist &&
           a.snapshotIntervalSec == b.snapshotIntervalSec;
}

bool verifyConfig(Preferences &p, const SdLoggerConfig &expected) {
    const SdLoggerConfig d = defaults();
    return p.getBool("enabled", d.enabled) == expected.enabled &&
           p.getBool("oregon", d.logOregon) == expected.logOregon &&
           p.getBool("tech", d.logTechnoline) == expected.logTechnoline &&
           p.getBool("bme", d.logBme280) == expected.logBme280 &&
           p.getBool("as3935", d.logAs3935) == expected.logAs3935 &&
           p.getBool("r_oreg", d.rainOregon) == expected.rainOregon &&
           p.getBool("r_tech", d.rainTechnoline) == expected.rainTechnoline &&
           p.getBool("r_sd", d.rainPersist) == expected.rainPersist &&
           p.getUShort("snap_s", d.snapshotIntervalSec) == expected.snapshotIntervalSec;
}

void refreshCapacity() {
    if (!status.mounted || !sd.card()) return;
    status.cardSizeBytes = static_cast<uint64_t>(sd.card()->sectorCount()) * 512ULL;
    const uint64_t bytesPerCluster = sd.bytesPerCluster();
    status.totalBytes = static_cast<uint64_t>(sd.clusterCount()) * bytesPerCluster;
    const uint64_t freeBytes = static_cast<uint64_t>(sd.freeClusterCount()) * bytesPerCluster;
    status.usedBytes = status.totalBytes >= freeBytes ? status.totalBytes - freeBytes : 0;
    lastCapacityRefreshMs = millis();
}

bool timeValid(struct tm *utcOut = nullptr) {
    const time_t now = time(nullptr);
    if (now < VALID_EPOCH_MIN) return false;
    if (utcOut) gmtime_r(&now, utcOut);
    return true;
}

void isoTimestamp(char *out, size_t outLen) {
    if (!out || outLen == 0) return;
    struct tm utc{};
    if (!timeValid(&utc)) {
        out[0] = '\0';
        return;
    }
    strftime(out, outLen, "%Y-%m-%dT%H:%M:%SZ", &utc);
}

void ensureDirectory(const char *path) {
    if (!path || !path[0] || sd.exists(path)) return;
    sd.mkdir(path);
}

bool buildLogPath(char *out, size_t outLen) {
    if (!out || outLen < 24U) return false;
    ensureDirectory("/weather");

    struct tm utc{};
    if (!timeValid(&utc)) {
        snprintf(out, outLen, "/weather/unsynced.csv");
        return true;
    }

    char yearDir[16];
    char monthDir[24];
    snprintf(yearDir, sizeof(yearDir), "/weather/%04d", utc.tm_year + 1900);
    snprintf(monthDir, sizeof(monthDir), "%s/%02d", yearDir, utc.tm_mon + 1);
    ensureDirectory(yearDir);
    ensureDirectory(monthDir);
    snprintf(out, outLen, "%s/%04d-%02d-%02d.csv",
             monthDir, utc.tm_year + 1900, utc.tm_mon + 1, utc.tm_mday);
    return true;
}

bool appendBatch() {
    if (!status.mounted || queueTail == queueHead) return false;

    char path[72];
    if (!buildLogPath(path, sizeof(path))) return false;
    const bool newFile = !sd.exists(path);
    File32 f = sd.open(path, O_WRONLY | O_CREAT | O_APPEND);
    if (!f) {
        status.writeErrors++;
        return false;
    }

    bool ok = true;
    if (newFile && f.print(CSV_HEADER) == 0) ok = false;

    uint8_t writtenThisBatch = 0;
    while (ok && queueTail != queueHead && writtenThisBatch < WRITE_BATCH_MAX) {
        const char *line = queueBuf[queueTail].text;
        if (f.println(line) == 0) {
            ok = false;
            break;
        }
        queueTail = static_cast<uint8_t>((queueTail + 1U) % QUEUE_SIZE);
        status.recordsWritten++;
        writtenThisBatch++;
    }
    f.flush();
    f.close();

    if (!ok) status.writeErrors++;
    else {
        status.lastWriteMs = millis();
        strncpy(status.currentFile, path, sizeof(status.currentFile) - 1U);
        status.currentFile[sizeof(status.currentFile) - 1U] = '\0';
    }
    status.queueDepth = queueDepth();
    return ok;
}

const char *oregonProtocol(const OregonPacket &packet) {
    return packet.decodeSource == static_cast<uint8_t>(OregonDecodeSource::EdgeTimingV21)
        ? "V2.1" : "OSV3";
}

void rawOregon(const OregonPacket &packet, char *out, size_t len) {
    if (!out || len == 0) return;
    size_t pos = 0;
    for (uint8_t i = 0; i < packet.length && pos + 3U < len; ++i) {
        pos += snprintf(out + pos, len - pos, "%02X", packet.bytes[i]);
    }
}

void rawTechnoline(const LaCrossePacket &packet, char *out, size_t len) {
    if (!out || len == 0) return;
    size_t pos = 0;
    for (uint8_t i = 0; i < LACROSSE_WS23XX_NIBBLES && pos + 2U < len; ++i) {
        pos += snprintf(out + pos, len - pos, "%X", packet.nibbles[i] & 0x0FU);
    }
}

void valueOrBlank(char *out, size_t len, bool valid, float v, uint8_t decimals = 1) {
    if (!out || len == 0) return;
    if (!valid || !isfinite(v)) { out[0] = '\0'; return; }
    snprintf(out, len, decimals == 2 ? "%.2f" : "%.1f", v);
}

void queueBmeSnapshot(const StationState &station) {
    if (!cfg.enabled || !cfg.logBme280 || !status.mounted) return;
    if (!station.indoorTemperatureValid && !station.indoorHumidityValid && !station.pressureValid) return;

    char ts[24]; isoTimestamp(ts, sizeof(ts));
    char temp[16], hum[16], pAbs[16], pSl[16], trend[16];
    valueOrBlank(temp, sizeof(temp), station.indoorTemperatureValid, station.indoorTemperatureC, 1);
    valueOrBlank(hum, sizeof(hum), station.indoorHumidityValid, station.indoorHumidityPct, 1);
    valueOrBlank(pAbs, sizeof(pAbs), station.pressureValid, station.pressureAbsoluteHpa, 1);
    valueOrBlank(pSl, sizeof(pSl), station.pressureValid, station.pressureSeaLevelHpa, 1);
    valueOrBlank(trend, sizeof(trend), station.pressureTrendValid, station.pressureTrendHpa3h, 1);

    char line[LINE_SIZE];
    snprintf(line, sizeof(line),
             "%s,%lu,local,I2C,environment,BME280,,,,,N/D,%s,%s,,,,,,,,%s,%s,%s,,,,,,",
             ts, static_cast<unsigned long>(millis()), temp, hum, pAbs, pSl, trend);
    queueLine(line);
}

void queueLightningSnapshot() {
    if (!cfg.enabled || !cfg.logAs3935 || !status.mounted) return;
    const LightningState s = getLightningState();
    if (!s.enabled && !s.detected && s.irqTotal == 0) return;

    char ts[24]; isoTimestamp(ts, sizeof(ts));
    char line[LINE_SIZE];
    snprintf(line, sizeof(line),
             "%s,%lu,local,I2C_IRQ,lightning,AS3935,,,,,N/D,,,,,,,,,,,,%u,%lu,%lu,,,%s",
             ts, static_cast<unsigned long>(millis()),
             static_cast<unsigned>(s.lastDistanceKm),
             static_cast<unsigned long>(s.lastEnergy),
             static_cast<unsigned long>(s.lightningTotal),
             lightningInterruptName(s.lastInterruptSource));
    queueLine(line);
}

void unmount() {
    sd.end();
    if (spiStarted) {
        sdSpi.end();
        spiStarted = false;
    }
    status.mounted = false;
    status.cardSizeBytes = 0;
    status.totalBytes = 0;
    status.usedBytes = 0;
    status.spiFrequencyHz = 0;
    status.currentFile[0] = '\0';
    queueHead = queueTail = 0;
    status.queueDepth = 0;
}

bool mountSdFat(bool formatRequested) {
    unmount();
    status.mountAttempts++;
    status.spiAttemptMask = 0;
    status.spiBeginFailMask = 0;
    status.initCode = 0;
    status.sdErrorCode = 0;
    status.sdErrorData = 0;

    // Official LILYGO T3 V1.6.1 HSPI pin order. CS is kept high while the
    // clock/data pins are configured, then SdFat owns it during transactions.
    constexpr uint32_t frequencies[] = {SD_SCK_MHZ(4), 400000UL};
    for (uint8_t i = 0; i < 2U; ++i) {
        const uint8_t bit = static_cast<uint8_t>(1U << i);
        status.spiAttemptMask |= bit;
        pinMode(SDCARD_CS_PIN, OUTPUT);
        digitalWrite(SDCARD_CS_PIN, HIGH);
        delay(10);
        sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN, SDCARD_MOSI_PIN);
        spiStarted = true;

        const SdSpiConfig spiConfig(SDCARD_CS_PIN, SHARED_SPI, frequencies[i], &sdSpi);
        bool mounted = sd.begin(spiConfig);
        status.sdErrorCode = sd.sdErrorCode();
        status.sdErrorData = sd.sdErrorData();

        // sdErrorCode()==0 with begin()==false means the card initialized but
        // no supported FAT volume exists. That is precisely the state in which
        // formatting must be allowed instead of aborting before the formatter.
        const bool cardReady = mounted || status.sdErrorCode == 0;
        if (formatRequested && cardReady) {
            Serial.println(F("[SD] formattazione FAT tramite SdFat..."));
            if (!sd.format(&Serial)) {
                status.sdErrorCode = sd.sdErrorCode();
                status.sdErrorData = sd.sdErrorData();
                status.initCode = 4;
                status.spiBeginFailMask |= bit;
                unmount();
                return false;
            }

            // Reinitialize from a clean bus after writing the partition/FAT.
            sd.end();
            sdSpi.end();
            spiStarted = false;
            delay(20);
            pinMode(SDCARD_CS_PIN, OUTPUT);
            digitalWrite(SDCARD_CS_PIN, HIGH);
            sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN, SDCARD_MOSI_PIN);
            spiStarted = true;
            mounted = sd.begin(spiConfig);
            status.sdErrorCode = sd.sdErrorCode();
            status.sdErrorData = sd.sdErrorData();
        }

        if (mounted) {
            status.mounted = true;
            status.spiFrequencyHz = frequencies[i];
            status.initCode = 1;
            status.sdErrorCode = 0;
            status.sdErrorData = 0;
            refreshCapacity();
            Serial.print(F("[SD] SdFat montata a "));
            Serial.print(frequencies[i] / 1000UL);
            Serial.print(F(" kHz: "));
            Serial.print(static_cast<unsigned long>(status.cardSizeBytes / (1024ULL * 1024ULL)));
            Serial.println(F(" MB"));
            return true;
        }

        status.spiBeginFailMask |= bit;
        status.initCode = cardReady ? 3 : 2;
        Serial.print(F("[SD] SdFat init fallita a "));
        Serial.print(frequencies[i] / 1000UL);
        Serial.print(F(" kHz, error 0x"));
        Serial.print(status.sdErrorCode, HEX);
        Serial.print(F(" data 0x"));
        Serial.println(status.sdErrorData, HEX);
        sd.end();
        sdSpi.end();
        spiStarted = false;

        // A valid card with an invalid FAT will not improve at a lower clock.
        // Preserve that state so the explicit FORMATTA action can repair it.
        if (cardReady) return false;
        delay(25);
    }

    Serial.println(F("[SD] scheda non inizializzata; gateway continua senza logging"));
    return false;
}

} // namespace

void initSdLogger() {
#if SDCARD_SUPPORTED
    status.supported = true;
#else
    status.supported = false;
#endif
    loadConfig();

    // UTC e' intenzionale: i file giornalieri non dipendono da DST/timezone.
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");

    if (cfg.enabled && status.supported) remountSdLogger();
    else Serial.println(F("[SD] datalogger disabilitato"));
}

bool remountSdLogger() {
#if !SDCARD_SUPPORTED
    status.supported = false;
    nextMountRetryMs = 0;
    return false;
#else
    const bool ok = mountSdFat(false);
    if (ok) resetMountRetry();
    else scheduleMountRetry();
    return ok;
#endif
}

bool formatSdLogger() {
#if !SDCARD_SUPPORTED
    return false;
#else
    resetMountRetry();
    const bool ok = mountSdFat(true);
    if (ok) {
        resetMountRetry();
        Serial.println(F("[SD] formattazione e rimontaggio completati"));
    } else {
        scheduleMountRetry();
    }
    return ok;
#endif
}

// ADMIN_SENSOR_SD_BROWSER_V1
namespace {
constexpr uint16_t SD_BROWSER_FILE_LIMIT = 48U;
constexpr size_t SD_BROWSER_CHUNK_MAX = 6144U;

bool validSdBrowserPath(const String &path) {
    return path.length() > 13U && path.length() < 96U &&
           path.startsWith("/weather/") && path.endsWith(".csv") &&
           path.indexOf("..") < 0 && path.indexOf('\\') < 0;
}

void appendSdJsonString(String &out, const char *value) {
    out += '"';
    if (value) {
        for (const char *p = value; *p; ++p) {
            const unsigned char c = static_cast<unsigned char>(*p);
            if (c == '"' || c == '\\') {
                out += '\\';
                out += static_cast<char>(c);
            } else if (c >= 0x20U) {
                out += static_cast<char>(c);
            }
        }
    }
    out += '"';
}

void appendSdDirectoryFiles(const String &dirPath, uint8_t depth, String &out,
                            uint16_t &count, bool &first) {
    if (!status.mounted || depth > 3U || count >= SD_BROWSER_FILE_LIMIT) return;

    File32 dir = sd.open(dirPath.c_str(), O_RDONLY);
    if (!dir || !dir.isDir()) {
        dir.close();
        return;
    }

    File32 entry;
    while (count < SD_BROWSER_FILE_LIMIT && entry.openNext(&dir, O_RDONLY)) {
        char name[64]{};
        entry.getName(name, sizeof(name));
        if (!name[0] || name[0] == '.') {
            entry.close();
            continue;
        }

        String full = dirPath;
        if (!full.endsWith("/")) full += '/';
        full += name;

        if (entry.isDir()) {
            entry.close();
            appendSdDirectoryFiles(full, static_cast<uint8_t>(depth + 1U), out, count, first);
            continue;
        }

        if (full.endsWith(".csv")) {
            const uint32_t fileSize = static_cast<uint32_t>(entry.fileSize());
            if (!first) out += ',';
            first = false;
            out += "{\"path\":";
            appendSdJsonString(out, full.c_str());
            out += ",\"size\":" + String(fileSize) + "}";
            count++;
        }
        entry.close();
    }
    dir.close();
}
} // namespace

String sdLoggerFilesJson() {
    String out;
    out.reserve(4096U);
    out = "{\"status\":" + sdLoggerStatusJson() + ",\"files\":[";
    uint16_t count = 0;
    bool first = true;
    appendSdDirectoryFiles("/weather", 0U, out, count, first);
    out += "],\"count\":" + String(count);
    out += ",\"truncated\":";
    out += count >= SD_BROWSER_FILE_LIMIT ? "true" : "false";
    out += "}";
    return out;
}

bool sdLoggerReadFileChunk(const String &path, uint32_t offset, size_t maxBytes,
                           String &data, uint32_t &totalBytes) {
    data = "";
    totalBytes = 0;
    if (!status.mounted || !validSdBrowserPath(path)) return false;
    if (maxBytes == 0U || maxBytes > SD_BROWSER_CHUNK_MAX) maxBytes = SD_BROWSER_CHUNK_MAX;

    File32 file = sd.open(path.c_str(), O_RDONLY);
    if (!file || file.isDir()) {
        file.close();
        return false;
    }

    totalBytes = static_cast<uint32_t>(file.fileSize());
    if (offset > totalBytes) {
        file.close();
        return false;
    }
    if (offset == totalBytes) {
        file.close();
        return true;
    }
    if (!file.seekSet(offset)) {
        file.close();
        return false;
    }

    const size_t remaining = static_cast<size_t>(totalBytes - offset);
    const size_t wanted = remaining < maxBytes ? remaining : maxBytes;
    if (!data.reserve(wanted + 1U)) {
        file.close();
        return false;
    }

    uint8_t buf[512];
    size_t done = 0;
    while (done < wanted) {
        const size_t ask = (wanted - done) < sizeof(buf) ? (wanted - done) : sizeof(buf);
        const int got = file.read(buf, ask);
        if (got <= 0) break;
        data.concat(reinterpret_cast<const char *>(buf), static_cast<unsigned int>(got));
        done += static_cast<size_t>(got);
    }
    file.close();
    return done == wanted;
}

void enqueueSdOregon(const WeatherReading &r, const OregonPacket &packet) {
    if (!cfg.enabled || !cfg.logOregon || !status.mounted) return;

    char ts[24]; isoTimestamp(ts, sizeof(ts));
    char code[8]; snprintf(code, sizeof(code), "%04X", r.sensorCode);
    char raw[OREGON_MAX_PACKET_BYTES * 2U + 1U]{}; rawOregon(packet, raw, sizeof(raw));
    char temp[16], hum[16], wAvg[16], wGust[16], wDir[16], rainTot[16], rainRate[16], uv[8];
    valueOrBlank(temp, sizeof(temp), r.temperatureValid, r.temperatureC, 1);
    valueOrBlank(hum, sizeof(hum), r.humidityValid, r.humidityPct, 1);
    valueOrBlank(wAvg, sizeof(wAvg), r.windAverageValid, r.windAverageKmh, 1);
    valueOrBlank(wGust, sizeof(wGust), r.windGustValid, r.windGustKmh, 1);
    valueOrBlank(wDir, sizeof(wDir), r.windDirectionValid, r.windDirectionDeg, 1);
    valueOrBlank(rainTot, sizeof(rainTot), r.rainTotalValid, r.rainTotalMm, 2);
    valueOrBlank(rainRate, sizeof(rainRate), r.rainRateValid, r.rainRateMmH, 2);
    if (r.uvValid) snprintf(uv, sizeof(uv), "%d", r.uvIndex); else uv[0] = '\0';

    const char *battery = r.batteryStatusValid ? (r.batteryLow ? "LOW" : "OK") : "N/D";
    char rssi[16]; valueOrBlank(rssi, sizeof(rssi), isfinite(r.rssi), r.rssi, 1);

    char line[LINE_SIZE];
    snprintf(line, sizeof(line),
             "%s,%lu,Oregon,%s,%s,%s,%s,%u,%u,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,,,,,,,,,,%s",
             ts, static_cast<unsigned long>(r.receivedAtMs), oregonProtocol(packet), sensorTypeName(r.type),
             sensorModelName(r.sensorCode), code, static_cast<unsigned>(r.channel), static_cast<unsigned>(r.rollingCode),
             rssi, battery, temp, hum, wAvg, wGust, wDir, rainTot, rainRate, uv, raw);
    queueLine(line);
}

void enqueueSdTechnoline(const LaCrosseReading &r, const LaCrossePacket &packet) {
    if (!cfg.enabled || !cfg.logTechnoline || !status.mounted) return;

    char ts[24]; isoTimestamp(ts, sizeof(ts));
    char raw[LACROSSE_WS23XX_NIBBLES + 1U]{}; rawTechnoline(packet, raw, sizeof(raw));
    char temp[16] = "", hum[16] = "", wind[16] = "", gust[16] = "", dir[16] = "", rain[16] = "", rssi[16] = "";
    valueOrBlank(temp, sizeof(temp), r.temperatureValid, r.temperatureC, 1);
    valueOrBlank(hum, sizeof(hum), r.humidityValid, r.humidityPct, 1);
    valueOrBlank(wind, sizeof(wind), r.windValid, r.windKmh, 1);
    valueOrBlank(gust, sizeof(gust), r.gustValid, r.gustKmh, 1);
    valueOrBlank(dir, sizeof(dir), r.directionValid, r.directionDeg, 1);
    valueOrBlank(rain, sizeof(rain), r.rainValid, r.rainTotalMm, 2);
    valueOrBlank(rssi, sizeof(rssi), isfinite(r.rssi), r.rssi, 1);

    char line[LINE_SIZE];
    snprintf(line, sizeof(line),
             "%s,%lu,Technoline,WS23xx,%s,%s,,,,%s,N/D,%s,%s,%s,%s,%s,%s,,,,,,,,,,%u,%s,%s",
             ts, static_cast<unsigned long>(r.receivedAtMs), laCrosseTypeName(r.type), laCrosseModelName(r.wsId),
             rssi, temp, hum, wind, gust, dir, rain,
             static_cast<unsigned>(r.sensorId), laCrosseNextUpdateName(r.nextUpdateCode), raw);
    queueLine(line);
}

void serviceSdLogger(const StationState &station) {
    status.timeSynced = timeValid();
    const uint32_t now = millis();

    if (cfg.enabled && status.supported && !status.mounted && nextMountRetryMs &&
        static_cast<int32_t>(now - nextMountRetryMs) >= 0) {
        remountSdLogger();
    }
    if (!cfg.enabled || !status.mounted) return;

    const uint32_t snapshotMs = static_cast<uint32_t>(cfg.snapshotIntervalSec) * 1000UL;
    if (snapshotMs && static_cast<uint32_t>(now - lastSnapshotMs) >= snapshotMs) {
        lastSnapshotMs = now;
        queueBmeSnapshot(station);
        queueLightningSnapshot();
    }

    if (static_cast<uint32_t>(now - lastWriteServiceMs) >= WRITE_PERIOD_MS) {
        lastWriteServiceMs = now;
        appendBatch();
    }
    if (static_cast<uint32_t>(now - lastCapacityRefreshMs) >= CAPACITY_REFRESH_MS) refreshCapacity();
}

void prepareSdLoggerForDeepSleep() {
    if (status.mounted) {
        for (uint8_t i = 0; i < 4U && queueTail != queueHead; ++i) appendBatch();
    }
    unmount();
    resetMountRetry();
}

SdLoggerConfig getSdLoggerConfig() { return cfg; }
SdLoggerStatus getSdLoggerStatus() {
    SdLoggerStatus s = status;
    s.queueDepth = queueDepth();
    s.timeSynced = timeValid();
    return s;
}

bool validateSdLoggerConfig(const SdLoggerConfig &c) {
    return c.snapshotIntervalSec >= 30U && c.snapshotIntervalSec <= 3600U;
}

bool saveSdLoggerConfig(const SdLoggerConfig &next, bool &changed) {
    if (!validateSdLoggerConfig(next)) return false;
    changed = !sameConfig(next, cfg);
    if (!changed) return true;

    Preferences p;
    if (!p.begin(NVS_NS, false)) return false;
    if (next.enabled != cfg.enabled) p.putBool("enabled", next.enabled);
    if (next.logOregon != cfg.logOregon) p.putBool("oregon", next.logOregon);
    if (next.logTechnoline != cfg.logTechnoline) p.putBool("tech", next.logTechnoline);
    if (next.logBme280 != cfg.logBme280) p.putBool("bme", next.logBme280);
    if (next.logAs3935 != cfg.logAs3935) p.putBool("as3935", next.logAs3935);
    if (next.rainOregon != cfg.rainOregon) p.putBool("r_oreg", next.rainOregon);
    if (next.rainTechnoline != cfg.rainTechnoline) p.putBool("r_tech", next.rainTechnoline);
    if (next.rainPersist != cfg.rainPersist) p.putBool("r_sd", next.rainPersist);
    if (next.snapshotIntervalSec != cfg.snapshotIntervalSec) p.putUShort("snap_s", next.snapshotIntervalSec);
    const bool verified = verifyConfig(p, next);
    p.end();
    if (!verified) return false;

    const bool wasEnabled = cfg.enabled;
    const bool oregonChanged = cfg.rainOregon != next.rainOregon;
    const bool technolineChanged = cfg.rainTechnoline != next.rainTechnoline;
    // Flush before disabling SD; otherwise pending totals could be lost.
    if (cfg.rainPersist && (!next.rainPersist || !next.enabled)) flushRainAccumulator();
    cfg = next;
    rainAccumulatorConfigChanged(oregonChanged, technolineChanged);
    if (wasEnabled && !cfg.enabled) prepareSdLoggerForDeepSleep();
    else if (!wasEnabled && cfg.enabled) remountSdLogger();
    return true;
}

bool resetSdLoggerConfigToDefaults(bool &changed) {
    return saveSdLoggerConfig(defaults(), changed);
}

String sdLoggerConfigJson() {
    String out;
    out.reserve(220);
    out = "{\"enabled\":"; out += cfg.enabled ? "true" : "false";
    out += ",\"oregon\":"; out += cfg.logOregon ? "true" : "false";
    out += ",\"technoline\":"; out += cfg.logTechnoline ? "true" : "false";
    out += ",\"bme280\":"; out += cfg.logBme280 ? "true" : "false";
    out += ",\"as3935\":"; out += cfg.logAs3935 ? "true" : "false";
    out += ",\"rain_oregon\":"; out += cfg.rainOregon ? "true" : "false";
    out += ",\"rain_technoline\":"; out += cfg.rainTechnoline ? "true" : "false";
    out += ",\"rain_sd\":"; out += cfg.rainPersist ? "true" : "false";
    out += ",\"snapshot_interval_s\":" + String(cfg.snapshotIntervalSec);
    out += "}";
    return out;
}

String sdLoggerStatusJson() {
    const SdLoggerStatus s = getSdLoggerStatus();
    String out;
    out.reserve(420);
    out = "{\"supported\":"; out += s.supported ? "true" : "false";
    out += ",\"mounted\":"; out += s.mounted ? "true" : "false";
    out += ",\"time_synced\":"; out += s.timeSynced ? "true" : "false";
    out += ",\"card_size\":" + String(static_cast<unsigned long long>(s.cardSizeBytes));
    out += ",\"total_bytes\":" + String(static_cast<unsigned long long>(s.totalBytes));
    out += ",\"used_bytes\":" + String(static_cast<unsigned long long>(s.usedBytes));
    out += ",\"mount_attempts\":" + String(s.mountAttempts);
    out += ",\"spi_hz\":" + String(s.spiFrequencyHz);
    out += ",\"spi_try\":" + String(s.spiAttemptMask);
    out += ",\"spi_fail\":" + String(s.spiBeginFailMask);
    out += ",\"init_code\":" + String(s.initCode);
    out += ",\"sd_error\":" + String(s.sdErrorCode);
    out += ",\"sd_error_data\":" + String(s.sdErrorData);
    out += ",\"queued_total\":" + String(s.recordsQueued);
    out += ",\"written\":" + String(s.recordsWritten);
    out += ",\"dropped\":" + String(s.recordsDropped);
    out += ",\"write_errors\":" + String(s.writeErrors);
    out += ",\"queue_depth\":" + String(s.queueDepth);
    out += ",\"last_write_ms\":" + String(s.lastWriteMs);
    out += ",\"retry_pending\":"; out += (cfg.enabled && s.supported && !s.mounted && nextMountRetryMs) ? "true" : "false";
    out += ",\"retry_in_ms\":" + String(mountRetryRemainingMs());
    out += ",\"file\":\"" + String(s.currentFile) + "\"";
    out += "}";
    return out;
}

// Two fixed-size checkpoint slots: an interrupted write cannot invalidate both.
bool sdRainStorageReady() { return cfg.enabled && cfg.rainPersist && status.mounted; }
namespace {
const char *sdRainPath(uint8_t slot) { return slot == 0 ? "/weather/rain_a.bin" : "/weather/rain_b.bin"; }
}
bool sdRainReadSlot(uint8_t slot, void *buffer, size_t size) {
    if (!status.mounted || slot > 1 || !buffer || !size || size > 256) return false;
    File32 f = sd.open(sdRainPath(slot), O_RDONLY);
    if (!f) return false;
    const bool ok = !f.isDir() && f.fileSize() == size && f.read(buffer, size) == static_cast<int>(size);
    f.close();
    return ok;
}
bool sdRainWriteSlot(uint8_t slot, const void *buffer, size_t size) {
    if (!status.mounted || slot > 1 || !buffer || !size || size > 256) return false;
    if (!sd.exists("/weather") && !sd.mkdir("/weather")) return false;
    File32 f = sd.open(sdRainPath(slot), O_WRONLY | O_CREAT | O_TRUNC);
    if (!f) return false;
    const bool wrote = f.write(reinterpret_cast<const uint8_t *>(buffer), size) == size;
    const bool flushed = f.sync();
    f.close();
    return wrote && flushed;
}
