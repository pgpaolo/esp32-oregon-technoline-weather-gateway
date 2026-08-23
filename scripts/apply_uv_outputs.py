#!/usr/bin/env python3
"""Patch Oregon multi-sensor outputs for the hardware-validation branch.

Adds:
- backwards-compatible per-UV retained MQTT topics;
- a generic per-transmitter Oregon MQTT namespace for every supported sensor;
- an optional OLED SENSORI RF page with compact RSSI/battery state for up to
  ten Oregon transmitters, rotating five rows at a time;
- a compact UV summary on the normal ESTERNO OLED page.

The stable MQTT transmitter key is sensorCode + channel + rollingCode, so
multiple thermo channels and future supported Oregon sensors never overwrite
one another. Existing legacy MQTT topics remain unchanged.
No RF decoder logic is changed.
"""

from pathlib import Path

Import("env")
ROOT = Path(env.subst("$PROJECT_DIR"))
MQTT = ROOT / "src" / "mqtt_publisher.cpp"
DISPLAY_H = ROOT / "src" / "display_manager.h"
DISPLAY_CPP = ROOT / "src" / "display_manager.cpp"
MAIN = ROOT / "src" / "main.cpp"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def patch_mqtt() -> None:
    text = MQTT.read_text(encoding="utf-8")

    if "oregon/uv/%04X/index" not in text:
        old = '    if (reading.uvValid && fieldEnabled(MQTT_F_OR_UV)) publishInt(client, "oregon/uv", reading.uvIndex);'
        new = '''    if (reading.uvValid && fieldEnabled(MQTT_F_OR_UV)) {
        // Legacy aggregate topic remains for existing consumers. Every UV
        // transmitter also receives its own retained namespace keyed by the
        // stable Oregon sensor code (D874=UVN800, EC70=UVR128).
        publishInt(client, "oregon/uv", reading.uvIndex);
        char uvSuffix[56];
        snprintf(uvSuffix, sizeof(uvSuffix), "oregon/uv/%04X/index", reading.sensorCode);
        publishInt(client, uvSuffix, reading.uvIndex);
        if (fieldEnabled(MQTT_F_RF_META)) {
            snprintf(uvSuffix, sizeof(uvSuffix), "oregon/uv/%04X/model", reading.sensorCode);
            client.publish(topic(uvSuffix).c_str(), sensorModelName(reading.sensorCode), true);
            if (!isnan(reading.rssi)) {
                snprintf(uvSuffix, sizeof(uvSuffix), "oregon/uv/%04X/rssi", reading.sensorCode);
                publishFloat(client, uvSuffix, reading.rssi, 1);
            }
            if (reading.batteryStatusValid) {
                snprintf(uvSuffix, sizeof(uvSuffix), "oregon/uv/%04X/battery", reading.sensorCode);
                client.publish(topic(uvSuffix).c_str(), reading.batteryLow ? "LOW" : "OK", true);
            }
            if (reading.channel) {
                snprintf(uvSuffix, sizeof(uvSuffix), "oregon/uv/%04X/channel", reading.sensorCode);
                publishInt(client, uvSuffix, reading.channel);
            }
            snprintf(uvSuffix, sizeof(uvSuffix), "oregon/uv/%04X/rolling_code", reading.sensorCode);
            publishInt(client, uvSuffix, reading.rollingCode);
        }
    }'''
        text = replace_once(text, old, new, "per-sensor UV MQTT")

    if "oregon/sensor/%04X/ch%u/id%u" not in text:
        marker = '''    if (fieldEnabled(MQTT_F_RF_META)) {
        char sensorId[8]; snprintf(sensorId, sizeof(sensorId), "0x%02X", reading.sensorId);'''
        generic = '''    // Generic per-transmitter namespace. Every accepted Oregon transmitter
    // is kept separate by sensor code + channel + rolling code. Field selection
    // still uses the existing 32-bit MQTT mask, so no extra NVS schema is needed.
    char sensorBase[64];
    snprintf(sensorBase, sizeof(sensorBase), "oregon/sensor/%04X/ch%u/id%u",
             reading.sensorCode, reading.channel, reading.rollingCode);
    char sensorSuffix[88];

    if (reading.temperatureValid && fieldEnabled(MQTT_F_OR_TEMP)) {
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/temperature", sensorBase);
        publishFloat(client, sensorSuffix, reading.temperatureC, 1);
    }
    if (reading.humidityValid && fieldEnabled(MQTT_F_OR_HUM)) {
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/humidity", sensorBase);
        publishFloat(client, sensorSuffix, reading.humidityPct, 0);
    }
    if (reading.windAverageValid && fieldEnabled(MQTT_F_OR_WIND_AVG)) {
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/wind_average", sensorBase);
        publishFloat(client, sensorSuffix, reading.windAverageKmh, 1);
    }
    if (reading.windGustValid && fieldEnabled(MQTT_F_OR_WIND_GUST)) {
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/wind_gust", sensorBase);
        publishFloat(client, sensorSuffix, reading.windGustKmh, 1);
    }
    if (reading.windDirectionValid && fieldEnabled(MQTT_F_OR_WIND_DIR)) {
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/wind_direction_deg", sensorBase);
        publishFloat(client, sensorSuffix, reading.windDirectionDeg, 1);
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/wind_direction", sensorBase);
        client.publish(topic(sensorSuffix).c_str(), windDirectionName(reading.windDirectionIndex), true);
    }
    if (reading.rainTotalValid && fieldEnabled(MQTT_F_OR_RAIN_TOTAL)) {
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/rain_total", sensorBase);
        publishFloat(client, sensorSuffix, reading.rainTotalMm, 2);
    }
    if (reading.rainRateValid && fieldEnabled(MQTT_F_OR_RAIN_RATE)) {
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/rain_rate", sensorBase);
        publishFloat(client, sensorSuffix, reading.rainRateMmH, 2);
    }
    if (reading.uvValid && fieldEnabled(MQTT_F_OR_UV)) {
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/uv", sensorBase);
        publishInt(client, sensorSuffix, reading.uvIndex);
    }

    if (fieldEnabled(MQTT_F_RF_META)) {
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/type", sensorBase);
        client.publish(topic(sensorSuffix).c_str(), sensorTypeName(reading.type), true);
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/model", sensorBase);
        client.publish(topic(sensorSuffix).c_str(), sensorModelName(reading.sensorCode), true);
        snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/protocol", sensorBase);
        client.publish(topic(sensorSuffix).c_str(),
                       packet.decodeSource == static_cast<uint8_t>(OregonDecodeSource::EdgeTimingV21) ? "V2.1" : "OSV3", true);
        if (!isnan(reading.rssi)) {
            snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/rssi", sensorBase);
            publishFloat(client, sensorSuffix, reading.rssi, 1);
        }
        if (reading.batteryStatusValid) {
            snprintf(sensorSuffix, sizeof(sensorSuffix), "%s/battery", sensorBase);
            client.publish(topic(sensorSuffix).c_str(), reading.batteryLow ? "LOW" : "OK", true);
        }
    }

''' + marker
        text = replace_once(text, marker, generic, "generic Oregon MQTT namespace")

    MQTT.write_text(text, encoding="utf-8")
    print("Oregon outputs: patched mqtt_publisher.cpp")


