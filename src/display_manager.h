#pragma once
#include <PubSubClient.h>
#include "station_state.h"
#include "oregon_receiver.h"
#include "lacrosse_ws23xx.h"

void initDisplay();
bool displayEnabled();
void setDisplayEnabled(bool enabled);
void updateDisplay(const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats, bool wifiOk, bool mqttOk);
