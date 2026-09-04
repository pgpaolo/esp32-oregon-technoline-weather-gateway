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

// Web/provisioning availability is intentionally separate from wifiConnected():
// MQTT and Internet-facing services must still see STA connectivity only, while
// the configuration WebServer may also run on the local recovery AP.
bool networkWebAvailable();
String networkWebIpAddress();
bool networkRecoveryApActive();
String networkRecoveryApSsid();
String networkRecoveryApPassword();

// Wi-Fi credentials are persisted in NVS but the password is never returned by
// any API. A blank password in saveWifiCredentials() means "keep current" when
// replacePassword is false.
String networkWifiSsid();
bool networkWifiPasswordConfigured();
bool networkWifiCredentialTrialPending();
bool validateWifiCredentials(const String &ssid, const String &password);
bool saveWifiCredentials(const String &ssid, const String &password,
                         bool replacePassword, bool &changed);
bool resetWifiCredentialsToFirmwareDefaults(bool &changed);

NetworkRuntimeConfig getNetworkConfig();
bool validateNetworkConfig(const NetworkRuntimeConfig &cfg);
bool saveNetworkConfig(const NetworkRuntimeConfig &cfg, bool &changed);
bool resetNetworkConfigToDefaults(bool &changed);
