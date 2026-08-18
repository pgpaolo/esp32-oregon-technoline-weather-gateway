#pragma once
#include <Arduino.h>

struct NetworkRuntimeConfig {
    bool useStatic{true};
    String ip;
    String gateway;
    String subnet;
    String dns;
};

void initNetwork();
void serviceWiFi();
bool wifiConnected();
int32_t wifiRssi();
String wifiIpAddress();

NetworkRuntimeConfig getNetworkConfig();
bool saveNetworkConfig(const NetworkRuntimeConfig &cfg, bool &changed);
bool resetNetworkConfigToDefaults(bool &changed);
