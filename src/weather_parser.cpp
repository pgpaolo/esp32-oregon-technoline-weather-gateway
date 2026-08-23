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

uint16_t packetSensorCode(const OregonPacket &packet) {
    uint8_t n1, n2, n3, n4;
    if (!getNybble(packet, 1, n1) || !getNybble(packet, 2, n2) ||
        !getNybble(packet, 3, n3) || !getNybble(packet, 4, n4)) return 0;
    return static_cast<uint16_t>((n1 << 12U) | (n2 << 8U) | (n3 << 4U) | n4);
}

uint8_t checksumPositionForPacket(const OregonPacket &packet) {
    const uint16_t code = packetSensorCode(packet);
    if (code == 0xEC40U) return 13; // THN132N V2.1 temperatura
    if (code == 0xEC70U) return 13; // UVR128 V2.1 UV
    if (code == 0x1D20U) return 16; // THGR122NX/THGR228N V2.1 termo/igro
    if (code == 0x1D30U) return 16; // THGR968/THGN500 V2.1 termo/igro
    if (code == 0x2D10U) return 17; // RGR968 V2.1 pioggia
    if (code == 0x3D00U) return 18; // WGR968 V2.1 vento
    switch (packet.bytes[0]) {
        case 0xAF: return 16; // THGN800/THGN801 family
        case 0xA1: return 18; // WGR800
        case 0xA2: return 19; // PCR800, checksum attraversa il byte
        case 0xAD: return 14; // UVN800
        case 0xA3: return 18;
        default: return 0;
    }
}

bool parseThermoPayload(const OregonPacket &packet, WeatherReading &reading, bool withHumidity) {
    uint8_t tens, ones, tenths, sign;
    if (!decimalNybble(packet, 11, tens) || !decimalNybble(packet, 10, ones) ||
        !decimalNybble(packet, 9, tenths) || !getNybble(packet, 12, sign)) return false;

    float temp = static_cast<float>(tens * 10U + ones) + static_cast<float>(tenths) / 10.0f;
    if (sign == 8U) temp = -temp;
    else if (sign != 0U) return false;
    if (!plausibleTemperature(temp)) return false;

    reading.temperatureC = temp;
    reading.temperatureValid = true;
    if (!withHumidity) return true;

    uint8_t humTens, humOnes;
    if (!decimalNybble(packet, 14, humTens) || !decimalNybble(packet, 13, humOnes)) return false;
    const float humidity = static_cast<float>(humTens * 10U + humOnes);
    if (!plausibleHumidity(humidity)) return false;
    reading.humidityPct = humidity;
    reading.humidityValid = true;
    return true;
}

uint8_t decodeChannel(uint8_t raw) {
    // Oregon OS v2.1/v3 does not use one single channel coding across all
    // thermo families. Legacy 3-channel sensors commonly use one-hot coding
    // 1,2,4 -> CH1,CH2,CH3. F824 hardware in this project was also observed
    // on-air using raw=3 for CH3, so accept direct numeric 1,2,3 as well.
    if (raw == 1) return 1;
    if (raw == 2) return 2;
    if (raw == 3 || raw == 4) return 3;
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
            return code == 0xF824 || code == 0xF8B4 || code == 0x1D20 ||
                   code == 0x1D30 || code == 0xEC40;
        case SensorType::Wind:
            return code == 0x1984 || code == 0x1994 || code == 0x3D00;
        case SensorType::Rain:
            return code == 0x2914 || code == 0x2D10;
        case SensorType::UV:
            return code == 0xD874 || code == 0xEC70;
        default:
            return true;
    }
}

} // namespace

