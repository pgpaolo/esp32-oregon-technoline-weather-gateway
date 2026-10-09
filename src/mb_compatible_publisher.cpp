#include "mb_compatible_publisher.h"

#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <math.h>
#include <time.h>
#include <freertos/task.h>
#include <esp_heap_caps.h>

#include "config.h"
#include "firmware_info.h"
#include "network_manager.h"
#include "remote_access.h"
#include "remote_trust.h"

namespace {
constexpr char NVS_NS[] = "mbcompat";
constexpr uint16_t DEFAULT_INTERVAL_SEC = 60;
constexpr uint16_t DEFAULT_TIMEOUT_MS = 2500;
constexpr uint16_t MIN_INTERVAL_SEC = 10;
constexpr uint16_t MAX_INTERVAL_SEC = 3600;
constexpr uint16_t MIN_TIMEOUT_MS = 500;
constexpr uint16_t MAX_TIMEOUT_MS = 10000;
constexpr size_t MAX_URL_LEN = 384;
constexpr size_t MAX_CA_LEN = 3600;
constexpr size_t MB_FIELD_COUNT = 192;
constexpr time_t MIN_VALID_EPOCH = 1577836800; // 2020-01-01 UTC
constexpr uint32_t WORKER_STACK = 8192;

StationState *gState = nullptr;
MbCompatibleConfig gConfig{};
SemaphoreHandle_t gMutex = nullptr;
TaskHandle_t gWorkerTask = nullptr;
volatile bool gForceTest = false;
volatile bool gPending = false;
volatile bool gBusy = false;
String gPendingUrl;
String gPendingPayload;
uint32_t gLastScheduleMs = 0;
uint32_t gLastAttemptMs = 0;
uint32_t gLastSuccessMs = 0;
int gLastHttpCode = 0;
String gLastResponse;
String gLastError;
size_t gLastPayloadBytes = 0;
size_t gLastFieldCount = 0;
volatile uint8_t gLastWeatherValues = 0; // excludes metadata/uptime

struct DailyBaseline {
    uint32_t dayKey{0};
    float baseMm{NAN};
    bool valid{false};
};
DailyBaseline gOregonDaily;
DailyBaseline gTechnolineDaily;

struct LiveSelection {
    float tempC{NAN};
    float humPct{NAN};
    float dewC{NAN};
    float heatIndexC{NAN};
    float windKmh{NAN};
    float gustKmh{NAN};
    float dirDeg{NAN};
    float windChillC{NAN};
    float rainRateMmH{NAN};
    float rainTodayMm{NAN};
    float rain1hMm{NAN};
    float rain24hMm{NAN};
    float rainTotalMm{NAN};
    float pressureHpa{NAN};
    float pressure3hAgoHpa{NAN};
    float indoorTempC{NAN};
    float indoorHumPct{NAN};
    float uv{NAN};
    bool tempFromOregon{false};
    bool windFromOregon{false};
    bool rainFromOregon{false};
};

bool finiteValue(float value) { return isfinite(value); }

String jsonEscape(const String &value) {
    String out;
    out.reserve(value.length() + 8U);
    for (size_t i = 0; i < value.length(); ++i) {
        const char c = value[i];
        switch (c) {
            case '\\': out += "\\\\"; break;
            case '"': out += "\\\""; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<uint8_t>(c) >= 0x20U) out += c;
                break;
        }
    }
    return out;
}

bool validUrl(const String &url) {
    if (url.length() == 0U || url.length() > MAX_URL_LEN) return false;
    if (!(url.startsWith("http://") || url.startsWith("https://"))) return false;
    for (size_t i = 0; i < url.length(); ++i) {
        const uint8_t c = static_cast<uint8_t>(url[i]);
        if (c < 0x20U || c == 0x7FU) return false;
    }
    return true;
}

String urlEncode(const String &value) {
    static const char HEX_DIGITS[] = "0123456789ABCDEF";
    String out;
    out.reserve(value.length() * 2U);
    for (size_t i = 0; i < value.length(); ++i) {
        const uint8_t c = static_cast<uint8_t>(value[i]);
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~') {
            out += static_cast<char>(c);
        } else {
            out += '%';
            out += HEX_DIGITS[(c >> 4) & 0x0FU];
            out += HEX_DIGITS[c & 0x0FU];
        }
    }
    return out;
}

