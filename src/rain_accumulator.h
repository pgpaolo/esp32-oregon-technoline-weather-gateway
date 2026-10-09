#pragma once
#include <Arduino.h>
#include "oregon_types.h"
#include "lacrosse_ws23xx.h"

void initRainAccumulator();
void observeOregonRain(const WeatherReading &reading);
void observeTechnolineRain(const LaCrosseReading &reading);
void serviceRainAccumulator();
void flushRainAccumulator();
void rainAccumulatorSdFormatted();
void rainAccumulatorConfigChanged(bool oregonChanged, bool technolineChanged);
String rainAccumulatorJson();
// Main-task only, allocation-free daily rain view. NAN if day/source unavailable.
float rainAccumulatorTodayMm(bool oregon, uint32_t utcDayKey);
