#include "web_manager.h"
#include <Arduino.h>
#include <WebServer.h>
#include <WiFi.h>
#include <math.h>
#include <ctype.h>
#include "config.h"
#include "board_config.h"
#include "network_manager.h"
#include "barometer_manager.h"
#include "weather_parser.h"
#include "oregon_receiver.h"
#include "lacrosse_ws23xx.h"
#include "mqtt_publisher.h"
#include "display_manager.h"
#include "firmware_info.h"
#include "power_manager.h"
#include "lightning_manager.h"
#include "thermo_channel_manager.h"
#include "web_ui_generated.h"

namespace {
WebServer server(80);
StationState *station = nullptr;
bool webStarted = false;
uint32_t rebootAtMs = 0;
uint32_t powerOffAtMs = 0;
String jsonEscapeString(const String &in);

constexpr uint8_t RAW_HISTORY_SIZE = 32;
struct RawEntry {
    uint32_t ms{0};
    float rssi{NAN};
    uint8_t len{0};
    uint8_t sensorId{0};
    uint16_t sensorCode{0};
    uint8_t source{0};
    char protocol[12]{};
    char sourceName[16]{};
    bool accepted{false};
    bool batteryKnown{false};
    bool batteryLow{false};
    char type[16]{};
    char decoded[128]{};
    char hex[OREGON_MAX_PACKET_BYTES * 3]{};
};
RawEntry history[RAW_HISTORY_SIZE];
uint8_t historyHead = 0;
uint8_t historyCount = 0;


// V6.3: sessione di acquisizione. In DUAL entrambi i protocolli restano attivi.
// I valori meteo restano memorizzati, ma al cambio modalita' la UI considera
// "acquisito" solo cio' che e' stato ricevuto dopo l'attivazione corrente.
constexpr uint8_t OREGON_SESSION_SENSOR_MAX = 10;
struct OregonSessionSensor {
    SensorType type{SensorType::Unknown};
    uint16_t code{0};
    uint8_t channel{0};
    uint8_t rollingCode{0};
    uint8_t protocolVersion{0};
    uint8_t cadenceSamples{0};
    uint32_t firstMs{0};
    uint32_t lastMs{0};
    uint32_t received{0};
    uint32_t observedCadenceMs{0};
    float lastRssi{NAN};
};

struct RfSessionState {
    bool initialized{false};
    RfProtocolMode mode{RfProtocolMode::Oregon};
    uint32_t startedMs{0};
    uint32_t baseLcTemp{0};
    uint32_t baseLcHum{0};
    uint32_t baseLcRain{0};
    uint32_t baseLcWind{0};
    uint32_t baseLcGust{0};
    uint32_t baseLcValid{0};
    uint32_t lcFirstValidMs{0};
    OregonSessionSensor oregon[OREGON_SESSION_SENSOR_MAX]{};
    uint8_t oregonOverflow{0};
};
RfSessionState rfSession{};

bool timestampInSession(uint32_t updatedMs, uint32_t startMs) {
    if (updatedMs == 0 || startMs == 0) return false;
    return static_cast<int32_t>(updatedMs - startMs) >= 0;
}

uint32_t expectedPacketsSinceFirst(uint32_t nowMs, uint32_t firstMs, uint32_t cadenceMs) {
    if (firstMs == 0 || cadenceMs == 0) return 0;
    return 1UL + static_cast<uint32_t>(nowMs - firstMs) / cadenceMs;
}

uint32_t nominalOregonCadenceMs(SensorType type, uint16_t code, uint8_t channel) {
    switch (type) {
        case SensorType::ThermoHygro:
            if (code == 0xF824U || code == 0xF8B4U) return 53000UL;
            if (code == 0x1D20U || code == 0xEC40U) {
                if (channel == 2U) return 41000UL;
                if (channel == 3U) return 43000UL;
                return 39000UL;
            }
            return 0UL;
        case SensorType::Wind:
            return (code == 0x1984U || code == 0x1994U || code == 0x3D00U) ? 14000UL : 0UL;
        case SensorType::Rain:
            return code == 0x2914U ? 47000UL : 0UL;
        case SensorType::UV:
            return (code == 0xD874U || code == 0xEC70U) ? 73000UL : 0UL;
        default:
            return 0UL;
    }
}

uint32_t effectiveOregonCadenceMs(const OregonSessionSensor &sensor) {
    const uint32_t nominal = nominalOregonCadenceMs(sensor.type, sensor.code, sensor.channel);
    if (nominal != 0) return nominal;
    return sensor.cadenceSamples >= 3U ? sensor.observedCadenceMs : 0UL;
}

void noteOregonSessionSensor(const WeatherReading &reading, uint8_t decodeSource) {
    OregonSessionSensor *freeSlot = nullptr;
    OregonSessionSensor *sensor = nullptr;
    for (uint8_t i = 0; i < OREGON_SESSION_SENSOR_MAX; ++i) {
        OregonSessionSensor &candidate = rfSession.oregon[i];
        if (candidate.received == 0) {
            if (!freeSlot) freeSlot = &candidate;
            continue;
        }
        if (candidate.type == reading.type && candidate.code == reading.sensorCode &&
            candidate.channel == reading.channel && candidate.rollingCode == reading.rollingCode) {
            sensor = &candidate;
            break;
        }
    }
    if (!sensor) sensor = freeSlot;
    if (!sensor) {
        if (rfSession.oregonOverflow < 255U) rfSession.oregonOverflow++;
        return;
    }
    if (sensor->received == 0) {
        sensor->type = reading.type;
        sensor->code = reading.sensorCode;
        sensor->channel = reading.channel;
        sensor->rollingCode = reading.rollingCode;
        sensor->protocolVersion = decodeSource == static_cast<uint8_t>(OregonDecodeSource::EdgeTimingV21) ? 2U : 3U;
        sensor->firstMs = reading.receivedAtMs;
    } else {
        const uint32_t interval = static_cast<uint32_t>(reading.receivedAtMs - sensor->lastMs);
        if (interval >= 5000UL && interval <= 180000UL &&
            nominalOregonCadenceMs(sensor->type, sensor->code, sensor->channel) == 0) {
            if (sensor->cadenceSamples == 0 || interval < sensor->observedCadenceMs)
                sensor->observedCadenceMs = interval;
            if (sensor->cadenceSamples < 255U) sensor->cadenceSamples++;
        }
    }
    sensor->lastMs = reading.receivedAtMs;
    sensor->lastRssi = reading.rssi;
    sensor->received++;
}

int qualityPct(uint32_t received, uint32_t expected) {
    if (expected == 0) return -1;
    const uint32_t pct = (received * 100UL) / expected;
    return static_cast<int>(pct > 100UL ? 100UL : pct);
}

void resetRfSession(bool clearRawHistory = false) {
    if (!station) return;
    rfSession.initialized = true;
    rfSession.mode = getRfProtocolMode();
    rfSession.startedMs = millis();
    rfSession.baseLcTemp = station->lacrosse.temperaturePacketCount;
    rfSession.baseLcHum = station->lacrosse.humidityPacketCount;
    rfSession.baseLcRain = station->lacrosse.rainPacketCount;
    rfSession.baseLcWind = station->lacrosse.windPacketCount;
    rfSession.baseLcGust = station->lacrosse.gustPacketCount;
    rfSession.baseLcValid = station->lacrosse.validPacketCount;
    rfSession.lcFirstValidMs = 0;
    for (uint8_t i = 0; i < OREGON_SESSION_SENSOR_MAX; ++i)
        rfSession.oregon[i] = OregonSessionSensor{};
    rfSession.oregonOverflow = 0;
    if (clearRawHistory) {
        historyHead = 0;
        historyCount = 0;
    }
}

void ensureRfSession() {
    const RfProtocolMode mode = getRfProtocolMode();
    if (!rfSession.initialized || rfSession.mode != mode) resetRfSession(false);
}

String jsonFloat(float v, uint8_t decimals = 1) {
    if (!isfinite(v)) return "null";
    return String(v, static_cast<unsigned int>(decimals));
}

uint32_t ageSeconds(uint32_t updatedMs, uint32_t now) {
    if (updatedMs == 0) return 0xFFFFFFFFUL;
    return static_cast<uint32_t>(now - updatedMs) / 1000UL;
}

void sendNoCache() {
    server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    server.sendHeader("Pragma", "no-cache");
}

String hex4(uint16_t value) {
    char b[5];
    snprintf(b, sizeof(b), "%04X", value);
    return String(b);
}

void appendSensorJson(String &out, const char *name, const OregonSensorStatus &sensor, bool comma) {
    if (comma) out += ",";
    out += "\"" + String(name) + "\":{";
    out += "\"code\":\"" + hex4(sensor.code) + "\"";
    out += ",\"model\":\"" + String(sensorModelName(sensor.code)) + "\"";
    out += ",\"channel\":" + String(sensor.channel);
    out += ",\"rolling_code\":" + String(sensor.rollingCode);
    out += ",\"flags\":" + String(sensor.flags);
    out += ",\"battery_known\":"; out += sensor.batteryKnown ? "true" : "false";
    out += ",\"battery_low\":"; out += sensor.batteryLow ? "true" : "false";
    out += ",\"battery\":\"" + String(sensorBatteryName(sensor)) + "\"";
    out += "}";
}

void handleState() {
    if (!station) {
        server.send(503, "application/json", "{\"error\":\"state unavailable\"}");
        return;
    }

    const OregonRxStats rx = getOregonRxStats();
    const LaCrosseRxStats lcRx = getLaCrosseRxStats();
    const RfBurstAnalyzerStats burst = getRfBurstAnalyzerStats();
    const WgrProbeStats wgrProbe = getWgrProbeStats();
    const uint32_t now = millis();
    ensureRfSession();
    const uint32_t sessionElapsedMs = static_cast<uint32_t>(now - rfSession.startedMs);
    const RfProtocolMode activeMode = getRfProtocolMode();
    const bool oregonActive = activeMode != RfProtocolMode::LaCrosse;
    const bool technolineActive = activeMode != RfProtocolMode::Oregon;

    uint32_t sessionThermo = 0, sessionWind = 0, sessionRain = 0, sessionUv = 0;
    const auto &lcState = station->lacrosse;
    const uint32_t sessionLcTemp = lcState.temperaturePacketCount - rfSession.baseLcTemp;
    const uint32_t sessionLcHum = lcState.humidityPacketCount - rfSession.baseLcHum;
    const uint32_t sessionLcRain = lcState.rainPacketCount - rfSession.baseLcRain;
    const uint32_t sessionLcWind = lcState.windPacketCount - rfSession.baseLcWind;
    const uint32_t sessionLcGust = lcState.gustPacketCount - rfSession.baseLcGust;
    const uint32_t sessionLcValid = lcState.validPacketCount - rfSession.baseLcValid;

    // Aggregati mantenuti per compatibilita' API. La UI usa invece una riga per
    // trasmettitore (codice + canale + rolling code), evitando che sensori
    // OSV2.1 e OSV3 falsino reciprocamente ricevuti e attesi.
    uint32_t expThermo = 0, expWind = 0, expRain = 0, expUv = 0;
    uint8_t thermoSeenCount = 0;
    bool thermoQualityAvailable = true, windQualityAvailable = true;
    bool rainQualityAvailable = true, uvQualityAvailable = true;
    bool windSeen = false, rainSeen = false, uvSeen = false;
    for (uint8_t i = 0; i < OREGON_SESSION_SENSOR_MAX; ++i) {
        const OregonSessionSensor &sensor = rfSession.oregon[i];
        if (sensor.received == 0) continue;
        const uint32_t cadence = effectiveOregonCadenceMs(sensor);
        const uint32_t expected = cadence ? expectedPacketsSinceFirst(now, sensor.firstMs, cadence) : 0;
        switch (sensor.type) {
            case SensorType::ThermoHygro:
                thermoSeenCount++; sessionThermo += sensor.received; expThermo += expected;
                if (!cadence) thermoQualityAvailable = false;
                break;
            case SensorType::Wind:
                windSeen = true; sessionWind += sensor.received; expWind += expected;
                if (!cadence) windQualityAvailable = false;
                break;
            case SensorType::Rain:
                rainSeen = true; sessionRain += sensor.received; expRain += expected;
                if (!cadence) rainQualityAvailable = false;
                break;
            case SensorType::UV:
                uvSeen = true; sessionUv += sensor.received; expUv += expected;
                if (!cadence) uvQualityAvailable = false;
                break;
            default: break;
        }
    }
    thermoQualityAvailable = thermoSeenCount > 0 && thermoQualityAvailable;
    windQualityAvailable = windSeen && windQualityAvailable;
    rainQualityAvailable = rainSeen && rainQualityAvailable;
    uvQualityAvailable = uvSeen && uvQualityAvailable;

    const bool acqThermo = oregonActive && timestampInSession(station->thermoUpdatedMs, rfSession.startedMs);
    const bool acqWind = oregonActive && timestampInSession(station->windUpdatedMs, rfSession.startedMs);
    const bool acqRain = oregonActive && timestampInSession(station->rainUpdatedMs, rfSession.startedMs);
    const bool acqUv = oregonActive && timestampInSession(station->uvUpdatedMs, rfSession.startedMs);

    // Il protocollo WS23xx trasmette nel nibble 6 il prossimo aggiornamento
    // (8/32/128 s). Lo usiamo per la qualita' del LINK Technoline, senza
    // inventare cadenze diverse per i singoli tipi di messaggio.
    if (technolineActive && sessionLcValid > 0 && rfSession.lcFirstValidMs == 0 &&
        timestampInSession(lcState.lastPacketMs, rfSession.startedMs)) {
        // Primo riferimento temporale noto della sessione. Dal pacchetto valido
        // in poi il campo UU ci dice quando aspettare il successivo update.
        rfSession.lcFirstValidMs = lcState.lastPacketMs;
    }
    const uint32_t lcCadenceMs = (technolineActive && rfSession.lcFirstValidMs != 0)
        ? laCrosseNextUpdateMs(lcState.nextUpdateCode) : 0;
    const uint32_t lcQualityElapsedMs = rfSession.lcFirstValidMs
        ? static_cast<uint32_t>(now - rfSession.lcFirstValidMs) : 0;
    const uint32_t expLcLink = (lcCadenceMs && sessionLcValid > 0)
        ? (1UL + lcQualityElapsedMs / lcCadenceMs) : 0;
    const int lcLinkQuality = qualityPct(sessionLcValid, expLcLink);
    const int lcDecoderQuality = lcRx.leaderFrames ? qualityPct(lcRx.leaderValidFrames, lcRx.leaderFrames) : -1;
    // Nibble 5 = GWRH, nibble 6 bit 3 = T. Queste flag indicano i tipi
    // inviati nel ciclo WS23xx corrente secondo rtl_433.
    uint8_t lcExpectedMask = 0;
    if (lcState.lastUpdateFlags & 0x08U) lcExpectedMask |= 0x01U; // T
    if (lcState.lastDataFlags & 0x01U) lcExpectedMask |= 0x02U;   // H
    if (lcState.lastDataFlags & 0x02U) lcExpectedMask |= 0x04U;   // R
    if (lcState.lastDataFlags & 0x04U) lcExpectedMask |= 0x08U;   // W
    if (lcState.lastDataFlags & 0x08U) lcExpectedMask |= 0x10U;   // G
    uint8_t lcReceivedMask = 0;
    if (sessionLcTemp) lcReceivedMask |= 0x01U;
    if (sessionLcHum) lcReceivedMask |= 0x02U;
    if (sessionLcRain) lcReceivedMask |= 0x04U;
    if (sessionLcWind) lcReceivedMask |= 0x08U;
    if (sessionLcGust) lcReceivedMask |= 0x10U;
    auto bitCount5=[](uint8_t v)->uint8_t { uint8_t n=0; for(uint8_t i=0;i<5;i++) if(v&(1U<<i)) n++; return n; };
    const uint8_t lcExpectedTypes = bitCount5(lcExpectedMask);
    const uint8_t lcReceivedTypes = bitCount5(static_cast<uint8_t>(lcReceivedMask & lcExpectedMask));
    const int lcTypeCoverage = lcExpectedTypes ? static_cast<int>((lcReceivedTypes * 100U) / lcExpectedTypes) : -1;
    const bool acqLcTemp = technolineActive && timestampInSession(lcState.temperatureUpdatedMs, rfSession.startedMs);
    const bool acqLcHum = technolineActive && timestampInSession(lcState.humidityUpdatedMs, rfSession.startedMs);
    const bool acqLcRain = technolineActive && timestampInSession(lcState.rainUpdatedMs, rfSession.startedMs);
    const bool acqLcWind = technolineActive && timestampInSession(lcState.windUpdatedMs, rfSession.startedMs);
    const bool acqLcGust = technolineActive && timestampInSession(lcState.gustUpdatedMs, rfSession.startedMs);

    String out;
    out.reserve(9000);
    out += "{";
    out += "\"version\":\"" + String(firmwareVersion()) + "\"";
    out += ",\"rf_mode\":\"" + String(rfProtocolModeName(getRfProtocolMode())) + "\"";
    out += ",\"uptime_s\":" + String(now / 1000UL);
    out += ",\"wifi\":{\"connected\":";
    out += wifiConnected() ? "true" : "false";
    out += ",\"ip\":\"" + wifiIpAddress() + "\"";
    out += ",\"hostname\":\"" + networkHostname() + "\"";
    out += ",\"mdns\":\"" + networkMdnsName() + "\"";
    out += ",\"mdns_active\":"; out += networkMdnsActive() ? "true" : "false";
    out += ",\"rssi\":" + String(wifiRssi()) + "}";

    out += ",\"session\":{";
    out += "\"mode\":\"" + String(rfProtocolModeName(rfSession.mode)) + "\"";
    out += ",\"age_s\":" + String(sessionElapsedMs / 1000UL);
    out += ",\"oregon_active\":"; out += oregonActive ? "true" : "false";
    out += ",\"technoline_active\":"; out += technolineActive ? "true" : "false";
    out += ",\"thermo_acquired\":"; out += acqThermo ? "true" : "false";
    out += ",\"wind_acquired\":"; out += acqWind ? "true" : "false";
    out += ",\"rain_acquired\":"; out += acqRain ? "true" : "false";
    out += ",\"uv_acquired\":"; out += acqUv ? "true" : "false";
    out += ",\"thermo_received\":" + String(sessionThermo);
    out += ",\"wind_received\":" + String(sessionWind);
    out += ",\"rain_received\":" + String(sessionRain);
    out += ",\"uv_received\":" + String(sessionUv);
    out += ",\"thermo_seen\":"; out += thermoSeenCount ? "true" : "false";
    out += ",\"wind_seen\":"; out += windSeen ? "true" : "false";
    out += ",\"rain_seen\":"; out += rainSeen ? "true" : "false";
    out += ",\"uv_seen\":"; out += uvSeen ? "true" : "false";
    out += ",\"thermo_channels\":" + String(thermoSeenCount);
    out += ",\"thermo_expected\":" + String(expThermo);
    out += ",\"wind_expected\":" + String(expWind);
    out += ",\"rain_expected\":" + String(expRain);
    out += ",\"uv_expected\":" + String(expUv);
    out += ",\"thermo_quality_available\":"; out += thermoQualityAvailable ? "true" : "false";
    out += ",\"wind_quality_available\":"; out += windQualityAvailable ? "true" : "false";
    out += ",\"rain_quality_available\":"; out += rainQualityAvailable ? "true" : "false";
    out += ",\"uv_quality_available\":"; out += uvQualityAvailable ? "true" : "false";
    out += ",\"thermo_quality_pct\":" + String(qualityPct(sessionThermo, expThermo));
    out += ",\"wind_quality_pct\":" + String(qualityPct(sessionWind, expWind));
    out += ",\"rain_quality_pct\":" + String(qualityPct(sessionRain, expRain));
    out += ",\"uv_quality_pct\":" + String(qualityPct(sessionUv, expUv));
    out += ",\"oregon_sensor_overflow\":" + String(rfSession.oregonOverflow);
    out += ",\"oregon_sensors\":[";
    bool firstOregonSensor = true;
    for (uint8_t i = 0; i < OREGON_SESSION_SENSOR_MAX; ++i) {
        const OregonSessionSensor &sensor = rfSession.oregon[i];
        if (sensor.received == 0) continue;
        const uint32_t nominal = nominalOregonCadenceMs(sensor.type, sensor.code, sensor.channel);
        const uint32_t cadence = effectiveOregonCadenceMs(sensor);
        const uint32_t expected = cadence ? expectedPacketsSinceFirst(now, sensor.firstMs, cadence) : 0;
        const int quality = qualityPct(sensor.received, expected);
        if (!firstOregonSensor) out += ',';
        firstOregonSensor = false;
        out += "{\"t\":\"" + String(sensorTypeName(sensor.type)) + "\"";
        out += ",\"m\":\"" + String(sensorModelName(sensor.code)) + "\"";
        out += ",\"c\":\"" + hex4(sensor.code) + "\"";
        out += ",\"ch\":" + String(sensor.channel);
        out += ",\"id\":" + String(sensor.rollingCode);
        out += ",\"v\":" + String(sensor.protocolVersion);
        out += ",\"rx\":" + String(sensor.received);
        out += ",\"ex\":" + String(expected);
        out += ",\"q\":" + String(quality);
        out += ",\"lost\":" + String(expected > sensor.received ? expected - sensor.received : 0UL);
        out += ",\"cad\":" + String(cadence / 1000UL);
        out += ",\"rssi\":" + jsonFloat(sensor.lastRssi, 1);
        out += ",\"src\":\"" + String(nominal ? "nom" : (cadence ? "auto" : "cal")) + "\"}";
    }
    out += ']';
    out += ",\"lc_temperature_acquired\":"; out += acqLcTemp ? "true" : "false";
    out += ",\"lc_humidity_acquired\":"; out += acqLcHum ? "true" : "false";
    out += ",\"lc_rain_acquired\":"; out += acqLcRain ? "true" : "false";
    out += ",\"lc_wind_acquired\":"; out += acqLcWind ? "true" : "false";
    out += ",\"lc_gust_acquired\":"; out += acqLcGust ? "true" : "false";
    out += ",\"lc_temperature_received\":" + String(sessionLcTemp);
    out += ",\"lc_humidity_received\":" + String(sessionLcHum);
    out += ",\"lc_rain_received\":" + String(sessionLcRain);
    out += ",\"lc_wind_received\":" + String(sessionLcWind);
    out += ",\"lc_gust_received\":" + String(sessionLcGust);
    out += ",\"lc_valid_received\":" + String(sessionLcValid);
    out += ",\"lc_expected\":" + String(expLcLink);
    out += ",\"lc_cadence_ms\":" + String(lcCadenceMs);
    out += ",\"lc_link_quality_pct\":" + String(lcLinkQuality);
    out += ",\"lc_decoder_quality_pct\":" + String(lcDecoderQuality);
    out += ",\"lc_expected_mask\":" + String(lcExpectedMask);
    out += ",\"lc_received_mask\":" + String(lcReceivedMask);
    out += ",\"lc_expected_types\":" + String(lcExpectedTypes);
    out += ",\"lc_received_types\":" + String(lcReceivedTypes);
    out += ",\"lc_type_coverage_pct\":" + String(lcTypeCoverage);
    out += "}";

    out += ",\"weather\":{";
    out += "\"temperature_c\":" + jsonFloat(station->temperatureC, 1);
    out += ",\"humidity_pct\":" + jsonFloat(station->humidityPct, 0);
    out += ",\"heat_index_c\":" + jsonFloat(station->heatIndexC, 1);
    out += ",\"dew_point_c\":" + jsonFloat(station->dewPointC, 1);
    out += ",\"indoor_temperature_c\":" + jsonFloat(station->indoorTemperatureC, 1);
    out += ",\"indoor_humidity_pct\":" + jsonFloat(station->indoorHumidityPct, 0);

    out += ",\"wind_average_kmh\":" + jsonFloat(station->windAverageKmh, 1);
    out += ",\"wind_gust_kmh\":" + jsonFloat(station->windGustKmh, 1);
    out += ",\"wind_current_kmh\":" + jsonFloat(station->windGustKmh, 1);
    out += ",\"wind_direction_deg\":" + jsonFloat(station->windDirectionDeg, 1);
    out += ",\"wind_direction\":\"";
    out += station->windValid ? windDirectionName(station->windDirectionIndex) : "-";
    out += "\"";
    out += ",\"wind_chill_c\":" + jsonFloat(station->windChillC, 1);

    out += ",\"rain_total_mm\":" + jsonFloat(station->rainTotalMm, 2);
    out += ",\"rain_rate_mmh\":" + jsonFloat(station->rainRateMmH, 2);
    out += ",\"rain_increment_mm\":" + jsonFloat(station->rainIncrementMm, 2);
    out += ",\"rain_last_hour_mm\":" + jsonFloat(station->rainLastHourMm, 2);
    out += ",\"rain_last_24h_mm\":" + jsonFloat(station->rainLast24hMm, 2);
    out += ",\"uv\":" + String(station->uvValid ? station->uvIndex : -1);

    out += ",\"pressure_station_hpa\":" + jsonFloat(station->pressureAbsoluteHpa, 1);
    out += ",\"altimeter_hpa\":" + jsonFloat(station->pressureSeaLevelHpa, 1);
    out += ",\"pressure_trend_hpa_3h\":" + jsonFloat(station->pressureTrendHpa3h, 1);
    out += ",\"pressure_trend_window_min\":" + String(station->pressureTrendWindowMin);
    out += ",\"pressure_trend\":\"" + String(barometerTrendName(*station)) + "\"";
    out += ",\"forecast\":\"" + String(barometerForecastName(*station)) + "\"";
    out += ",\"barometer\":\"" + String(barometerName()) + "\"";
    out += ",\"barometer_altitude_m\":" + String(BAROMETER_ALTITUDE_M, static_cast<unsigned int>(1));
    out += "}";

    // V6.3: BME280 locale, separato dai protocolli radio.
    out += ",\"bme280\":{";
    out += "\"detected\":"; out += barometerDetected() ? "true" : "false";
    out += ",\"model\":\"" + String(barometerName()) + "\"";
    out += ",\"temperature_c\":" + jsonFloat(station->indoorTemperatureC, 1);
    out += ",\"humidity_pct\":" + jsonFloat(station->indoorHumidityPct, 0);
    out += ",\"pressure_station_hpa\":" + jsonFloat(station->pressureAbsoluteHpa, 1);
    out += ",\"altimeter_hpa\":" + jsonFloat(station->pressureSeaLevelHpa, 1);
    out += ",\"trend_hpa_3h\":" + jsonFloat(station->pressureTrendHpa3h, 1);
    out += ",\"trend_window_min\":" + String(station->pressureTrendWindowMin);
    out += ",\"trend\":\"" + String(barometerTrendName(*station)) + "\"";
    out += ",\"forecast\":\"" + String(barometerForecastName(*station)) + "\"";
    out += ",\"altitude_m\":" + String(BAROMETER_ALTITUDE_M, static_cast<unsigned int>(1));
    out += ",\"age_s\":" + String(ageSeconds(station->pressureUpdatedMs, now));
    out += "}";

    const auto &lc = station->lacrosse;
    out += ",\"lacrosse\":{";
    out += "\"model\":\"" + String(laCrosseModelName(lc.wsId)) + "\"";
    out += ",\"ws_id\":" + String(lc.wsId);
    out += ",\"sensor_id\":" + String(lc.sensorId);
    out += ",\"data_flags\":" + String(lc.lastDataFlags);
    out += ",\"update_flags\":" + String(lc.lastUpdateFlags);
    out += ",\"temperature_c\":" + jsonFloat(lc.temperatureC, 1);
    out += ",\"humidity_pct\":" + jsonFloat(lc.humidityPct, 0);
    out += ",\"rain_total_mm\":" + jsonFloat(lc.rainTotalMm, 2);
    out += ",\"rain_increment_mm\":" + jsonFloat(lc.rainIncrementMm, 2);
    out += ",\"wind_kmh\":" + jsonFloat(lc.windKmh, 1);
    out += ",\"gust_kmh\":" + jsonFloat(lc.gustKmh, 1);
    out += ",\"direction_deg\":" + jsonFloat(lc.windDirectionDeg, 1);
    out += ",\"direction\":\"" + String(lc.directionValid ? laCrosseWindDirectionName(lc.windDirectionIndex) : "-") + "\"";
    out += ",\"next_update\":\"" + String(laCrosseNextUpdateName(lc.nextUpdateCode)) + "\"";
    out += ",\"packets\":" + String(lc.validPacketCount);
    out += ",\"rejected\":" + String(lc.rejectedPacketCount);
    out += ",\"temperature_packets\":" + String(lc.temperaturePacketCount);
    out += ",\"humidity_packets\":" + String(lc.humidityPacketCount);
    out += ",\"rain_packets\":" + String(lc.rainPacketCount);
    out += ",\"wind_packets\":" + String(lc.windPacketCount);
    out += ",\"gust_packets\":" + String(lc.gustPacketCount);
    out += ",\"temperature_age_s\":" + String(ageSeconds(lc.temperatureUpdatedMs, now));
    out += ",\"humidity_age_s\":" + String(ageSeconds(lc.humidityUpdatedMs, now));
    out += ",\"rain_age_s\":" + String(ageSeconds(lc.rainUpdatedMs, now));
    out += ",\"wind_age_s\":" + String(ageSeconds(lc.windUpdatedMs, now));
    out += ",\"gust_age_s\":" + String(ageSeconds(lc.gustUpdatedMs, now));
    out += ",\"battery\":\"N/D\"";
    out += "}";

    out += ",\"lacrosse_rf\":{";
    out += "\"valid\":" + String(lcRx.validFrames);
    out += ",\"candidates\":" + String(lcRx.candidates);
    out += ",\"stream_pulses\":" + String(lcRx.streamPulses);
    out += ",\"stream_windows\":" + String(lcRx.streamWindows);
    out += ",\"stream_header_matches\":" + String(lcRx.streamHeaderMatches);
    out += ",\"stream_valid\":" + String(lcRx.streamValidFrames);
    out += ",\"stream_resets\":" + String(lcRx.streamResets);
    out += ",\"stream_rejects\":" + String(lcRx.streamPulseRejects);
    out += ",\"leader_starts\":" + String(lcRx.leaderStarts);
    out += ",\"leader_lost_zero\":" + String(lcRx.leaderLostZeroStarts);
    out += ",\"leader_frames\":" + String(lcRx.leaderFrames);
    out += ",\"leader_valid\":" + String(lcRx.leaderValidFrames);
    out += ",\"leader_invalid\":" + String(lcRx.leaderInvalidFrames);
    out += ",\"leader_resets\":" + String(lcRx.leaderResets);
    out += ",\"leader_rejects\":" + String(lcRx.leaderPulseRejects);
    out += ",\"leader_bits_0\":" + String(lcRx.leaderBits0);
    out += ",\"leader_bits_1\":" + String(lcRx.leaderBits1);
    out += ",\"burst_recovered_missing_edge\":" + String(lcRx.burstRecoveredMissingEdge);
    out += ",\"burst_rejects\":" + String(lcRx.burstRejects);
    out += ",\"duplicates\":" + String(lcRx.duplicateFrames);
    out += ",\"header_fail\":" + String(lcRx.headerFails);
    out += ",\"complement_fail\":" + String(lcRx.complementFails);
    out += ",\"parity_fail\":" + String(lcRx.parityFails);
    out += ",\"checksum_fail\":" + String(lcRx.checksumFails);
    out += ",\"pair_rejects\":" + String(lcRx.pairRejects);
    out += ",\"reset_gaps\":" + String(lcRx.resetGaps);
    out += ",\"frame_length_fail\":" + String(lcRx.frameLengthFails);
    out += ",\"burst_attempts\":" + String(lcRx.burstAttempts);
    out += ",\"burst_windows\":" + String(lcRx.burstPulseWindows);
    out += ",\"burst_valid\":" + String(lcRx.burstValidFrames);
    out += ",\"burst_too_short\":" + String(lcRx.burstTooShort);
    out += ",\"last_burst_intervals\":" + String(lcRx.lastBurstIntervals);
    out += ",\"last_pulses_0\":" + String(lcRx.lastBurstPulseCount0);
    out += ",\"last_pulses_1\":" + String(lcRx.lastBurstPulseCount1);
    out += ",\"burst_pulse_level\":" + String(lcRx.burstPulseLevel);
    out += ",\"sequence_pairs\":" + String(lcRx.sequencePairs);
    out += ",\"sequence_restarts\":" + String(lcRx.sequenceRestarts);
    out += ",\"sequence_windows\":" + String(lcRx.sequenceWindows);
    out += ",\"sequence_header_matches\":" + String(lcRx.sequenceHeaderMatches);
    out += ",\"sequence_valid\":" + String(lcRx.sequenceValidFrames);
    out += ",\"sequence_gap_rejects\":" + String(lcRx.sequenceGapRejects);
    out += ",\"sequence_pulse_rejects\":" + String(lcRx.sequencePulseRejects);
    out += ",\"sequence_bits_0\":" + String(lcRx.lastSequenceBits0);
    out += ",\"sequence_bits_1\":" + String(lcRx.lastSequenceBits1);
    out += ",\"sequence_pulse_level\":" + String(lcRx.sequencePulseLevel);
    out += ",\"short_us\":" + String(lcRx.shortPulseAverageUs);
    out += ",\"long_us\":" + String(lcRx.longPulseAverageUs);
    out += ",\"gap_us\":" + String(lcRx.gapAverageUs);
    out += ",\"short_period_us\":" + String(lcRx.shortPeriodAverageUs);
    out += ",\"long_period_us\":" + String(lcRx.longPeriodAverageUs);
    out += ",\"active_hypothesis\":" + String(lcRx.activeHypothesis);
    out += ",\"hypothesis_valid\":[" + String(lcRx.hypothesisValid[0]) + "," + String(lcRx.hypothesisValid[1]) + "," + String(lcRx.hypothesisValid[2]) + "," + String(lcRx.hypothesisValid[3]) + "]";
    out += ",\"interval_bins\":[" + String(lcRx.intervalBins[0]) + "," + String(lcRx.intervalBins[1]) + "," + String(lcRx.intervalBins[2]) + "," + String(lcRx.intervalBins[3]) + "," + String(lcRx.intervalBins[4]) + "," + String(lcRx.intervalBins[5]) + "]";
    out += "}";

    out += ",\"burst\":{";
    out += "\"enabled\":"; out += burstRecoveryEnabled() ? "true" : "false";
    out += ",\"total\":" + String(burst.burstsTotal);
    out += ",\"osv3_like\":" + String(burst.osv3LikeBursts);
    out += ",\"discarded\":" + String(burst.discardedBursts);
    out += ",\"auto_active\":"; out += burst.autoActive ? "true" : "false";
    out += ",\"auto_step\":" + String(burst.autoStep);
    out += ",\"auto_step_started_ms\":" + String(burst.autoStepStartedMs);
    out += ",\"auto_step_duration_ms\":" + String(burst.autoStepDurationMs);
    out += ",\"best_profile\":" + String(burst.bestProfile);
    out += ",\"profile_bursts\":[" + String(burst.profileBursts[0]) + "," + String(burst.profileBursts[1]) + "," + String(burst.profileBursts[2]) + "," + String(burst.profileBursts[3]) + "]";
    out += ",\"profile_osv3\":[" + String(burst.profileOsv3Like[0]) + "," + String(burst.profileOsv3Like[1]) + "," + String(burst.profileOsv3Like[2]) + "," + String(burst.profileOsv3Like[3]) + "]";
    out += ",\"profile_valid\":[" + String(burst.profileValidFrames[0]) + "," + String(burst.profileValidFrames[1]) + "," + String(burst.profileValidFrames[2]) + "," + String(burst.profileValidFrames[3]) + "]";
    out += ",\"profile_score\":[" + String(burst.profileScore[0]) + "," + String(burst.profileScore[1]) + "," + String(burst.profileScore[2]) + "," + String(burst.profileScore[3]) + "]";
    out += ",\"adaptive_attempts\":" + String(burst.adaptiveAttempts);
    out += ",\"adaptive_candidates\":" + String(burst.adaptiveCandidates);
    out += ",\"adaptive_recovered\":" + String(burst.adaptiveRecovered);
    out += ",\"adaptive_checksum_fail\":" + String(burst.adaptiveChecksumFail);
    out += ",\"technoline_like\":" + String(burst.technolineLikeBursts);
    out += "}";

    out += ",\"wgr_probe\":{";
    out += "\"enabled\":"; out += wgrProbe.enabled ? "true" : "false";
    out += ",\"bursts_total\":" + String(wgrProbe.burstsTotal);
    out += ",\"osv3_like\":" + String(wgrProbe.osv3LikeBursts);
    out += ",\"classified_af\":" + String(wgrProbe.classifiedThermo);
    out += ",\"classified_a1\":" + String(wgrProbe.classifiedWind);
    out += ",\"classified_a2\":" + String(wgrProbe.classifiedRain);
    out += ",\"classified_ad\":" + String(wgrProbe.classifiedUv);
    out += ",\"unclassified_osv3\":" + String(wgrProbe.unclassifiedOsv3);
    out += ",\"cadence14\":" + String(wgrProbe.cadence14Matches);
    out += ",\"last_unclassified_ms\":" + String(wgrProbe.lastUnclassifiedMs);
    out += ",\"last_unclassified_delta_ms\":" + String(wgrProbe.lastUnclassifiedDeltaMs);
    out += ",\"last_unclassified_duration_ms\":" + String(wgrProbe.lastUnclassifiedDurationMs);
    out += ",\"last_unclassified_edges\":" + String(wgrProbe.lastUnclassifiedEdges);
    out += ",\"last_unclassified_match_pct\":" + String(wgrProbe.lastUnclassifiedMatchPct);
    out += ",\"last_unclassified_rssi\":" + jsonFloat(wgrProbe.lastUnclassifiedRssi, 1);
    out += "}";

    out += ",\"fresh\":{";
    out += "\"thermo\":"; out += sensorFresh(station->thermoUpdatedMs, now) ? "true" : "false";
    out += ",\"wind\":"; out += sensorFresh(station->windUpdatedMs, now) ? "true" : "false";
    out += ",\"rain\":"; out += sensorFresh(station->rainUpdatedMs, now) ? "true" : "false";
    out += ",\"uv\":"; out += sensorFresh(station->uvUpdatedMs, now) ? "true" : "false";
    out += ",\"pressure\":"; out += sensorFresh(station->pressureUpdatedMs, now) ? "true" : "false";
    out += ",\"thermo_age_s\":" + String(ageSeconds(station->thermoUpdatedMs, now));
    out += ",\"wind_age_s\":" + String(ageSeconds(station->windUpdatedMs, now));
    out += ",\"rain_age_s\":" + String(ageSeconds(station->rainUpdatedMs, now));
    out += ",\"uv_age_s\":" + String(ageSeconds(station->uvUpdatedMs, now));
    out += ",\"pressure_age_s\":" + String(ageSeconds(station->pressureUpdatedMs, now));
    out += "}";

    out += ",\"packets\":{";
    out += "\"valid\":" + String(station->validPacketCount);
    out += ",\"rejected\":" + String(station->rejectedPacketCount);
    out += ",\"AF\":" + String(station->thermoPacketCount);
    out += ",\"A1\":" + String(station->windPacketCount);
    out += ",\"A2\":" + String(station->rainPacketCount);
    out += ",\"AD\":" + String(station->uvPacketCount);
    out += "}";

    out += ",\"sensors\":{";
    appendSensorJson(out, "thermo", station->thermoSensor, false);
    appendSensorJson(out, "wind", station->windSensor, true);
    appendSensorJson(out, "rain", station->rainSensor, true);
    appendSensorJson(out, "uv", station->uvSensor, true);
    out += "}";

    const ThermoChannelConfig thermoCfg = getThermoChannelConfig();
    out += ",\"oregon_thermo\":{\"m\":" + String(thermoEffectiveMask());
    out += ",\"p\":" + String(thermoCfg.primaryChannel) + ",\"c\":[";
    for (uint8_t ch = 1; ch <= 3; ++ch) {
        if (ch > 1) out += ",";
        const ThermoChannelState ts = getThermoChannelState(ch);
        out += "[" + jsonFloat(ts.temperatureC, 1) + "," + jsonFloat(ts.humidityPct, 0);
        out += "," + String(ageSeconds(ts.updatedMs, now)) + "," + jsonFloat(ts.lastRssi, 1);
        out += ",\"" + hex4(ts.sensor.code) + "\",\"" + String(sensorBatteryName(ts.sensor)) + "\"]";
    }
    out += "]}";

    out += ",\"rf\":{";
    out += "\"frequency_mhz\":" + String(OREGON_FREQUENCY_MHZ, static_cast<unsigned int>(2));
    out += ",\"rx_bw_khz\":" + String(getRadioBandwidthKhz(), static_cast<unsigned int>(1));
    out += ",\"bw_oregon_khz\":" + String(getRadioBandwidthForMode(RfProtocolMode::Oregon), static_cast<unsigned int>(1));
    out += ",\"bw_lacrosse_khz\":" + String(getRadioBandwidthForMode(RfProtocolMode::LaCrosse), static_cast<unsigned int>(1));
    out += ",\"frontend_profile\":\"" + String(radioFrontendProfileName(getRadioFrontendProfile())) + "\"";
    out += ",\"frontend_profile_id\":" + String(static_cast<uint8_t>(getRadioFrontendProfile()));
    out += ",\"rx_gain\":" + String(getRadioGain());
    out += ",\"gain_oregon\":" + String(getRadioGainForMode(RfProtocolMode::Oregon));
    out += ",\"gain_lacrosse\":" + String(getRadioGainForMode(RfProtocolMode::LaCrosse));
    out += ",\"gain_name\":\"" + String(radioGainName(getRadioGain())) + "\"";
    out += ",\"edges\":" + String(rx.edgesCaptured);
    out += ",\"strong_preambles\":" + String(rx.preamblesDetected);
    out += ",\"wind_recovery_starts\":" + String(rx.windRecoveryStarts);
    out += ",\"wind_recovery_success\":" + String(rx.windRecoverySuccess);
    out += ",\"strong_frames\":" + String(rx.edgeFrames);
    out += ",\"v21_preambles\":" + String(rx.v21Preambles);
    out += ",\"v21_short_preambles\":" + String(rx.v21ShortPreambles);
    out += ",\"v21_candidates\":" + String(rx.v21Candidates);
    out += ",\"v21_frames\":" + String(rx.v21Frames);
    out += ",\"v21_uv_candidates\":" + String(rx.v21UvCandidates);
    out += ",\"v21_uv_frames\":" + String(rx.v21UvFrames);
    out += ",\"v21_checksum_fail\":" + String(rx.v21ChecksumFail);
    out += ",\"v21_pair_errors\":" + String(rx.v21PairErrors);
    out += ",\"weak_frames\":" + String(rx.weakEdgeFrames);
    out += ",\"state_frames\":" + String(rx.stateEdgeFrames);
    out += ",\"state_preambles\":" + String(rx.statePreambles);
    out += ",\"state_candidates\":" + String(rx.stateCandidates);
    out += ",\"state_checksum_ok\":" + String(rx.stateChecksumOk);
    out += ",\"state_checksum_fail\":" + String(rx.stateChecksumFail);
    out += ",\"state_timing_errors\":" + String(rx.stateTimingErrors);
    out += ",\"state_manchester_errors\":" + String(rx.stateManchesterErrors);
    out += ",\"burst_adaptive_frames\":" + String(rx.burstAdaptiveFrames);
    out += ",\"burst_adaptive_AF\":" + String(rx.burstAdaptiveThermo);
    out += ",\"burst_adaptive_A1\":" + String(rx.burstAdaptiveWind);
    out += ",\"burst_adaptive_A2\":" + String(rx.burstAdaptiveRain);
    out += ",\"burst_adaptive_AD\":" + String(rx.burstAdaptiveUv);
    out += ",\"duplicates\":" + String(rx.duplicateFrames);
    out += ",\"raw_AF\":" + String(rx.rawThermoFrames);
    out += ",\"raw_A1\":" + String(rx.rawWindFrames);
    out += ",\"raw_A2\":" + String(rx.rawRainFrames);
    out += ",\"raw_AD\":" + String(rx.rawUvFrames);
    out += ",\"strong_timing_errors\":" + String(rx.timingErrors);
    out += ",\"strong_sync_errors\":" + String(rx.syncErrors);
    out += ",\"recovery_timing_errors\":" + String(rx.weakTimingErrors);
    out += ",\"recovery_sync_errors\":" + String(rx.weakSyncErrors);
    out += ",\"wind_scan_checksum_fail\":" + String(rx.windWindowChecksumFail);
    out += ",\"short_avg_us\":" + String(rx.shortAverageUs);
    out += ",\"long_avg_us\":" + String(rx.longAverageUs);
    out += ",\"on_short_avg_us\":" + String(rx.onShortAverageUs);
    out += ",\"on_long_avg_us\":" + String(rx.onLongAverageUs);
    out += ",\"off_short_avg_us\":" + String(rx.offShortAverageUs);
    out += ",\"off_long_avg_us\":" + String(rx.offLongAverageUs);
    out += ",\"max_preamble_shorts\":" + String(rx.maxPreambleShorts);
    out += ",\"run_04_07\":" + String(rx.preRun04_07);
    out += ",\"run_08_11\":" + String(rx.preRun08_11);
    out += ",\"run_12_17\":" + String(rx.preRun12_17);
    out += ",\"run_18_27\":" + String(rx.preRun18_27);
    out += ",\"run_28_plus\":" + String(rx.preRun28Plus);
    out += ",\"overflows\":" + String(rx.ringOverflows);
    out += "}";

    const uint32_t heapSize = ESP.getHeapSize();
    const uint32_t heapFree = ESP.getFreeHeap();
    const uint32_t heapMin = ESP.getMinFreeHeap();
    const uint32_t sketchSize = ESP.getSketchSize();
    const uint32_t flashSize = ESP.getFlashChipSize();
    const uint32_t freeSketch = ESP.getFreeSketchSpace();
    out += ",\"system\":{";
    out += "\"chip\":\"" + String(ESP.getChipModel()) + "\"";
    out += ",\"board\":\"" + jsonEscapeString(String(BOARD_NAME)) + "\"";
    out += ",\"firmware\":\"" + jsonEscapeString(String(firmwareVersion())) + "\"";
    out += ",\"git_commit\":\"" + jsonEscapeString(String(firmwareGitCommit())) + "\"";
    out += ",\"build\":\"" + jsonEscapeString(firmwareBuildTimestamp()) + "\"";
    out += ",\"reset_reason\":\"" + String(firmwareResetReason()) + "\"";
    out += ",\"revision\":" + String(ESP.getChipRevision());
    out += ",\"cores\":" + String(ESP.getChipCores());
    out += ",\"cpu_mhz\":" + String(ESP.getCpuFreqMHz());
    out += ",\"heap_size\":" + String(heapSize);
    out += ",\"heap_free\":" + String(heapFree);
    out += ",\"heap_used\":" + String(heapSize > heapFree ? heapSize - heapFree : 0);
    out += ",\"heap_min_free\":" + String(heapMin);
    out += ",\"sketch_size\":" + String(sketchSize);
    out += ",\"flash_size\":" + String(flashSize);
    out += ",\"free_sketch_space\":" + String(freeSketch);
    out += ",\"uptime_s\":" + String(now / 1000UL);
    out += ",\"wifi_rssi\":" + String(wifiRssi());
    out += ",\"rf_overflows\":" + String(rx.ringOverflows);
    out += ",\"display_on\":"; out += displayEnabled() ? "true" : "false";
    out += ",\"display_button_enabled\":"; out += displayButtonEnabled() ? "true" : "false";
    out += ",\"display_button_pin\":" + String(displayButtonPin());
    out += "}";
    out += "}";

    sendNoCache();
    server.send(200, "application/json", out);
}


void handleThermoConfigGet() {
    const ThermoChannelConfig c = getThermoChannelConfig();
    String out = "{\"enabled_mask\":" + String(c.enabledMask);
    out += ",\"detected_mask\":" + String(thermoDetectedMask());
    out += ",\"visible_mask\":" + String(thermoEffectiveMask());
    out += ",\"primary_channel\":" + String(c.primaryChannel);
    out += ",\"auto_discover\":"; out += c.autoDiscover ? "true" : "false";
    out += "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleThermoConfigPost() {
    const uint8_t previousVisibleMask = thermoEffectiveMask();
    ThermoChannelConfig c = getThermoChannelConfig();
    const uint8_t previousPrimaryChannel = c.primaryChannel;
    if (server.hasArg("enabled_mask")) c.enabledMask = static_cast<uint8_t>(server.arg("enabled_mask").toInt());
    if (server.hasArg("primary_channel")) c.primaryChannel = static_cast<uint8_t>(server.arg("primary_channel").toInt());
    if (server.hasArg("auto_discover")) {
        const String v = server.arg("auto_discover");
        c.autoDiscover = v == "1" || v == "true" || v == "on";
    }
    if (c.primaryChannel < 1U || c.primaryChannel > 3U || (c.enabledMask & 0xF8U)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid thermo channel configuration\"}");
        return;
    }
    if (!saveThermoChannelConfig(c)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"thermo NVS verification failed\"}");
        return;
    }
    if (station) syncPrimaryThermoState(*station);
    reconcileThermoMqttRetained(previousVisibleMask, previousPrimaryChannel);
    handleThermoConfigGet();
}

