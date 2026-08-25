#include "web_security.h"

#include <Preferences.h>
#include <WebServer.h>

namespace {
constexpr const char *NVS_NS = "webauth";
constexpr const char *DEFAULT_USER = "admin";
constexpr uint8_t MAX_FAILED_ATTEMPTS = 10U;
constexpr uint32_t LOCKOUT_MS = 30000UL;

Preferences prefs;
WebSecurityConfig cfg;
String password;
String bootstrapPassword;
uint8_t failedAttempts = 0;
uint32_t lockedUntilMs = 0;

bool validUsername(const String &value) {
    if (value.length() < 1U || value.length() > 24U) return false;
    for (size_t i = 0; i < value.length(); ++i) {
        const char c = value[i];
        const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                        (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.';
        if (!ok) return false;
    }
    return true;
}

bool validPassword(const String &value) {
    return value.length() >= 8U && value.length() <= 63U;
}

String randomPassword() {
    static const char alphabet[] = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
    String out;
    out.reserve(14);
    for (uint8_t i = 0; i < 14U; ++i) {
        const uint32_t r = esp_random();
        out += alphabet[r % (sizeof(alphabet) - 1U)];
    }
    return out;
}

bool lockoutActive() {
    if (lockedUntilMs == 0U) return false;
    if (static_cast<int32_t>(millis() - lockedUntilMs) >= 0) {
        lockedUntilMs = 0;
        failedAttempts = 0;
        return false;
    }
    return true;
}

uint32_t lockoutRemainingMs() {
    if (!lockoutActive()) return 0U;
    return static_cast<uint32_t>(lockedUntilMs - millis());
}

void noteFailure() {
    if (failedAttempts < 255U) failedAttempts++;
    if (failedAttempts >= MAX_FAILED_ATTEMPTS) {
        failedAttempts = 0;
        lockedUntilMs = millis() + LOCKOUT_MS;
        Serial.println(F("[AUTH] troppi tentativi errati: blocco temporaneo 30 s"));
    }
}

bool persistConfig(const WebSecurityConfig &next, const String &nextPassword) {
    if (!prefs.begin(NVS_NS, false)) return false;
    prefs.putBool("enabled", next.enabled);
    prefs.putString("user", next.username);
    prefs.putString("pass", nextPassword);
    const bool ok = prefs.getBool("enabled", !next.enabled) == next.enabled &&
                    prefs.getString("user", "") == next.username &&
                    prefs.getString("pass", "") == nextPassword;
    prefs.end();
    return ok;
}
} // namespace

void initWebSecurity() {
    cfg = WebSecurityConfig{};
    password = "";
    bootstrapPassword = "";

    bool haveStoredPassword = false;
    if (prefs.begin(NVS_NS, true)) {
        cfg.enabled = prefs.getBool("enabled", true);
        cfg.username = prefs.getString("user", DEFAULT_USER);
        if (prefs.isKey("pass")) {
            password = prefs.getString("pass", "");
            haveStoredPassword = validPassword(password);
        }
        prefs.end();
    }

    if (!validUsername(cfg.username)) cfg.username = DEFAULT_USER;

    if (!haveStoredPassword) {
        password = randomPassword();
        bootstrapPassword = password;
        cfg.enabled = true;
        if (!persistConfig(cfg, password)) {
            Serial.println(F("[AUTH] ERRORE: impossibile salvare la password iniziale in NVS"));
        }
        Serial.println(F("[AUTH] autenticazione Web iniziale generata"));
        Serial.print(F("[AUTH] utente: ")); Serial.println(cfg.username);
        Serial.print(F("[AUTH] password iniziale: ")); Serial.println(bootstrapPassword);
        Serial.println(F("[AUTH] cambiare la password dalla sezione SISTEMA dopo il primo accesso"));
    }

    cfg.passwordSet = validPassword(password);
    failedAttempts = 0;
    lockedUntilMs = 0;
}

WebSecurityConfig getWebSecurityConfig() {
    WebSecurityConfig out = cfg;
    out.passwordSet = validPassword(password);
    return out;
}

bool webSecurityEnabled() { return cfg.enabled; }

bool webSecurityAuthorized(WebServer &server) {
    if (!cfg.enabled) return true;
    if (lockoutActive()) return false;

    if (server.authenticate(cfg.username.c_str(), password.c_str())) {
        failedAttempts = 0;
        return true;
    }
    noteFailure();
    return false;
}

void requestWebAuthentication(WebServer &server) {
    if (lockoutActive()) {
        server.sendHeader("Retry-After", String((lockoutRemainingMs() + 999U) / 1000U));
        server.send(429, "text/plain; charset=utf-8", "Troppi tentativi di autenticazione. Riprovare tra poco.");
        return;
    }
    server.requestAuthentication();
}

bool saveWebSecurityConfig(bool enabled, const String &username,
                           const String &newPassword, bool replacePassword,
                           bool &changed, String &error) {
    String nextUser = username;
    nextUser.trim();
    if (!validUsername(nextUser)) {
        error = "username must be 1..24 chars: letters, digits, . _ -";
        return false;
    }

    String nextPassword = password;
    if (replacePassword) {
        if (!validPassword(newPassword)) {
            error = "password must be 8..63 characters";
            return false;
        }
        nextPassword = newPassword;
    }
    if (enabled && !validPassword(nextPassword)) {
        error = "authentication cannot be enabled without a valid password";
        return false;
    }

    WebSecurityConfig next = cfg;
    next.enabled = enabled;
    next.username = nextUser;
    next.passwordSet = validPassword(nextPassword);
    changed = next.enabled != cfg.enabled || next.username != cfg.username || nextPassword != password;
    if (!changed) return true;

    if (!persistConfig(next, nextPassword)) {
        error = "NVS verification failed";
        return false;
    }

    cfg = next;
    password = nextPassword;
    failedAttempts = 0;
    lockedUntilMs = 0;
    bootstrapPassword = "";
    return true;
}

String webSecurityConfigJson() {
    String out;
    out.reserve(180);
    out = "{\"enabled\":";
    out += cfg.enabled ? "true" : "false";
    out += ",\"username\":\"" + cfg.username + "\"";
    out += ",\"password_set\":";
    out += validPassword(password) ? "true" : "false";
    out += ",\"locked\":";
    out += lockoutActive() ? "true" : "false";
    out += ",\"lock_remaining_ms\":" + String(lockoutRemainingMs());
    out += "}";
    return out;
}

String webSecurityBootstrapPassword() { return bootstrapPassword; }