String buildRequestUrl(const String &base, const String &encodedPayload) {
    String url = base;
    const int marker = url.indexOf("{data}");
    if (marker >= 0) {
        url.remove(static_cast<unsigned int>(marker), 6U);
        url = url.substring(0, marker) + encodedPayload + url.substring(marker);
        return url;
    }
    if (url.endsWith("?d=") || url.endsWith("&d=")) return url + encodedPayload;
    url += (url.indexOf('?') >= 0) ? '&' : '?';
    url += "d=";
    url += encodedPayload;
    return url;
}

float dewPoint(float tempC, float humidityPct) {
    if (!finiteValue(tempC) || !finiteValue(humidityPct) || humidityPct <= 0.0f || humidityPct > 100.0f) return NAN;
    const float a = 17.62f;
    const float b = 243.12f;
    const float gamma = logf(humidityPct / 100.0f) + (a * tempC) / (b + tempC);
    return (b * gamma) / (a - gamma);
}

uint8_t beaufortFromKmh(float kmh) {
    if (!finiteValue(kmh)) return 0;
    const float ms = kmh / 3.6f;
    static const float limits[] = {0.3f,1.6f,3.4f,5.5f,8.0f,10.8f,13.9f,17.2f,20.8f,24.5f,28.5f,32.7f};
    for (uint8_t i = 0; i < 12U; ++i) if (ms < limits[i]) return i;
    return 12U;
}

uint32_t utcDayKey(const tm &utc) {
    return static_cast<uint32_t>(utc.tm_year + 1900) * 10000UL +
           static_cast<uint32_t>(utc.tm_mon + 1) * 100UL +
           static_cast<uint32_t>(utc.tm_mday);
}

void loadDailyBaselines() {
    Preferences p;
    if (!p.begin(NVS_NS, true)) return;
    gOregonDaily.dayKey = p.getUInt("orDay", 0U);
    gOregonDaily.baseMm = p.getFloat("orBase", NAN);
    gOregonDaily.valid = gOregonDaily.dayKey != 0U && finiteValue(gOregonDaily.baseMm);
    gTechnolineDaily.dayKey = p.getUInt("lcDay", 0U);
    gTechnolineDaily.baseMm = p.getFloat("lcBase", NAN);
    gTechnolineDaily.valid = gTechnolineDaily.dayKey != 0U && finiteValue(gTechnolineDaily.baseMm);
    p.end();
}

void persistDailyBaseline(bool oregon, const DailyBaseline &baseline) {
    Preferences p;
    if (!p.begin(NVS_NS, false)) return;
    if (oregon) {
        p.putUInt("orDay", baseline.dayKey);
        p.putFloat("orBase", baseline.baseMm);
    } else {
        p.putUInt("lcDay", baseline.dayKey);
        p.putFloat("lcBase", baseline.baseMm);
    }
    p.end();
}

float dailyRain(bool oregon, uint32_t dayKey, float totalMm) {
    if (!finiteValue(totalMm)) return NAN;
    DailyBaseline &b = oregon ? gOregonDaily : gTechnolineDaily;
    if (!b.valid || b.dayKey != dayKey || totalMm + 0.001f < b.baseMm) {
        b.dayKey = dayKey;
        b.baseMm = totalMm;
        b.valid = true;
        persistDailyBaseline(oregon, b); // at most daily, plus genuine counter reset
        return 0.0f;
    }
    return max(0.0f, totalMm - b.baseMm);
}

bool oregonThermoFresh(const StationState &s, uint32_t now) {
    return s.thermoValid && sensorFresh(s.thermoUpdatedMs, now) && finiteValue(s.temperatureC) && finiteValue(s.humidityPct);
}
// WS23xx publishes sensor types in separate messages. Its own configured
// freshness window is 300s, not Oregon's 180s generic window.
bool lcFresh(uint32_t stamp, uint32_t now) {
    return stamp != 0U && static_cast<uint32_t>(now - stamp) <= LACROSSE_SENSOR_STALE_MS;
}
bool lcThermoFresh(const StationState &s, uint32_t now) {
    return s.lacrosse.temperatureValid && s.lacrosse.humidityValid &&
           lcFresh(s.lacrosse.temperatureUpdatedMs, now) && lcFresh(s.lacrosse.humidityUpdatedMs, now) &&
           finiteValue(s.lacrosse.temperatureC) && finiteValue(s.lacrosse.humidityPct);
}
bool oregonWindFresh(const StationState &s, uint32_t now) {
    return s.windValid && sensorFresh(s.windUpdatedMs, now) && finiteValue(s.windAverageKmh);
}
bool lcWindFresh(const StationState &s, uint32_t now) {
    return s.lacrosse.windValid && lcFresh(s.lacrosse.windUpdatedMs, now) && finiteValue(s.lacrosse.windKmh);
}
bool oregonRainFresh(const StationState &s, uint32_t now) {
    return s.rainValid && sensorFresh(s.rainUpdatedMs, now) && finiteValue(s.rainTotalMm);
}
bool lcRainFresh(const StationState &s, uint32_t now) {
    return s.lacrosse.rainValid && lcFresh(s.lacrosse.rainUpdatedMs, now) && finiteValue(s.lacrosse.rainTotalMm);
}

