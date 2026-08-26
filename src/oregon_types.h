#pragma once
#include <Arduino.h>
#include <math.h>

static constexpr size_t OREGON_MAX_PACKET_BYTES = 12;

enum class SensorType : uint8_t {
    Unknown = 0,
    ThermoHygro,
    Wind,
    Rain,
    UV
};

struct OregonPacket {
    uint8_t bytes[OREGON_MAX_PACKET_BYTES]{};
    uint8_t length{0};
    uint32_t receivedAtMs{0};
    float rssi{NAN};
    uint8_t decodeSource{0}; // OregonDecodeSource, numerico per evitare dipendenze circolari.
};

struct WeatherReading {
    SensorType type{SensorType::Unknown};
    uint8_t sensorId{0};              // header legacy A1/A2/AD/AF
    uint16_t sensorCode{0};           // ID Oregon V2.1/V3, es. EC40/1D20/F824/D874/2914/1984
    uint8_t channelRaw{0};
    uint8_t channel{0};               // 1..3 quando decodificabile
    uint8_t rollingCode{0};
    uint8_t flags{0};
    bool batteryStatusValid{false};
    bool batteryLow{false};
    uint32_t receivedAtMs{0};
    float rssi{NAN};

    bool temperatureValid{false};
    float temperatureC{NAN};

    bool humidityValid{false};
    float humidityPct{NAN};

    bool windAverageValid{false};
    float windAverageKmh{NAN};

    bool windGustValid{false};
    float windGustKmh{NAN};

    bool windDirectionValid{false};
    uint8_t windDirectionIndex{0};
    float windDirectionDeg{NAN};

    bool rainTotalValid{false};
    float rainTotalMm{NAN};

    bool rainRateValid{false};
    float rainRateMmH{NAN};

    bool uvValid{false};
    int uvIndex{-1};
};
