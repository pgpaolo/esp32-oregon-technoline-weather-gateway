#include "thermo_channel_manager.h"
#include <Preferences.h>
#include <math.h>

namespace {
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
    // Always establish valid defaults first. A missing/unreadable optional
    // namespace simply leaves CH1 primary + auto-discovery active.
    cfg = defaults();
    normalize(cfg);

    Preferences p;
    if (!p.begin("thermoch", true)) return;

    ThermoChannelConfig loaded = cfg;
    loaded.enabledMask = p.getUChar("enabled", cfg.enabledMask);
    loaded.primaryChannel = p.getUChar("primary", cfg.primaryChannel);
    loaded.autoDiscover = p.getBool("auto", cfg.autoDiscover);
    p.end();

    normalize(loaded);
    cfg = loaded;
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
    return channel == 0U || channel == cfg.primaryChannel;
}

bool saveThermoChannelConfig(const ThermoChannelConfig &input) {
    ThermoChannelConfig next = input;
    normalize(next);
    if (next.enabledMask == cfg.enabledMask && next.primaryChannel == cfg.primaryChannel && next.autoDiscover == cfg.autoDiscover) return true;

    Preferences p;
    if (!p.begin("thermoch", false)) return false;
    if (next.enabledMask != cfg.enabledMask) p.putUChar("enabled", next.enabledMask);
    if (next.primaryChannel != cfg.primaryChannel) p.putUChar("primary", next.primaryChannel);
    if (next.autoDiscover != cfg.autoDiscover) p.putBool("auto", next.autoDiscover);
    const bool ok = verifyStored(p, next);
    p.end();
    if (!ok) return false;

    cfg = next;
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
