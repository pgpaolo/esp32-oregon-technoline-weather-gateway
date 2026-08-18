#pragma once
#include "station_state.h"
#include "oregon_receiver.h"
#include "weather_parser.h"
#include "lacrosse_ws23xx.h"

void initWeb(StationState &state);
void serviceWeb();
void recordWebPacket(const OregonPacket &packet, const WeatherReading *reading, bool accepted);

void recordWebLaCrossePacket(const LaCrossePacket &packet, const LaCrosseReading *reading, bool accepted);