LiveSelection selectLive(const StationState &s, const MbCompatibleConfig &cfg, uint32_t now, uint32_t dayKey) {
    LiveSelection v;
    const bool useTechnoline = cfg.sourcePriority == 1U;

    if (!useTechnoline) {
        // Oregon source: no Technoline fallback is allowed.
        if (oregonThermoFresh(s, now)) {
            v.tempC = s.temperatureC;
            v.humPct = s.humidityPct;
            v.tempFromOregon = true;
            if (s.dewPointValid) v.dewC = s.dewPointC;
            if (s.heatIndexValid) v.heatIndexC = s.heatIndexC;
        }
        if (oregonWindFresh(s, now)) {
            v.windKmh = s.windAverageKmh;
            if (finiteValue(s.windGustKmh)) v.gustKmh = s.windGustKmh;
            if (finiteValue(s.windDirectionDeg)) v.dirDeg = s.windDirectionDeg;
            if (s.windChillValid) v.windChillC = s.windChillC;
            v.windFromOregon = true;
        }
        if (oregonRainFresh(s, now)) {
            v.rainTotalMm = s.rainTotalMm;
            if (finiteValue(s.rainRateMmH)) v.rainRateMmH = s.rainRateMmH;
            if (s.rainLastHourValid) v.rain1hMm = s.rainLastHourMm;
            if (s.rainLast24hValid) v.rain24hMm = s.rainLast24hMm;
            v.rainTodayMm = dailyRain(true, dayKey, s.rainTotalMm);
            v.rainFromOregon = true;
        }
        if (s.uvValid && sensorFresh(s.uvUpdatedMs, now) && s.uvIndex >= 0)
            v.uv = static_cast<float>(s.uvIndex);
    } else {
        // Technoline source: no Oregon fallback is allowed.
        if (lcThermoFresh(s, now)) {
            v.tempC = s.lacrosse.temperatureC;
            v.humPct = s.lacrosse.humidityPct;
            v.dewC = dewPoint(v.tempC, v.humPct);
        }
        if (lcWindFresh(s, now)) {
            v.windKmh = s.lacrosse.windKmh;
            if (s.lacrosse.gustValid && sensorFresh(s.lacrosse.gustUpdatedMs, now))
                v.gustKmh = s.lacrosse.gustKmh;
            if (s.lacrosse.directionValid) v.dirDeg = s.lacrosse.windDirectionDeg;
        }
        if (lcRainFresh(s, now)) {
            v.rainTotalMm = s.lacrosse.rainTotalMm;
            if (s.lacrosse.rainRate5mValid) v.rainRateMmH = s.lacrosse.rainRate5mMmH;
            if (s.lacrosse.rainLastHourValid) v.rain1hMm = s.lacrosse.rainLastHourMm;
            if (s.lacrosse.rainLast24hValid) v.rain24hMm = s.lacrosse.rainLast24hMm;
            v.rainTodayMm = dailyRain(false, dayKey, s.lacrosse.rainTotalMm);
        }
        // UV belongs to the Oregon station and must remain unavailable here.
    }

    // BME280 is local gateway hardware, not a fallback weather station.
    if (s.pressureValid && sensorFresh(s.pressureUpdatedMs, now)) {
        if (finiteValue(s.pressureSeaLevelHpa)) v.pressureHpa = s.pressureSeaLevelHpa;
        if (s.pressureTrendValid && finiteValue(v.pressureHpa) && finiteValue(s.pressureTrendHpa3h))
            v.pressure3hAgoHpa = v.pressureHpa - s.pressureTrendHpa3h;
        if (s.indoorTemperatureValid) v.indoorTempC = s.indoorTemperatureC;
        if (s.indoorHumidityValid) v.indoorHumPct = s.indoorHumidityPct;
    }
    return v;
}

String floatField(float value, uint8_t decimals) {
    return finiteValue(value) ? String(value, static_cast<unsigned int>(decimals)) : String("--");
}

