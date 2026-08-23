#!/usr/bin/env python3
"""Patch UV/Oregon outputs for the hardware-validation branch.

Adds:
- backwards-compatible per-UV retained MQTT topics;
- a generic per-transmitter Oregon MQTT namespace for every supported sensor;
- a two-slot OLED UV view.

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
        generic = '''    // Generic per-transmitter namespace. This is intentionally independent
    // from the dashboard/primary-channel selection: every valid Oregon
    // transmitter that is actually received is exposed to MQTT. Existing
    // legacy topics above remain for backwards compatibility.
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
    print("UV/Oregon outputs: patched mqtt_publisher.cpp")


def patch_display_header() -> None:
    text = DISPLAY_H.read_text(encoding="utf-8")
    if "noteDisplayUvReading" in text:
        print("UV outputs: display_manager.h already patched")
        return
    old = "void updateDisplay(const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats, bool wifiOk, bool mqttOk);"
    new = "void noteDisplayUvReading(const WeatherReading &reading);\nvoid updateDisplay(const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats, bool wifiOk, bool mqttOk);"
    text = replace_once(text, old, new, "OLED UV declaration")
    DISPLAY_H.write_text(text, encoding="utf-8")
    print("UV outputs: patched display_manager.h")


def patch_display_cpp() -> None:
    text = DISPLAY_CPP.read_text(encoding="utf-8")
    if "OledUvSlot oledUvSlots[2]" in text:
        print("UV outputs: display_manager.cpp already patched")
        return

    old_state = "Preferences displayPrefs;\nDisplayRuntimeConfig displayCfg{};\n"
    new_state = '''Preferences displayPrefs;
DisplayRuntimeConfig displayCfg{};

// Only the two currently supported Oregon UV families need simultaneous OLED
// state (D874 UVN800 + EC70 UVR128). No history/buffer is allocated.
struct OledUvSlot {
    uint32_t updatedMs{0};
    uint16_t code{0};
    uint8_t channel{0};
    uint8_t rollingCode{0};
    int8_t uvIndex{-1};
    int8_t rssiDbm{-127};
};
OledUvSlot oledUvSlots[2]{};

const char *oledUvName(uint16_t code) {
    if (code == 0xD874U) return "N800";
    if (code == 0xEC70U) return "R128";
    return "UV";
}

char oledRssiGrade(int8_t dbm) {
    if (dbm <= -127) return '-';
    if (dbm >= -100) return 'G';
    if (dbm >= -115) return 'Y';
    return 'R';
}
'''
    text = replace_once(text, old_state, new_state, "OLED UV compact state")

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
        uint8_t shown = 0;
        for (uint8_t i = 0; i < 2U && y <= 63U; ++i) {
            const OledUvSlot &u = oledUvSlots[i];
            if (!u.updatedMs || static_cast<uint32_t>(now - u.updatedMs) > 300000UL || u.uvIndex < 0) continue;
            snprintf(line, sizeof(line), "%s UV%d %ddBm %c", oledUvName(u.code),
                     static_cast<int>(u.uvIndex), static_cast<int>(u.rssiDbm), oledRssiGrade(u.rssiDbm));
            drawLine(line, y);
            shown++;
        }
        if (!shown) drawLine("UV --", y);
    }
'''
    text = replace_once(text, old_render, new_render, "OLED multi-UV rendering")

    ns_end = "} // namespace\n\nvoid initDisplay() {"
    public_fn = '''} // namespace

void noteDisplayUvReading(const WeatherReading &reading) {
    if (reading.type != SensorType::UV || !reading.uvValid) return;
    OledUvSlot *slot = nullptr;
    OledUvSlot *oldest = &oledUvSlots[0];
    for (uint8_t i = 0; i < 2U; ++i) {
        OledUvSlot &candidate = oledUvSlots[i];
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
    slot->uvIndex = static_cast<int8_t>(reading.uvIndex);
    if (isfinite(reading.rssi)) {
        int rssi = static_cast<int>(lroundf(reading.rssi));
        if (rssi < -126) rssi = -126;
        if (rssi > 0) rssi = 0;
        slot->rssiDbm = static_cast<int8_t>(rssi);
    }
}

void initDisplay() {'''
    text = replace_once(text, ns_end, public_fn, "OLED UV recorder")

    DISPLAY_CPP.write_text(text, encoding="utf-8")
    print("UV outputs: patched display_manager.cpp")


def patch_main() -> None:
    text = MAIN.read_text(encoding="utf-8")
    if "noteDisplayUvReading(reading);" in text:
        print("UV outputs: main.cpp already patched")
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
            if (reading.type == SensorType::UV) noteDisplayUvReading(reading);
            applyWeatherReading(station, reading, applyThermoPrimary);'''
    text = replace_once(text, old, new, "OLED UV feed")
    MAIN.write_text(text, encoding="utf-8")
    print("UV outputs: patched main.cpp")


patch_mqtt()
patch_display_header()
patch_display_cpp()
patch_main()
