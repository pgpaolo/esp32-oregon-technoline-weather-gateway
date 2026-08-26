#include "sd_logger.h"

#include <Arduino.h>
#include <FS.h>
#include <SD.h>
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
SdLoggerConfig cfg{};
SdLoggerStatus status{};
PendingLine queueBuf[QUEUE_SIZE];
uint8_t queueHead = 0;
uint8_t queueTail = 0;
uint32_t lastWriteServiceMs = 0;
uint32_t lastCapacityRefreshMs = 0;
uint32_t lastSnapshotMs = 0;
bool spiStarted = false;

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
           a.snapshotIntervalSec == b.snapshotIntervalSec;
}

bool verifyConfig(Preferences &p, const SdLoggerConfig &expected) {
    const SdLoggerConfig d = defaults();
    return p.getBool("enabled", d.enabled) == expected.enabled &&
           p.getBool("oregon", d.logOregon) == expected.logOregon &&
           p.getBool("tech", d.logTechnoline) == expected.logTechnoline &&
           p.getBool("bme", d.logBme280) == expected.logBme280 &&
           p.getBool("as3935", d.logAs3935) == expected.logAs3935 &&
           p.getUShort("snap_s", d.snapshotIntervalSec) == expected.snapshotIntervalSec;
}

void refreshCapacity() {
    if (!status.mounted) return;
    status.cardSizeBytes = SD.cardSize();
    status.totalBytes = SD.totalBytes();
    status.usedBytes = SD.usedBytes();
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
    if (!path || !path[0] || SD.exists(path)) return;
    SD.mkdir(path);
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
    const bool newFile = !SD.exists(path);
    File f = SD.open(path, FILE_APPEND);
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
    if (status.mounted) SD.end();
    if (spiStarted) {
        sdSpi.end();
        spiStarted = false;
    }
    status.mounted = false;
    status.cardSizeBytes = 0;
    status.totalBytes = 0;
    status.usedBytes = 0;
    status.currentFile[0] = '\0';
    queueHead = queueTail = 0;
    status.queueDepth = 0;
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
    return false;
#else
    unmount();
    status.mountAttempts++;
    pinMode(SDCARD_CS_PIN, OUTPUT);
    digitalWrite(SDCARD_CS_PIN, HIGH);
    sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN, SDCARD_MOSI_PIN, SDCARD_CS_PIN);
    spiStarted = true;

    if (!SD.begin(SDCARD_CS_PIN, sdSpi, 8000000U)) {
        Serial.println(F("[SD] microSD non rilevata / mount fallito; gateway continua senza logging"));
        unmount();
        return false;
    }
    if (SD.cardType() == CARD_NONE) {
        Serial.println(F("[SD] nessuna scheda presente"));
        unmount();
        return false;
    }

    status.mounted = true;
    refreshCapacity();
    Serial.print(F("[SD] montata: "));
    Serial.print(static_cast<unsigned long>(status.cardSizeBytes / (1024ULL * 1024ULL)));
    Serial.println(F(" MB"));
    return true;
#endif
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
    if (!cfg.enabled || !status.mounted) return;

    const uint32_t now = millis();
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
    if (next.snapshotIntervalSec != cfg.snapshotIntervalSec) p.putUShort("snap_s", next.snapshotIntervalSec);
    const bool verified = verifyConfig(p, next);
    p.end();
    if (!verified) return false;

    const bool wasEnabled = cfg.enabled;
    cfg = next;
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
    out += ",\"queued_total\":" + String(s.recordsQueued);
    out += ",\"written\":" + String(s.recordsWritten);
    out += ",\"dropped\":" + String(s.recordsDropped);
    out += ",\"write_errors\":" + String(s.writeErrors);
    out += ",\"queue_depth\":" + String(s.queueDepth);
    out += ",\"last_write_ms\":" + String(s.lastWriteMs);
    out += ",\"file\":\"" + String(s.currentFile) + "\"";
    out += "}";
    return out;
}