String fieldValue(size_t index, const LiveSelection &v, const tm &utc, uint32_t uptimeSec) {
    char buf[24]{};
    switch (index) {
        case 0: snprintf(buf, sizeof(buf), "%02d/%02d/%04d", utc.tm_mday, utc.tm_mon + 1, utc.tm_year + 1900); return String(buf);
        case 1: snprintf(buf, sizeof(buf), "%02d:%02d:%02d", utc.tm_hour, utc.tm_min, utc.tm_sec); return String(buf);
        case 2: return floatField(v.tempC, 1);
        case 3: return floatField(v.humPct, 0);
        case 4: return floatField(v.dewC, 1);
        case 5: return floatField(finiteValue(v.windKmh) ? v.windKmh / 3.6f : NAN, 2);
        case 6: return floatField(finiteValue(v.gustKmh) ? v.gustKmh / 3.6f : NAN, 2);
        case 7: return floatField(v.dirDeg, 0);
        case 8: return floatField(v.rainRateMmH, 2);
        case 9: return floatField(v.rainTodayMm, 2);
        case 10: return floatField(v.pressureHpa, 1);
        case 11: return floatField(v.dirDeg, 0); // best available direction, compatible fallback for avg-5m slot
        case 12: return finiteValue(v.windKmh) ? String(beaufortFromKmh(v.windKmh)) : String("--");
        case 15: return String("hPa");
        case 16: return String("mm");
        case 18: return floatField(v.pressure3hAgoHpa, 1);
        case 22: return floatField(v.indoorTempC, 1);
        case 23: return floatField(v.indoorHumPct, 0);
        case 24: return floatField(v.windChillC, 1);
        case 25: return String("ESP32-Oregon-Technoline");
        case 38: return String(FIRMWARE_VERSION);
        case 42: return floatField(v.heatIndexC, 1);
        case 43: return floatField(v.uv, 1);
        case 44: return floatField(v.rain24hMm, 2);
        case 46: return floatField(v.dirDeg, 0);
        case 47: return floatField(v.rain1hMm, 2);
        case 81: return String(uptimeSec);
        case 151: return floatField(v.rainTotalMm, 2);
        default: return String("--");
    }
}

bool buildPayload(const StationState &snapshot, const MbCompatibleConfig &cfg, String &payload, String &error) {
    const time_t nowEpoch = time(nullptr);
    if (nowEpoch < MIN_VALID_EPOCH) {
        error = "time not synchronized";
        return false;
    }
    tm utc{};
    if (!gmtime_r(&nowEpoch, &utc)) {
        error = "UTC conversion failed";
        return false;
    }
    const uint32_t dayKey = utcDayKey(utc);
    const LiveSelection live = selectLive(snapshot, cfg, millis(), dayKey);
    // MB_MEASUREMENT_DIAGNOSTICS_V1
    const uint8_t realValues =
        static_cast<uint8_t>(finiteValue(live.tempC)) +
        static_cast<uint8_t>(finiteValue(live.humPct)) +
        static_cast<uint8_t>(finiteValue(live.windKmh)) +
        static_cast<uint8_t>(finiteValue(live.gustKmh)) +
        static_cast<uint8_t>(finiteValue(live.dirDeg)) +
        static_cast<uint8_t>(finiteValue(live.rainRateMmH)) +
        static_cast<uint8_t>(finiteValue(live.rainTodayMm)) +
        static_cast<uint8_t>(finiteValue(live.rainTotalMm)) +
        static_cast<uint8_t>(finiteValue(live.pressureHpa)) +
        static_cast<uint8_t>(finiteValue(live.indoorTempC)) +
        static_cast<uint8_t>(finiteValue(live.indoorHumPct)) +
        static_cast<uint8_t>(finiteValue(live.uv));
    gLastWeatherValues = realValues;
    if (realValues == 0U) {
        error = cfg.sourcePriority == 1U
            ? "no fresh meteorological measurements (TECHNOLINE + local BME280)"
            : "no fresh meteorological measurements (OREGON + local BME280)";
        payload = "";
        return false;  // Do not send empty frames or initiate unnecessary TLS.
    }

    payload = "";
    payload.reserve(1050);
    for (size_t i = 0; i < MB_FIELD_COUNT; ++i) {
        if (i) payload += ' ';
        payload += fieldValue(i, live, utc, millis() / 1000UL);
    }
    return true;
}

bool beginPrefs(Preferences &p, bool readOnly) { return p.begin(NVS_NS, readOnly); }