void handleThermoConfigReset() {
    const uint8_t previousVisibleMask = thermoEffectiveMask();
    const uint8_t previousPrimaryChannel = getThermoChannelConfig().primaryChannel;
    if (!resetThermoChannelConfig()) {
        server.send(500, "application/json", "{\"ok\":false}");
        return;
    }
    if (station) syncPrimaryThermoState(*station);
    reconcileThermoMqttRetained(previousVisibleMask, previousPrimaryChannel);
    handleThermoConfigGet();
}

void handleDisplayPower() {
    if (!server.hasArg("on")) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"missing on\"}");
        return;
    }
    const String arg = server.arg("on");
    const bool enabled = arg == "1" || arg == "true" || arg == "on";
    if (!setDisplayEnabled(enabled)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"display NVS verification failed\"}");
        return;
    }
    sendNoCache();
    String out = String("{\"ok\":true,\"display_on\":") + (displayEnabled() ? "true" : "false") + "}";
    server.send(200, "application/json", out);
}


void handleDisplayConfigGet() {
    const DisplayRuntimeConfig c = getDisplayConfig();
    String out;
    out.reserve(420);
    out = "{\"on\":"; out += displayEnabled() ? "true" : "false";
    out += ",\"page_mask\":" + String(c.pageMask);
    out += ",\"environment_fields\":" + String(c.environmentFields);
    out += ",\"wind_rain_fields\":" + String(c.windRainFields);
    out += ",\"technoline_fields\":" + String(c.technolineFields);
    out += ",\"pressure_fields\":" + String(c.pressureFields);
    out += ",\"status_fields\":" + String(c.statusFields);
    out += ",\"lightning_fields\":" + String(c.lightningFields);
    out += ",\"page_interval_sec\":" + String(c.pageIntervalSec);
    out += ",\"contrast\":" + String(c.contrast);
    out += ",\"current_page\":" + String(displayCurrentPage());
    out += ",\"nvs_ok\":"; out += displayPersistenceAvailable() ? "true" : "false";
    out += "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleDisplayConfigPost() {
    DisplayRuntimeConfig c = getDisplayConfig();
    if (server.hasArg("page_mask")) c.pageMask = static_cast<uint8_t>(server.arg("page_mask").toInt());
    if (server.hasArg("environment_fields")) c.environmentFields = static_cast<uint8_t>(server.arg("environment_fields").toInt());
    if (server.hasArg("wind_rain_fields")) c.windRainFields = static_cast<uint8_t>(server.arg("wind_rain_fields").toInt());
    if (server.hasArg("technoline_fields")) c.technolineFields = static_cast<uint8_t>(server.arg("technoline_fields").toInt());
    if (server.hasArg("pressure_fields")) c.pressureFields = static_cast<uint8_t>(server.arg("pressure_fields").toInt());
    if (server.hasArg("status_fields")) c.statusFields = static_cast<uint8_t>(server.arg("status_fields").toInt());
    if (server.hasArg("lightning_fields")) c.lightningFields = static_cast<uint8_t>(server.arg("lightning_fields").toInt());
    if (server.hasArg("page_interval_sec")) {
        const long v = server.arg("page_interval_sec").toInt();
        if (v < 2 || v > 60) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"page interval must be 2..60 seconds\"}"); return; }
        c.pageIntervalSec = static_cast<uint16_t>(v);
    }
    if (server.hasArg("contrast")) {
        const long v = server.arg("contrast").toInt();
        if (v < 8 || v > 255) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"contrast must be 8..255\"}"); return; }
        c.contrast = static_cast<uint8_t>(v);
    }
    if (!validateDisplayConfig(c)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid display configuration; enable at least one page\"}");
        return;
    }
    bool changed = false;
    if (!saveDisplayConfig(c, changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"display configuration rejected\"}");
        return;
    }
    if (server.hasArg("on")) {
        const String v = server.arg("on");
        if (!setDisplayEnabled(v == "1" || v == "true" || v == "on")) {
            server.send(500, "application/json", "{\"ok\":false,\"error\":\"display power NVS verification failed\"}");
            return;
        }
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":"; out += changed ? "true" : "false";
    out += ",\"display_on\":"; out += displayEnabled() ? "true" : "false";
    out += "}";
    server.send(200, "application/json", out);
}

