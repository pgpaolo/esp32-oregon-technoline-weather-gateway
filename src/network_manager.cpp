#include "network_manager.h"
#include <WiFi.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include "config.h"

namespace {
constexpr uint32_t WIFI_CREDENTIAL_TRIAL_MS = 45000UL;
constexpr uint32_t WIFI_RECOVERY_AP_AFTER_MS = 60000UL;
constexpr const char *NVS_NS = "netcfg";

uint32_t lastAttemptMs = 0;
uint32_t disconnectedSinceMs = 0;
uint32_t credentialTrialStartedMs = 0;
bool wasConnected = false;
uint8_t bestBssid[6] = {0};
int32_t bestChannel = 0;
bool haveBestAp = false;
bool mdnsStarted = false;
bool recoveryApActive = false;
bool credentialTrialPending = false;
Preferences netPrefs;
NetworkRuntimeConfig netCfg;
String wifiSsid;
String wifiPassword;
String previousWifiSsid;
String previousWifiPassword;
String recoverySsid;
String recoveryPassword;

String ipText(uint8_t a, uint8_t b, uint8_t c, uint8_t d) {
    return String(a) + "." + String(b) + "." + String(c) + "." + String(d);
}

NetworkRuntimeConfig defaults() {
    NetworkRuntimeConfig c;
    c.hostname = DEVICE_HOSTNAME;
    c.useStatic = WIFI_USE_STATIC_IP != 0;
    c.ip = ipText(WIFI_IP_A, WIFI_IP_B, WIFI_IP_C, WIFI_IP_D);
    c.gateway = ipText(WIFI_GW_A, WIFI_GW_B, WIFI_GW_C, WIFI_GW_D);
    c.subnet = ipText(WIFI_MASK_A, WIFI_MASK_B, WIFI_MASK_C, WIFI_MASK_D);
    c.dns = ipText(WIFI_DNS_A, WIFI_DNS_B, WIFI_DNS_C, WIFI_DNS_D);
    return c;
}

bool validIp(const String &s) {
    IPAddress ip;
    return ip.fromString(s);
}

void normalize(NetworkRuntimeConfig &c) {
    c.hostname.trim();
    c.hostname.toLowerCase();
    c.ip.trim(); c.gateway.trim(); c.subnet.trim(); c.dns.trim();
}

bool validHostname(const String &s) {
    // Arduino-ESP32 WiFi.setHostname(): massimo 32 caratteri.
    if (s.length() < 1U || s.length() > 32U) return false;
    if (s[0] == '-' || s[s.length() - 1U] == '-') return false;
    for (size_t i = 0; i < s.length(); ++i) {
        const char ch = s[i];
        const bool ok = (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '-';
        if (!ok) return false;
    }
    return true;
}

bool validConfig(NetworkRuntimeConfig c) {
    normalize(c);
    if (!validHostname(c.hostname)) return false;
    if (!c.useStatic) return true;
    return validIp(c.ip) && validIp(c.gateway) && validIp(c.subnet) && validIp(c.dns);
}

bool sameConfig(const NetworkRuntimeConfig &a, const NetworkRuntimeConfig &b) {
    return a.hostname == b.hostname && a.useStatic == b.useStatic && a.ip == b.ip &&
           a.gateway == b.gateway && a.subnet == b.subnet && a.dns == b.dns;
}

bool verifyStoredConfig(Preferences &p, const NetworkRuntimeConfig &expected) {
    NetworkRuntimeConfig d = defaults();
    normalize(d);
    return p.getString("host", d.hostname) == expected.hostname &&
           p.getBool("static", d.useStatic) == expected.useStatic &&
           p.getString("ip", d.ip) == expected.ip &&
           p.getString("gw", d.gateway) == expected.gateway &&
           p.getString("mask", d.subnet) == expected.subnet &&
           p.getString("dns", d.dns) == expected.dns;
}

String firmwareWifiSsid() { return String(WIFI_SSID); }
String firmwareWifiPassword() { return String(WIFI_PASSWORD); }

bool validWifiCredentialsInternal(const String &ssid, const String &password) {
    if (ssid.length() < 1U || ssid.length() > 32U) return false;
    // Open network is allowed. WPA/WPA2 passphrases are 8..63 characters.
    if (password.length() != 0U && (password.length() < 8U || password.length() > 63U)) return false;
    return true;
}

void buildRecoveryCredentials() {
    const uint32_t id = static_cast<uint32_t>(ESP.getEfuseMac() & 0xFFFFFFULL);
    char suffix[7];
    snprintf(suffix, sizeof(suffix), "%06lX", static_cast<unsigned long>(id));
    recoverySsid = String("OregonGateway-Setup-") + suffix;
    recoveryPassword = String("Oregon-") + suffix;
}

void loadConfig() {
    const NetworkRuntimeConfig d = defaults();
    wifiSsid = firmwareWifiSsid();
    wifiPassword = firmwareWifiPassword();
    previousWifiSsid = "";
    previousWifiPassword = "";
    credentialTrialPending = false;

    if (!netPrefs.begin(NVS_NS, true)) {
        Serial.println(F("[WiFi] NVS netcfg non disponibile: uso valori firmware"));
        netCfg = d;
        return;
    }
    netCfg.hostname = netPrefs.getString("host", d.hostname);
    netCfg.useStatic = netPrefs.getBool("static", d.useStatic);
    netCfg.ip = netPrefs.getString("ip", d.ip);
    netCfg.gateway = netPrefs.getString("gw", d.gateway);
    netCfg.subnet = netPrefs.getString("mask", d.subnet);
    netCfg.dns = netPrefs.getString("dns", d.dns);

    if (netPrefs.isKey("ssid")) wifiSsid = netPrefs.getString("ssid", wifiSsid);
    if (netPrefs.isKey("pass")) wifiPassword = netPrefs.getString("pass", wifiPassword);
    previousWifiSsid = netPrefs.getString("prevssid", "");
    previousWifiPassword = netPrefs.getString("prevpass", "");
    credentialTrialPending = netPrefs.getBool("credpend", false);
    netPrefs.end();

    normalize(netCfg);
    if (!validConfig(netCfg)) {
        Serial.println(F("[WiFi] configurazione NVS non valida: uso rete/IP firmware"));
        netCfg = d;
    }
    if (!validWifiCredentialsInternal(wifiSsid, wifiPassword)) {
        Serial.println(F("[WiFi] credenziali NVS non valide: uso SSID/password firmware"));
        wifiSsid = firmwareWifiSsid();
        wifiPassword = firmwareWifiPassword();
        credentialTrialPending = false;
        previousWifiSsid = "";
        previousWifiPassword = "";
    }
}

const char *statusName(wl_status_t s) {
    switch (s) {
        case WL_IDLE_STATUS: return "IDLE";
        case WL_NO_SSID_AVAIL: return "NO_SSID";
        case WL_SCAN_COMPLETED: return "SCAN_DONE";
        case WL_CONNECTED: return "CONNECTED";
        case WL_CONNECT_FAILED: return "CONNECT_FAILED";
        case WL_CONNECTION_LOST: return "CONNECTION_LOST";
        case WL_DISCONNECTED: return "DISCONNECTED";
        default: return "UNKNOWN";
    }
}

void configureIp() {
    if (!netCfg.useStatic) {
        Serial.println(F("[WiFi] rete in DHCP"));
        return;
    }
    IPAddress ip, gw, mask, dns;
    if (!ip.fromString(netCfg.ip) || !gw.fromString(netCfg.gateway) ||
        !mask.fromString(netCfg.subnet) || !dns.fromString(netCfg.dns)) {
        Serial.println(F("[WiFi] ERRORE configurazione IP: fallback DHCP"));
        return;
    }
    if (!WiFi.config(ip, gw, mask, dns)) {
        Serial.println(F("[WiFi] ERRORE applicazione IP statico"));
    }
}

void scanTargetOnce() {
    haveBestAp = false;
    Serial.println(F("[WiFi] scansione 2.4 GHz iniziale..."));
    const int n = WiFi.scanNetworks(false, true);
    if (n < 0) {
        Serial.printf("[WiFi] scansione fallita: %d\n", n);
        return;
    }

    int best = -1;
    int32_t bestRssi = -1000;
    for (int i = 0; i < n; ++i) {
        const String ssid = WiFi.SSID(i);
        Serial.printf("[WiFi-SCAN] ch=%d rssi=%d ssid='%s'\n",
                      WiFi.channel(i), WiFi.RSSI(i), ssid.c_str());
        if (ssid == wifiSsid && WiFi.RSSI(i) > bestRssi) {
            best = i;
            bestRssi = WiFi.RSSI(i);
        }
    }

    if (best >= 0) {
        const uint8_t *b = WiFi.BSSID(best);
        if (b) memcpy(bestBssid, b, sizeof(bestBssid));
        bestChannel = WiFi.channel(best);
        haveBestAp = true;
        Serial.printf("[WiFi] target trovato: ch=%d RSSI=%d BSSID=%s\n",
                      bestChannel, bestRssi, WiFi.BSSIDstr(best).c_str());
    } else {
        Serial.printf("[WiFi] ATTENZIONE: SSID '%s' non visto sulla banda 2.4 GHz\n", wifiSsid.c_str());
    }
    WiFi.scanDelete();
}

void beginSta() {
    configureIp();
    const char *pass = wifiPassword.length() ? wifiPassword.c_str() : nullptr;
    if (haveBestAp) WiFi.begin(wifiSsid.c_str(), pass, bestChannel, bestBssid, true);
    else WiFi.begin(wifiSsid.c_str(), pass);
}

void stopRecoveryAp() {
    if (!recoveryApActive) return;
    WiFi.softAPdisconnect(true);
    recoveryApActive = false;
    // Preserve the working STA connection and remove the provisioning AP.
    WiFi.mode(WIFI_STA);
    Serial.println(F("[WiFi] AP di recupero disattivato: STA principale nuovamente disponibile"));
}

void startRecoveryAp() {
    if (recoveryApActive) return;
    if (recoverySsid.length() == 0) buildRecoveryCredentials();
    WiFi.mode(WIFI_AP_STA);
    const bool ok = WiFi.softAP(recoverySsid.c_str(), recoveryPassword.c_str());
    if (!ok) {
        Serial.println(F("[WiFi] ERRORE avvio AP di recupero"));
        return;
    }
    recoveryApActive = true;
    Serial.print(F("[WiFi] AP RECUPERO attivo SSID='")); Serial.print(recoverySsid);
    Serial.print(F("' password='")); Serial.print(recoveryPassword);
    Serial.print(F("' IP=")); Serial.println(WiFi.softAPIP());
}

bool clearCredentialTrial() {
    Preferences p;
    if (!p.begin(NVS_NS, false)) return false;
    p.putBool("credpend", false);
    p.remove("prevssid");
    p.remove("prevpass");
    p.end();
    credentialTrialPending = false;
    previousWifiSsid = "";
    previousWifiPassword = "";
    return true;
}

bool restorePreviousCredentials() {
    if (!credentialTrialPending || previousWifiSsid.length() == 0U) return false;
    if (!validWifiCredentialsInternal(previousWifiSsid, previousWifiPassword)) return false;

    Preferences p;
    if (!p.begin(NVS_NS, false)) return false;
    p.putString("ssid", previousWifiSsid);
    p.putString("pass", previousWifiPassword);
    p.putBool("credpend", false);
    p.remove("prevssid");
    p.remove("prevpass");
    p.end();

    wifiSsid = previousWifiSsid;
    wifiPassword = previousWifiPassword;
    previousWifiSsid = "";
    previousWifiPassword = "";
    credentialTrialPending = false;
    haveBestAp = false;
    Serial.println(F("[WiFi] nuove credenziali non confermate: ripristino automatico delle precedenti"));
    return true;
}
} // namespace

void initNetwork() {
    loadConfig();
    buildRecoveryCredentials();

    // Deve essere impostato prima di WiFi.mode()/WiFi.begin().
    if (!WiFi.setHostname(netCfg.hostname.c_str())) {
        Serial.println(F("[WiFi] ATTENZIONE: setHostname fallito"));
    }
    WiFi.mode(WIFI_STA);
    // Non affidiamo credenziali/configurazione al layer WiFi: evita scritture
    // automatiche nella flash. Le sole impostazioni persistenti sono in NVS e
    // vengono scritte esclusivamente quando l'utente preme Salva.
    WiFi.persistent(false);
    WiFi.setAutoReconnect(true);
    WiFi.setSleep(false);
    WiFi.disconnect(false, false);
    delay(50);

    Serial.print(F("[WiFi] hostname=")); Serial.println(netCfg.hostname);
    Serial.print(F("[WiFi] modo=")); Serial.print(netCfg.useStatic ? F("STATICO") : F("DHCP"));
    if (netCfg.useStatic) {
        Serial.print(F(" IP=")); Serial.print(netCfg.ip);
        Serial.print(F(" GW=")); Serial.print(netCfg.gateway);
        Serial.print(F(" MASK=")); Serial.print(netCfg.subnet);
        Serial.print(F(" DNS=")); Serial.print(netCfg.dns);
    }
    Serial.println();
    Serial.print(F("[WiFi] SSID='")); Serial.print(wifiSsid); Serial.println('\'');
    if (credentialTrialPending) Serial.println(F("[WiFi] nuove credenziali in prova: rollback automatico dopo 45 s se non si collegano"));

    scanTargetOnce();
    beginSta();
    const uint32_t now = millis();
    lastAttemptMs = now;
    disconnectedSinceMs = now;
    credentialTrialStartedMs = now;
}

void serviceWiFi() {
    const wl_status_t status = WiFi.status();
    const bool connected = status == WL_CONNECTED;
    const uint32_t now = millis();

    if (connected) {
        if (!wasConnected) {
            Serial.print(F("[WiFi] CONNESSO IP=")); Serial.print(WiFi.localIP());
            Serial.print(F(" RSSI=")); Serial.print(WiFi.RSSI());
            Serial.print(F(" ch=")); Serial.println(WiFi.channel());
        }
        if (credentialTrialPending) {
            if (clearCredentialTrial()) Serial.println(F("[WiFi] nuove credenziali confermate e rese definitive"));
            else Serial.println(F("[WiFi] ATTENZIONE: connessione OK ma conferma credenziali in NVS fallita"));
        }
        if (recoveryApActive) stopRecoveryAp();
        if (!mdnsStarted) {
            if (MDNS.begin(netCfg.hostname.c_str())) {
                MDNS.addService("http", "tcp", 80);
                mdnsStarted = true;
                Serial.print(F("[mDNS] ATTIVO: http://"));
                Serial.print(netCfg.hostname);
                Serial.println(F(".local/"));
            } else {
                Serial.println(F("[mDNS] inizializzazione fallita; accesso via IP disponibile"));
            }
        }
        wasConnected = true;
        disconnectedSinceMs = now;
        return;
    }

    if (wasConnected) {
        Serial.println(F("[WiFi] connessione persa"));
        if (mdnsStarted) {
            MDNS.end();
            mdnsStarted = false;
        }
        wasConnected = false;
        disconnectedSinceMs = now;
    }

    if (credentialTrialPending &&
        static_cast<uint32_t>(now - credentialTrialStartedMs) >= WIFI_CREDENTIAL_TRIAL_MS) {
        if (restorePreviousCredentials()) {
            WiFi.disconnect(false, false);
            delay(20);
            if (recoveryApActive) WiFi.mode(WIFI_AP_STA); else WiFi.mode(WIFI_STA);
            scanTargetOnce();
            beginSta();
            lastAttemptMs = now;
            disconnectedSinceMs = now;
            return;
        }
        // No valid previous credentials exist: stop retrying the trial state,
        // then let the recovery AP provide local access to configuration.
        clearCredentialTrial();
    }

    if (!recoveryApActive &&
        static_cast<uint32_t>(now - disconnectedSinceMs) >= WIFI_RECOVERY_AP_AFTER_MS) {
        startRecoveryAp();
    }

    if (static_cast<uint32_t>(now - lastAttemptMs) >= WIFI_RETRY_MS) {
        lastAttemptMs = now;
        Serial.print(F("[WiFi] retry status="));
        Serial.print(static_cast<int>(status));
        Serial.print(F(" (")); Serial.print(statusName(status)); Serial.println(')');
        if (!WiFi.reconnect()) beginSta();
    }
}

bool wifiConnected() { return WiFi.status() == WL_CONNECTED; }
int32_t wifiRssi() { return wifiConnected() ? WiFi.RSSI() : -127; }
String wifiIpAddress() { return wifiConnected() ? WiFi.localIP().toString() : String("-"); }
String networkHostname() { return netCfg.hostname; }
String networkMdnsName() { return netCfg.hostname.length() ? netCfg.hostname + ".local" : String("-"); }
bool networkMdnsActive() { return mdnsStarted; }

bool networkWebAvailable() { return wifiConnected() || recoveryApActive; }
String networkWebIpAddress() {
    if (wifiConnected()) return WiFi.localIP().toString();
    if (recoveryApActive) return WiFi.softAPIP().toString();
    return String("-");
}
bool networkRecoveryApActive() { return recoveryApActive; }
String networkRecoveryApSsid() { return recoverySsid; }
String networkRecoveryApPassword() { return recoveryPassword; }
String networkWifiSsid() { return wifiSsid; }
bool networkWifiPasswordConfigured() { return wifiPassword.length() > 0U; }
bool networkWifiCredentialTrialPending() { return credentialTrialPending; }

bool validateWifiCredentials(const String &ssid, const String &password) {
    return validWifiCredentialsInternal(ssid, password);
}

bool saveWifiCredentials(const String &ssid, const String &password,
                         bool replacePassword, bool &changed) {
    const String nextSsid = ssid;
    const String nextPassword = replacePassword ? password : wifiPassword;
    if (!validWifiCredentialsInternal(nextSsid, nextPassword)) return false;

    changed = nextSsid != wifiSsid || nextPassword != wifiPassword;
    if (!changed) return true;

    Preferences p;
    if (!p.begin(NVS_NS, false)) {
        Serial.println(F("[WiFi] ERRORE apertura NVS per credenziali"));
        return false;
    }
    // Transaction-like recovery: current credentials are retained until the
    // new pair proves it can associate after reboot.
    p.putString("prevssid", wifiSsid);
    p.putString("prevpass", wifiPassword);
    p.putString("ssid", nextSsid);
    p.putString("pass", nextPassword);
    p.putBool("credpend", true);
    const bool verified = p.getString("ssid", "") == nextSsid &&
                          p.getString("pass", "") == nextPassword &&
                          p.getBool("credpend", false);
    p.end();
    if (!verified) {
        Serial.println(F("[WiFi] ERRORE verifica nuove credenziali in NVS"));
        return false;
    }

    previousWifiSsid = wifiSsid;
    previousWifiPassword = wifiPassword;
    wifiSsid = nextSsid;
    wifiPassword = nextPassword;
    credentialTrialPending = true;
    credentialTrialStartedMs = millis();
    Serial.println(F("[WiFi] nuove credenziali salvate in modalita' trial; richiesto riavvio"));
    return true;
}

bool resetWifiCredentialsToFirmwareDefaults(bool &changed) {
    return saveWifiCredentials(firmwareWifiSsid(), firmwareWifiPassword(), true, changed);
}

NetworkRuntimeConfig getNetworkConfig() { return netCfg; }

bool validateNetworkConfig(const NetworkRuntimeConfig &cfg) { return validConfig(cfg); }

bool saveNetworkConfig(const NetworkRuntimeConfig &cfg, bool &changed) {
    NetworkRuntimeConfig next = cfg;
    normalize(next);
    if (!validConfig(next)) return false;
    changed = !sameConfig(next, netCfg);
    if (!changed) return true; // zero scritture NVS se non cambia nulla

    if (!netPrefs.begin(NVS_NS, false)) {
        Serial.println(F("[WiFi] ERRORE apertura NVS netcfg in scrittura"));
        return false;
    }

    if (next.hostname != netCfg.hostname) netPrefs.putString("host", next.hostname);
    if (next.useStatic != netCfg.useStatic) netPrefs.putBool("static", next.useStatic);
    if (next.ip != netCfg.ip) netPrefs.putString("ip", next.ip);
    if (next.gateway != netCfg.gateway) netPrefs.putString("gw", next.gateway);
    if (next.subnet != netCfg.subnet) netPrefs.putString("mask", next.subnet);
    if (next.dns != netCfg.dns) netPrefs.putString("dns", next.dns);

    const bool verified = verifyStoredConfig(netPrefs, next);
    netPrefs.end();
    if (!verified) {
        Serial.println(F("[WiFi] ERRORE verifica NVS netcfg: configurazione non confermata"));
        return false;
    }

    netCfg = next;
    Serial.println(F("[WiFi] configurazione Web verificata in NVS"));
    return true;
}

bool resetNetworkConfigToDefaults(bool &changed) {
    const NetworkRuntimeConfig d = defaults();
    return saveNetworkConfig(d, changed);
}