void loadConfig() {
    Preferences p;
    if (!beginPrefs(p, true)) return;
    gConfig.enabled = p.getBool("enabled", false);
    gConfig.url = p.getString("url", "");
    gConfig.intervalSec = p.getUShort("interval", DEFAULT_INTERVAL_SEC);
    gConfig.timeoutMs = p.getUShort("timeout", DEFAULT_TIMEOUT_MS);
    gConfig.tlsMode = static_cast<MbCompatibleTlsMode>(p.getUChar("tls", 0U));
    gConfig.caCertificate = p.getString("ca", "");
    gConfig.sourcePriority = p.getUChar("priority", 0U);
    p.end();
    if (!validateMbCompatibleConfig(gConfig, true)) {
        gConfig = MbCompatibleConfig{};
        gConfig.intervalSec = DEFAULT_INTERVAL_SEC;
        gConfig.timeoutMs = DEFAULT_TIMEOUT_MS;
    }
}

bool persistConfig(const MbCompatibleConfig &cfg) {
    Preferences p;
    if (!beginPrefs(p, false)) return false;
    bool ok = true;
    ok = p.putBool("enabled", cfg.enabled) > 0 && ok;
    ok = p.putString("url", cfg.url) == cfg.url.length() && ok;
    ok = p.putUShort("interval", cfg.intervalSec) > 0 && ok;
    ok = p.putUShort("timeout", cfg.timeoutMs) > 0 && ok;
    ok = p.putUChar("tls", static_cast<uint8_t>(cfg.tlsMode)) > 0 && ok;
    ok = p.putString("ca", cfg.caCertificate) == cfg.caCertificate.length() && ok;
    ok = p.putUChar("priority", cfg.sourcePriority) > 0 && ok;
    p.end();
    if (!ok) return false;

    MbCompatibleConfig readback;
    if (!beginPrefs(p, true)) return false;
    readback.enabled = p.getBool("enabled", !cfg.enabled);
    readback.url = p.getString("url", "__invalid__");
    readback.intervalSec = p.getUShort("interval", 0U);
    readback.timeoutMs = p.getUShort("timeout", 0U);
    readback.tlsMode = static_cast<MbCompatibleTlsMode>(p.getUChar("tls", 255U));
    readback.caCertificate = p.getString("ca", "__invalid__");
    readback.sourcePriority = p.getUChar("priority", 255U);
    p.end();
    return readback.enabled == cfg.enabled && readback.url == cfg.url &&
           readback.intervalSec == cfg.intervalSec && readback.timeoutMs == cfg.timeoutMs &&
           readback.tlsMode == cfg.tlsMode && readback.caCertificate == cfg.caCertificate &&
           readback.sourcePriority == cfg.sourcePriority;
}

void setStatusError(const String &error) {
    if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        gLastError = error;
        xSemaphoreGive(gMutex);
    } else {
        gLastError = error;
    }
}