void handleDisplayConfigReset() {
    bool changed = false;
    if (!resetDisplayConfigToDefaults(changed)) {
        server.send(500, "application/json", "{\"ok\":false}");
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":"; out += changed ? "true" : "false"; out += "}";
    server.send(200, "application/json", out);
}

void handleRaw() {
    String out;
    out.reserve(7000);
    out = "[";
    for (uint8_t n = 0; n < historyCount; ++n) {
        const int idx = (static_cast<int>(historyHead) - 1 - n + RAW_HISTORY_SIZE) % RAW_HISTORY_SIZE;
        const RawEntry &e = history[idx];
        if (n) out += ",";
        out += "{\"ms\":" + String(e.ms);
        out += ",\"rssi\":" + jsonFloat(e.rssi, 1);
        out += ",\"len\":" + String(e.len);
        out += ",\"id\":\"0x";
        if (e.sensorId < 0x10) out += "0";
        out += String(static_cast<unsigned int>(e.sensorId), HEX);
        out += "\",\"sensor_code\":\"" + hex4(e.sensorCode) + "\"";
        out += ",\"model\":\"" + String(sensorModelName(e.sensorCode)) + "\"";
        out += ",\"battery\":\"" + String(!e.batteryKnown ? "N/D" : (e.batteryLow ? "LOW" : "OK")) + "\"";
        out += ",\"type\":\"" + String(e.type) + "\"";
        out += ",\"protocol\":\"" + String(e.protocol) + "\"";
        out += ",\"source\":\"" + String(e.sourceName) + "\"";
        out += ",\"accepted\":";
        out += e.accepted ? "true" : "false";
        out += ",\"decoded\":\"" + String(e.decoded) + "\"";
        out += ",\"hex\":\"" + String(e.hex) + "\"}";
    }
    out += "]";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleRawText() {
    String out;
    out.reserve(5500);
    for (uint8_t n = 0; n < historyCount; ++n) {
        const int idx = (static_cast<int>(historyHead) - 1 - n + RAW_HISTORY_SIZE) % RAW_HISTORY_SIZE;
        const RawEntry &e = history[idx];
        out += String(e.ms);
        out += " ms  ";
        out += e.accepted ? "OK   " : "DROP ";
        out += e.type;
        out += " proto="; out += e.protocol;
        out += " src="; out += e.sourceName;
        out += " RSSI=";
        out += jsonFloat(e.rssi, 1);
        out += "  ";
        out += e.hex;
        if (e.decoded[0]) { out += "  => "; out += e.decoded; }
        out += "\n";
    }
    sendNoCache();
    server.send(200, "text/plain; charset=utf-8", out);
}

void handleRfMode() {
    if (!server.hasArg("mode")) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"mode missing\"}"); return; }
    const String m = server.arg("mode");
    bool ok = false;
    if (m == "oregon") ok = setRfProtocolMode(RfProtocolMode::Oregon);
    else if (m == "lacrosse" || m == "technoline") ok = setRfProtocolMode(RfProtocolMode::LaCrosse);
    else if (m == "dual") ok = setRfProtocolMode(RfProtocolMode::Dual);
    else { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid mode\"}"); return; }
    if (!ok) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"RF mode NVS/runtime apply failed\"}");
        return;
    }

    resetRfSession(true);
    sendNoCache();
    server.send(200, "application/json", String("{\"ok\":true,\"mode\":\"") + rfProtocolModeName(getRfProtocolMode()) + "\"}");
}

