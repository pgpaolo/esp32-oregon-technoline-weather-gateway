#include "weather_parser.h"
#include <Arduino.h>
#include "config.h"

namespace {

bool getNybble(const OregonPacket &packet, uint8_t index, uint8_t &value) {
    const uint8_t byteIndex = index / 2U;
    if (byteIndex >= packet.length) return false;
    const uint8_t b = packet.bytes[byteIndex];
    value = (index % 2U == 0U) ? static_cast<uint8_t>(b >> 4U)
                               : static_cast<uint8_t>(b & 0x0FU);
    return true;
}

bool decimalNybble(const OregonPacket &packet, uint8_t index, uint8_t &value) {
    if (!getNybble(packet, index, value)) return false;
    return value <= 9;
}

bool plausibleTemperature(float value) { return value >= -60.0f && value <= 70.0f; }
bool plausibleHumidity(float value)    { return value >= 0.0f && value <= 100.0f; }
bool plausibleWind(float value)        { return value >= 0.0f && value <= 300.0f; }
bool plausibleRain(float value)        { return value >= 0.0f && value <= 100000.0f; }

uint8_t checksumPositionForSensor(uint8_t sensorId) {
    switch (sensorId) {
        case 0xAF: return 16; // THGN800/THGN801 family
        case 0xA1: return 18; // WGR800
        case 0xA2: return 19; // PCR800, checksum attraversa il byte
        case 0xAD: return 14; // UVN800
        case 0xA3: return 18;
        default: return 0;
    }
}

uint8_t decodeChannel(uint8_t raw) {
    // OS v2.1/v3 spesso usa 1 << (channel-1): 1,2,4 -> canali 1,2,3.
    if (raw == 1) return 1;
    if (raw == 2) return 2;
    if (raw == 4) return 3;
    return 0;
}

bool parseCommonFields(const OregonPacket &packet, WeatherReading &reading) {
    // Il buffer legacy include il sync nibble A come nibble 0; quindi il payload
    // documentato OSV3 inizia da nibble 1. La documentazione definisce:
    // payload nibbles 0..3 sensor ID, 4 channel, 5..6 rolling, 7 flags.
    uint8_t n1, n2, n3, n4, ch, rollHi, rollLo, flags;
    if (!getNybble(packet, 1, n1) || !getNybble(packet, 2, n2) ||
        !getNybble(packet, 3, n3) || !getNybble(packet, 4, n4) ||
        !getNybble(packet, 5, ch) || !getNybble(packet, 6, rollHi) ||
        !getNybble(packet, 7, rollLo) || !getNybble(packet, 8, flags)) {
        return false;
    }

    reading.sensorCode = static_cast<uint16_t>((n1 << 12U) | (n2 << 8U) | (n3 << 4U) | n4);
    reading.channelRaw = ch;
    reading.channel = decodeChannel(ch);
    reading.rollingCode = static_cast<uint8_t>((rollHi << 4U) | rollLo);
    reading.flags = flags;
    reading.batteryStatusValid = true;
    reading.batteryLow = (flags & 0x04U) != 0U;
    return true;
}

bool sensorCodeMatchesType(SensorType type, uint16_t code) {
    switch (type) {
        case SensorType::ThermoHygro:
            return code == 0xF824 || code == 0xF8B4 || code == 0x1D20;
        case SensorType::Wind:
            return code == 0x1984 || code == 0x1994;
        case SensorType::Rain:
            return code == 0x2914;
        case SensorType::UV:
            return code == 0xD874 || code == 0xEC70;
        default:
            return true;
    }
}

} // namespace

bool validateOregonChecksum(const OregonPacket &packet) {
    if (packet.length == 0) return false;

    const uint8_t csPos = checksumPositionForSensor(packet.bytes[0]);
    if (csPos == 0) return false;

    const uint8_t requiredNibbles = static_cast<uint8_t>(csPos + 2U);
    if (requiredNibbles > packet.length * 2U) return false;

    uint8_t calculated = 0;
    for (uint8_t i = 1; i < csPos; ++i) {
        uint8_t n = 0;
        if (!getNybble(packet, i, n)) return false;
        calculated = static_cast<uint8_t>(calculated + n);
    }

    uint8_t checkLow = 0, checkHigh = 0;
    if (!getNybble(packet, csPos, checkLow) ||
        !getNybble(packet, static_cast<uint8_t>(csPos + 1U), checkHigh)) return false;

    const uint8_t received = static_cast<uint8_t>((checkHigh << 4U) | checkLow);
    return calculated == received;
}