void performHttp(const String &url, const String &payload, const MbCompatibleConfig &cfg) {
    // MB_PUBLIC_TLS_V2
    gBusy = true;
    gLastAttemptMs = millis();
    int httpCode = 0;
    String response;
    String error;
    HTTPClient http;

    // Match the proven Davis transport envelope. A saved shorter timeout is
    // still accepted by UI/NVS, but HTTPS gets enough time for DNS + TLS.
    const uint32_t connectTimeoutMs = cfg.timeoutMs < 5000U ? 5000U : cfg.timeoutMs;
    const uint32_t requestTimeoutMs = cfg.timeoutMs < 7000U ? 7000U : cfg.timeoutMs;
    http.setConnectTimeout(connectTimeoutMs);
    http.setTimeout(requestTimeoutMs);
    http.setReuse(false);

    const String requestUrl = buildRequestUrl(url, urlEncode(payload));
    bool begun = false;

    if (requestUrl.startsWith("https://")) {
        // MB_TLS_MEMORY_ARBITRATION_V1
        constexpr uint32_t MB_TLS_HEAP_PAUSE_THRESHOLD = 32768U;
        const uint32_t blockInitial = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
        const bool remotePaused = blockInitial < MB_TLS_HEAP_PAUSE_THRESHOLD &&
                                  remoteAccessPauseForExternalTls(2000U);
        // LILYGO_STABILITY_TLS_GUARD_V1: prefer an omitted report to MCU reset.
        if(blockInitial < MB_TLS_HEAP_PAUSE_THRESHOLD && !remotePaused){
            setStatusError("HTTPS deferred: insufficient contiguous heap for a second TLS session");
            gBusy=false;
            return;
        }
        const uint32_t heapBefore = ESP.getFreeHeap();
        const uint32_t blockBefore = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
        WiFiClientSecure client;
        if (cfg.tlsMode == MbCompatibleTlsMode::Insecure) {
            client.setInsecure();
        } else if (cfg.tlsMode == MbCompatibleTlsMode::CustomCa) {
            if (cfg.caCertificate.length() == 0U) {
                error = "custom CA required for selected HTTPS mode";
            } else {
                client.setCACert(cfg.caCertificate.c_str());
            }
        } else {
            // Normal Internet HTTPS: reuse the public ISRG X1/X2 bundle already
            // used by AdminSensor Remote. No PEM copy from NVS is required.
            client.setCACert(REMOTE_TRUST_CA);
        }

        if (error.length() == 0U) {
            client.setTimeout((requestTimeoutMs + 999U) / 1000U);
            client.setHandshakeTimeout((requestTimeoutMs + 999U) / 1000U);
            begun = http.begin(client, requestUrl);
            if (begun) {
                httpCode = http.GET();
                if (httpCode > 0) {
                    response = http.getString();
                } else {
                    // HTTPClient collapses all client.connect() failures to -1.
                    // Preserve the underlying mbedTLS error before destroying the
                    // secure client, then distinguish transport from TLS/heap by
                    // probing the same host with a plain TCP socket.
                    char sslText[112] = {0};
                    const int sslCode = client.lastError(sslText, sizeof(sslText));

                    String authority = requestUrl.substring(8);
                    const int slash = authority.indexOf('/');
                    if (slash >= 0) authority.remove(slash);
                    String host = authority;
                    uint16_t port = 443U;
                    const int colon = authority.lastIndexOf(':');
                    if (colon > 0) {
                        const long parsedPort = authority.substring(colon + 1).toInt();
                        if (parsedPort > 0 && parsedPort <= 65535) port = static_cast<uint16_t>(parsedPort);
                        host = authority.substring(0, colon);
                    }
                    IPAddress resolved;
                    const bool dnsOk = WiFi.hostByName(host.c_str(), resolved);
                    bool tcpOk = false;
                    if (dnsOk) {
                        WiFiClient probe;
                        probe.setTimeout(2);
                        tcpOk = probe.connect(resolved, port, 2000) == 1;
                        probe.stop();
                    }

                    char diag[384];
                    snprintf(diag, sizeof(diag),
                             "HTTPS fail http=%d ssl=%d %s dns=%s tcp=%s ip=%s heap=%lu block=%lu preblock=%lu remote_pause=%s",
                             httpCode, sslCode, sslText[0] ? sslText : "n/a",
                             dnsOk ? "ok" : "fail", tcpOk ? "ok" : "fail",
                             dnsOk ? resolved.toString().c_str() : "--",
                             static_cast<unsigned long>(heapBefore),
                             static_cast<unsigned long>(blockBefore),
                             static_cast<unsigned long>(blockInitial),
                             remotePaused ? "yes" : "no");
                    error = diag;
                }
                http.end();
            } else {
                error = "HTTPS begin failed";
            }
            client.stop();
        }
        if (remotePaused) remoteAccessResumeAfterExternalTls();
    } else {
        WiFiClient client;
        client.setTimeout((requestTimeoutMs + 999U) / 1000U);
        begun = http.begin(client, requestUrl);
        if (begun) {
            httpCode = http.GET();
            if (httpCode > 0) response = http.getString();
            else error = String("HTTP transport error ") + http.errorToString(httpCode);
            http.end();
        } else {
            error = "HTTP begin failed";
        }
        client.stop();
    }

    response.trim();
    const bool success = httpCode >= 200 && httpCode < 300 && response.equalsIgnoreCase("success");
    if (!success && error.length() == 0U) {
        error = String("endpoint response ") + httpCode + " / " + (response.length() ? response : String("empty"));
    }

    if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        gLastHttpCode = httpCode;
        gLastResponse = response.substring(0, 96);
        gLastError = success ? String("") : error.substring(0, 300);
        if (success) gLastSuccessMs = millis();
        xSemaphoreGive(gMutex);
    }
    Serial.print(F("[MB-COMPAT] HTTP "));
    Serial.print(httpCode);
    Serial.print(F(" result="));
    Serial.println(success ? F("success") : error);
    gBusy = false;
}

void worker(void *) {
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        String url, payload;
        MbCompatibleConfig cfg;
        if (gMutex && xSemaphoreTake(gMutex, portMAX_DELAY) == pdTRUE) {
            url = gPendingUrl;
            payload = gPendingPayload;
            cfg = gConfig;
            gPendingUrl = "";
            gPendingPayload = "";
            gPending = false;
            xSemaphoreGive(gMutex);
        }
        if (url.length() && payload.length()) performHttp(url, payload, cfg);
    }
}
// LILYGO_STABILITY_MB_TASK_FACTORY_V1
bool ensureMbWorker(){
    if(gWorkerTask)return true;
    // The original worker uses core 0 on the T3 ESP32 and T3-S3 targets.
    const BaseType_t core=0;
    if(xTaskCreatePinnedToCore(worker,"mb-compatible",WORKER_STACK,nullptr,1,
                               &gWorkerTask,core)!=pdPASS){
        gWorkerTask=nullptr;
        setStatusError("worker task creation failed - insufficient heap");
        return false;
    }
    return true;
}
} // namespace

