#include "thermo_channel_manager.h"
#include <Preferences.h>
#include <math.h>

namespace {
ThermoChannelConfig cfg{};
ThermoChannelState channels[3]{};
bool cfgLoaded = false;

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
    // Fail-safe boot policy: defaults are valid before touching NVS.
    // If the namespace is missing/unreadable, the gateway still boots with
    // CH1 primary + auto-discovery and RF decoding remains unaffected.
    cfg = defaults();
    normalize(cfg);
    cfgLoaded = false;

    Preferences p;
    if (!p.begin("thermoch", true)) {
        Serial.println(F("[THERMO] NVS unavailable; defaults CH1 + auto"));
        cfgLoaded = true;
        return;
    }

    ThermoChannelConfig loaded = cfg;
    loaded.enabledMask = p.getUChar("enabled", cfg.enabledMask);
    loaded.primaryChannel = p.getUChar("primary", cfg.primaryChannel);
    loaded.autoDiscover = p.getBool("auto", cfg.autoDiscover);
    p.end();

    normalize(loaded);
    cfg = loaded;
    cfgLoaded = true;

    Serial.print(F("[THERMO] ready primary=CH"));
    Serial.print(cfg.primaryChannel);
    Serial.print(F(" enabled=0x"));
    Serial.print(cfg.enabledMask, HEX);
    Serial.print(F(" auto="));
    Serial.println(cfg.autoDiscover ? F("ON") : F("OFF"));
}

void noteThermoChannelReading(const WeatherReading &r) {
    if (r.type != SensorType::ThermoHygro || r.channel < 1U || r.channel > 3U) return;
    ThermoChannelState &s = channels[r.channel - 1U];
    s.detected = true;
    s.updatedMs = r.receivedAtMs;
    s.lastRssi = r.rssi;
    copySensor(s.sensor, r);
    if (r.temperatureValid) s.temperatureC = r.temperatureC;
    if (r.humidityValid) s.humidityPct = r.humidityPct;
    s.valid = r.temperatureValid || r.humidityValid;
}

ThermoChannelConfig getThermoChannelConfig() {
    if (!cfgLoaded) {
        ThermoChannelConfig d = defaults();
        normalize(d);
        return d;
    }
    return cfg;
}

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
    const ThermoChannelConfig c = getThermoChannelConfig();
    return static_cast<uint8_t>((c.enabledMask | (c.autoDiscover ? thermoDetectedMask() : 0U)) & 0x07U);
}

bool thermoChannelVisible(uint8_t channel) {
    if (channel < 1U || channel > 3U) return false;
    return (thermoEffectiveMask() & static_cast<uint8_t>(1U << (channel - 1U))) != 0U;
}

bool thermoChannelIsPrimary(uint8_t channel) {
    // Channel 0 means no decoded channel: preserve legacy behavior.
    const ThermoChannelConfig c = getThermoChannelConfig();
    return channel == 0U || channel == c.primaryChannel;
}

bool saveThermoChannelConfig(const ThermoChannelConfig &input) {
    ThermoChannelConfig next = input;
    normalize(next);
    const ThermoChannelConfig old = getThermoChannelConfig();
    if (next.enabledMask == old.enabledMask && next.primaryChannel == old.primaryChannel && next.autoDiscover == old.autoDiscover) return true;

    Preferences p;
    if (!p.begin("thermoch", false)) return false;
    if (next.enabledMask != old.enabledMask) p.putUChar("enabled", next.enabledMask);
    if (next.primaryChannel != old.primaryChannel) p.putUChar("primary", next.primaryChannel);
    if (next.autoDiscover != old.autoDiscover) p.putBool("auto", next.autoDiscover);
    const bool ok = verifyStored(p, next);
    p.end();
    if (!ok) return false;

    cfg = next;
    cfgLoaded = true;
    return true;
}

bool resetThermoChannelConfig() {
    ThermoChannelConfig d = defaults();
    normalize(d);

    Preferences p;
    if (!p.begin("thermoch", false)) return false;
    const bool cleared = p.clear();
    p.end();
    if (!cleared) return false;

    cfg = d;
    cfgLoaded = true;
    return true;
}

void syncPrimaryThermoState(StationState &station) {
    const ThermoChannelConfig c = getThermoChannelConfig();
    const ThermoChannelState &s = channels[c.primaryChannel - 1U];
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