void handleRfGain() {
    if (!server.hasArg("gain")) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"gain missing\"}");
        return;
    }
    const int g = server.arg("gain").toInt();
    // UI volutamente limitata a 0..3: 0=AGC raccomandato, 1=max, 2=alto, 3=medio.
    if (g < 0 || g > 3) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"gain must be 0..3\"}");
        return;
    }
    const RfProtocolMode mode = getRfProtocolMode();
    if (!setRadioGainForMode(mode, static_cast<uint8_t>(g))) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"radio rejected gain\"}");
        return;
    }
    // Anche un cambio gain apre una nuova sessione di misura: in questo modo
    // la percentuale di ricezione confronta realmente AGC/MAX/ALTO/MEDIO.
    resetRfSession(true);
    sendNoCache();
    String out = "{\"ok\":true,\"mode\":\"";
    out += rfProtocolModeName(mode);
    out += "\",\"gain\":" + String(g) + ",\"name\":\"" + String(radioGainName(static_cast<uint8_t>(g))) + "\"}";
    server.send(200, "application/json", out);
}


void handleRfProfile() {
    if (!server.hasArg("profile")) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"profile missing\"}");
        return;
    }
    const String p = server.arg("profile");
    bool ok = false;
    if (p == "stable") ok = setRadioFrontendProfile(RfFrontendProfile::Stable);
    else if (p == "wide") ok = setRadioFrontendProfile(RfFrontendProfile::WideAgc);
    else if (p == "max") ok = setRadioFrontendProfile(RfFrontendProfile::MaxGain);
    else if (p == "wide-max") ok = setRadioFrontendProfile(RfFrontendProfile::WideMaxGain);
    else if (p == "auto") ok = startRadioAutoCalibration();
    else if (p == "stop") { stopRadioAutoCalibration(); ok = true; }
    else {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid profile\"}");
        return;
    }
    if (!ok) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"profile rejected\"}");
        return;
    }
    resetRfSession(true);
    sendNoCache();
    String out = "{\"ok\":true,\"profile\":\"";
    out += radioFrontendProfileName(getRadioFrontendProfile());
    out += "\",\"bw_khz\":" + String(getRadioBandwidthKhz(), 1);
    out += ",\"gain\":" + String(getRadioGain()) + "}";
    server.send(200, "application/json", out);
}