bool validateOregonChecksum(const OregonPacket &packet) {
    if (packet.length == 0) return false;

    const uint8_t csPos = checksumPositionForPacket(packet);
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

    // I codici completi disambiguano i sensori V2.1. In particolare 1D20
    // condivide il byte legacy A1 con il WGR800 V3 e non deve finire nel ramo vento.
    if (reading.sensorCode == 0xEC40U) {
        reading.type = SensorType::ThermoHygro;
        return parseThermoPayload(packet, reading, false);
    }
    if (reading.sensorCode == 0x1D20U) {
        reading.type = SensorType::ThermoHygro;
        return parseThermoPayload(packet, reading, true);
    }
    if (reading.sensorCode == 0x1D30U) {
        reading.type = SensorType::ThermoHygro;
        return parseThermoPayload(packet, reading, true);
    }
    if (reading.sensorCode == 0x3D00U) {
        reading.type = SensorType::Wind;
        uint8_t dirHundreds, dirTens, dirOnes;
        uint8_t gustUnits, gustTenthsA, gustTenthsB;
        uint8_t avgUnits, avgTenthsA, avgTenthsB;
        if (!decimalNybble(packet, 11, dirHundreds) ||
            !decimalNybble(packet, 10, dirTens) ||
            !decimalNybble(packet, 9, dirOnes) ||
            !decimalNybble(packet, 13, gustUnits) ||
            !decimalNybble(packet, 12, gustTenthsA) ||
            !decimalNybble(packet, 14, gustTenthsB) ||
            !decimalNybble(packet, 16, avgUnits) ||
            !decimalNybble(packet, 15, avgTenthsA) ||
            !decimalNybble(packet, 17, avgTenthsB)) return false;

        const float direction = static_cast<float>(dirHundreds * 100U + dirTens * 10U + dirOnes);
        const float gustMs = static_cast<float>(gustUnits) +
                             static_cast<float>(gustTenthsA + gustTenthsB) / 10.0f;
        const float avgMs = static_cast<float>(avgUnits) +
                            static_cast<float>(avgTenthsA + avgTenthsB) / 10.0f;
        const float gust = gustMs * 3.6f;
        const float avg = avgMs * 3.6f;
        if (direction > 360.0f || !plausibleWind(gust) || !plausibleWind(avg)) return false;

        reading.windDirectionDeg = direction;
        reading.windDirectionIndex = static_cast<uint8_t>(direction / 22.5f + 0.5f) & 0x0FU;
        reading.windDirectionValid = true;
        reading.windGustKmh = gust;
        reading.windGustValid = true;
        reading.windAverageKmh = avg;
        reading.windAverageValid = true;
        return true;
    }
    if (reading.sensorCode == 0x2D10U) {
        reading.type = SensorType::Rain;
        uint8_t rateHundreds, rateTens, rateTenths;
        uint8_t totalTenThousands, totalThousands, totalHundreds, totalTens, totalTenths;
        if (!decimalNybble(packet, 10, rateHundreds) ||
            !decimalNybble(packet, 9, rateTens) ||
            !decimalNybble(packet, 11, rateTenths) ||
            !decimalNybble(packet, 16, totalTenThousands) ||
            !decimalNybble(packet, 15, totalThousands) ||
            !decimalNybble(packet, 14, totalHundreds) ||
            !decimalNybble(packet, 13, totalTens) ||
            !decimalNybble(packet, 12, totalTenths)) return false;

        const float rate = static_cast<float>(rateHundreds * 100U + rateTens * 10U + rateTenths) / 10.0f;
        const uint32_t totalRaw = static_cast<uint32_t>(totalTenThousands) * 10000UL +
                                  static_cast<uint32_t>(totalThousands) * 1000UL +
                                  static_cast<uint32_t>(totalHundreds) * 100UL +
                                  static_cast<uint32_t>(totalTens) * 10UL + totalTenths;
        const float total = static_cast<float>(totalRaw) / 10.0f;
        if (!plausibleRain(total) || rate > 2000.0f) return false;

        reading.rainTotalMm = total;
        reading.rainTotalValid = true;
        reading.rainRateMmH = rate;
        reading.rainRateValid = true;
        return true;
    }
    if (reading.sensorCode == 0xEC70U) {
        reading.type = SensorType::UV;
        uint8_t tens, ones;
        if (!decimalNybble(packet, 10, tens) || !decimalNybble(packet, 9, ones)) return false;
        const uint8_t uv = static_cast<uint8_t>(tens * 10U + ones);
        if (uv > 25U) return false;
        reading.uvIndex = uv;
        reading.uvValid = true;
        return true;
    }

    uint8_t a, b, c, d, e;

    switch (reading.sensorId) {
        case 0xAF: { // Thermo/Hygro
            reading.type = SensorType::ThermoHygro;
            if (!sensorCodeMatchesType(reading.type, reading.sensorCode)) return false;
            return parseThermoPayload(packet, reading, true);
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
        case 0x1D20: return "THGR122NX/THGR228N";
        case 0x1D30: return "THGR968/THGN500";
        case 0xEC40: return "THN132N/THR228N";
        case 0x3D00: return "WGR968";
        case 0x2D10: return "RGR968";
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
