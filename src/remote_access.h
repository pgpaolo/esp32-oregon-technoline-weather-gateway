#pragma once

#include <Arduino.h>

struct RemoteAccessConfig {
    String portalUrl;
};

struct RemoteAccessStatus {
    bool initialized{false};
    bool configured{false};
    bool approved{false};
    bool transportActive{false};
    String state;
    String deviceId;
    uint32_t enrollAttempts{0};
    int lastEnrollHttpCode{0};
    uint32_t wsAttempts{0};
    uint32_t wsConnects{0};
    uint32_t wsDisconnects{0};
    uint32_t requests{0};
    uint32_t responses{0};
    uint32_t lastActivityMs{0};
    uint32_t lastWsAttemptMs{0};
    String wsHost;
    String wsPath;
    String lastWsEvent;
    String lastError;
};

void initRemoteAccess();
RemoteAccessConfig getRemoteAccessConfig();
RemoteAccessStatus getRemoteAccessStatus();
bool saveRemoteAccessPortalUrl(const String &portalUrl);
bool resetRemoteAccessConfig();
void retryRemoteAccessNow();
String remoteAccessConfigJson();
String remoteAccessStatusJson();
String remoteDefaultDeviceId();
