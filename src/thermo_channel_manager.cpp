#include "thermo_channel_manager.h"
#include <Preferences.h>
#include <math.h>

namespace {
Preferences prefs;
ThermoChannelConfig cfg{};
ThermoChannelState channels[3]{};

ThermoChannelConfig defaults() { return ThermoChannelConfig{}; }

void normalize(ThermoChannelConfig &c) {
    c.enabledMask &= 0x07U;
    if (c.primaryChannel < 1U || c.primaryChannel > 3U) c.primaryChannel = 1U;
    c.enabledMask |= static_cast<uint8_t>(1U << (c.primaryChannel - 1U));
}

bool verifyStored(Preferences &p, const ThermoChannelConfig &expected) {
    const ThermoChannelConfig d = defaults();
    return p.getUChar("enabled", d.enabledMask) == expected.enabledMask &&
           p.getUChar("primary", d.primaryChannel) == expected.primaryChannel &&
           p.getBool("auto", d.autoDiscover) == expected.autoDiscover;
}

void copySensor(OregonSensorStatus &dst, const WeatherReading &r) {
    dst.code = r.sensorCode;
    dst.channel = r.channel;
    dst.channelRaw = r.channelRaw;
    dst.rollingCode = r.rollingCode;
    dst.flags = r.flags;
    dst.batteryKnown = r.batteryStatusValid;
    dst.batteryLow = r.batteryLow;
    dst.updatedMs = r.receivedAtMs;
}
} // namespace

void initThermoChannels() {
    const ThermoChannelConfig d = defaults();
    if (!prefs.begin("thermoch", true)) {
        cfg = d;
        normalize(cfg);
        Serial.println(F("[THERMO] NVS non disponibile: CH1 principale"));
        return;
    }
    cfg.enabledMask = prefs.getUChar("enabled", d.enabledMask);
    cfg.primaryChannel = prefs.getUChar("primary", d.primaryChannel);
    cfg.autoDiscover = prefs.getBool("auto", d.autoDiscover);
    prefs.end();
    normalize(cfg);
    Serial.print(F("[THERMO] primary=CH")); Serial.print(cfg.primaryChannel);
    Serial.print(F(" enabled=0x")); Serial.print(cfg.enabledMask, HEX);
    Serial.print(F(" auto=")); Serial.println(cfg.autoDiscover ? F("ON") : F("OFF"));
}

void noteThermoChannelReading(const WeatherReading &r) {
    if (r.type != SensorType::ThermoHygro || r.channel < 1U || r.channel > 3U) return;
    ThermoChannelState &s = channels[r.channel - 1U];
    s.detected = true;
    s.packetCount++;
    s.updatedMs = r.receivedAtMs;
    s.lastRssi = r.rssi;
    copySensor(s.sensor, r);
    if (r.temperatureValid) s.temperatureC = r.temperatureC;
    if (r.humidityValid) s.humidityPct = r.humidityPct;
    s.valid = r.temperatureValid || r.humidityValid;
}

ThermoChannelConfig getThermoChannelConfig() { return cfg; }

ThermoChannelState getThermoChannelState(uint8_t channel) {
    if (channel < 1U || channel > 3U) return ThermoChannelState{};
    return channels[channel - 1U];
}

uint8_t thermoDetectedMask() {
    uint8_t m = 0;
    for (uint8_t i = 0; i < 3U; ++i) if (channels[i].detected) m |= static_cast<uint8_t>(1U << i);
    return m;
}

uint8_t thermoEffectiveMask() {
    return static_cast<uint8_t>((cfg.enabledMask | (cfg.autoDiscover ? thermoDetectedMask() : 0U)) & 0x07U);
}

bool thermoChannelVisible(uint8_t channel) {
    if (channel < 1U || channel > 3U) return false;
    return (thermoEffectiveMask() & static_cast<uint8_t>(1U << (channel - 1U))) != 0U;
}

bool thermoChannelIsPrimary(uint8_t channel) {
    // Canale 0 = header non decodificabile: mantiene la compatibilita' legacy.
    return channel == 0U || channel == cfg.primaryChannel;
}

bool saveThermoChannelConfig(const ThermoChannelConfig &input) {
    ThermoChannelConfig next = input;
    normalize(next);
    if (next.enabledMask == cfg.enabledMask && next.primaryChannel == cfg.primaryChannel && next.autoDiscover == cfg.autoDiscover) return true;
    if (!prefs.begin("thermoch", false)) return false;
    if (next.enabledMask != cfg.enabledMask) prefs.putUChar("enabled", next.enabledMask);
    if (next.primaryChannel != cfg.primaryChannel) prefs.putUChar("primary", next.primaryChannel);
    if (next.autoDiscover != cfg.autoDiscover) prefs.putBool("auto", next.autoDiscover);
    const bool ok = verifyStored(prefs, next);
    prefs.end();
    if (!ok) return false;
    cfg = next;
    return true;
}

bool resetThermoChannelConfig() {
    ThermoChannelConfig d = defaults();
    normalize(d);
    if (!prefs.begin("thermoch", false)) return false;
    const bool cleared = prefs.clear();
    const bool ok = cleared && verifyStored(prefs, d);
    prefs.end();
    if (!ok) return false;
    cfg = d;
    return true;
}

void syncPrimaryThermoState(StationState &station) {
    const ThermoChannelState &s = channels[cfg.primaryChannel - 1U];
    if (!s.valid) {
        station.temperatureC = NAN;
        station.humidityPct = NAN;
        station.thermoUpdatedMs = 0;
        station.thermoValid = false;
        station.thermoSensor = OregonSensorStatus{};
        refreshDerivedWeather(station);
        return;
    }
    station.temperatureC = s.temperatureC;
    station.humidityPct = s.humidityPct;
    station.thermoUpdatedMs = s.updatedMs;
    station.thermoValid = true;
    station.thermoSensor = s.sensor;
    refreshDerivedWeather(station);
}
