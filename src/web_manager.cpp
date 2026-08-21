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

namespace {
WebServer server(80);
StationState *station = nullptr;
bool webStarted = false;
uint32_t rebootAtMs = 0;
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
struct RfSessionState {
    bool initialized{false};
    RfProtocolMode mode{RfProtocolMode::Oregon};
    uint32_t startedMs{0};
    uint32_t baseThermo{0};
    uint32_t baseWind{0};
    uint32_t baseRain{0};
    uint32_t baseUv{0};
    uint32_t baseLcTemp{0};
    uint32_t baseLcHum{0};
    uint32_t baseLcRain{0};
    uint32_t baseLcWind{0};
    uint32_t baseLcGust{0};
    uint32_t baseLcValid{0};
    uint32_t lcFirstValidMs{0};
};
RfSessionState rfSession{};

bool timestampInSession(uint32_t updatedMs, uint32_t startMs) {
    if (updatedMs == 0 || startMs == 0) return false;
    return static_cast<int32_t>(updatedMs - startMs) >= 0;
}

uint32_t expectedPackets(uint32_t elapsedMs, uint32_t cadenceMs) {
    if (cadenceMs == 0 || elapsedMs < cadenceMs) return 0;
    return elapsedMs / cadenceMs;
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
    rfSession.baseThermo = station->thermoPacketCount;
    rfSession.baseWind = station->windPacketCount;
    rfSession.baseRain = station->rainPacketCount;
    rfSession.baseUv = station->uvPacketCount;
    rfSession.baseLcTemp = station->lacrosse.temperaturePacketCount;
    rfSession.baseLcHum = station->lacrosse.humidityPacketCount;
    rfSession.baseLcRain = station->lacrosse.rainPacketCount;
    rfSession.baseLcWind = station->lacrosse.windPacketCount;
    rfSession.baseLcGust = station->lacrosse.gustPacketCount;
    rfSession.baseLcValid = station->lacrosse.validPacketCount;
    rfSession.lcFirstValidMs = 0;
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

    const uint32_t sessionThermo = station->thermoPacketCount - rfSession.baseThermo;
    const uint32_t sessionWind = station->windPacketCount - rfSession.baseWind;
    const uint32_t sessionRain = station->rainPacketCount - rfSession.baseRain;
    const uint32_t sessionUv = station->uvPacketCount - rfSession.baseUv;
    const auto &lcState = station->lacrosse;
    const uint32_t sessionLcTemp = lcState.temperaturePacketCount - rfSession.baseLcTemp;
    const uint32_t sessionLcHum = lcState.humidityPacketCount - rfSession.baseLcHum;
    const uint32_t sessionLcRain = lcState.rainPacketCount - rfSession.baseLcRain;
    const uint32_t sessionLcWind = lcState.windPacketCount - rfSession.baseLcWind;
    const uint32_t sessionLcGust = lcState.gustPacketCount - rfSession.baseLcGust;
    const uint32_t sessionLcValid = lcState.validPacketCount - rfSession.baseLcValid;

    // Cadenze osservate/nominali dei sensori Oregon usate solo per stimare la
    // qualita' di acquisizione della sessione corrente.
    constexpr uint32_t THERMO_CADENCE_MS = 53000UL;
    constexpr uint32_t WIND_CADENCE_MS = 14000UL;
    constexpr uint32_t RAIN_CADENCE_MS = 47000UL;
    constexpr uint32_t UV_CADENCE_MS = 73000UL;

    const uint32_t expThermo = oregonActive ? expectedPackets(sessionElapsedMs, THERMO_CADENCE_MS) : 0;
    const uint32_t expWind = oregonActive ? expectedPackets(sessionElapsedMs, WIND_CADENCE_MS) : 0;
    const uint32_t expRain = oregonActive ? expectedPackets(sessionElapsedMs, RAIN_CADENCE_MS) : 0;
    const uint32_t expUv = oregonActive ? expectedPackets(sessionElapsedMs, UV_CADENCE_MS) : 0;

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
    out += ",\"thermo_expected\":" + String(expThermo);
    out += ",\"wind_expected\":" + String(expWind);
    out += ",\"rain_expected\":" + String(expRain);
    out += ",\"uv_expected\":" + String(expUv);
    out += ",\"thermo_quality_pct\":" + String(qualityPct(sessionThermo, expThermo));
    out += ",\"wind_quality_pct\":" + String(qualityPct(sessionWind, expWind));
    out += ",\"rain_quality_pct\":" + String(qualityPct(sessionRain, expRain));
    out += ",\"uv_quality_pct\":" + String(qualityPct(sessionUv, expUv));
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
    if (m == "oregon") setRfProtocolMode(RfProtocolMode::Oregon);
    else if (m == "lacrosse" || m == "technoline") setRfProtocolMode(RfProtocolMode::LaCrosse);
    else if (m == "dual") setRfProtocolMode(RfProtocolMode::Dual);
    else { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid mode\"}"); return; }

    // Nuova sessione: i valori storici restano nello StationState, mentre
    // acquisizione/qualita' ripartono da zero e lo storico RAW viene pulito.
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
    out += ",\n  \"display_page_interval_sec\":" + String(d.pageIntervalSec);
    out += ",\n  \"display_contrast\":" + String(d.contrast);
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
    if (jsonGetUInt(body, "display_page_interval_sec", tmpUInt)) displayCfg.pageIntervalSec = static_cast<uint16_t>(tmpUInt);
    if (jsonGetUInt(body, "display_contrast", tmpUInt)) displayCfg.contrast = static_cast<uint8_t>(tmpUInt);
    if (!validateDisplayConfig(displayCfg)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid display backup values\"}");
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