String jsonEscapeString(const String &in) {
    String out;
    out.reserve(in.length() + 8);
    for (size_t i = 0; i < in.length(); ++i) {
        const char c = in[i];
        if (c == '\\' || c == '"') { out += '\\'; out += c; }
        else if (c == '\n') out += "\\n";
        else if (c == '\r') out += "\\r";
        else if (static_cast<uint8_t>(c) >= 0x20U) out += c;
    }
    return out;
}

String configBackupJson(bool includeSecrets) {
    const NetworkRuntimeConfig n = getNetworkConfig();
    const MqttRuntimeConfig m = getMqttConfig();
    String out;
    out.reserve(6500);
    out += "{\n  \"schema\":1";
    out += ",\n  \"firmware\":\"" + jsonEscapeString(String(firmwareVersion())) + "\"";
    out += ",\n  \"generated_by\":\"" + jsonEscapeString(networkHostname()) + "\"";
    out += ",\n  \"include_secrets\":"; out += includeSecrets ? "true" : "false";
    out += ",\n  \"wifi_credentials_included\":false";
    out += ",\n  \"hostname\":\"" + jsonEscapeString(n.hostname) + "\"";
    out += ",\n  \"use_static\":"; out += n.useStatic ? "true" : "false";
    out += ",\n  \"ip\":\"" + jsonEscapeString(n.ip) + "\"";
    out += ",\n  \"gateway\":\"" + jsonEscapeString(n.gateway) + "\"";
    out += ",\n  \"subnet\":\"" + jsonEscapeString(n.subnet) + "\"";
    out += ",\n  \"dns\":\"" + jsonEscapeString(n.dns) + "\"";
    out += ",\n  \"mqtt_enabled\":"; out += m.enabled ? "true" : "false";
    out += ",\n  \"mqtt_broker\":\"" + jsonEscapeString(m.broker) + "\"";
    out += ",\n  \"mqtt_port\":" + String(m.port);
    out += ",\n  \"mqtt_user\":\"" + jsonEscapeString(m.user) + "\"";
    if (includeSecrets) out += ",\n  \"mqtt_password\":\"" + jsonEscapeString(m.password) + "\"";
    out += ",\n  \"mqtt_client_id\":\"" + jsonEscapeString(m.clientId) + "\"";
    out += ",\n  \"mqtt_base_topic\":\"" + jsonEscapeString(m.baseTopic) + "\"";
    out += ",\n  \"mqtt_tls_mode\":" + String(static_cast<uint8_t>(m.tlsMode));
    out += ",\n  \"mqtt_ca_certificate\":\"" + jsonEscapeString(m.caCertificate) + "\"";
    out += ",\n  \"mqtt_fields_mask\":" + String(m.fieldsMask);
    out += ",\n  \"display_on\":"; out += displayEnabled() ? "true" : "false";
    const DisplayRuntimeConfig d = getDisplayConfig();
    out += ",\n  \"display_page_mask\":" + String(d.pageMask);
    out += ",\n  \"display_environment_fields\":" + String(d.environmentFields);
    out += ",\n  \"display_wind_rain_fields\":" + String(d.windRainFields);
    out += ",\n  \"display_technoline_fields\":" + String(d.technolineFields);
    out += ",\n  \"display_pressure_fields\":" + String(d.pressureFields);
    out += ",\n  \"display_status_fields\":" + String(d.statusFields);
    out += ",\n  \"display_lightning_fields\":" + String(d.lightningFields);
    out += ",\n  \"display_page_interval_sec\":" + String(d.pageIntervalSec);
    out += ",\n  \"display_contrast\":" + String(d.contrast);
    const ThermoChannelConfig tc = getThermoChannelConfig();
    out += ",\n  \"thermo_enabled_mask\":" + String(tc.enabledMask);
    out += ",\n  \"thermo_primary_channel\":" + String(tc.primaryChannel);
    out += ",\n  \"thermo_auto_discover\":"; out += tc.autoDiscover ? "true" : "false";
    const LightningConfig l = getLightningConfig();
    out += ",\n  \"as3935_enabled\":"; out += l.enabled ? "true" : "false";
    out += ",\n  \"as3935_indoor\":"; out += l.indoor ? "true" : "false";
    out += ",\n  \"as3935_i2c_address\":" + String(l.i2cAddress);
    out += ",\n  \"as3935_irq_pin\":" + String(static_cast<int>(l.irqPin));
    out += ",\n  \"as3935_noise_floor\":" + String(l.noiseFloor);
    out += ",\n  \"as3935_watchdog_threshold\":" + String(l.watchdogThreshold);
    out += ",\n  \"as3935_spike_rejection\":" + String(l.spikeRejection);
    out += ",\n  \"as3935_min_strikes\":" + String(l.minStrikes);
    out += ",\n  \"as3935_mask_disturbers\":"; out += l.maskDisturbers ? "true" : "false";
    out += ",\n  \"as3935_tuning_cap\":" + String(l.tuningCap);
    out += ",\n  \"as3935_auto_tune\":"; out += l.autoTune ? "true" : "false";
    out += ",\n  \"rf_mode\":" + String(static_cast<uint8_t>(getRfProtocolMode()));
    out += ",\n  \"rf_gain_oregon\":" + String(getRadioGainForMode(RfProtocolMode::Oregon));
    out += ",\n  \"rf_gain_technoline\":" + String(getRadioGainForMode(RfProtocolMode::LaCrosse));
    out += ",\n  \"rf_profile\":" + String(static_cast<uint8_t>(getRadioFrontendProfile()));
    out += ",\n  \"burst_extra\":"; out += burstRecoveryEnabled() ? "true" : "false";
    out += "\n}\n";
    return out;
}