const char *mbCompatibleTlsModeName(MbCompatibleTlsMode mode) {
    if (mode == MbCompatibleTlsMode::Insecure) return "INSECURE";
    if (mode == MbCompatibleTlsMode::CustomCa) return "CUSTOM_CA";
    return "PUBLIC_CA";
}

bool validateMbCompatibleConfig(const MbCompatibleConfig &cfg, bool replaceCaCertificate) {
    (void)replaceCaCertificate;
    if (cfg.url.length() > 0U && !validUrl(cfg.url)) return false;
    if (cfg.enabled && !validUrl(cfg.url)) return false;
    if (cfg.intervalSec < MIN_INTERVAL_SEC || cfg.intervalSec > MAX_INTERVAL_SEC) return false;
    if (cfg.timeoutMs < MIN_TIMEOUT_MS || cfg.timeoutMs > MAX_TIMEOUT_MS) return false;
    if (static_cast<uint8_t>(cfg.tlsMode) > static_cast<uint8_t>(MbCompatibleTlsMode::CustomCa)) return false;
    if (cfg.caCertificate.length() > MAX_CA_LEN) return false;
    if (cfg.tlsMode == MbCompatibleTlsMode::CustomCa && cfg.caCertificate.length() == 0U) return false;
    if (cfg.sourcePriority > 1U) return false;
    return true;
}

MbCompatibleConfig getMbCompatibleConfig() {
    MbCompatibleConfig copy;
    if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        copy = gConfig;
        xSemaphoreGive(gMutex);
    } else copy = gConfig;
    return copy;
}

bool saveMbCompatibleConfig(const MbCompatibleConfig &cfg, bool replaceCaCertificate) {
    MbCompatibleConfig next = getMbCompatibleConfig();
    next.enabled = cfg.enabled;
    next.url = cfg.url;
    next.intervalSec = cfg.intervalSec;
    next.timeoutMs = cfg.timeoutMs;
    next.tlsMode = cfg.tlsMode;
    next.sourcePriority = cfg.sourcePriority;
    if (replaceCaCertificate) next.caCertificate = cfg.caCertificate;
    if (!validateMbCompatibleConfig(next, true) || !persistConfig(next)) return false;
    if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        gConfig = next;
        gLastScheduleMs = 0;
        xSemaphoreGive(gMutex);
    } else gConfig = next;
    return true;
}

bool resetMbCompatibleConfig() {
    MbCompatibleConfig defaults;
    defaults.intervalSec = DEFAULT_INTERVAL_SEC;
    defaults.timeoutMs = DEFAULT_TIMEOUT_MS;
    if (!persistConfig(defaults)) return false;
    if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        gConfig = defaults;
        gLastScheduleMs = 0;
        xSemaphoreGive(gMutex);
    } else gConfig = defaults;
    return true;
}

void requestMbCompatibleTest() { gForceTest = true; }

void initMbCompatiblePublisher(StationState &state) {
    gState = &state;
    gMutex = xSemaphoreCreateMutex();
    loadConfig();
    loadDailyBaselines();
    configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");
// LILYGO_STABILITY_MB_LAZY_V1: reserve stack only if publisher enabled.
    if(gConfig.enabled)ensureMbWorker();
    Serial.println(F("[MB-COMPAT] publisher initialized"));
}

