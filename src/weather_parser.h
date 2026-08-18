#pragma once
#include "oregon_types.h"

bool validateOregonChecksum(const OregonPacket &packet);
bool parseWeatherPacket(const OregonPacket &packet, WeatherReading &reading);
const char *sensorTypeName(SensorType type);
const char *windDirectionName(uint8_t index);
const char *sensorModelName(uint16_t sensorCode);
const char *batteryStatusName(const WeatherReading &reading);
