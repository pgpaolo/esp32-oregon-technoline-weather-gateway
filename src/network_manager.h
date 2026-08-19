#pragma once
#include <Arduino.h>

struct NetworkRuntimeConfig {
    String hostname;
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
String networkHostname();
String networkMdnsName();
bool networkMdnsActive();

NetworkRuntimeConfig getNetworkConfig();
bool validateNetworkConfig(const NetworkRuntimeConfig &cfg);
bool saveNetworkConfig(const NetworkRuntimeConfig &cfg, bool &changed);
bool resetNetworkConfigToDefaults(bool &changed);
