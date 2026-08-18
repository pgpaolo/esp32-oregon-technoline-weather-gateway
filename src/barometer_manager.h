#pragma once
#include "station_state.h"

void initBarometer();
void serviceBarometer(StationState &state);
bool barometerDetected();
const char *barometerName();
uint8_t barometerAddress();
const char *barometerTrendName(const StationState &state);
const char *barometerForecastName(const StationState &state);