def patch_display_header() -> None:
    text = DISPLAY_H.read_text(encoding="utf-8")
    if "DISPLAY_PAGE_SENSORS" not in text:
        text = replace_once(
            text,
            "static constexpr uint8_t DISPLAY_PAGE_LIGHTNING   = 1U << 5;\nstatic constexpr uint8_t DISPLAY_PAGE_ALL         = 0x3FU;",
            "static constexpr uint8_t DISPLAY_PAGE_LIGHTNING   = 1U << 5;\nstatic constexpr uint8_t DISPLAY_PAGE_SENSORS     = 1U << 6;\nstatic constexpr uint8_t DISPLAY_PAGE_ALL         = 0x7FU;",
            "OLED sensor page bit",
        )
    if "noteDisplayOregonReading" not in text:
        old = "void updateDisplay(const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats, bool wifiOk, bool mqttOk);"
        new = "void noteDisplayOregonReading(const WeatherReading &reading);\nvoid updateDisplay(const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats, bool wifiOk, bool mqttOk);"
        text = replace_once(text, old, new, "OLED Oregon declaration")
    DISPLAY_H.write_text(text, encoding="utf-8")
    print("Oregon outputs: patched display_manager.h")


def patch_display_cpp() -> None:
    text = DISPLAY_CPP.read_text(encoding="utf-8")
    if "OledOregonSlot oledOregonSlots[10]" in text:
        print("Oregon outputs: display_manager.cpp already patched")
        return

    old_state = "Preferences displayPrefs;\nDisplayRuntimeConfig displayCfg{};\n"
    new_state = '''Preferences displayPrefs;
DisplayRuntimeConfig displayCfg{};

// Compact live registry for OLED only. It stores no history: ten slots mirror
// the maximum Web session registry and cost only a few bytes per transmitter.
struct OledOregonSlot {
    uint32_t updatedMs{0};
    uint16_t code{0};
    uint8_t channel{0};
    uint8_t rollingCode{0};
    uint8_t type{0};
    uint8_t batteryState{0}; // 0=N/D, 1=OK, 2=LOW
    int8_t uvIndex{-1};
    int8_t rssiDbm{-127};
};
OledOregonSlot oledOregonSlots[10]{};
uint8_t oledSensorWindow{0};
uint32_t oledSensorWindowEpoch{0};

char oledRssiGrade(int8_t dbm) {
    if (dbm <= -127) return '-';
    if (dbm >= -100) return 'G';
    if (dbm >= -115) return 'Y';
    return 'R';
}

char oledBatteryGrade(uint8_t state) {
    if (state == 1U) return '+';
    if (state == 2U) return '!';
    return '-';
}

char oledSensorTypeChar(uint8_t type) {
    switch (static_cast<SensorType>(type)) {
        case SensorType::ThermoHygro: return 'T';
        case SensorType::Wind: return 'W';
        case SensorType::Rain: return 'R';
        case SensorType::UV: return 'U';
        default: return '?';
    }
}
'''
    text = replace_once(text, old_state, new_state, "OLED Oregon compact state")

    text = replace_once(text, "return p < 6U &&", "return p < 7U &&", "OLED page count check")
    text = replace_once(text, "for (uint8_t p = 0; p < 6U; ++p)", "for (uint8_t p = 0; p < 7U; ++p)", "OLED first page loop")
    text = replace_once(text, "for (uint8_t step = 1; step <= 6U; ++step)", "for (uint8_t step = 1; step <= 7U; ++step)", "OLED next page loop")
    text = replace_once(text, "% 6U);", "% 7U);", "OLED page modulo")

    old_render = '''    if (displayCfg.environmentFields & DISPLAY_ENV_DEW) {
        if (s.dewPointValid) snprintf(line, sizeof(line), "Dew %.1fC", s.dewPointC);
        else snprintf(line, sizeof(line), "Dew --.-C");
        drawLine(line, y);
    }
    if (displayCfg.environmentFields & DISPLAY_ENV_HEAT_UV) {
        if (s.heatIndexValid) snprintf(line, sizeof(line), "Heat %.1fC  UV %d", s.heatIndexC, s.uvValid ? s.uvIndex : -1);
        else if (s.uvValid) snprintf(line, sizeof(line), "Heat N/A  UV %d", s.uvIndex);
        else snprintf(line, sizeof(line), "Heat N/A  UV --");
        drawLine(line, y);
    }
'''
    new_render = '''    const bool showHeatUv = (displayCfg.environmentFields & DISPLAY_ENV_HEAT_UV) != 0U;
    if (displayCfg.environmentFields & DISPLAY_ENV_DEW) {
        if (s.dewPointValid && showHeatUv && s.heatIndexValid)
            snprintf(line, sizeof(line), "Dew %.1f Heat %.1f", s.dewPointC, s.heatIndexC);
        else if (s.dewPointValid) snprintf(line, sizeof(line), "Dew %.1fC", s.dewPointC);
        else snprintf(line, sizeof(line), "Dew --.-C");
        drawLine(line, y);
    }
    if (showHeatUv) {
        if (!(displayCfg.environmentFields & DISPLAY_ENV_DEW)) {
            if (s.heatIndexValid) snprintf(line, sizeof(line), "Heat %.1fC", s.heatIndexC);
            else snprintf(line, sizeof(line), "Heat N/A");
            drawLine(line, y);
        }
        int uvA = -1, uvB = -1;
        uint16_t codeA = 0, codeB = 0;
        for (uint8_t i = 0; i < 10U; ++i) {
            const OledOregonSlot &u = oledOregonSlots[i];
            if (static_cast<SensorType>(u.type) != SensorType::UV || u.uvIndex < 0 || !u.updatedMs ||
                static_cast<uint32_t>(now - u.updatedMs) > 300000UL) continue;
            if (uvA < 0) { uvA = u.uvIndex; codeA = u.code; }
            else if (uvB < 0) { uvB = u.uvIndex; codeB = u.code; break; }
        }
        if (uvA >= 0 && uvB >= 0) snprintf(line, sizeof(line), "UV %04X:%d %04X:%d", codeA, uvA, codeB, uvB);
        else if (uvA >= 0) snprintf(line, sizeof(line), "UV %04X:%d", codeA, uvA);
        else snprintf(line, sizeof(line), "UV --");
        drawLine(line, y);
    }
'''
    text = replace_once(text, old_render, new_render, "OLED compact multi-UV rendering")

    sensor_renderer_marker = "void applyDisplayPower() {"
    sensor_renderer = '''void renderSensorHealth(bool wifiOk, bool mqttOk) {
    const uint32_t now = millis();
    uint8_t active[10];
    uint8_t count = 0;
    for (uint8_t i = 0; i < 10U; ++i) {
        if (!oledOregonSlots[i].updatedMs) continue;
        if (static_cast<uint32_t>(now - oledOregonSlots[i].updatedMs) > 600000UL) continue;
        active[count++] = i;
    }

    if (oledSensorWindowEpoch != pageEpochMs) {
        oledSensorWindowEpoch = pageEpochMs;
        if (count > 5U) oledSensorWindow = static_cast<uint8_t>((oledSensorWindow + 5U) % count);
        else oledSensorWindow = 0;
    }

    char title[20];
    if (count > 5U) snprintf(title, sizeof(title), "SENSORI RF %u/%u", oledSensorWindow / 5U + 1U, (count + 4U) / 5U);
    else snprintf(title, sizeof(title), "SENSORI RF");
    header(title, wifiOk, mqttOk);
    oled.setFont(u8g2_font_5x8_tf);
    uint8_t y = 23;
    if (!count) {
        drawLine("Nessun Oregon recente", y);
        return;
    }

    const uint8_t rows = count < 5U ? count : 5U;
    for (uint8_t n = 0; n < rows && y <= 63U; ++n) {
        const uint8_t pos = static_cast<uint8_t>((oledSensorWindow + n) % count);
        const OledOregonSlot &s = oledOregonSlots[active[pos]];
        char line[30];
        if (static_cast<SensorType>(s.type) == SensorType::UV && s.uvIndex >= 0) {
            snprintf(line, sizeof(line), "%c%u %04X U%d %d%c B%c", oledSensorTypeChar(s.type), s.channel,
                     s.code, static_cast<int>(s.uvIndex), static_cast<int>(s.rssiDbm),
                     oledRssiGrade(s.rssiDbm), oledBatteryGrade(s.batteryState));
        } else {
            snprintf(line, sizeof(line), "%c%u %04X %d%c B%c", oledSensorTypeChar(s.type), s.channel,
                     s.code, static_cast<int>(s.rssiDbm), oledRssiGrade(s.rssiDbm),
                     oledBatteryGrade(s.batteryState));
        }
        drawLine(line, y);
    }
}

''' + sensor_renderer_marker
    text = replace_once(text, sensor_renderer_marker, sensor_renderer, "OLED sensor health page")

    ns_end = "} // namespace\n\nvoid initDisplay() {"
    public_fn = '''} // namespace

void noteDisplayOregonReading(const WeatherReading &reading) {
    if (reading.type == SensorType::Unknown) return;
    OledOregonSlot *slot = nullptr;
    OledOregonSlot *oldest = &oledOregonSlots[0];
    for (uint8_t i = 0; i < 10U; ++i) {
        OledOregonSlot &candidate = oledOregonSlots[i];
        if (candidate.updatedMs == 0) { slot = &candidate; break; }
        if (candidate.code == reading.sensorCode && candidate.channel == reading.channel &&
            candidate.rollingCode == reading.rollingCode) { slot = &candidate; break; }
        if (static_cast<int32_t>(candidate.updatedMs - oldest->updatedMs) < 0) oldest = &candidate;
    }
    if (!slot) slot = oldest;
    slot->updatedMs = reading.receivedAtMs ? reading.receivedAtMs : millis();
    slot->code = reading.sensorCode;
    slot->channel = reading.channel;
    slot->rollingCode = reading.rollingCode;
    slot->type = static_cast<uint8_t>(reading.type);
    slot->batteryState = reading.batteryStatusValid ? (reading.batteryLow ? 2U : 1U) : 0U;
    slot->uvIndex = (reading.type == SensorType::UV && reading.uvValid) ? static_cast<int8_t>(reading.uvIndex) : -1;
    if (isfinite(reading.rssi)) {
        int rssi = static_cast<int>(lroundf(reading.rssi));
        if (rssi < -126) rssi = -126;
        if (rssi > 0) rssi = 0;
        slot->rssiDbm = static_cast<int8_t>(rssi);
    }
}

void initDisplay() {'''
    text = replace_once(text, ns_end, public_fn, "OLED Oregon recorder")

    old_switch = '''    if (page == 0) renderEnvironment(state, wifiOk, mqttOk);
    else if (page == 1) renderWindRain(state, wifiOk, mqttOk);
    else if (page == 2) renderLaCrosse(state, wifiOk, mqttOk);
    else if (page == 3) renderPressure(state, wifiOk, mqttOk);
    else if (page == 4) renderStatus(state, rxStats, lcStats, wifiOk, mqttOk);
    else renderLightning(wifiOk, mqttOk);'''
    new_switch = '''    if (page == 0) renderEnvironment(state, wifiOk, mqttOk);
    else if (page == 1) renderWindRain(state, wifiOk, mqttOk);
    else if (page == 2) renderLaCrosse(state, wifiOk, mqttOk);
    else if (page == 3) renderPressure(state, wifiOk, mqttOk);
    else if (page == 4) renderStatus(state, rxStats, lcStats, wifiOk, mqttOk);
    else if (page == 5) renderLightning(wifiOk, mqttOk);
    else renderSensorHealth(wifiOk, mqttOk);'''
    text = replace_once(text, old_switch, new_switch, "OLED sensor page dispatch")

    DISPLAY_CPP.write_text(text, encoding="utf-8")
    print("Oregon outputs: patched display_manager.cpp")


def patch_main() -> None:
    text = MAIN.read_text(encoding="utf-8")
    if "noteDisplayOregonReading(reading);" in text:
        print("Oregon outputs: main.cpp already patched")
        return
    old = '''            if (reading.type == SensorType::ThermoHygro) {
                noteThermoChannelReading(reading);
                applyThermoPrimary = thermoChannelIsPrimary(reading.channel);
            }
            applyWeatherReading(station, reading, applyThermoPrimary);'''
    new = '''            if (reading.type == SensorType::ThermoHygro) {
                noteThermoChannelReading(reading);
                applyThermoPrimary = thermoChannelIsPrimary(reading.channel);
            }
            noteDisplayOregonReading(reading);
            applyWeatherReading(station, reading, applyThermoPrimary);'''
    text = replace_once(text, old, new, "OLED Oregon feed")
    MAIN.write_text(text, encoding="utf-8")
    print("Oregon outputs: patched main.cpp")


patch_mqtt()
patch_display_header()
patch_display_cpp()
patch_main()