    // Per rendere persistente il profilo Oregon anche se il backup proviene da
    // una sessione Technoline, applichiamo il profilo in Oregon e poi torniamo
    // alla modalita' RF richiesta. L'import e' un'operazione occasionale.
    const RfProtocolMode desiredMode = static_cast<RfProtocolMode>(rfMode);
    setRfProtocolMode(RfProtocolMode::Oregon);
    setRadioGainForMode(RfProtocolMode::LaCrosse, static_cast<uint8_t>(gainL));
    if (profile <= static_cast<uint8_t>(RfFrontendProfile::WideMaxGain)) {
        setRadioFrontendProfile(static_cast<RfFrontendProfile>(profile));
    } else {
        setRadioGainForMode(RfProtocolMode::Oregon, static_cast<uint8_t>(gainO));
    }
    setBurstRecoveryEnabled(burstExtra);
    setRfProtocolMode(desiredMode);
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
    static const char PAGE[] PROGMEM = R"HTML(
<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Oregon + Technoline Gateway</title>
<style>
:root{color-scheme:dark;--bg:#08111f;--panel:#0d1829;--panel2:#101d30;--panel3:#0a1525;--border:#26384e;--text:#e8eef8;--muted:#8fa7c5;--ok:#30d99a;--warn:#f0b24a;--bad:#ff7070;--blue:#83b7ff;--oregon:#3fd39b;--tech:#55aef6;--bme:#f0b24a}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#08111f 0,#07101c 100%);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif}main{max-width:1580px;margin:auto;padding:14px}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.brand{min-width:280px;flex:1}.title{font-weight:800;font-size:1.28rem;letter-spacing:.01em}.sub,.muted{color:var(--muted);font-size:.83rem}.headerActions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.statusPill{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--border);background:#0d1829;padding:8px 11px;border-radius:999px;font-size:.78rem;font-weight:700;color:var(--muted)}.statusPill:before{content:'';width:8px;height:8px;border-radius:50%;background:#65758a;box-shadow:0 0 0 3px #65758a18}.statusPill.ok{color:#91e8c4;border-color:#1d664f}.statusPill.ok:before{background:var(--ok);box-shadow:0 0 0 3px #30d99a20}.statusPill.wait{color:#f2cb7c;border-color:#6a5424}.statusPill.wait:before{background:var(--warn)}.statusPill.bad{color:#ff9b9b;border-color:#71323a}.statusPill.bad:before{background:var(--bad)}
.mainTabs{display:flex;gap:8px;margin-top:14px;padding:5px;border:1px solid var(--border);border-radius:13px;background:#0a1525;overflow:auto}.mainTab{border:0;background:transparent;color:var(--muted);padding:9px 16px;border-radius:9px;cursor:pointer;font-weight:800;white-space:nowrap}.mainTab.active{background:#16304a;color:#eef7ff;box-shadow:inset 0 0 0 1px #3c6b91}.mainPage{display:none}.mainPage.active{display:block}
.panel{border:1px solid var(--border);border-radius:14px;background:var(--panel);overflow:hidden;margin-top:12px;box-shadow:0 8px 28px #00000012}.panelHead{padding:13px 15px;border-bottom:1px solid var(--border);font-weight:750;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.stationOregon .panelHead{box-shadow:inset 3px 0 0 var(--oregon)}.stationTechnoline .panelHead{box-shadow:inset 3px 0 0 var(--tech)}.stationBme .panelHead{box-shadow:inset 3px 0 0 var(--bme)}
.weatherGrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:14px}.bmeGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.card{position:relative;border:1px solid var(--border);border-radius:14px;background:linear-gradient(180deg,#101d30 0,#0e1a2b 100%);overflow:hidden;min-width:0}.card.good{border-color:#235448}.cardTitle{padding:12px 13px;font-weight:750;display:flex;align-items:center;justify-content:space-between;gap:8px;border-bottom:1px solid var(--border);min-height:52px}.cardTitle:before{content:'';width:7px;height:7px;border-radius:50%;background:#65758a;flex:0 0 auto}.card.fresh .cardTitle:before{background:var(--ok);box-shadow:0 0 0 3px #30d99a1c}.card.aging .cardTitle:before{background:var(--warn);box-shadow:0 0 0 3px #f0b24a1c}.card.stale .cardTitle:before{background:var(--bad);box-shadow:0 0 0 3px #ff70701c}.card.nodata .cardTitle:before{background:#65758a}.stationOregon .cardTitle{border-top:2px solid #3fd39b40}.stationTechnoline .cardTitle{border-top:2px solid #55aef640}.stationBme .cardTitle{border-top:2px solid #f0b24a40}.spark{width:92px;height:25px;margin-left:auto}.body{padding:4px 13px 10px}.row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid #1c2b3e}.row:last-child{border-bottom:0}.body>.row:first-child{padding:12px 0}.body>.row:first-child .value{font-size:1.42rem;line-height:1.1;color:#f4f8ff}.name{color:#b5c8e1;font-size:.9rem}.value{font-weight:700;text-align:right}.age{font-size:.68rem;color:var(--muted);margin-top:4px;text-align:right}.forecast{padding:10px 0;font-size:1rem;font-weight:700}.foot{background:#0a1525;padding:8px 13px;color:var(--muted);font-size:.7rem;line-height:1.4}.uvCard{grid-column:auto}
.windCard .body{display:grid;grid-template-columns:minmax(0,1fr) 112px;column-gap:8px}.windCard .row{grid-column:1}.windCard .compassBlock{grid-column:2;grid-row:1/6;align-self:center}.compassBlock{display:flex;justify-content:center;padding:4px}.windCompass{width:104px;height:104px;filter:drop-shadow(0 3px 8px #0005)}.compassRing{fill:#0a1525;stroke:#65758a;stroke-width:4}.compassTick{stroke:#3c5068;stroke-width:1.5}.compassAxis{stroke:#235f45;stroke-width:2}.compassNeedleN{fill:#ff5c64}.compassNeedleS{fill:#73b9ff}.compassCardinal{fill:#dce8f8;font-size:10px;font-weight:800;text-anchor:middle;dominant-baseline:middle}.compassDeg{fill:#70e2ad;font-size:14px;font-weight:800;text-anchor:middle}.compassDir{fill:#9fb5d0;font-size:8px;font-weight:700;text-anchor:middle}
.diagGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:12px}.diag{padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--panel2);line-height:1.55;min-width:0}.rawWrap{overflow:auto;padding:0 12px 12px}table{width:100%;border-collapse:collapse;font:12px ui-monospace,SFMono-Regular,Consolas,monospace}th,td{padding:7px;border-bottom:1px solid var(--border);text-align:left;white-space:nowrap}.ok{color:#70e2ad}.bad{color:#ff9b9b}.battOK{color:#70e2ad}.battLOW{color:#ff7070;font-weight:800}.battNA{color:var(--muted)}a{color:var(--blue)}details summary{cursor:pointer;padding:13px 15px;font-weight:750}.diagSection{border:1px solid var(--border);border-radius:12px;background:#0b1727;margin:12px;overflow:hidden}.diagSection>summary{background:#0e1b2d}.diagSection[open]>summary{border-bottom:1px solid var(--border)}
.modeBox{display:flex;align-items:center;gap:8px;border:1px solid var(--border);background:var(--panel);padding:7px;border-radius:12px;flex-wrap:wrap}.modeLabel{color:var(--muted);font-size:.76rem;margin-right:3px}.modeBtn{border:1px solid var(--border);background:#111d2d;color:var(--text);padding:8px 13px;border-radius:9px;cursor:pointer;font-weight:750}.modeBtn:hover{border-color:#4c6c91;background:#15243a}.modeBtn.active{background:#17634f;border-color:#2ad09a;color:#fff}.modeBtn:disabled{opacity:.55;cursor:wait}.dangerBtn{border-color:#60343b!important;color:#ffc0c4!important;background:#28191e!important}.dangerBtn:hover{border-color:#a94e59!important;background:#3a1d24!important}.rfControls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:14px}.stationInactive{opacity:.38;filter:saturate(.5)}.acqBar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:8px 14px;background:#0a1525;border-bottom:1px solid var(--border);font-size:.76rem}.badge{display:inline-flex;align-items:center;gap:5px;padding:4px 8px;border-radius:999px;border:1px solid var(--border);background:#111d2d}.badge.ok{border-color:#17634f;color:#70e2ad}.badge.wait{border-color:#6a5424;color:#f0c56c}.badge.off{color:var(--muted)}.card.waiting{border-color:#6a5424}.value.waitingText{color:#f0c56c}.qrow{display:grid;grid-template-columns:1fr 62px 70px 70px;gap:8px;padding:4px 0;border-bottom:1px solid #1c2b3e}.qrow:last-child{border-bottom:0}.qhdr{color:var(--muted);font-size:.72rem}.qgood{color:#70e2ad}.qwarn{color:#f0c56c}.qbad{color:#ff9b9b}
.cfgPanel{padding-bottom:2px}.cfgGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:14px}.cfgGrid label{display:flex;flex-direction:column;gap:6px;color:var(--muted);font-size:.78rem}.cfgGrid input[type=text],.cfgGrid input[type=password],.cfgGrid input[type=number],.cfgGrid select,.cfgGrid textarea{background:#081423;border:1px solid var(--border);color:var(--text);border-radius:8px;padding:9px}.cfgGrid textarea{min-height:150px;resize:vertical;font:11px ui-monospace,SFMono-Regular,Consolas,monospace}.cfgWide{grid-column:1/-1}.fieldGrid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:8px;padding:0 14px 14px}.fieldGroup{border:1px solid var(--border);border-radius:10px;padding:10px;background:#0b1727}.fieldGroup b{display:block;margin-bottom:7px}.fieldCheck{display:flex;gap:7px;align-items:center;color:#b5c8e1;font-size:.78rem;padding:3px 0}.cfgGrid .checkLine{flex-direction:row;align-items:center}.cfgActions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:0 14px 14px}.cfgTabs{display:flex;gap:8px;padding:12px 14px 0;overflow:auto}.cfgTab{border:1px solid var(--border);background:#111d2d;color:var(--text);padding:8px 14px;border-radius:9px;cursor:pointer;font-weight:700;white-space:nowrap}.cfgTab.active{background:#174d66;border-color:#4aaad8}.cfgPage{display:none}.cfgPage.active{display:block}.cfgNote{padding:0 14px 12px;color:var(--muted);font-size:.78rem;line-height:1.45}
.resourceHeroGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:14px 14px 0}.resourceHero{border:1px solid var(--border);border-radius:13px;background:linear-gradient(180deg,#122238,#0d1929);padding:14px}.resourceHero .heroLabel{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.08em}.resourceHero .heroValue{font-size:1.7rem;font-weight:850;margin-top:5px}.resourceHero .heroState{font-size:.72rem;color:var(--ok);margin-top:4px}.resourceGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:14px}.resourceLine{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-bottom:1px solid #1c2b3e}.resourceLine:last-child{border-bottom:0}.meter{height:7px;background:#081423;border:1px solid var(--border);border-radius:99px;overflow:hidden;margin-top:7px}.meter>span{display:block;height:100%;width:0;background:#30d99a;transition:width .25s}
@media(max-width:1220px){.weatherGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.bmeGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.diagGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.fieldGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.rfControls{grid-template-columns:1fr 1fr}}
@media(max-width:760px){main{padding:9px}.title{font-size:1.08rem}.sub{font-size:.75rem}.headerActions{width:100%}.statusPill{padding:7px 9px}.mainTabs{position:sticky;top:0;z-index:5}.weatherGrid,.bmeGrid{grid-template-columns:1fr;padding:10px}.diagGrid,.resourceGrid,.resourceHeroGrid,.fieldGrid,.cfgGrid,.rfControls{grid-template-columns:1fr}.windCard .body{grid-template-columns:minmax(0,1fr) 100px}.windCompass{width:94px;height:94px}.spark{width:82px}.modeBox{align-items:flex-start}.modeBtn{padding:8px 10px}}
</style></head><body><main>
<div class="top"><div class="brand"><div class="title">Oregon + Technoline 433 Gateway</div><div class="sub">LILYGO T3 · SX1278 OOK 433.92 MHz · decoder Oregon OSV3 + Technoline WS230x</div></div><div class="headerActions"><span id="hdrRf" class="statusPill wait">RF --</span><span id="net" class="statusPill wait">Wi-Fi...</span><span id="hdrMqtt" class="statusPill wait">MQTT...</span><button id="displayBtn" class="modeBtn" onclick="toggleDisplay()" title="Accende o spegne il display OLED; RF, Wi-Fi, Web e MQTT restano attivi">OLED --</button><button class="modeBtn dangerBtn" onclick="restartDevice()" title="Riavvia ESP32 senza cancellare la configurazione">⟳ RIAVVIA</button></div></div>
<div class="mainTabs"><button id="mainTabDashboard" class="mainTab active" onclick="showMainTab('dashboard')">DASHBOARD</button><button id="mainTabHardware" class="mainTab" onclick="showMainTab('hardware')">HARDWARE</button><button id="mainTabConfig" class="mainTab" onclick="showMainTab('config')">CONFIGURAZIONE</button><button id="mainTabDiag" class="mainTab" onclick="showMainTab('diag')">DIAGNOSTICA</button></div>
<section id="mainDashboard" class="mainPage active"><div class="panel stationOregon" id="oregonPanel"><div class="panelHead">Dati meteo live · Oregon OSV3 <span id="oregonModeBadge" class="badge off">RF non in ascolto</span></div><div class="acqBar"><b>Acquisizione Oregon</b><span id="sessionAge" class="badge off">--</span><span id="acqThermo" class="badge wait">THGN attesa</span><span id="acqWind" class="badge wait">WGR attesa</span><span id="acqRain" class="badge wait">PCR attesa</span><span id="acqUv" class="badge wait">UVN attesa</span></div><div class="weatherGrid">
<section class="card good"><div class="cardTitle">Temperatura e umidita<svg class="spark" id="spTemp"></svg></div><div class="body">
<div class="row"><div class="name">Temperatura esterna</div><div><div class="value" id="temp">--</div><div class="age" id="ageT"></div></div></div>
<div class="row"><div class="name">Umidita esterna</div><div class="value" id="hum">--</div></div>
<div class="row"><div class="name">Heat index esterno</div><div class="value" id="hi">N/A</div></div>
<div class="row"><div class="name">Punto di rugiada</div><div class="value" id="dew">--</div></div>
</div><div class="foot" id="footT"></div></section>

<section class="card good windCard"><div class="cardTitle">Vento<svg class="spark" id="spWind"></svg></div><div class="body">
<div class="row"><div class="name">Velocita media</div><div><div class="value" id="wind">--</div><div class="age" id="ageW"></div></div></div>
<div class="row"><div class="name">Raffica / massimo</div><div class="value" id="gust">--</div></div>
<div class="row"><div class="name">Direzione</div><div class="value" id="dir">--</div></div>
<div class="row"><div class="name">Wind chill</div><div class="value" id="wc">N/A</div></div><div class="compassBlock"><svg class="windCompass" viewBox="0 0 120 120" aria-label="Bussola vento Oregon"><circle class="compassRing" cx="60" cy="60" r="49"/><line class="compassAxis" x1="60" y1="13" x2="60" y2="107"/><line class="compassAxis" x1="13" y1="60" x2="107" y2="60"/><text class="compassCardinal" x="60" y="6">N</text><text class="compassCardinal" x="114" y="60">E</text><text class="compassCardinal" x="60" y="114">S</text><text class="compassCardinal" x="6" y="60">W</text><g id="oregonCompassNeedle"><polygon class="compassNeedleN" points="60,12 55,60 65,60"/><polygon class="compassNeedleS" points="60,108 55,60 65,60"/></g><circle cx="60" cy="60" r="5" fill="#dce8f8"/><text id="oregonCompassDeg" class="compassDeg" x="60" y="55">--°</text><text id="oregonCompassDir" class="compassDir" x="60" y="72">--</text></svg></div></div><div class="foot" id="footW"></div></section>

<section class="card good"><div class="cardTitle">Pioggia<svg class="spark" id="spRain"></svg></div><div class="body">
<div class="row"><div class="name">Intensita</div><div><div class="value" id="rate">--</div><div class="age" id="ageR"></div></div></div>
<div class="row"><div class="name">Ultima ora</div><div class="value" id="r1h">--</div></div>
<div class="row"><div class="name">Ultime 24 ore</div><div class="value" id="r24">--</div></div>
<div class="row"><div class="name">Totale sensore</div><div class="value" id="rtot">--</div></div>
<div class="row"><div class="name">Incremento ultimo frame</div><div class="value" id="rinc">--</div></div></div><div class="foot" id="footR"></div></section>

<section class="card good uvCard"><div class="cardTitle">Radiazione UV<svg class="spark" id="spUv"></svg></div><div class="body"><div class="row"><div class="name">Indice UV</div><div><div class="value" id="uv">--</div><div class="age" id="ageU"></div></div></div></div><div class="foot" id="footU"></div></section>
</div></div>

<div class="panel stationTechnoline" id="lacrossePanel"><div class="panelHead">Dati meteo live · Technoline WS230x <span id="technolineModeBadge" class="badge off">RF non in ascolto</span></div><div class="acqBar"><b>Acquisizione Technoline</b><span id="lcSessionAge" class="badge off">--</span><span id="lcAcqT" class="badge wait">TEMP attesa</span><span id="lcAcqH" class="badge wait">HUM attesa</span><span id="lcAcqW" class="badge wait">WIND attesa</span><span id="lcAcqG" class="badge wait">GUST attesa</span><span id="lcAcqR" class="badge wait">RAIN attesa</span></div><div class="weatherGrid">
<section class="card good"><div class="cardTitle">Temperatura e umidita<svg class="spark" id="spLcTemp"></svg></div><div class="body">
<div class="row"><div class="name">Temperatura esterna</div><div><div class="value" id="lcTemp">--</div><div class="age" id="lcAgeT"></div></div></div>
<div class="row"><div class="name">Umidita esterna</div><div class="value" id="lcHum">--</div></div>
<div class="row"><div class="name">Modello / ID</div><div class="value" style="font-size:14px"><span id="lcModel">--</span> · <span id="lcId">--</span></div></div>
</div><div class="foot" id="lcFootTH"></div></section>

<section class="card good windCard"><div class="cardTitle">Vento<svg class="spark" id="spLcWind"></svg></div><div class="body">
<div class="row"><div class="name">Velocita</div><div><div class="value" id="lcWind">--</div><div class="age" id="lcAgeW"></div></div></div>
<div class="row"><div class="name">Raffica</div><div class="value" id="lcGust">--</div></div>
<div class="row"><div class="name">Direzione</div><div class="value" id="lcDir">--</div></div>
<div class="row"><div class="name">Prossimo update</div><div class="value" id="lcNext">--</div></div>
<div class="compassBlock"><svg class="windCompass" viewBox="0 0 120 120" aria-label="Bussola vento Technoline"><circle class="compassRing" cx="60" cy="60" r="49"/><line class="compassAxis" x1="60" y1="13" x2="60" y2="107"/><line class="compassAxis" x1="13" y1="60" x2="107" y2="60"/><text class="compassCardinal" x="60" y="6">N</text><text class="compassCardinal" x="114" y="60">E</text><text class="compassCardinal" x="60" y="114">S</text><text class="compassCardinal" x="6" y="60">W</text><g id="lcCompassNeedle"><polygon class="compassNeedleN" points="60,12 55,60 65,60"/><polygon class="compassNeedleS" points="60,108 55,60 65,60"/></g><circle cx="60" cy="60" r="5" fill="#dce8f8"/><text id="lcCompassDeg" class="compassDeg" x="60" y="55">--°</text><text id="lcCompassDir" class="compassDir" x="60" y="72">--</text></svg></div></div><div class="foot" id="lcFootW"></div></section>

<section class="card good"><div class="cardTitle">Pioggia<svg class="spark" id="spLcRain"></svg></div><div class="body">
<div class="row"><div class="name">Totale sensore</div><div><div class="value" id="lcRain">--</div><div class="age" id="lcAgeR"></div></div></div>
<div class="row"><div class="name">Incremento ultimo frame</div><div class="value" id="lcRainInc">--</div></div>
</div><div class="foot" id="lcFootR"></div></section>

<section class="card good uvCard nodata"><div class="cardTitle">Radiazione UV</div><div class="body">
<div class="row"><div class="name">Indice UV</div><div class="value">N/D</div></div>
<div class="row"><div class="name">WS-2305</div><div class="value">non trasmesso</div></div>
</div><div class="foot">Il protocollo WS-23xx non contiene un dato UV.</div></section>
</div></div>
<div class="panel stationBme" id="bmePanel"><div class="panelHead">Sensore locale · BME280 <span id="bmeBadge" class="badge off">rilevamento...</span></div><div class="weatherGrid bmeGrid">
<section class="card good"><div class="cardTitle">Ambiente locale<svg class="spark" id="spBmeTemp"></svg></div><div class="body">
<div class="row"><div class="name">Temperatura interna</div><div><div class="value" id="tin">--</div><div class="age" id="bmeAge"></div></div></div>
<div class="row"><div class="name">Umidita interna</div><div class="value" id="hin">--</div></div>
<div class="row"><div class="name">Origine</div><div class="value">I²C locale</div></div>
</div><div class="foot" id="bmeFootEnv">Indipendente dai protocolli RF.</div></section>
<section class="card good"><div class="cardTitle">Barometro<svg class="spark" id="spPress"></svg></div><div class="body">
<div class="row"><div class="name">Pressione stazione</div><div><div class="value" id="psta">--</div><div class="age" id="ageP"></div></div></div>
<div class="row"><div class="name">Pressione al livello del mare</div><div class="value" id="psea">--</div></div>
<div class="row"><div class="name">Trend normalizzato 3 h</div><div class="value" id="ptrend">--</div></div>
<div class="forecast" id="forecast">In acquisizione</div>
</div><div class="foot" id="footP"></div></section>
</div></div>
</section>
<section id="mainHardware" class="mainPage">
<div class="panel"><div class="panelHead">Hardware Monitor <span class="muted">aggiornamento live · nessuna scrittura flash</span></div>
<div class="resourceHeroGrid"><div class="resourceHero"><div class="heroLabel">CPU</div><div class="heroValue" id="sysCpu">--</div><div class="heroState">ESP32 runtime</div></div><div class="resourceHero"><div class="heroLabel">RAM utilizzata</div><div class="heroValue" id="sysHeapPct">--</div><div class="heroState">heap dinamico</div></div><div class="resourceHero"><div class="heroLabel">Wi-Fi</div><div class="heroValue" id="sysWifi">--</div><div class="heroState">RSSI collegamento</div></div></div>
<div class="resourceGrid">
<section class="card"><div class="cardTitle">CPU / SoC</div><div class="body"><div class="resourceLine"><span class="name">Chip</span><span class="value" id="sysChip">--</span></div><div class="resourceLine"><span class="name">Core</span><span class="value" id="sysCores">--</span></div><div class="resourceLine"><span class="name">Uptime</span><span class="value" id="sysUptime">--</span></div><div class="resourceLine"><span class="name">Display OLED</span><span class="value" id="sysDisplay">--</span></div><div class="resourceLine"><span class="name">Pulsante OLED</span><span class="value" id="sysDisplayButton">--</span></div></div></section>
<section class="card"><div class="cardTitle">Firmware / boot</div><div class="body"><div class="resourceLine"><span class="name">Firmware</span><span class="value" id="sysFirmware">--</span></div><div class="resourceLine"><span class="name">Git commit</span><span class="value" id="sysGit">--</span></div><div class="resourceLine"><span class="name">Build</span><span class="value" id="sysBuild">--</span></div><div class="resourceLine"><span class="name">Ultimo reset</span><span class="value" id="sysReset">--</span></div><div class="resourceLine"><span class="name">Board</span><span class="value" id="sysBoard">--</span></div></div></section>
<section class="card"><div class="cardTitle">Memoria RAM</div><div class="body"><div class="resourceLine"><span class="name">Heap usato</span><span class="value" id="sysHeapUsed">--</span></div><div class="resourceLine"><span class="name">Heap libero</span><span class="value" id="sysHeapFree">--</span></div><div class="resourceLine"><span class="name">Minimo libero</span><span class="value" id="sysHeapMin">--</span></div><div class="meter"><span id="sysHeapBar"></span></div></div></section>
<section class="card"><div class="cardTitle">Flash / radio</div><div class="body"><div class="resourceLine"><span class="name">Sketch / flash</span><span class="value" id="sysFlash">--</span></div><div class="resourceLine"><span class="name">Spazio OTA libero</span><span class="value" id="sysOta">--</span></div><div class="resourceLine"><span class="name">RF ring overflow</span><span class="value" id="sysOvf">--</span></div><div class="meter"><span id="sysFlashBar"></span></div></div></section>
<section class="card"><div class="cardTitle">Rete</div><div class="body"><div class="resourceLine"><span class="name">Hostname</span><span class="value" id="sysHostname">--</span></div><div class="resourceLine"><span class="name">mDNS</span><span class="value" id="sysMdns">--</span></div><div class="resourceLine"><span class="name">IP</span><span class="value" id="sysIp">--</span></div></div></section>
</div><div class="cfgNote">Il monitor usa i dati gia presenti in <code>/api/state</code>. Non aggiunge polling, storage o scritture NVS.</div></div>
</section>
<section id="mainConfig" class="mainPage">
<div class="panel cfgPanel"><div class="panelHead">Configurazione dispositivo <span class="muted">NVS solo su modifica</span></div><div class="cfgTabs"><button id="tabNet" class="cfgTab active" onclick="showCfgTab('net')">RETE / IP</button><button id="tabMqtt" class="cfgTab" onclick="showCfgTab('mqtt')">MQTT / TLS</button><button id="tabDisplay" class="cfgTab" onclick="showCfgTab('display')">DISPLAY</button><button id="tabBackup" class="cfgTab" onclick="showCfgTab('backup')">BACKUP / RESTORE</button></div><div id="cfgNet" class="cfgPage active">
<div class="cfgGrid">
<label><span>Hostname dispositivo</span><input id="netHostname" type="text" maxlength="32" placeholder="oregon-gateway"></label>
<label><span>Indirizzo mDNS</span><input id="netMdns" type="text" readonly></label>
<label class="checkLine"><input id="netStatic" type="checkbox"><span>Usa IP statico</span></label>
<label><span>IP scheda</span><input id="netIp" type="text" maxlength="15" placeholder="192.168.1.220"></label>
<label><span>Gateway</span><input id="netGw" type="text" maxlength="15" placeholder="192.168.1.1"></label>
<label><span>Subnet mask</span><input id="netMask" type="text" maxlength="15" placeholder="255.255.255.0"></label>
<label><span>DNS</span><input id="netDns" type="text" maxlength="15" placeholder="192.168.1.1"></label>
<label><span>IP attuale</span><input id="netActual" type="text" readonly></label>
</div><div class="cfgActions"><button class="modeBtn" onclick="saveNetwork()">Salva e riavvia</button><button class="modeBtn" onclick="resetNetwork()">Default firmware</button><span id="netSummary" class="muted"></span></div>
<div class="cfgNote">Hostname: 1-32 caratteri, solo a-z, 0-9 e trattino; viene convertito in minuscolo. Le modifiche di rete diventano attive dopo il riavvio. mDNS consente l'accesso come <code>http://hostname.local/</code> sui client che supportano Bonjour/mDNS. I dati meteo non vengono mai scritti in flash.</div>
</div>
<div id="cfgMqtt" class="cfgPage">
<div class="cfgGrid">
<label><span>Abilitato</span><input id="mqEnabled" type="checkbox"></label>
<label><span>Broker / host</span><input id="mqBroker" type="text" maxlength="96" placeholder="192.168.1.100"></label>
<label><span>Porta</span><input id="mqPort" type="number" min="1" max="65535" value="1883"></label>
<label><span>Utente</span><input id="mqUser" type="text" maxlength="64"></label>
<label><span>Password</span><input id="mqPassword" type="password" maxlength="96" placeholder="lascia vuoto per mantenere"></label>
<label><span>Client ID</span><input id="mqClient" type="text" maxlength="64"></label>
<label><span>Base topic</span><input id="mqTopic" type="text" maxlength="96" placeholder="weatherstation"></label>
<label><span>TLS</span><select id="mqTlsMode" onchange="updateTlsUi()"><option value="0">Disabilitato</option><option value="1">TLS + verifica CA</option><option value="2">TLS senza verifica (test)</option></select></label>
<label class="checkLine"><input id="mqClearPass" type="checkbox"><span>cancella password salvata</span></label>
<label class="cfgWide" id="mqCaLabel"><span>CA certificate PEM</span><textarea id="mqCa" maxlength="3900" placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"></textarea></label>
</div>
<div class="cfgActions"><b>Campi da pubblicare</b><button class="modeBtn" onclick="mqttSelectAll(true)">Tutti</button><button class="modeBtn" onclick="mqttSelectAll(false)">Nessuno</button></div>
<div class="fieldGrid">
<div class="fieldGroup"><b>Oregon</b>
<label class="fieldCheck"><input data-mqbit="0" type="checkbox">Temperatura</label><label class="fieldCheck"><input data-mqbit="1" type="checkbox">Umidita</label><label class="fieldCheck"><input data-mqbit="2" type="checkbox">Heat index</label><label class="fieldCheck"><input data-mqbit="3" type="checkbox">Punto di rugiada</label><label class="fieldCheck"><input data-mqbit="4" type="checkbox">Vento medio</label><label class="fieldCheck"><input data-mqbit="5" type="checkbox">Raffica/current</label><label class="fieldCheck"><input data-mqbit="6" type="checkbox">Direzione vento</label><label class="fieldCheck"><input data-mqbit="7" type="checkbox">Wind chill</label><label class="fieldCheck"><input data-mqbit="8" type="checkbox">Pioggia totale</label><label class="fieldCheck"><input data-mqbit="9" type="checkbox">Intensita pioggia</label><label class="fieldCheck"><input data-mqbit="10" type="checkbox">Pioggia 1 h</label><label class="fieldCheck"><input data-mqbit="11" type="checkbox">Pioggia 24 h</label><label class="fieldCheck"><input data-mqbit="12" type="checkbox">Incremento pioggia</label><label class="fieldCheck"><input data-mqbit="13" type="checkbox">UV</label>
</div>
<div class="fieldGroup"><b>Technoline</b>
<label class="fieldCheck"><input data-mqbit="14" type="checkbox">Temperatura</label><label class="fieldCheck"><input data-mqbit="15" type="checkbox">Umidita</label><label class="fieldCheck"><input data-mqbit="16" type="checkbox">Pioggia</label><label class="fieldCheck"><input data-mqbit="17" type="checkbox">Vento</label><label class="fieldCheck"><input data-mqbit="18" type="checkbox">Gust</label><label class="fieldCheck"><input data-mqbit="19" type="checkbox">Direzione vento</label>
</div>
<div class="fieldGroup"><b>BME280 locale</b>
<label class="fieldCheck"><input data-mqbit="20" type="checkbox">Temperatura</label><label class="fieldCheck"><input data-mqbit="21" type="checkbox">Umidita</label><label class="fieldCheck"><input data-mqbit="22" type="checkbox">Pressione stazione</label><label class="fieldCheck"><input data-mqbit="23" type="checkbox">Altimetro</label><label class="fieldCheck"><input data-mqbit="24" type="checkbox">Trend 3 h</label>
</div>
<div class="fieldGroup"><b>Gateway</b>
<label class="fieldCheck"><input data-mqbit="25" type="checkbox">JSON state completo</label><label class="fieldCheck"><input data-mqbit="26" type="checkbox">Metadati RF / RAW / batterie</label><label class="fieldCheck"><input data-mqbit="27" type="checkbox">Risorse ESP32</label>
</div>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveMqtt()">Salva MQTT / TLS</button><button class="modeBtn" onclick="resetMqtt()">Default firmware</button><span id="mqttSummary" class="muted"></span></div>
<div class="cfgNote">TLS verificato usa la CA PEM inserita qui. La modalita TLS senza verifica cifra il traffico ma non autentica il broker: usala solo per test. Password, CA e mask campi vengono scritti in NVS soltanto se cambiano.</div>
</div>
<div id="cfgDisplay" class="cfgPage">
<div class="cfgGrid">
<label class="checkLine"><input id="dispOn" type="checkbox"><span>OLED acceso</span></label>
<label><span>Cambio pagina (secondi)</span><input id="dispInterval" type="number" min="2" max="60" value="7"></label>
<label><span>Contrasto OLED (8-255)</span><input id="dispContrast" type="number" min="8" max="255" value="255"></label>
</div>
<div class="cfgActions"><b>Pagine da mostrare</b><button class="modeBtn" onclick="displaySelectPages(true)">Tutte</button><button class="modeBtn" onclick="displaySelectPages(false)">Nessuna</button></div>
<div class="fieldGrid">
<div class="fieldGroup"><b>Pagine OLED</b>
<label class="fieldCheck"><input data-dpagebit="0" type="checkbox">Esterno</label><label class="fieldCheck"><input data-dpagebit="1" type="checkbox">Vento / Pioggia</label><label class="fieldCheck"><input data-dpagebit="2" type="checkbox">Technoline</label><label class="fieldCheck"><input data-dpagebit="3" type="checkbox">Barometro</label><label class="fieldCheck"><input data-dpagebit="4" type="checkbox">RF / Status</label>
</div>
<div class="fieldGroup"><b>Esterno</b>
<label class="fieldCheck"><input data-denvbit="0" type="checkbox">Temperatura + umidita</label><label class="fieldCheck"><input data-denvbit="1" type="checkbox">Punto di rugiada</label><label class="fieldCheck"><input data-denvbit="2" type="checkbox">Heat index + UV</label><label class="fieldCheck"><input data-denvbit="3" type="checkbox">Stato batterie</label>
</div>
<div class="fieldGroup"><b>Vento / Pioggia</b>
<label class="fieldCheck"><input data-dwindbit="0" type="checkbox">Vento + raffica</label><label class="fieldCheck"><input data-dwindbit="1" type="checkbox">Direzione</label><label class="fieldCheck"><input data-dwindbit="2" type="checkbox">Pioggia</label><label class="fieldCheck"><input data-dwindbit="3" type="checkbox">Stato batterie</label>
</div>
<div class="fieldGroup"><b>Technoline</b>
<label class="fieldCheck"><input data-dtechbit="0" type="checkbox">Temperatura + umidita</label><label class="fieldCheck"><input data-dtechbit="1" type="checkbox">Vento + Gust</label><label class="fieldCheck"><input data-dtechbit="2" type="checkbox">Direzione</label><label class="fieldCheck"><input data-dtechbit="3" type="checkbox">Pioggia</label><label class="fieldCheck"><input data-dtechbit="4" type="checkbox">ID + pacchetti</label>
</div>
<div class="fieldGroup"><b>Barometro</b>
<label class="fieldCheck"><input data-dpressbit="0" type="checkbox">Pressione stazione</label><label class="fieldCheck"><input data-dpressbit="1" type="checkbox">Altimetro</label><label class="fieldCheck"><input data-dpressbit="2" type="checkbox">Trend 3 h</label><label class="fieldCheck"><input data-dpressbit="3" type="checkbox">Previsione</label>
</div>
<div class="fieldGroup"><b>RF / Status</b>
<label class="fieldCheck"><input data-dstatusbit="0" type="checkbox">Conteggi Oregon</label><label class="fieldCheck"><input data-dstatusbit="1" type="checkbox">Decoder / WGR scan</label><label class="fieldCheck"><input data-dstatusbit="2" type="checkbox">Timing / run</label><label class="fieldCheck"><input data-dstatusbit="3" type="checkbox">Statistiche Technoline</label><label class="fieldCheck"><input data-dstatusbit="4" type="checkbox">IP / rete</label>
</div>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveDisplayConfig()">Salva DISPLAY</button><button class="modeBtn" onclick="resetDisplayConfig()">Default firmware</button><span id="displaySummary" class="muted"></span></div>
<div class="cfgNote">Le pagine disabilitate vengono saltate automaticamente. Intervallo e campi sono persistenti in NVS e vengono scritti solo quando cambiano. Se il Gust Technoline non e' stato ricevuto il display mostra <code>G --</code>, mai uno zero artificiale.</div>
</div>
<div id="cfgBackup" class="cfgPage">
<div class="cfgGrid">
<label class="checkLine"><input id="backupSecrets" type="checkbox"><span>Includi password MQTT nel backup</span></label>
<label class="cfgWide"><span>File backup da ripristinare</span><input id="backupFile" type="file" accept="application/json,.json"></label>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="exportConfig()">Esporta configurazione</button><button class="modeBtn dangerBtn" onclick="importConfig()">Importa e riavvia</button><span id="backupSummary" class="muted">Backup schema 1 · JSON</span></div>
<div class="cfgNote"><b>Incluso:</b> hostname/IP, MQTT/TLS, campi MQTT, configurazione OLED (pagine, campi, intervallo, contrasto) e configurazione RF persistente. <b>Non incluso:</b> SSID/password Wi-Fi, che in questa versione restano nel firmware/config_private.h. Per sicurezza la password MQTT e' esclusa salvo selezione esplicita. L'import valida il file e riavvia il gateway.</div>
</div>
</div>
</section>
<section id="mainDiag" class="mainPage">
<div class="panel"><div class="panelHead">Controlli RF <span class="muted">le modifiche agiscono sugli stessi endpoint della versione precedente</span></div><div class="rfControls">
<div class="modeBox"><span class="modeLabel">RICEZIONE</span><button id="modeDual" class="modeBtn" onclick="setRfMode('dual')">DUAL</button><button id="modeOregon" class="modeBtn" onclick="setRfMode('oregon')">OREGON</button><button id="modeTechnoline" class="modeBtn" onclick="setRfMode('technoline')">TECHNOLINE</button></div>
<div class="modeBox"><span class="modeLabel">GUADAGNO</span><button id="gain0" class="modeBtn" onclick="setRfGain(0)">AGC AUTO ✓</button><button id="gain1" class="modeBtn" onclick="setRfGain(1)">MAX</button><button id="gain2" class="modeBtn" onclick="setRfGain(2)">ALTO</button><button id="gain3" class="modeBtn" onclick="setRfGain(3)">MEDIO</button></div>
<div class="modeBox"><span class="modeLabel">PROFILO RF</span><button id="profStable" class="modeBtn" onclick="setRfProfile('stable')">STABILE</button><button id="profWide" class="modeBtn" onclick="setRfProfile('wide')">AMPIO</button><button id="profMax" class="modeBtn" onclick="setRfProfile('max')">MAX RF</button><button id="profAuto" class="modeBtn" onclick="setRfProfile('auto')">AUTO SCAN</button></div>
<div class="modeBox"><span class="modeLabel">STRUMENTI</span><button id="burstExtra" class="modeBtn" onclick="toggleBurstExtra()">BURST EXTRA OFF</button><button id="wgrProbe" class="modeBtn" onclick="toggleWgrProbe()">WGR PROBE OFF</button></div>
</div></div>
<details class="diagSection" open><summary>Decoder, timing e qualita ricezione</summary><div class="diagGrid"><div class="diag" id="pkts"></div><div class="diag" id="rf"></div><div class="diag" id="timing"></div><div class="diag" id="quality"></div><div class="diag" id="qualityLc"></div></div></details>
<details class="diagSection"><summary>Burst Analyzer / WGR Probe</summary><div class="diagGrid"><div class="diag" id="burstDiag"></div><div class="diag" id="wgrDiag"></div></div><div class="rawWrap"><div class="top" style="padding:5px 0 10px"><b>Burst RF rilevati</b><span class="muted">indipendenti dal checksum Oregon</span></div><table><thead><tr><th>ms</th><th>Durata</th><th>Edges</th><th>RSSI</th><th>Match</th><th>OSV3-like</th><th>Classe</th><th>Rec.</th><th>ON S/L</th><th>OFF S/L</th></tr></thead><tbody id="bursts"></tbody></table></div></details>
<details class="diagSection"><summary>Frame grezzi</summary><div class="rawWrap"><div class="top" style="padding:5px 0 10px"><b>Ultimi frame grezzi</b><a href="/api/raw.txt" target="_blank">raw.txt</a></div><table><thead><tr><th>ms</th><th>Esito</th><th>Proto</th><th>Src</th><th>Tipo</th><th>RSSI</th><th>Raw HEX</th><th>Decodificato</th></tr></thead><tbody id="raw"></tbody></table></div></details>
</section></main><script>
const E=id=>document.getElementById(id);const f=(v,d=1,u='')=>v==null?'--':Number(v).toFixed(d)+u;const age=v=>(v==null||v>4290000)?'mai':(v<60?v+' s fa':Math.floor(v/60)+' min fa');const batt=x=>!x||!x.battery_known?'<span class=\"battNA\">BAT N/D</span>':(x.battery_low?'<span class=\"battLOW\">BAT LOW</span>':'<span class=\"battOK\">BAT OK</span>');const setBadge=(id,ok,label)=>{const e=E(id);e.className='badge '+(ok?'ok':'wait');e.textContent=label};const qClass=q=>q<0?'':(q>=85?'qgood':(q>=60?'qwarn':'qbad'));const qText=q=>q<0?'--':q+'%';const showOrWait=(el,ok,value)=>{el.classList.toggle('waitingText',!ok);el.textContent=ok?value:'IN ATTESA'};
const hist={temp:[],bmeTemp:[],press:[],wind:[],rain:[],uv:[],lcTemp:[],lcWind:[],lcRain:[]};let modeBusy=false;async function setRfMode(mode){if(modeBusy)return;modeBusy=true;for(const id of ['modeDual','modeOregon','modeTechnoline'])E(id).disabled=true;try{const r=await fetch('/api/rfmode?mode='+encodeURIComponent(mode),{method:'POST',cache:'no-store'});if(!r.ok)throw new Error(await r.text());await refresh();}catch(e){alert('Cambio modalita RF fallito: '+e)}finally{modeBusy=false;for(const id of ['modeDual','modeOregon','modeTechnoline'])E(id).disabled=false}}async function setRfGain(g){if(modeBusy)return;modeBusy=true;for(let i=0;i<4;i++)E('gain'+i).disabled=true;try{const r=await fetch('/api/rfgain?gain='+g,{method:'POST',cache:'no-store'});if(!r.ok)throw new Error(await r.text());await refresh();}catch(e){alert('Cambio guadagno fallito: '+e)}finally{modeBusy=false;for(let i=0;i<4;i++)E('gain'+i).disabled=false}}async function setRfProfile(p){if(modeBusy)return;modeBusy=true;for(const id of ['profStable','profWide','profMax','profAuto'])E(id).disabled=true;try{const r=await fetch('/api/rfprofile?profile='+encodeURIComponent(p),{method:'POST',cache:'no-store'});if(!r.ok)throw new Error(await r.text());await refresh();}catch(e){alert('Cambio profilo RF fallito: '+e)}finally{modeBusy=false;for(const id of ['profStable','profWide','profMax','profAuto'])E(id).disabled=false}}async function toggleBurstExtra(){if(modeBusy)return;modeBusy=true;try{const cur=E('burstExtra').classList.contains('active');const r=await fetch('/api/burstextra?enabled='+(cur?'0':'1'),{method:'POST',cache:'no-store'});if(!r.ok)throw new Error(await r.text());await refresh();}catch(e){alert('BURST EXTRA: '+e)}finally{modeBusy=false}}async function toggleWgrProbe(){if(modeBusy)return;modeBusy=true;try{const cur=E('wgrProbe').classList.contains('active');const r=await fetch('/api/wgrprobe?enabled='+(cur?'0':'1'),{method:'POST',cache:'no-store'});if(!r.ok)throw new Error(await r.text());await refresh();}catch(e){alert('WGR PROBE: '+e)}finally{modeBusy=false}}
let mainTab='dashboard';function showMainTab(t){mainTab=t;for(const x of ['dashboard','hardware','config','diag']){const on=t===x;E('main'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on);E('mainTab'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on)}if(t==='config')loadNetwork();if(t==='config')loadMqtt();}function showCfgTab(t){for(const x of ['net','mqtt','display','backup']){const on=t===x;E('cfg'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on);E('tab'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on)}if(t==='net')loadNetwork();else if(t==='mqtt')loadMqtt();else if(t==='display')loadDisplay();}function setFresh(id,sec,available=true){const e=E(id),c=e&&e.closest('.card');if(!c)return;c.classList.remove('fresh','aging','stale','nodata');if(!available||sec==null||Number(sec)>4290000){c.classList.add('nodata');return}const v=Number(sec);c.classList.add(v<=90?'fresh':(v<=240?'aging':'stale'))}
async function loadNetwork(){try{const n=await (await fetch('/api/network',{cache:'no-store'})).json();E('netHostname').value=n.hostname||'';E('netMdns').value=n.mdns?('http://'+n.mdns+'/'):'-';E('netStatic').checked=!!n.use_static;E('netIp').value=n.ip||'';E('netGw').value=n.gateway||'';E('netMask').value=n.subnet||'';E('netDns').value=n.dns||'';E('netActual').value=n.actual_ip||'-';E('netSummary').textContent=(n.use_static?'IP statico':'DHCP')+' · '+(n.mdns_active?'mDNS attivo':'mDNS in attesa');}catch(e){E('netSummary').textContent='errore lettura rete'}}
async function saveNetwork(){const q=new URLSearchParams();q.set('hostname',E('netHostname').value.trim().toLowerCase());q.set('use_static',E('netStatic').checked?'1':'0');q.set('ip',E('netIp').value);q.set('gateway',E('netGw').value);q.set('subnet',E('netMask').value);q.set('dns',E('netDns').value);q.set('reboot','1');const r=await fetch('/api/network?'+q.toString(),{method:'POST',cache:'no-store'});if(!r.ok){alert('Rete: '+await r.text());return}const j=await r.json();if(j.changed){alert('Configurazione salvata. Riavvio in corso. Prova http://'+j.mdns+'/ oppure l\'IP configurato.');}else{E('netSummary').textContent='Nessuna modifica: zero scritture NVS';}}
async function resetNetwork(){if(!confirm('Ripristinare IP/rete ai valori compilati nel firmware?'))return;const r=await fetch('/api/network/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset rete fallito');return}const j=await r.json();if(j.changed)alert('Rete ripristinata. Riavvio in corso.');else E('netSummary').textContent='Gia ai default: zero scritture NVS';}
function exportConfig(){const secrets=E('backupSecrets').checked?'1':'0';if(secrets&&!confirm('Il file conterra la password MQTT in chiaro. Continuare?'))return;window.location='/api/config/export?secrets='+secrets;}async function importConfig(){const file=E('backupFile').files[0];if(!file){alert('Seleziona un file JSON di backup.');return}if(file.size>12000){alert('Backup troppo grande.');return}if(!confirm('Importare la configurazione e riavviare il gateway?'))return;E('backupSummary').textContent='Importazione in corso...';try{const txt=await file.text();const r=await fetch('/api/config/import',{method:'POST',headers:{'Content-Type':'application/json'},body:txt,cache:'no-store'});const body=await r.text();if(!r.ok)throw new Error(body);const j=JSON.parse(body);E('backupSummary').textContent='Configurazione importata · riavvio in corso';alert('Backup importato correttamente. Il gateway si riavviera.');}catch(e){E('backupSummary').textContent='Importazione fallita';alert('Import backup fallito: '+e)}}
function mqttSelectAll(v){document.querySelectorAll('[data-mqbit]').forEach(x=>x.checked=!!v)}function mqttSetMask(mask){const m=Number(mask)>>>0;document.querySelectorAll('[data-mqbit]').forEach(x=>x.checked=(m&(1<<Number(x.dataset.mqbit)))!==0)}function mqttGetMask(){let m=0;document.querySelectorAll('[data-mqbit]').forEach(x=>{if(x.checked)m|=(1<<Number(x.dataset.mqbit))});return m>>>0}function updateTlsUi(){const mode=Number(E('mqTlsMode').value);E('mqCaLabel').style.display=mode===1?'flex':'none'}async function loadMqtt(){try{const m=await (await fetch('/api/mqtt',{cache:'no-store'})).json();E('mqEnabled').checked=!!m.enabled;E('mqBroker').value=m.broker||'';E('mqPort').value=m.port||1883;E('mqUser').value=m.user||'';E('mqClient').value=m.client_id||'';E('mqTopic').value=m.base_topic||'';E('mqTlsMode').value=String(m.tls_mode||0);E('mqCa').value=m.ca_certificate||'';mqttSetMask(m.fields_mask==null?268435455:m.fields_mask);E('mqPassword').value='';E('mqClearPass').checked=false;E('mqPassword').placeholder=m.has_password?'password salvata · vuoto = mantieni':'nessuna password';updateTlsUi();E('mqttSummary').textContent=(m.enabled?(m.connected?' · CONNESSO':' · non connesso'):' · disabilitato')+' · '+(m.broker||'-')+':'+m.port+' · '+(m.tls_name||'OFF');const hm=E('hdrMqtt');hm.className='statusPill '+(!m.enabled?'wait':(m.connected?'ok':'bad'));hm.textContent=!m.enabled?'MQTT OFF':(m.connected?'MQTT OK':'MQTT KO');}catch(e){E('mqttSummary').textContent=' · errore';const hm=E('hdrMqtt');if(hm){hm.className='statusPill bad';hm.textContent='MQTT ERR'}}}
async function saveMqtt(){const q=new URLSearchParams();q.set('enabled',E('mqEnabled').checked?'1':'0');q.set('broker',E('mqBroker').value);q.set('port',E('mqPort').value);q.set('user',E('mqUser').value);q.set('client_id',E('mqClient').value);q.set('base_topic',E('mqTopic').value);q.set('tls_mode',E('mqTlsMode').value);q.set('ca_certificate',E('mqCa').value);q.set('fields_mask',String(mqttGetMask()));if(E('mqPassword').value)q.set('password',E('mqPassword').value);if(E('mqClearPass').checked)q.set('clear_password','1');const r=await fetch('/api/mqtt',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});if(!r.ok){alert('MQTT: '+await r.text());return}await loadMqtt();}
async function resetMqtt(){if(!confirm('Ripristinare i valori MQTT compilati nel firmware?'))return;const r=await fetch('/api/mqtt/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset MQTT fallito');return}await loadMqtt();}
function dSet(attr,mask){const m=Number(mask)>>>0;document.querySelectorAll('['+attr+']').forEach(x=>x.checked=(m&(1<<Number(x.getAttribute(attr))))!==0)}
function dGet(attr){let m=0;document.querySelectorAll('['+attr+']').forEach(x=>{if(x.checked)m|=(1<<Number(x.getAttribute(attr)))});return m>>>0}
function displaySelectPages(v){document.querySelectorAll('[data-dpagebit]').forEach(x=>x.checked=!!v)}function displayAutoEnablePages(){const groups=[['data-denvbit',0],['data-dwindbit',1],['data-dtechbit',2],['data-dpressbit',3],['data-dstatusbit',4]];for(const [attr,bit] of groups){if([...document.querySelectorAll('['+attr+']')].some(x=>x.checked)){const p=document.querySelector('[data-dpagebit=\"'+bit+'\"]');if(p)p.checked=true;}}}
async function loadDisplay(){try{const d=await (await fetch('/api/display/config',{cache:'no-store'})).json();E('dispOn').checked=!!d.on;E('dispInterval').value=d.page_interval_sec||7;E('dispContrast').value=d.contrast||255;dSet('data-dpagebit',d.page_mask==null?31:d.page_mask);dSet('data-denvbit',d.environment_fields==null?15:d.environment_fields);dSet('data-dwindbit',d.wind_rain_fields==null?15:d.wind_rain_fields);dSet('data-dtechbit',d.technoline_fields==null?31:d.technoline_fields);dSet('data-dpressbit',d.pressure_fields==null?15:d.pressure_fields);dSet('data-dstatusbit',d.status_fields==null?31:d.status_fields);E('displaySummary').textContent=(d.on?'OLED ON':'OLED OFF')+' · pagina '+(Number(d.current_page)+1)+' · cambio '+d.page_interval_sec+' s · contrasto '+d.contrast+' · NVS '+(d.nvs_ok?'OK':'KO');}catch(e){E('displaySummary').textContent='errore lettura display'}}
async function saveDisplayConfig(){displayAutoEnablePages();const pageMask=dGet('data-dpagebit');if(!pageMask){alert('Seleziona almeno una pagina OLED.');return}const q=new URLSearchParams();q.set('on',E('dispOn').checked?'1':'0');q.set('page_mask',String(pageMask));q.set('environment_fields',String(dGet('data-denvbit')));q.set('wind_rain_fields',String(dGet('data-dwindbit')));q.set('technoline_fields',String(dGet('data-dtechbit')));q.set('pressure_fields',String(dGet('data-dpressbit')));q.set('status_fields',String(dGet('data-dstatusbit')));q.set('page_interval_sec',E('dispInterval').value);q.set('contrast',E('dispContrast').value);const r=await fetch('/api/display/config',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});if(!r.ok){alert('DISPLAY: '+await r.text());return}const j=await r.json();displayOn=!!j.display_on;updateDisplayUi();await loadDisplay();}
async function resetDisplayConfig(){if(!confirm('Ripristinare pagine/campi/intervallo/contrasto OLED ai default firmware?'))return;const r=await fetch('/api/display/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset DISPLAY fallito');return}await loadDisplay();}
async function restartDevice(){if(!confirm('Riavviare ora la scheda ESP32?'))return;const r=await fetch('/api/restart',{method:'POST',cache:'no-store'});if(r.ok)alert('Riavvio ESP32 avviato. La pagina tornera disponibile tra pochi secondi.');else alert('Riavvio fallito');}let displayOn=true,displayBusy=false;async function toggleDisplay(){if(displayBusy)return;displayBusy=true;const btn=E('displayBtn'),target=!displayOn;if(btn)btn.disabled=true;try{const r=await fetch('/api/display?on='+(target?1:0),{method:'POST',cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const j=await r.json();displayOn=!!j.display_on;}catch(e){alert('Comando display fallito: '+e)}finally{if(btn)btn.disabled=false;updateDisplayUi();}}function updateDisplayUi(){const btn=E('displayBtn'),st=E('sysDisplay'),cfg=E('dispOn');if(btn){btn.textContent=displayOn?'OLED ON':'OLED OFF';btn.classList.toggle('active',!displayOn);btn.title=displayOn?'Clic per spegnere il display OLED':'Clic per riaccendere il display OLED';}if(st){st.textContent=displayOn?'ON':'POWER SAVE';st.className='value '+(displayOn?'ok':'muted');}if(cfg&&!(mainTab==='config'&&E('cfgDisplay')&&E('cfgDisplay').classList.contains('active')))cfg.checked=displayOn;}function setCompass(prefix,deg,label){const g=E(prefix+'CompassNeedle'),d=E(prefix+'CompassDeg'),n=E(prefix+'CompassDir');if(!g||deg==null||!Number.isFinite(Number(deg))){if(g)g.style.opacity=.25;if(d)d.textContent='--°';if(n)n.textContent='--';return}const v=((Number(deg)%360)+360)%360;g.style.opacity=1;g.setAttribute('transform','rotate('+v+' 60 60)');d.textContent=Math.round(v)+'°';n.textContent=label||''}function fmtBytes(v){const n=Number(v||0);if(n>=1048576)return (n/1048576).toFixed(2)+' MB';if(n>=1024)return (n/1024).toFixed(1)+' KB';return n+' B'}function fmtUptime(sec){let s=Number(sec||0),d=Math.floor(s/86400);s%=86400;let h=Math.floor(s/3600);s%=3600;let m=Math.floor(s/60);return (d?d+' g ':'')+String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')}
function push(k,v){if(v==null)return;hist[k].push(Number(v));if(hist[k].length>60)hist[k].shift()}function spark(id,a){const el=document.getElementById(id);if(!el||a.length<2){if(el)el.innerHTML='';return}let mn=Math.min(...a),mx=Math.max(...a);if(mx===mn)mx=mn+1;let pts=a.map((v,i)=>((i/(a.length-1))*112+1).toFixed(1)+','+(26-((v-mn)/(mx-mn))*22).toFixed(1)).join(' ');el.innerHTML='<polyline points="'+pts+'" fill="none" stroke="#83b7ff" stroke-width="2"/>'}
async function refresh(){try{const s=await (await fetch('/api/state',{cache:'no-store'})).json(),w=s.weather,bme=s.bme280||{},p=s.packets,r=s.rf,a=s.fresh,ss=s.sensors,lc=s.lacrosse,lcr=s.lacrosse_rf,sess=s.session,b=s.burst,wp=s.wgr_probe||{},sys=s.system||{};
const net=E('net'),temp=E('temp'),hum=E('hum'),hi=E('hi'),dew=E('dew'),tin=E('tin'),hin=E('hin'),ageT=E('ageT'),footT=E('footT'),psta=E('psta'),psea=E('psea'),ptrend=E('ptrend'),forecast=E('forecast'),ageP=E('ageP'),footP=E('footP'),wind=E('wind'),gust=E('gust'),dir=E('dir'),wc=E('wc'),ageW=E('ageW'),footW=E('footW'),rate=E('rate'),r1h=E('r1h'),r24=E('r24'),rtot=E('rtot'),rinc=E('rinc'),ageR=E('ageR'),footR=E('footR'),uv=E('uv'),ageU=E('ageU'),footU=E('footU'),pkts=E('pkts'),rf=E('rf'),timing=E('timing'),quality=E('quality'),qualityLc=E('qualityLc'),burstDiag=E('burstDiag'),wgrDiag=E('wgrDiag'),bursts=E('bursts'),raw=E('raw');
net.className='statusPill '+(s.wifi.connected?'ok':'bad');net.textContent=s.wifi.connected?'Wi-Fi '+s.wifi.rssi+' dBm':'Wi-Fi KO';const hr=E('hdrRf');hr.className='statusPill '+(s.rf_mode?'ok':'wait');hr.textContent='RF '+String(s.rf_mode||'--').toUpperCase();E('sysChip').textContent=(sys.chip||'ESP32')+' rev '+(sys.revision??'-');E('sysCpu').textContent=(sys.cpu_mhz??'--')+' MHz';E('sysCores').textContent=sys.cores??'--';E('sysUptime').textContent=fmtUptime(sys.uptime_s);E('sysFirmware').textContent=sys.firmware||'--';E('sysGit').textContent=sys.git_commit||'--';E('sysBuild').textContent=sys.build||'--';E('sysReset').textContent=sys.reset_reason||'--';E('sysBoard').textContent=sys.board||'--';E('sysDisplayButton').textContent=sys.display_button_enabled?('GPIO '+sys.display_button_pin+' · pressione breve'):'disabilitato';E('sysHeapUsed').textContent=fmtBytes(sys.heap_used)+' / '+fmtBytes(sys.heap_size);E('sysHeapFree').textContent=fmtBytes(sys.heap_free);E('sysHeapMin').textContent=fmtBytes(sys.heap_min_free);const heapPct=sys.heap_size?Math.min(100,Math.max(0,Number(sys.heap_used)*100/Number(sys.heap_size))):0;E('sysHeapBar').style.width=heapPct.toFixed(1)+'%';E('sysHeapPct').textContent=heapPct.toFixed(1)+'%';E('sysFlash').textContent=fmtBytes(sys.sketch_size)+' / '+fmtBytes(sys.flash_size);E('sysOta').textContent=fmtBytes(sys.free_sketch_space);E('sysWifi').textContent=(sys.wifi_rssi??'--')+' dBm';E('sysOvf').textContent=sys.rf_overflows??0;E('sysHostname').textContent=s.wifi.hostname||'--';E('sysMdns').textContent=s.wifi.mdns||'--';E('sysIp').textContent=s.wifi.ip||'--';displayOn=sys.display_on!==false;updateDisplayUi();const flashPct=sys.flash_size?Math.min(100,Math.max(0,Number(sys.sketch_size)*100/Number(sys.flash_size))):0;E('sysFlashBar').style.width=flashPct.toFixed(1)+'%';const isDual=s.rf_mode==='dual',isO=s.rf_mode==='oregon'||isDual,isT=s.rf_mode==='technoline'||isDual;E('modeDual').classList.toggle('active',isDual);E('modeOregon').classList.toggle('active',s.rf_mode==='oregon');E('modeTechnoline').classList.toggle('active',s.rf_mode==='technoline');E('oregonPanel').classList.toggle('stationInactive',!isO);E('lacrossePanel').classList.toggle('stationInactive',!isT);for(let i=0;i<4;i++)E('gain'+i).classList.toggle('active',Number(r.rx_gain)===i);const profMap={STABILE:'profStable','AMPIO-AGC':'profWide','MAX-125':'profMax','AUTO-SCAN':'profAuto'};for(const id of ['profStable','profWide','profMax','profAuto']){E(id).classList.toggle('active',profMap[r.frontend_profile]===id);E(id).disabled=!isO||modeBusy||(id==='profAuto'&&isDual)}const mb=E('oregonModeBadge');mb.className='badge '+(isO?'ok':'off');mb.textContent=isO?(isDual?'RF OREGON · DUAL':'RF OREGON IN ASCOLTO'):'RF non in ascolto · seleziona OREGON/DUAL';E('sessionAge').textContent=isO?'attiva da '+age(sess.age_s).replace(' fa',''):'sessione sospesa';E('sessionAge').className='badge '+(isO?'ok':'off');setBadge('acqThermo',sess.thermo_acquired,'THGN '+(sess.thermo_acquired?'OK':'attesa'));setBadge('acqWind',sess.wind_acquired,'WGR '+(sess.wind_acquired?'OK':'attesa'));setBadge('acqRain',sess.rain_acquired,'PCR '+(sess.rain_acquired?'OK':'attesa'));setBadge('acqUv',sess.uv_acquired,'UVN '+(sess.uv_acquired?'OK':'attesa'));const tmb=E('technolineModeBadge');tmb.className='badge '+(isT?'ok':'off');tmb.textContent=isT?(isDual?'RF TECHNOLINE · DUAL':'RF TECHNOLINE IN ASCOLTO'):'RF non in ascolto';E('lcSessionAge').textContent=isT?'attiva da '+age(sess.age_s).replace(' fa',''):'sessione sospesa';E('lcSessionAge').className='badge '+(isT?'ok':'off');setBadge('lcAcqT',sess.lc_temperature_acquired,'TEMP '+(sess.lc_temperature_acquired?'OK':'attesa'));setBadge('lcAcqH',sess.lc_humidity_acquired,'HUM '+(sess.lc_humidity_acquired?'OK':'attesa'));setBadge('lcAcqW',sess.lc_wind_acquired,'WIND '+(sess.lc_wind_acquired?'OK':'attesa'));const lcGustExpected=(Number(sess.lc_expected_mask||0)&16)!==0;if(lcGustExpected)setBadge('lcAcqG',sess.lc_gust_acquired,'GUST '+(sess.lc_gust_acquired?'OK':'attesa'));else{E('lcAcqG').className='badge off';E('lcAcqG').textContent='GUST non annunciata'}setBadge('lcAcqR',sess.lc_rain_acquired,'RAIN '+(sess.lc_rain_acquired?'OK':'attesa'));E('burstExtra').classList.toggle('active',!!b.enabled);E('burstExtra').textContent=b.enabled?'BURST EXTRA ON':'BURST EXTRA OFF';E('wgrProbe').classList.toggle('active',!!wp.enabled);E('wgrProbe').textContent=wp.enabled?'WGR PROBE ON':'WGR PROBE OFF';
if(isO&&!sess.thermo_acquired){showOrWait(temp,false,'');showOrWait(hum,false,'');showOrWait(hi,false,'');showOrWait(dew,false,'');ageT.textContent='ultimo dato '+age(a.thermo_age_s)}else{showOrWait(temp,true,f(w.temperature_c,1,' °C'));showOrWait(hum,true,f(w.humidity_pct,0,' %'));showOrWait(hi,true,w.heat_index_c==null?'N/A':f(w.heat_index_c,1,' °C'));showOrWait(dew,true,f(w.dew_point_c,1,' °C'));ageT.textContent=age(a.thermo_age_s)}footT.innerHTML='AF: '+p.AF+' · sessione '+sess.thermo_received+' · '+ss.thermo.model+' '+ss.thermo.code+' · '+batt(ss.thermo);setFresh('ageT',a.thermo_age_s,isO&&sess.thermo_acquired);
const bmeOk=!!bme.detected;E('bmeBadge').className='badge '+(bmeOk?'ok':'off');E('bmeBadge').textContent=bmeOk?'BME280 locale OK':'BME280 non rilevato';tin.textContent=f(bme.temperature_c,1,' °C');hin.textContent=f(bme.humidity_pct,0,' %');E('bmeAge').textContent=age(bme.age_s);psta.textContent=f(bme.pressure_station_hpa,1,' hPa');psea.textContent=f(bme.altimeter_hpa,1,' hPa');ptrend.textContent=bme.trend_hpa_3h==null?'in acquisizione':((bme.trend_hpa_3h>=0?'+':'')+f(bme.trend_hpa_3h,1,' hPa/3h'));forecast.textContent=bme.forecast||'In acquisizione';ageP.textContent=age(bme.age_s);footP.textContent=bmeOk?(bme.model+' · quota '+f(bme.altitude_m,0,' m')+' · trend '+(bme.trend||'N/D')):'BME280 non rilevato';E('bmeFootEnv').textContent=bmeOk?'Sensore hardware locale · indipendente da Oregon e Technoline':'BME280 non rilevato sul bus I²C';setFresh('bmeAge',bme.age_s,bmeOk);setFresh('ageP',bme.age_s,bmeOk);
if(isO&&!sess.wind_acquired){showOrWait(wind,false,'');showOrWait(gust,false,'');showOrWait(dir,false,'');showOrWait(wc,false,'');ageW.textContent='ultimo dato '+age(a.wind_age_s)}else{showOrWait(wind,true,f(w.wind_average_kmh,1,' km/h'));showOrWait(gust,true,f(w.wind_gust_kmh,1,' km/h'));showOrWait(dir,true,w.wind_direction_deg==null?'--':f(w.wind_direction_deg,1,'° ')+w.wind_direction);showOrWait(wc,true,w.wind_chill_c==null?'N/A':f(w.wind_chill_c,1,' °C'));ageW.textContent=age(a.wind_age_s)}footW.innerHTML='A1: '+p.A1+' · sessione '+sess.wind_received+' · '+ss.wind.model+' '+ss.wind.code+' · '+batt(ss.wind)+' · WGR scan '+r.wind_recovery_success+'/'+r.wind_recovery_starts+' · csKO '+r.wind_scan_checksum_fail;setCompass('oregon',isO&&sess.wind_acquired?w.wind_direction_deg:null,w.wind_direction||'');setFresh('ageW',a.wind_age_s,isO&&sess.wind_acquired);
if(isO&&!sess.rain_acquired){showOrWait(rate,false,'');showOrWait(r1h,false,'');showOrWait(r24,false,'');showOrWait(rtot,false,'');showOrWait(rinc,false,'');ageR.textContent='ultimo dato '+age(a.rain_age_s)}else{showOrWait(rate,true,f(w.rain_rate_mmh,2,' mm/h'));showOrWait(r1h,true,f(w.rain_last_hour_mm,2,' mm'));showOrWait(r24,true,f(w.rain_last_24h_mm,2,' mm'));showOrWait(rtot,true,f(w.rain_total_mm,2,' mm'));showOrWait(rinc,true,f(w.rain_increment_mm,2,' mm'));ageR.textContent=age(a.rain_age_s)}footR.innerHTML='A2: '+p.A2+' · sessione '+sess.rain_received+' · '+ss.rain.model+' '+ss.rain.code+' · '+batt(ss.rain)+' · storico 1h/24h locale';setFresh('ageR',a.rain_age_s,isO&&sess.rain_acquired);
if(isO&&!sess.uv_acquired){showOrWait(uv,false,'');ageU.textContent='ultimo dato '+age(a.uv_age_s)}else{showOrWait(uv,true,w.uv<0?'--':Number(w.uv).toFixed(1));ageU.textContent=age(a.uv_age_s)}footU.innerHTML='AD: '+p.AD+' · sessione '+sess.uv_received+' · '+ss.uv.model+' '+ss.uv.code+' · '+batt(ss.uv);setFresh('ageU',a.uv_age_s,isO&&sess.uv_acquired);
if(isT&&!sess.lc_temperature_acquired){showOrWait(E('lcTemp'),false,'')}else{showOrWait(E('lcTemp'),true,f(lc.temperature_c,1,' °C'))}if(isT&&!sess.lc_humidity_acquired){showOrWait(E('lcHum'),false,'')}else{showOrWait(E('lcHum'),true,f(lc.humidity_pct,0,' %'))}E('lcAgeT').textContent='T '+age(lc.temperature_age_s)+' · H '+age(lc.humidity_age_s);E('lcModel').textContent=lc.model;E('lcId').textContent='0x'+Number(lc.sensor_id||0).toString(16).padStart(2,'0').toUpperCase();if(isT&&!sess.lc_wind_acquired){showOrWait(E('lcWind'),false,'')}else{showOrWait(E('lcWind'),true,f(lc.wind_kmh,1,' km/h'))}if(isT&&!sess.lc_gust_acquired&&lcGustExpected){showOrWait(E('lcGust'),false,'')}else if(!lcGustExpected&&!sess.lc_gust_acquired){E('lcGust').classList.remove('waitingText');E('lcGust').textContent='non annunciata'}else{showOrWait(E('lcGust'),true,f(lc.gust_kmh,1,' km/h'))}if(isT&&!sess.lc_wind_acquired){showOrWait(E('lcDir'),false,'')}else{showOrWait(E('lcDir'),true,lc.direction_deg==null?'--':f(lc.direction_deg,1,'° ')+lc.direction)}E('lcAgeW').textContent='W '+age(lc.wind_age_s)+' · G '+age(lc.gust_age_s);E('lcNext').textContent=lc.next_update;if(isT&&!sess.lc_rain_acquired){showOrWait(E('lcRain'),false,'');showOrWait(E('lcRainInc'),false,'')}else{showOrWait(E('lcRain'),true,f(lc.rain_total_mm,2,' mm'));showOrWait(E('lcRainInc'),true,f(lc.rain_increment_mm,2,' mm'))}E('lcAgeR').textContent=age(lc.rain_age_s);E('lcFootTH').textContent='T '+lc.temperature_packets+' · H '+lc.humidity_packets+' · sessione '+sess.lc_temperature_received+'/'+sess.lc_humidity_received+' · BAT N/D';setFresh('lcAgeT',lc.temperature_age_s,isT&&sess.lc_temperature_acquired);E('lcFootW').textContent='W '+lc.wind_packets+' · G '+lc.gust_packets+' · sessione '+sess.lc_wind_received+'/'+sess.lc_gust_received+' · GUST '+(lcGustExpected?'annunciata':'non annunciata')+' · next '+lc.next_update;setFresh('lcAgeW',lc.wind_age_s,isT&&(sess.lc_wind_acquired||sess.lc_gust_acquired));setCompass('lc',isT&&(sess.lc_wind_acquired||sess.lc_gust_acquired)?lc.direction_deg:null,lc.direction||'');E('lcFootR').textContent='Rain '+lc.rain_packets+' · sessione '+sess.lc_rain_received+' · incremento locale';setFresh('lcAgeR',lc.rain_age_s,isT&&sess.lc_rain_acquired);
push('temp',w.temperature_c);push('bmeTemp',bme.temperature_c);push('press',bme.pressure_station_hpa);push('wind',w.wind_average_kmh);push('rain',w.rain_rate_mmh);push('uv',w.uv<0?null:w.uv);push('lcTemp',lc.temperature_c);push('lcWind',lc.wind_kmh);push('lcRain',lc.rain_total_mm);spark('spTemp',hist.temp);spark('spBmeTemp',hist.bmeTemp);spark('spPress',hist.press);spark('spWind',hist.wind);spark('spRain',hist.rain);spark('spUv',hist.uv);spark('spLcTemp',hist.lcTemp);spark('spLcWind',hist.lcWind);spark('spLcRain',hist.lcRain);
pkts.innerHTML='<b>Pacchetti validi</b><br>AF termo: '+p.AF+'<br>A1 vento: <b>'+p.A1+'</b><br>A2 pioggia: '+p.A2+'<br>AD UV: '+p.AD+'<br>DROP parser/checksum: '+p.rejected;
rf.innerHTML='<b>Decoder RF Oregon</b><br>legacy strong: '+r.strong_frames+' frame<br>state-aware: <b>'+r.state_frames+'</b> frame · pre '+r.state_preambles+' · cand '+r.state_candidates+'<br>state checksum OK/fail: '+r.state_checksum_ok+'/'+r.state_checksum_fail+'<br><b>WGR800 1984 V3.0</b>: nessun preambolo speciale<br>WGR window OK/header/checksum KO: <b>'+r.wind_recovery_success+'</b>/'+r.wind_recovery_starts+'/'+r.wind_scan_checksum_fail+'<br>Burst Analyzer: <span class=muted>solo diagnostica, non decodifica</span><br>raw A1: <b>'+r.raw_A1+'</b> · duplicati '+r.duplicates;
timing.innerHTML='<b>Timing RF · modo '+s.rf_mode.toUpperCase()+'</b><br>ON short/long: '+r.on_short_avg_us+'/'+r.on_long_avg_us+' µs<br>OFF short/long: '+r.off_short_avg_us+'/'+r.off_long_avg_us+' µs<br>state err timing/manchester: '+r.state_timing_errors+'/'+r.state_manchester_errors+'<br>legacy short/long: '+r.short_avg_us+'/'+r.long_avg_us+' µs<br>BW '+r.rx_bw_khz.toFixed(1)+' kHz · gain '+r.rx_gain+' ('+r.gain_name+') · profilo <b>'+r.frontend_profile+'</b> · O/T '+r.gain_oregon+'/'+r.gain_lacrosse+' · ovf '+r.overflows+(r.rx_gain===0?' · <span class=ok>AGC</span>':' · <span class=bad>gain fisso</span>')+'<br><b>TECH live PWM · doppio decoder</b><br><b>PracticalArduino leader 00001:</b> start '+lcr.leader_starts+' (lost0 '+lcr.leader_lost_zero+') · frame '+lcr.leader_frames+' · <span class=ok>OK '+lcr.leader_valid+'</span> · KO '+lcr.leader_invalid+'<br>progress L0/L1 '+lcr.leader_bits_0+'/'+lcr.leader_bits_1+' · reset '+lcr.leader_resets+' · reject '+lcr.leader_rejects+'<br><b>rtl_433 pulse-window:</b> OK '+lcr.stream_valid+' · windows '+lcr.stream_windows+' · header '+lcr.stream_header_matches+' · pulses '+lcr.stream_pulses+' · H '+lcr.active_hypothesis+'<br>fail H/C/P/S '+lcr.header_fail+'/'+lcr.complement_fail+'/'+lcr.parity_fail+'/'+lcr.checksum_fail+' · short/long '+lcr.short_us+'/'+lcr.long_us+' µs<br>BURST recovery '+lcr.burst_valid+'/'+lcr.burst_attempts+' · missing-edge '+lcr.burst_recovered_missing_edge+' · reject '+lcr.burst_rejects+'<br>raw intervalli &lt;200/200-599/600-1099/1100-1799/1800-3499/≥3500: '+(lcr.interval_bins||[]).join('/');const stepRemain=b.auto_active?Math.max(0,Math.ceil((b.auto_step_duration_ms-(Number(s.uptime_s)*1000-b.auto_step_started_ms))/1000)):0;burstDiag.innerHTML='<b>RF Burst Analyzer / Recovery</b><br>stato: '+(b.enabled?'<span class=ok>ON</span>':'<span class=muted>OFF · percorso live invariato</span>')+'<br>burst totali: '+b.total+' · OSV3-like: <b>'+b.osv3_like+'</b> · TECH-like '+b.technoline_like+' · scartati '+b.discarded+'<br>profilo: <b>'+r.frontend_profile+'</b> · BW '+r.rx_bw_khz.toFixed(1)+' kHz · gain '+r.rx_gain+(b.auto_active?'<br><span class=ok>AUTO SCAN step '+(b.auto_step+1)+'/4 · ~'+stepRemain+' s residui</span>':'')+'<br><span class=muted>BURST EXTRA è opzionale: attivalo solo per diagnostica/recovery. In DUAL i decoder Oregon e Technoline live lavorano sempre insieme.</span>';wgrDiag.innerHTML='<b>WGR800 1984 · RF Probe</b><br>stato: '+(wp.enabled?'<span class=ok>ON · RAM-only</span>':'<span class=muted>OFF · nessun overhead</span>')+'<br>burst/osv3: '+wp.bursts_total+'/'+wp.osv3_like+' · classificati AF/A1/A2/AD '+wp.classified_af+'/'+wp.classified_a1+'/'+wp.classified_a2+'/'+wp.classified_ad+'<br>OSV3 non classificati: <b>'+wp.unclassified_osv3+'</b> · cadenza ~14 s: <b>'+wp.cadence14+'</b><br>ultimo non classificato: Δ '+(wp.last_unclassified_delta_ms?Math.round(wp.last_unclassified_delta_ms/1000*10)/10+' s':'-')+' · '+wp.last_unclassified_duration_ms+' ms · '+wp.last_unclassified_edges+' edge · match '+wp.last_unclassified_match_pct+'% · RSSI '+f(wp.last_unclassified_rssi,1)+'<br><span class=muted>Se crescono “OSV3 non classificati” e “cadenza ~14 s” mentre A1 resta a zero, la portante WGR arriva ma il Manchester/frame non viene ricostruito. Se restano a zero, indagare il trasmettitore/RF.</span>';quality.innerHTML=isO?('<b>Qualita sessione Oregon</b><div class="qrow qhdr"><span>Sensore</span><span>Rx</span><span>Attesi</span><span>Qualita</span></div>'+'<div class="qrow"><span>THGN ~53s</span><span>'+sess.thermo_received+'</span><span>'+sess.thermo_expected+'</span><span class="'+qClass(sess.thermo_quality_pct)+'">'+qText(sess.thermo_quality_pct)+'</span></div>'+'<div class="qrow"><span>WGR ~14s</span><span>'+sess.wind_received+'</span><span>'+sess.wind_expected+'</span><span class="'+qClass(sess.wind_quality_pct)+'">'+qText(sess.wind_quality_pct)+'</span></div>'+'<div class="qrow"><span>PCR ~47s</span><span>'+sess.rain_received+'</span><span>'+sess.rain_expected+'</span><span class="'+qClass(sess.rain_quality_pct)+'">'+qText(sess.rain_quality_pct)+'</span></div>'+'<div class="qrow"><span>UVN ~73s</span><span>'+sess.uv_received+'</span><span>'+sess.uv_expected+'</span><span class="'+qClass(sess.uv_quality_pct)+'">'+qText(sess.uv_quality_pct)+'</span></div><div class="muted" style="margin-top:7px">Sessione azzerata al cambio protocollo/gain.</div>'):'<b>Qualita sessione Oregon</b><br><span class="muted">OREGON non in ascolto.</span>';qualityLc.innerHTML=isT?('<b>Qualita sessione Technoline</b><div class="qrow qhdr"><span>Dato</span><span>Rx</span><span>Ultimo</span><span>Stato</span></div>'+ '<div class="qrow"><span>Decoder leader</span><span>'+lcr.leader_valid+'/'+lcr.leader_frames+'</span><span>-</span><span class="'+qClass(sess.lc_decoder_quality_pct)+'">'+qText(sess.lc_decoder_quality_pct)+'</span></div>'+ '<div class="qrow"><span>Temperatura</span><span>'+sess.lc_temperature_received+'</span><span>'+age(lc.temperature_age_s)+'</span><span>'+(sess.lc_temperature_acquired?'<span class=qgood>OK</span>':'attesa')+'</span></div>'+ '<div class="qrow"><span>Umidita</span><span>'+sess.lc_humidity_received+'</span><span>'+age(lc.humidity_age_s)+'</span><span>'+(sess.lc_humidity_acquired?'<span class=qgood>OK</span>':'attesa')+'</span></div>'+ '<div class="qrow"><span>Pioggia</span><span>'+sess.lc_rain_received+'</span><span>'+age(lc.rain_age_s)+'</span><span>'+(sess.lc_rain_acquired?'<span class=qgood>OK</span>':'attesa')+'</span></div>'+ '<div class="qrow"><span>Vento/Gust</span><span>'+sess.lc_wind_received+'/'+sess.lc_gust_received+'</span><span>'+age(lc.wind_age_s)+'</span><span>'+((sess.lc_wind_acquired||sess.lc_gust_acquired)?'<span class=qgood>OK</span>':'attesa')+'</span></div>'+ '<div class="muted" style="margin-top:7px">Tipi annunciati GWRH/T: mask 0x'+Number(sess.lc_expected_mask||0).toString(16).toUpperCase()+' · copertura tipi sessione <span class="'+qClass(sess.lc_type_coverage_pct)+'">'+qText(sess.lc_type_coverage_pct)+'</span> · next '+(sess.lc_cadence_ms?Math.round(sess.lc_cadence_ms/1000)+' s':'N/D')+'.</div>'):'<b>Qualita sessione Technoline</b><br><span class="muted">TECHNOLINE non in ascolto.</span>';if(mainTab==='diag'){const rr=await (await fetch('/api/raw',{cache:'no-store'})).json();raw.innerHTML=rr.map(e=>'<tr><td>'+e.ms+'</td><td class="'+(e.accepted?'ok':'bad')+'">'+(e.accepted?'OK':'DROP')+'</td><td>'+e.protocol+'</td><td>'+e.source+'</td><td>'+e.type+'</td><td>'+f(e.rssi,1)+'</td><td>'+e.hex+'</td><td>'+e.decoded+'</td></tr>').join('');if(b.enabled||b.auto_active){const bb=await (await fetch('/api/bursts',{cache:'no-store'})).json();bursts.innerHTML=bb.map(x=>'<tr><td>'+x.ms+'</td><td>'+x.duration_ms+' ms</td><td>'+x.edges+'</td><td>'+f(x.rssi,1)+'</td><td>'+x.match_pct+'%</td><td class="'+(x.osv3_like?'ok':'muted')+'">'+(x.osv3_like?'SI':'no')+'</td><td>'+(x.technoline_like?'TECH-like':(x.osv3_like?'OREGON-like':'rumore'))+'</td><td class="'+(x.adaptive_recovered?'ok':'muted')+'">'+(x.adaptive_recovered?'REC':'-')+'</td><td>'+x.on_short_us+'/'+x.on_long_us+'</td><td>'+x.off_short_us+'/'+x.off_long_us+'</td></tr>').join('')}else{bursts.innerHTML='<tr><td colspan=10 class=muted>BURST EXTRA disattivato · nessun overhead diagnostico sul percorso RF live</td></tr>';}}
}catch(e){net.textContent='Web: '+e}}
loadNetwork();loadMqtt();refresh();setInterval(refresh,2000);setInterval(()=>{const editing=mainTab==='config'&&E('cfgMqtt')&&E('cfgMqtt').classList.contains('active');if(!editing)loadMqtt();},10000);
</script></body></html>)HTML";
    sendNoCache();
    server.send_P(200, "text/html; charset=utf-8", PAGE);
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
    server.on("/api/display", HTTP_POST, handleDisplayPower);
    server.on("/api/display/config", HTTP_GET, handleDisplayConfigGet);
    server.on("/api/display/config", HTTP_POST, handleDisplayConfigPost);
    server.on("/api/display/reset", HTTP_POST, handleDisplayConfigReset);
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
    if (rebootAtMs && static_cast<int32_t>(millis() - rebootAtMs) >= 0) {
        Serial.println(F("[WEB] riavvio richiesto dalla configurazione"));
        delay(80);
        ESP.restart();
    }
#endif
}

void recordWebPacket(const OregonPacket &packet, const WeatherReading *reading, bool accepted) {
#if WEB_ENABLE
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