bool parseWeatherPacket(const OregonPacket &packet, WeatherReading &reading) {
    reading = WeatherReading{};
    if (packet.length == 0 || !validateOregonChecksum(packet)) return false;

    reading.sensorId = packet.bytes[0];
    reading.receivedAtMs = packet.receivedAtMs;
    reading.rssi = packet.rssi;
    if (!parseCommonFields(packet, reading)) return false;

    uint8_t a, b, c, d, e;

    switch (reading.sensorId) {
        case 0xAF: { // Thermo/Hygro
            reading.type = SensorType::ThermoHygro;
            if (!sensorCodeMatchesType(reading.type, reading.sensorCode)) return false;
            uint8_t sign;
            if (!decimalNybble(packet, 11, a) || !decimalNybble(packet, 10, b) ||
                !decimalNybble(packet, 9, c) || !getNybble(packet, 12, sign) ||
                !decimalNybble(packet, 14, d) || !decimalNybble(packet, 13, e)) return false;

            float temp = static_cast<float>(a * 10U + b) + static_cast<float>(c) / 10.0f;
            if (sign == 8) temp = -temp;
            else if (sign != 0) return false;
            const float hum = static_cast<float>(d * 10U + e);
            if (!plausibleTemperature(temp) || !plausibleHumidity(hum)) return false;

            reading.temperatureC = temp;
            reading.temperatureValid = true;
            reading.humidityPct = hum;
            reading.humidityValid = true;
            return true;
        }

        case 0xA1: { // WGR800 Protocol 3.0, ID 1984/1994
            reading.type = SensorType::Wind;
            if (!sensorCodeMatchesType(reading.type, reading.sensorCode)) return false;
            uint8_t quadrant, avgTens, avgOnes, avgTenths, gustTens, gustOnes, gustTenths;
            if (!getNybble(packet, 9, quadrant) || quadrant > 15 ||
                !decimalNybble(packet, 17, avgTens) || !decimalNybble(packet, 16, avgOnes) ||
                !decimalNybble(packet, 15, avgTenths) || !decimalNybble(packet, 14, gustTens) ||
                !decimalNybble(packet, 13, gustOnes) || !decimalNybble(packet, 12, gustTenths)) return false;

            const float avgMs = static_cast<float>(avgTens * 10U + avgOnes) + static_cast<float>(avgTenths) / 10.0f;
            const float gustMs = static_cast<float>(gustTens * 10U + gustOnes) + static_cast<float>(gustTenths) / 10.0f;
            const float avg = avgMs * 3.6f;
            const float gust = gustMs * 3.6f;
            if (!plausibleWind(avg) || !plausibleWind(gust)) return false;

            reading.windAverageKmh = avg;
            reading.windAverageValid = true;
            reading.windGustKmh = gust;
            reading.windGustValid = true;
            reading.windDirectionIndex = quadrant;
            reading.windDirectionDeg = static_cast<float>(quadrant) * 22.5f;
            reading.windDirectionValid = true;
            return true;
        }

        case 0xA2: { // PCR800
            reading.type = SensorType::Rain;
            if (!sensorCodeMatchesType(reading.type, reading.sensorCode)) return false;
            uint8_t n[11];
            const uint8_t idx[] = {18,17,16,15,14,13,8,9,10,11,12};
            for (uint8_t i = 0; i < 11; ++i) if (!decimalNybble(packet, idx[i], n[i])) return false;

            const uint32_t totalRaw =
                static_cast<uint32_t>(n[0]) * 100000UL + static_cast<uint32_t>(n[1]) * 10000UL +
                static_cast<uint32_t>(n[2]) * 1000UL + static_cast<uint32_t>(n[3]) * 100UL +
                static_cast<uint32_t>(n[4]) * 10UL + n[5];
            const uint32_t rateRaw =
                static_cast<uint32_t>(n[6]) * 10000UL + static_cast<uint32_t>(n[7]) * 1000UL +
                static_cast<uint32_t>(n[8]) * 100UL + static_cast<uint32_t>(n[9]) * 10UL + n[10];

            const float total = static_cast<float>(totalRaw) * OREGON_RAIN_MM_PER_RAW;
            // PCR800: rain rate ha LSD 0.01 in/h = 0.254 mm/h per count.
            const float rate = static_cast<float>(rateRaw) * 0.254f;
            if (!plausibleRain(total) || rate < 0.0f || rate > 2000.0f) return false;

            reading.rainTotalMm = total;
            reading.rainTotalValid = true;
            reading.rainRateMmH = rate;
            reading.rainRateValid = true;
            return true;
        }

        case 0xAD: { // UVN800
            reading.type = SensorType::UV;
            if (!sensorCodeMatchesType(reading.type, reading.sensorCode)) return false;
            // Oregon RF Protocol Description: per D874/EC70 i nibble 8..9 sono
            // un "UV Index Unit-less Integer", non un campo BCD. I frame reali
            // del sensore confermano la sequenza 09 -> 0A -> 0B ... per UV 9,10,11.
            // Nel buffer legacy il campo corrisponde al byte 4.
            const int uv = static_cast<int>(packet.bytes[4]);
            if (uv < 0 || uv > 25) return false;
            reading.uvIndex = uv;
            reading.uvValid = true;
            return true;
        }

        default:
            reading.type = SensorType::Unknown;
            return false;
    }
}

const char *sensorTypeName(SensorType type) {
    switch (type) {
        case SensorType::ThermoHygro: return "thermo_hygro";
        case SensorType::Wind: return "wind";
        case SensorType::Rain: return "rain";
        case SensorType::UV: return "uv";
        default: return "unknown";
    }
}

const char *sensorModelName(uint16_t sensorCode) {
    switch (sensorCode) {
        case 0xF824: return "THGN801/THGR810";
        case 0xF8B4: return "THGR810";
        case 0x1D20: return "THGN123N/THGR122NX";
        case 0x1984: return "WGR800";
        case 0x1994: return "WGR800";
        case 0x2914: return "PCR800";
        case 0xD874: return "UVN800";
        case 0xEC70: return "UVR128";
        default: return "OSV3";
    }
}

const char *batteryStatusName(const WeatherReading &reading) {
    if (!reading.batteryStatusValid) return "N/D";
    return reading.batteryLow ? "LOW" : "OK";
}

const char *windDirectionName(uint8_t index) {
    static const char *dirs[16] = {
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
    };
    return dirs[index & 0x0F];
}
