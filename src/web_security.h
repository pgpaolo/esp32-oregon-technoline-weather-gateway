#pragma once

#include <Arduino.h>

class WebServer;

struct WebSecurityConfig {
    bool enabled{true};
    String username{"admin"};
    bool passwordSet{false};
};

void initWebSecurity();
WebSecurityConfig getWebSecurityConfig();
bool webSecurityEnabled();
bool webSecurityAuthorized(WebServer &server);
void requestWebAuthentication(WebServer &server);
bool saveWebSecurityConfig(bool enabled, const String &username,
                           const String &newPassword, bool replacePassword,
                           bool &changed, String &error);
String webSecurityConfigJson();

// Non-empty only during the first boot in which a password is generated. It is
// deliberately never exposed by the HTTP API; initWebSecurity() prints it to
// Serial so the administrator can perform the initial login.
String webSecurityBootstrapPassword();