bool jsonExtractValue(const String &json, const char *key, String &value, bool &quoted) {
    // Parser minimale, ma limitato alle chiavi dell'oggetto JSON di primo livello.
    // In questo modo una stringa PEM/password che contiene ad esempio "hostname"
    // non puo' essere scambiata per una chiave del backup.
    int depth = 0;
    int pos = 0;
    const int len = static_cast<int>(json.length());
    while (pos < len) {
        const char c = json[pos];
        if (c == '{') { depth++; pos++; continue; }
        if (c == '}') { depth--; pos++; continue; }
        if (c != '"') { pos++; continue; }

        // Legge una stringa intera; a depth==1 potrebbe essere una chiave oppure
        // un valore. Dopo la chiusura verifichiamo la presenza dei due punti.
        ++pos;
        bool escape = false;
        String token;
        while (pos < len) {
            const char ch = json[pos++];
            if (escape) {
                token += ch;
                escape = false;
            } else if (ch == '\\') {
                escape = true;
            } else if (ch == '"') {
                break;
            } else {
                token += ch;
            }
        }
        if (depth != 1 || token != key) continue;

        int p = pos;
        while (p < len && isspace(static_cast<unsigned char>(json[p]))) p++;
        if (p >= len || json[p] != ':') continue; // era un valore stringa, non una chiave
        p++;
        while (p < len && isspace(static_cast<unsigned char>(json[p]))) p++;
        if (p >= len) return false;

        value = "";
        quoted = json[p] == '"';
        if (quoted) {
            p++;
            bool valueEscape = false;
            while (p < len) {
                const char ch = json[p++];
                if (valueEscape) {
                    switch (ch) {
                        case 'n': value += '\n'; break;
                        case 'r': value += '\r'; break;
                        case 't': value += '\t'; break;
                        case '\\': value += '\\'; break;
                        case '"': value += '"'; break;
                        default: value += ch; break;
                    }
                    valueEscape = false;
                } else if (ch == '\\') {
                    valueEscape = true;
                } else if (ch == '"') {
                    return true;
                } else {
                    value += ch;
                }
            }
            return false;
        }

        const int valueStart = p;
        while (p < len && json[p] != ',' && json[p] != '}') p++;
        value = json.substring(valueStart, p);
        value.trim();
        return value.length() > 0;
    }
    return false;
}

bool jsonGetString(const String &json, const char *key, String &value) {
    bool quoted = false;
    String raw;
    if (!jsonExtractValue(json, key, raw, quoted) || !quoted) return false;
    value = raw;
    return true;
}

bool jsonGetBool(const String &json, const char *key, bool &value) {
    bool quoted = false;
    String raw;
    if (!jsonExtractValue(json, key, raw, quoted) || quoted) return false;
    raw.toLowerCase();
    if (raw == "true" || raw == "1") { value = true; return true; }
    if (raw == "false" || raw == "0") { value = false; return true; }
    return false;
}

bool jsonGetUInt(const String &json, const char *key, uint32_t &value) {
    bool quoted = false;
    String raw;
    if (!jsonExtractValue(json, key, raw, quoted) || quoted || raw.length() == 0 || raw[0] == '-') return false;
    char *end = nullptr;
    const unsigned long parsed = strtoul(raw.c_str(), &end, 10);
    if (!end || *end != '\0') return false;
    value = static_cast<uint32_t>(parsed);
    return true;
}

void handleConfigExport() {
    const bool includeSecrets = server.hasArg("secrets") && (server.arg("secrets") == "1" || server.arg("secrets") == "true");
    const String filename = networkHostname() + "-config-backup.json";
    sendNoCache();
    server.sendHeader("Content-Disposition", "attachment; filename=\"" + filename + "\"");
    server.send(200, "application/json; charset=utf-8", configBackupJson(includeSecrets));
}

void handleConfigImport() {
    const String body = server.arg("plain");
    if (body.length() < 20U || body.length() > 12000U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"backup size invalid\"}");
        return;
    }

    uint32_t schema = 0;
    if (!jsonGetUInt(body, "schema", schema) || schema != 1U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"unsupported backup schema\"}");
        return;
    }

    NetworkRuntimeConfig n = getNetworkConfig();
    MqttRuntimeConfig m = getMqttConfig();
    bool tmpBool = false;
    uint32_t tmpUInt = 0;
    String tmpString;

    if (jsonGetString(body, "hostname", tmpString)) n.hostname = tmpString;
    if (jsonGetBool(body, "use_static", tmpBool)) n.useStatic = tmpBool;
    if (jsonGetString(body, "ip", tmpString)) n.ip = tmpString;
    if (jsonGetString(body, "gateway", tmpString)) n.gateway = tmpString;
    if (jsonGetString(body, "subnet", tmpString)) n.subnet = tmpString;
    if (jsonGetString(body, "dns", tmpString)) n.dns = tmpString;

    if (jsonGetBool(body, "mqtt_enabled", tmpBool)) m.enabled = tmpBool;
    if (jsonGetString(body, "mqtt_broker", tmpString)) m.broker = tmpString;
    if (jsonGetUInt(body, "mqtt_port", tmpUInt)) {
        if (tmpUInt < 1U || tmpUInt > 65535U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid mqtt port\"}"); return; }
        m.port = static_cast<uint16_t>(tmpUInt);
    }
    if (jsonGetString(body, "mqtt_user", tmpString)) m.user = tmpString;
    bool replacePassword = jsonGetString(body, "mqtt_password", tmpString);
    if (replacePassword) m.password = tmpString;
    if (jsonGetString(body, "mqtt_client_id", tmpString)) m.clientId = tmpString;
    if (jsonGetString(body, "mqtt_base_topic", tmpString)) m.baseTopic = tmpString;
    if (jsonGetUInt(body, "mqtt_tls_mode", tmpUInt)) {
        if (tmpUInt > 2U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid mqtt tls mode\"}"); return; }
        m.tlsMode = static_cast<MqttTlsMode>(tmpUInt);
    }
    const bool replaceCa = jsonGetString(body, "mqtt_ca_certificate", tmpString);
    if (replaceCa) m.caCertificate = tmpString;
    if (jsonGetUInt(body, "mqtt_fields_mask", tmpUInt)) m.fieldsMask = tmpUInt & MQTT_FIELDS_ALL;

    bool displayOn = displayEnabled();
    jsonGetBool(body, "display_on", displayOn);
    DisplayRuntimeConfig displayCfg = getDisplayConfig();
    if (jsonGetUInt(body, "display_page_mask", tmpUInt)) displayCfg.pageMask = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_environment_fields", tmpUInt)) displayCfg.environmentFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_wind_rain_fields", tmpUInt)) displayCfg.windRainFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_technoline_fields", tmpUInt)) displayCfg.technolineFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_pressure_fields", tmpUInt)) displayCfg.pressureFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_status_fields", tmpUInt)) displayCfg.statusFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_lightning_fields", tmpUInt)) displayCfg.lightningFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_page_interval_sec", tmpUInt)) displayCfg.pageIntervalSec = static_cast<uint16_t>(tmpUInt);
    if (jsonGetUInt(body, "display_contrast", tmpUInt)) displayCfg.contrast = static_cast<uint8_t>(tmpUInt);
    if (!validateDisplayConfig(displayCfg)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid display backup values\"}");
        return;
    }

    const uint8_t previousThermoVisibleMask = thermoEffectiveMask();
    ThermoChannelConfig thermoCfg = getThermoChannelConfig();
    const uint8_t previousThermoPrimaryChannel = thermoCfg.primaryChannel;
    if (jsonGetUInt(body, "thermo_enabled_mask", tmpUInt)) {
        if (tmpUInt > 7U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid thermo enabled mask\"}"); return; }
        thermoCfg.enabledMask = static_cast<uint8_t>(tmpUInt);
    }
    if (jsonGetUInt(body, "thermo_primary_channel", tmpUInt)) {
        if (tmpUInt < 1U || tmpUInt > 3U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid thermo primary channel\"}"); return; }
        thermoCfg.primaryChannel = static_cast<uint8_t>(tmpUInt);
    }
    if (jsonGetBool(body, "thermo_auto_discover", tmpBool)) thermoCfg.autoDiscover = tmpBool;
    if (!saveThermoChannelConfig(thermoCfg)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid thermo channel backup values\"}");
        return;
    }
    if (station) syncPrimaryThermoState(*station);
    reconcileThermoMqttRetained(previousThermoVisibleMask, previousThermoPrimaryChannel);

    LightningConfig lightningCfg = getLightningConfig();
    if (jsonGetBool(body, "as3935_enabled", tmpBool)) lightningCfg.enabled = tmpBool;
    if (jsonGetBool(body, "as3935_indoor", tmpBool)) lightningCfg.indoor = tmpBool;
    if (jsonGetUInt(body, "as3935_i2c_address", tmpUInt)) lightningCfg.i2cAddress = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "as3935_irq_pin", tmpUInt)) {
        if (tmpUInt > 127U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid AS3935 IRQ in backup\"}"); return; }
        lightningCfg.irqPin = static_cast<int8_t>(tmpUInt);
    }
    if (jsonGetUInt(body, "as3935_noise_floor", tmpUInt)) lightningCfg.noiseFloor = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "as3935_watchdog_threshold", tmpUInt)) lightningCfg.watchdogThreshold = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "as3935_spike_rejection", tmpUInt)) lightningCfg.spikeRejection = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "as3935_min_strikes", tmpUInt)) lightningCfg.minStrikes = static_cast<uint8_t>(tmpUInt);
    if (jsonGetBool(body, "as3935_mask_disturbers", tmpBool)) lightningCfg.maskDisturbers = tmpBool;
    if (jsonGetUInt(body, "as3935_tuning_cap", tmpUInt)) lightningCfg.tuningCap = static_cast<uint8_t>(tmpUInt);
    if (jsonGetBool(body, "as3935_auto_tune", tmpBool)) lightningCfg.autoTune = tmpBool;
    if (!validateLightningConfig(lightningCfg)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid AS3935 backup values\"}");
        return;
    }

    uint32_t rfMode = static_cast<uint8_t>(getRfProtocolMode());
    uint32_t gainO = getRadioGainForMode(RfProtocolMode::Oregon);
    uint32_t gainL = getRadioGainForMode(RfProtocolMode::LaCrosse);
    uint32_t profile = static_cast<uint8_t>(getRadioFrontendProfile());
    bool burstExtra = burstRecoveryEnabled();
    jsonGetUInt(body, "rf_mode", rfMode);
    jsonGetUInt(body, "rf_gain_oregon", gainO);
    jsonGetUInt(body, "rf_gain_technoline", gainL);
    jsonGetUInt(body, "rf_profile", profile);
    jsonGetBool(body, "burst_extra", burstExtra);
    if (rfMode > 2U || gainO > 3U || gainL > 3U || profile > static_cast<uint8_t>(RfFrontendProfile::Manual)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid RF backup values\"}");
        return;
    }
    if (profile == static_cast<uint8_t>(RfFrontendProfile::AutoScan)) profile = static_cast<uint8_t>(RfFrontendProfile::Stable);

    if (!validateNetworkConfig(n) || !validateMqttConfig(m, replacePassword, replaceCa)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"backup contains invalid network or MQTT values\"}");
        return;
    }

    bool netChanged = false;
    if (!saveMqttConfig(m, replacePassword, replaceCa) || !saveNetworkConfig(n, netChanged)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"could not save imported configuration\"}");
        return;
    }
    if (!setDisplayEnabled(displayOn)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"could not persist display power setting\"}");
        return;
    }
    bool displayChanged = false;
    if (!saveDisplayConfig(displayCfg, displayChanged)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"could not save display configuration\"}");
        return;
    }
    bool lightningChanged = false;
    if (!saveLightningConfig(lightningCfg, lightningChanged)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"could not save AS3935 configuration\"}");
        return;
    }

    // Per rendere persistente il profilo Oregon anche se il backup proviene da
    // una sessione Technoline, applichiamo il profilo in Oregon e poi torniamo
    // alla modalita' RF richiesta. L'import e' un'operazione occasionale.
    const RfProtocolMode desiredMode = static_cast<RfProtocolMode>(rfMode);
    bool rfSaved = setRfProtocolMode(RfProtocolMode::Oregon);
    rfSaved = setRadioGainForMode(RfProtocolMode::LaCrosse, static_cast<uint8_t>(gainL)) && rfSaved;
    if (profile <= static_cast<uint8_t>(RfFrontendProfile::WideMaxGain)) {
        rfSaved = setRadioFrontendProfile(static_cast<RfFrontendProfile>(profile)) && rfSaved;
    } else {
        rfSaved = setRadioGainForMode(RfProtocolMode::Oregon, static_cast<uint8_t>(gainO)) && rfSaved;
    }
    rfSaved = setBurstRecoveryEnabled(burstExtra) && rfSaved;
    rfSaved = setRfProtocolMode(desiredMode) && rfSaved;
    if (!rfSaved) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"could not persist imported RF configuration\"}");
        return;
    }
    resetRfSession(true);

    rebootAtMs = millis() + 1500UL;
    sendNoCache();
    String out = "{\"ok\":true,\"rebooting\":true,\"network_changed\":";
    out += netChanged ? "true" : "false";
    out += ",\"password_imported\":"; out += replacePassword ? "true" : "false";
    out += "}";
    server.send(200, "application/json", out);
}