void serviceMbCompatiblePublisher() {
    if (!gState || !wifiConnected() || gBusy || gPending) return;
    const MbCompatibleConfig cfg = getMbCompatibleConfig();
    if(!gWorkerTask && (cfg.enabled || gForceTest)){
        // Throttle allocation retries if memory is extremely low.
        static uint32_t nextWorkerRetryMs=0;
        const uint32_t current=millis();
        if(!nextWorkerRetryMs || (int32_t)(current-nextWorkerRetryMs)>=0){
            nextWorkerRetryMs=current+30000UL;
            ensureMbWorker();
        }
    }
    if(!gWorkerTask)return;
    const bool force = gForceTest;
    if (!force && !cfg.enabled) return;
    const uint32_t now = millis();
    if (!force && gLastScheduleMs != 0U && static_cast<uint32_t>(now - gLastScheduleMs) < static_cast<uint32_t>(cfg.intervalSec) * 1000UL) return;
    if (!validUrl(cfg.url)) {
        setStatusError("endpoint URL missing or invalid");
        gForceTest = false;
        return;
    }

    const StationState snapshot = *gState;
    String payload, error;
    if (!buildPayload(snapshot, cfg, payload, error)) {
        setStatusError(error);
        if (error.startsWith("no fresh meteorological measurements")) {
            // No network attempt occurred: throttle until the next interval.
            gLastScheduleMs = now;
            gForceTest = false;
            if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
                gLastPayloadBytes = 0;
                gLastFieldCount = 0;
                gLastHttpCode = 0;
                gLastResponse = "";
                xSemaphoreGive(gMutex);
            }
        }
        return; // time-sync retries may continue; empty RF reports are throttled
    }

    if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        gPendingUrl = cfg.url;
        gPendingPayload = payload;
        gLastPayloadBytes = payload.length();
        gLastFieldCount = MB_FIELD_COUNT;
        gPending = true;
        gLastScheduleMs = now;
        gForceTest = false;
        xSemaphoreGive(gMutex);
        xTaskNotifyGive(gWorkerTask);
    }
}

void prepareMbCompatibleForDeepSleep() {
    // No new sends are queued after this flag; an in-flight HTTP transaction has
    // a bounded timeout and does not own RF/SD state.
    if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        gConfig.enabled = false;
        gPending = false;
        gPendingPayload = "";
        gPendingUrl = "";
        xSemaphoreGive(gMutex);
    }
}

String mbCompatibleConfigStatusJson() {
    const MbCompatibleConfig cfg = getMbCompatibleConfig();
    int httpCode;
    String response, error;
    uint32_t attemptMs, successMs;
    size_t payloadBytes, fieldCount;
    if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        httpCode = gLastHttpCode;
        response = gLastResponse;
        error = gLastError;
        attemptMs = gLastAttemptMs;
        successMs = gLastSuccessMs;
        payloadBytes = gLastPayloadBytes;
        fieldCount = gLastFieldCount;
        xSemaphoreGive(gMutex);
    } else {
        httpCode = gLastHttpCode; response = gLastResponse; error = gLastError;
        attemptMs = gLastAttemptMs; successMs = gLastSuccessMs;
        payloadBytes = gLastPayloadBytes; fieldCount = gLastFieldCount;
    }
    const uint32_t now = millis();
    const bool timeSynced = time(nullptr) >= MIN_VALID_EPOCH;
    String out;
    out.reserve(900);
    out = "{\"enabled\":"; out += cfg.enabled ? "true" : "false";
    out += ",\"url\":\"" + jsonEscape(cfg.url) + "\"";
    out += ",\"interval_sec\":" + String(cfg.intervalSec);
    out += ",\"timeout_ms\":" + String(cfg.timeoutMs);
    out += ",\"tls_mode\":" + String(static_cast<uint8_t>(cfg.tlsMode));
    out += ",\"tls_name\":\"" + String(mbCompatibleTlsModeName(cfg.tlsMode)) + "\"";
    out += ",\"ca_set\":"; out += cfg.caCertificate.length() ? "true" : "false";
    out += ",\"source_priority\":" + String(cfg.sourcePriority);
    out += ",\"source_station\":\"" + String(cfg.sourcePriority == 1U ? "TECHNOLINE" : "OREGON") + "\"";
    out += ",\"busy\":"; out += gBusy ? "true" : "false";
    out += ",\"pending\":"; out += gPending ? "true" : "false";
    out += ",\"time_synced\":"; out += timeSynced ? "true" : "false";
    out += ",\"last_http_code\":" + String(httpCode);
    out += ",\"last_response\":\"" + jsonEscape(response) + "\"";
    out += ",\"last_error\":\"" + jsonEscape(error) + "\"";
    out += ",\"last_attempt_age_s\":" + String(attemptMs ? static_cast<uint32_t>(now - attemptMs) / 1000UL : 0xFFFFFFFFUL);
    out += ",\"last_success_age_s\":" + String(successMs ? static_cast<uint32_t>(now - successMs) / 1000UL : 0xFFFFFFFFUL);
    out += ",\"payload_bytes\":" + String(payloadBytes);
    out += ",\"payload_fields\":" + String(fieldCount);
    out += ",\"weather_measurements\":" + String(gLastWeatherValues);
    out += ",\"worker_stack_hwm\":" + String(gWorkerTask ? uxTaskGetStackHighWaterMark(gWorkerTask) : 0U);
    out += ",\"heap_largest\":" + String(heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
    out += "}";
    return out;
}