void handleBurstExtra() {
    if (!server.hasArg("enabled")) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"enabled missing\"}");
        return;
    }
    const String v = server.arg("enabled");
    const bool enabled = v == "1" || v == "true" || v == "on";
    if (!setBurstRecoveryEnabled(enabled)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"burst setting rejected\"}");
        return;
    }
    // Una nuova sessione rende confrontabile l'impatto del Burst EXTRA sul
    // WGR800 e sul link Technoline.
    resetRfSession(false);
    sendNoCache();
    String out = "{\"ok\":true,\"enabled\":";
    out += enabled ? "true" : "false";
    out += "}";
    server.send(200, "application/json", out);
}


void handleWgrProbe() {
    if (!server.hasArg("enabled")) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"enabled missing\"}");
        return;
    }
    const String v = server.arg("enabled");
    const bool enabled = v == "1" || v == "true" || v == "on";
    if (!setWgrProbeEnabled(enabled)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"wgr probe rejected\"}");
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"enabled\":";
    out += enabled ? "true" : "false";
    out += ",\"persistent\":false}";
    server.send(200, "application/json", out);
}

void handleWgrProbeHistory() {
    WgrProbeRecord rows[16];
    const uint8_t count = getWgrProbeHistory(rows, 16);
    String out;
    out.reserve(3600);
    out = "[";
    for (uint8_t i = 0; i < count; ++i) {
        if (i) out += ",";
        const WgrProbeRecord &r = rows[i];
        out += "{\"ms\":" + String(r.endedAtMs);
        out += ",\"duration_ms\":" + String(r.durationMs);
        out += ",\"edges\":" + String(r.edges);
        out += ",\"rssi\":" + jsonFloat(r.rssi, 1);
        out += ",\"match_pct\":" + String(r.timingMatchPct);
        out += ",\"header\":" + String(r.decodedHeader);
        out += ",\"osv3_like\":"; out += r.osv3Like ? "true" : "false";
        out += ",\"cadence14\":"; out += r.cadence14 ? "true" : "false";
        out += "}";
    }
    out += "]";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleMqttConfigGet() {
    const MqttRuntimeConfig c = getMqttConfig();
    String out;
    out.reserve(5600);
    out = "{\"enabled\":"; out += c.enabled ? "true" : "false";
    out += ",\"connected\":"; out += mqttRuntimeConnected() ? "true" : "false";
    out += ",\"broker\":\"" + jsonEscapeString(c.broker) + "\"";
    out += ",\"port\":" + String(c.port);
    out += ",\"user\":\"" + jsonEscapeString(c.user) + "\"";
    out += ",\"has_password\":"; out += c.password.length() ? "true" : "false";
    out += ",\"client_id\":\"" + jsonEscapeString(c.clientId) + "\"";
    out += ",\"base_topic\":\"" + jsonEscapeString(c.baseTopic) + "\"";
    out += ",\"tls_mode\":" + String(static_cast<uint8_t>(c.tlsMode));
    out += ",\"tls_name\":\"" + String(mqttTlsModeName(c.tlsMode)) + "\"";
    out += ",\"has_ca\":"; out += c.caCertificate.length() ? "true" : "false";
    out += ",\"ca_certificate\":\"" + jsonEscapeString(c.caCertificate) + "\"";
    out += ",\"fields_mask\":" + String(c.fieldsMask);
    out += "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleMqttConfigPost() {
    MqttRuntimeConfig c = getMqttConfig();
    if (server.hasArg("enabled")) c.enabled = server.arg("enabled") == "1" || server.arg("enabled") == "true" || server.arg("enabled") == "on";
    if (server.hasArg("broker")) c.broker = server.arg("broker");
    if (server.hasArg("port")) {
        const long p = server.arg("port").toInt();
        if (p < 1 || p > 65535) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid port\"}"); return; }
        c.port = static_cast<uint16_t>(p);
    }
    if (server.hasArg("user")) c.user = server.arg("user");
    if (server.hasArg("client_id")) c.clientId = server.arg("client_id");
    if (server.hasArg("base_topic")) c.baseTopic = server.arg("base_topic");
    if (server.hasArg("tls_mode")) {
        const int m = server.arg("tls_mode").toInt();
        if (m < 0 || m > 2) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid tls mode\"}"); return; }
        c.tlsMode = static_cast<MqttTlsMode>(m);
    }
    if (server.hasArg("fields_mask")) c.fieldsMask = static_cast<uint32_t>(strtoul(server.arg("fields_mask").c_str(), nullptr, 10));

    bool replacePassword = false;
    if (server.hasArg("clear_password") && (server.arg("clear_password") == "1" || server.arg("clear_password") == "true" || server.arg("clear_password") == "on")) {
        c.password = "";
        replacePassword = true;
    } else if (server.hasArg("password") && server.arg("password").length() > 0) {
        c.password = server.arg("password");
        replacePassword = true;
    }

    bool replaceCaCertificate = false;
    if (server.hasArg("ca_certificate")) {
        if (server.arg("ca_certificate").length() > 3900U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"CA certificate too large (max 3900 bytes)\"}"); return; }
        c.caCertificate = server.arg("ca_certificate");
        replaceCaCertificate = true;
    }

    if (!saveMqttConfig(c, replacePassword, replaceCaCertificate)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid mqtt/tls configuration\"}");
        return;
    }
    sendNoCache();
    server.send(200, "application/json", "{\"ok\":true}");
}

void handleMqttConfigReset() {
    if (!resetMqttConfigToDefaults()) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"MQTT NVS reset verification failed\"}");
        return;
    }
    sendNoCache();
    server.send(200, "application/json", "{\"ok\":true}");
}

void handleDeviceRestart() {
    rebootAtMs = millis() + 900UL;
    sendNoCache();
    server.send(200, "application/json", "{\"ok\":true,\"rebooting\":true}");
}

void handleDevicePowerOff() {
    if (!controllerSoftPowerOffEnabled()) {
        server.send(403, "application/json", "{\"ok\":false,\"error\":\"soft power-off disabled\"}");
        return;
    }
    powerOffAtMs = millis() + 900UL;
    sendNoCache();
    String out = "{\"ok\":true,\"powering_off\":true,\"mode\":\"deep_sleep\",\"wake_hint\":\"";
    out += jsonEscapeString(controllerWakeHint());
    out += "\"}";
    server.send(200, "application/json", out);
}

void handleNetworkConfigGet() {
    const NetworkRuntimeConfig c = getNetworkConfig();
    String out;
    out.reserve(520);
    out = "{\"hostname\":\"" + jsonEscapeString(c.hostname) + "\"";
    out += ",\"mdns\":\"" + jsonEscapeString(networkMdnsName()) + "\"";
    out += ",\"mdns_active\":"; out += networkMdnsActive() ? "true" : "false";
    out += ",\"use_static\":"; out += c.useStatic ? "true" : "false";
    out += ",\"ip\":\"" + jsonEscapeString(c.ip) + "\"";
    out += ",\"gateway\":\"" + jsonEscapeString(c.gateway) + "\"";
    out += ",\"subnet\":\"" + jsonEscapeString(c.subnet) + "\"";
    out += ",\"dns\":\"" + jsonEscapeString(c.dns) + "\"";
    out += ",\"actual_ip\":\"" + jsonEscapeString(wifiIpAddress()) + "\"}";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleNetworkConfigPost() {
    NetworkRuntimeConfig c = getNetworkConfig();
    if (server.hasArg("hostname")) c.hostname = server.arg("hostname");
    if (server.hasArg("use_static")) c.useStatic = server.arg("use_static") == "1" || server.arg("use_static") == "true" || server.arg("use_static") == "on";
    if (server.hasArg("ip")) c.ip = server.arg("ip");
    if (server.hasArg("gateway")) c.gateway = server.arg("gateway");
    if (server.hasArg("subnet")) c.subnet = server.arg("subnet");
    if (server.hasArg("dns")) c.dns = server.arg("dns");
    bool changed = false;
    if (!saveNetworkConfig(c, changed)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid network configuration\"}");
        return;
    }
    const bool reboot = changed && server.hasArg("reboot") && (server.arg("reboot") == "1" || server.arg("reboot") == "true");
    if (reboot) rebootAtMs = millis() + 1200UL;
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":"; out += changed ? "true" : "false";
    out += ",\"rebooting\":"; out += reboot ? "true" : "false";
    out += ",\"new_ip\":\"" + jsonEscapeString(c.ip) + "\"";
    out += ",\"hostname\":\"" + jsonEscapeString(c.hostname) + "\"";
    out += ",\"mdns\":\"" + jsonEscapeString(c.hostname + ".local") + "\"}";
    server.send(200, "application/json", out);
}

void handleNetworkConfigReset() {
    bool changed = false;
    if (!resetNetworkConfigToDefaults(changed)) {
        server.send(500, "application/json", "{\"ok\":false}"); return;
    }
    if (changed) rebootAtMs = millis() + 1200UL;
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":"; out += changed ? "true" : "false";
    out += ",\"rebooting\":"; out += changed ? "true" : "false"; out += "}";
    server.send(200, "application/json", out);
}


// AS3935_UI_INTEGRATED: il rilevatore fulmini usa lo stesso WebServer della dashboard.
bool lightningBoolArg(const char *name) {
    if (!server.hasArg(name)) return false;
    const String v = server.arg(name);
    return v == "1" || v == "true" || v == "on" || v == "yes";
}

bool lightningUIntArg(const char *name, uint32_t &value) {
    if (!server.hasArg(name)) return false;
    const String raw = server.arg(name);
    if (!raw.length()) return false;
    char *end = nullptr;
    const unsigned long parsed = strtoul(raw.c_str(), &end, 0);
    if (!end || *end != '\0') return false;
    value = static_cast<uint32_t>(parsed);
    return true;
}

void handleLightningState() {
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", lightningStateJson());
}

void handleLightningConfigGet() {
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", lightningConfigJson());
}

void handleLightningConfigPost() {
    LightningConfig c = getLightningConfig();
    if (server.hasArg("enabled")) c.enabled = lightningBoolArg("enabled");
    if (server.hasArg("mode")) c.indoor = server.arg("mode") != "outdoor";
    if (server.hasArg("mask_disturbers")) c.maskDisturbers = lightningBoolArg("mask_disturbers");
    if (server.hasArg("auto_tune")) c.autoTune = lightningBoolArg("auto_tune");

    uint32_t v = 0;
    if (server.hasArg("i2c_address")) {
        if (!lightningUIntArg("i2c_address", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid i2c_address\"}"); return; }
        c.i2cAddress = static_cast<uint8_t>(v);
    }
    if (server.hasArg("irq_pin")) {
        if (!lightningUIntArg("irq_pin", v) || v > 127U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid irq_pin\"}"); return; }
        c.irqPin = static_cast<int8_t>(v);
    }
    if (server.hasArg("noise_floor")) {
        if (!lightningUIntArg("noise_floor", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid noise_floor\"}"); return; }
        c.noiseFloor = static_cast<uint8_t>(v);
    }
    if (server.hasArg("watchdog_threshold")) {
        if (!lightningUIntArg("watchdog_threshold", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid watchdog_threshold\"}"); return; }
        c.watchdogThreshold = static_cast<uint8_t>(v);
    }
    if (server.hasArg("spike_rejection")) {
        if (!lightningUIntArg("spike_rejection", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid spike_rejection\"}"); return; }
        c.spikeRejection = static_cast<uint8_t>(v);
    }
    if (server.hasArg("min_strikes")) {
        if (!lightningUIntArg("min_strikes", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid min_strikes\"}"); return; }
        c.minStrikes = static_cast<uint8_t>(v);
    }
    if (server.hasArg("tuning_cap")) {
        if (!lightningUIntArg("tuning_cap", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid tuning_cap\"}"); return; }
        c.tuningCap = static_cast<uint8_t>(v);
    }

    if (!validateLightningConfig(c)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"configuration rejected\"}");
        return;
    }
    bool changed = false;
    if (!saveLightningConfig(c, changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"NVS save failed\"}");
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":";
    out += changed ? "true" : "false";
    out += ",\"state\":" + lightningStateJson() + "}";
    server.send(200, "application/json; charset=utf-8", out);
}

void handleLightningReset() {
    bool changed = false;
    if (!resetLightningConfigToDefaults(changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"reset failed\"}");
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":";
    out += changed ? "true" : "false";
    out += "}";
    server.send(200, "application/json", out);
}

void handleLightningReinit() {
    const bool ok = reinitializeLightning();
    sendNoCache();
    String out = "{\"ok\":";
    out += ok ? "true" : "false";
    out += ",\"state\":" + lightningStateJson() + "}";
    server.send(ok ? 200 : 503, "application/json", out);
}

void handleBursts() {
    RfBurstRecord rows[16];
    const uint8_t count = getRfBurstHistory(rows, 16);
    String out;
    out.reserve(5000);
    out = "[";
    for (uint8_t i = 0; i < count; ++i) {
        if (i) out += ",";
        const RfBurstRecord &b = rows[i];
        out += "{\"ms\":" + String(b.endedAtMs);
        out += ",\"duration_ms\":" + String(b.durationMs);
        out += ",\"edges\":" + String(b.edges);
        out += ",\"rssi\":" + jsonFloat(b.rssi, 1);
        out += ",\"match_pct\":" + String(b.timingMatchPct);
        out += ",\"osv3_like\":"; out += b.osv3Like ? "true" : "false";
        out += ",\"adaptive_recovered\":"; out += b.adaptiveRecovered ? "true" : "false";
        out += ",\"technoline_like\":"; out += b.likelyTechnoline ? "true" : "false";
        out += ",\"on_short_us\":" + String(b.onShortUs);
        out += ",\"on_long_us\":" + String(b.onLongUs);
        out += ",\"off_short_us\":" + String(b.offShortUs);
        out += ",\"off_long_us\":" + String(b.offLongUs);
        out += "}";
    }
    out += "]";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleRoot() {
    sendNoCache();
    server.sendHeader("Content-Encoding", "gzip");
    server.send_P(200, PSTR("text/html; charset=utf-8"), reinterpret_cast<PGM_P>(WEB_UI_GZ), WEB_UI_GZ_LEN);
}

void fillDecoded(char *dst, size_t size, const WeatherReading *r) {
    if (!r) { snprintf(dst, size, "checksum/parser KO"); return; }
    char value[78]{};
    switch (r->type) {
        case SensorType::ThermoHygro:
            snprintf(value, sizeof(value), "T=%.1fC H=%.0f%%", r->temperatureC, r->humidityPct); break;
        case SensorType::Wind:
            snprintf(value, sizeof(value), "avg=%.1f current=%.1f dir=%.1f %s", r->windAverageKmh, r->windGustKmh,
                     r->windDirectionDeg, windDirectionName(r->windDirectionIndex)); break;
        case SensorType::Rain:
            snprintf(value, sizeof(value), "tot=%.2fmm rate=%.2f", r->rainTotalMm, r->rainRateMmH); break;
        case SensorType::UV:
            snprintf(value, sizeof(value), "UV=%d", r->uvIndex); break;
        default:
            snprintf(value, sizeof(value), "unknown"); break;
    }
    snprintf(dst, size, "%s | %s %04X ch%u BAT=%s", value, sensorModelName(r->sensorCode),
             r->sensorCode, r->channel, batteryStatusName(*r));
}
} // namespace

void initWeb(StationState &stateRef) {
#if WEB_ENABLE
    station = &stateRef;
    // La modalita' RF persistente viene inizializzata poco dopo initWeb().
    // ensureRfSession() al primo /api/state riallinea automaticamente la
    // sessione alla modalita' effettiva letta dalla NVS.
    rfSession = RfSessionState{};
    server.on("/", HTTP_GET, handleRoot);
    server.on("/api/state", HTTP_GET, handleState);
    server.on("/api/raw", HTTP_GET, handleRaw);
    server.on("/api/raw.txt", HTTP_GET, handleRawText);
    server.on("/api/bursts", HTTP_GET, handleBursts);
    server.on("/api/rfmode", HTTP_POST, handleRfMode);
    server.on("/api/rfgain", HTTP_POST, handleRfGain);
    server.on("/api/rfprofile", HTTP_POST, handleRfProfile);
    server.on("/api/burstextra", HTTP_POST, handleBurstExtra);
    server.on("/api/wgrprobe", HTTP_POST, handleWgrProbe);
    server.on("/api/wgrprobe/history", HTTP_GET, handleWgrProbeHistory);
    server.on("/api/mqtt", HTTP_GET, handleMqttConfigGet);
    server.on("/api/mqtt", HTTP_POST, handleMqttConfigPost);
    server.on("/api/mqtt/reset", HTTP_POST, handleMqttConfigReset);
    server.on("/api/network", HTTP_GET, handleNetworkConfigGet);
    server.on("/api/network", HTTP_POST, handleNetworkConfigPost);
    server.on("/api/network/reset", HTTP_POST, handleNetworkConfigReset);
    server.on("/api/config/export", HTTP_GET, handleConfigExport);
    server.on("/api/config/import", HTTP_POST, handleConfigImport);
    server.on("/api/thermo/config", HTTP_GET, handleThermoConfigGet);
    server.on("/api/thermo/config", HTTP_POST, handleThermoConfigPost);
    server.on("/api/thermo/reset", HTTP_POST, handleThermoConfigReset);
    server.on("/api/display", HTTP_POST, handleDisplayPower);
    server.on("/api/display/config", HTTP_GET, handleDisplayConfigGet);
    server.on("/api/display/config", HTTP_POST, handleDisplayConfigPost);
    server.on("/api/display/reset", HTTP_POST, handleDisplayConfigReset);
    server.on("/api/as3935/state", HTTP_GET, handleLightningState);
    server.on("/api/as3935/config", HTTP_GET, handleLightningConfigGet);
    server.on("/api/as3935/config", HTTP_POST, handleLightningConfigPost);
    server.on("/api/as3935/reset", HTTP_POST, handleLightningReset);
    server.on("/api/as3935/reinit", HTTP_POST, handleLightningReinit);
    server.on("/api/poweroff", HTTP_POST, handleDevicePowerOff);
    server.on("/api/restart", HTTP_POST, handleDeviceRestart);
    server.onNotFound([](){ server.send(404, "text/plain", "Not found"); });
    Serial.println(F("[WEB] configurato; partira' appena il WiFi sara' connesso"));
#else
    (void)stateRef;
#endif
}

void serviceWeb() {
#if WEB_ENABLE
    if (wifiConnected()) {
        if (!webStarted) {
            server.begin();
            webStarted = true;
            Serial.print(F("[WEB] HTTP ATTIVO: http://"));
            Serial.print(wifiIpAddress());
            Serial.println('/');
        }
        server.handleClient();
    }
    if (powerOffAtMs && static_cast<int32_t>(millis() - powerOffAtMs) >= 0) {
        powerOffAtMs = 0;
        Serial.println(F("[WEB] spegnimento controller richiesto"));
        delay(50);
        enterControllerDeepSleep();
    }
    if (rebootAtMs && static_cast<int32_t>(millis() - rebootAtMs) >= 0) {
        Serial.println(F("[WEB] riavvio richiesto dalla configurazione"));
        delay(80);
        ESP.restart();
    }
#endif
}

void recordWebPacket(const OregonPacket &packet, const WeatherReading *reading, bool accepted) {
#if WEB_ENABLE
    if (accepted && reading) {
        ensureRfSession();
        noteOregonSessionSensor(*reading, packet.decodeSource);
    }
    RawEntry &e = history[historyHead];
    e = RawEntry{};
    e.ms = packet.receivedAtMs;
    e.rssi = packet.rssi;
    e.len = packet.length;
    e.sensorId = packet.length ? packet.bytes[0] : 0;
    e.sensorCode = reading ? reading->sensorCode : 0;
    e.source = packet.decodeSource;
    snprintf(e.protocol, sizeof(e.protocol), "Oregon");
    snprintf(e.sourceName, sizeof(e.sourceName), "%s", oregonDecodeSourceName(static_cast<OregonDecodeSource>(packet.decodeSource)));
    e.accepted = accepted;
    e.batteryKnown = reading ? reading->batteryStatusValid : false;
    e.batteryLow = reading ? reading->batteryLow : false;
    snprintf(e.type, sizeof(e.type), "%s", reading ? sensorTypeName(reading->type) : "rejected");
    fillDecoded(e.decoded, sizeof(e.decoded), reading);

    size_t pos = 0;
    for (uint8_t i = 0; i < packet.length && pos + 4 < sizeof(e.hex); ++i) {
        pos += snprintf(e.hex + pos, sizeof(e.hex) - pos, "%02X%s",
                        packet.bytes[i], (i + 1 < packet.length) ? " " : "");
    }

    historyHead = static_cast<uint8_t>((historyHead + 1U) % RAW_HISTORY_SIZE);
    if (historyCount < RAW_HISTORY_SIZE) historyCount++;
#else
    (void)packet; (void)reading; (void)accepted;
#endif
}


void recordWebLaCrossePacket(const LaCrossePacket &packet, const LaCrosseReading *reading, bool accepted) {
#if WEB_ENABLE
    RawEntry &e = history[historyHead];
    e = RawEntry{};
    e.ms = packet.receivedAtMs;
    e.rssi = packet.rssi;
    e.len = LACROSSE_WS23XX_NIBBLES;
    e.sensorId = reading ? reading->sensorId : 0;
    e.sensorCode = 0;
    e.source = 0;
    snprintf(e.protocol, sizeof(e.protocol), "Technoline");
    const char *lcSource = packet.decoder == 1U ? "pwm-leader" : (packet.decoder == 2U ? "pwm-burst" : "pwm-window");
    snprintf(e.sourceName, sizeof(e.sourceName), "%s", lcSource);
    e.accepted = accepted;
    snprintf(e.type, sizeof(e.type), "%s", reading ? laCrosseTypeName(reading->type) : "rejected");
    if (!reading) snprintf(e.decoded, sizeof(e.decoded), "validation/parser KO");
    else {
        switch (reading->type) {
            case LaCrosseType::Temperature: snprintf(e.decoded,sizeof(e.decoded),"T=%.1fC | %s id=%02X BAT=N/D",reading->temperatureC,laCrosseModelName(reading->wsId),reading->sensorId); break;
            case LaCrosseType::Humidity: snprintf(e.decoded,sizeof(e.decoded),"H=%.0f%% | %s id=%02X BAT=N/D",reading->humidityPct,laCrosseModelName(reading->wsId),reading->sensorId); break;
            case LaCrosseType::Rain: snprintf(e.decoded,sizeof(e.decoded),"rain=%.2fmm | %s id=%02X BAT=N/D",reading->rainTotalMm,laCrosseModelName(reading->wsId),reading->sensorId); break;
            case LaCrosseType::Wind: snprintf(e.decoded,sizeof(e.decoded),"wind=%.1f dir=%.1f %s | id=%02X",reading->windKmh,reading->directionDeg,laCrosseWindDirectionName(reading->directionIndex),reading->sensorId); break;
            case LaCrosseType::Gust: snprintf(e.decoded,sizeof(e.decoded),"gust=%.1f dir=%.1f %s | id=%02X",reading->gustKmh,reading->directionDeg,laCrosseWindDirectionName(reading->directionIndex),reading->sensorId); break;
            default: snprintf(e.decoded,sizeof(e.decoded),"unknown"); break;
        }
    }
    size_t pos=0;
    for(uint8_t i=0;i<LACROSSE_WS23XX_NIBBLES && pos+3<sizeof(e.hex);++i) pos += snprintf(e.hex+pos,sizeof(e.hex)-pos,"%X%s",packet.nibbles[i], i+1<LACROSSE_WS23XX_NIBBLES?" ":"");
    historyHead = static_cast<uint8_t>((historyHead + 1U) % RAW_HISTORY_SIZE);
    if (historyCount < RAW_HISTORY_SIZE) historyCount++;
#else
    (void)packet; (void)reading; (void)accepted;
#endif
}
