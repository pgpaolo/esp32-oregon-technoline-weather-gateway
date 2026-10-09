Import("env")
from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def replace_function(text, signature, replacement):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Web provisioning: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Web provisioning: opening brace missing: {signature}")
    depth = 0
    end = brace
    while end < len(text):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                end += 1
                while end < len(text) and text[end] in "\r\n":
                    end += 1
                return text[:start] + replacement + text[end:]
        end += 1
    raise RuntimeError(f"Web provisioning: closing brace missing: {signature}")


def function_block(text, signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Web provisioning: JS function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Web provisioning: JS opening brace missing: {signature}")
    depth = 0
    end = brace
    quote = None
    escape = False
    while end < len(text):
        ch = text[end]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
        else:
            if ch in ("'", '"', '`'):
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return start, end + 1, text[start:end + 1]
        end += 1
    raise RuntimeError(f"Web provisioning: JS closing brace missing: {signature}")


def replace_js_function(text, signature, replacement):
    start, end, _ = function_block(text, signature)
    return text[:start] + replacement + text[end:]


# ---------------------------------------------------------------------------
# Web server: authentication, Wi-Fi provisioning/recovery and firmware OTA.
# This script runs after the SD/SdFat scripts, so every route they add is also
# protected before the HTML is compressed into web_ui_generated.h.
# ---------------------------------------------------------------------------
cpp = read("src/web_manager.cpp")

if "#include <Update.h>" not in cpp:
    cpp = cpp.replace("#include <WebServer.h>\n", "#include <WebServer.h>\n#include <Update.h>\n", 1)
if '#include "web_security.h"' not in cpp:
    cpp = cpp.replace('#include "web_ui_generated.h"\n', '#include "web_security.h"\n#include "web_ui_generated.h"\n', 1)
if '#include "sd_logger.h"' not in cpp:
    cpp = cpp.replace('#include "web_security.h"\n', '#include "sd_logger.h"\n#include "web_security.h"\n', 1)

state_anchor = "uint32_t powerOffAtMs = 0;\n"
if "bool otaUploadActive" not in cpp:
    if state_anchor not in cpp:
        raise RuntimeError("Web provisioning: OTA state anchor missing")
    cpp = cpp.replace(
        state_anchor,
        state_anchor
        + "bool otaUploadActive = false;\n"
        + "bool otaUpdateBegun = false;\n"
        + "bool otaUploadOk = false;\n"
        + "bool otaAuthorized = false;\n"
        + "bool otaFirstChunk = true;\n"
        + "size_t otaBytes = 0;\n"
        + "size_t otaMaxBytes = 0;\n"
        + "String otaError;\n",
        1,
    )

forward_anchor = "String jsonEscapeString(const String &in);\n"
if "bool requireWebAuth()" not in cpp:
    if forward_anchor not in cpp:
        raise RuntimeError("Web provisioning: auth helper anchor missing")
    auth_helper = r'''
bool requireWebAuth() {
    if (webSecurityAuthorized(server)) return true;
    requestWebAuthentication(server);
    return false;
}

'''
    cpp = cpp.replace(forward_anchor, forward_anchor + auth_helper, 1)

network_get = r'''void handleNetworkConfigGet() {
    const NetworkRuntimeConfig c = getNetworkConfig();
    String out;
    out.reserve(900);
    out = "{\"hostname\":\"" + jsonEscapeString(c.hostname) + "\"";
    out += ",\"mdns\":\"" + jsonEscapeString(networkMdnsName()) + "\"";
    out += ",\"mdns_active\":"; out += networkMdnsActive() ? "true" : "false";
    out += ",\"use_static\":"; out += c.useStatic ? "true" : "false";
    out += ",\"ip\":\"" + jsonEscapeString(c.ip) + "\"";
    out += ",\"gateway\":\"" + jsonEscapeString(c.gateway) + "\"";
    out += ",\"subnet\":\"" + jsonEscapeString(c.subnet) + "\"";
    out += ",\"dns\":\"" + jsonEscapeString(c.dns) + "\"";
    out += ",\"actual_ip\":\"" + jsonEscapeString(wifiIpAddress()) + "\"";
    out += ",\"web_ip\":\"" + jsonEscapeString(networkWebIpAddress()) + "\"";
    out += ",\"wifi_ssid\":\"" + jsonEscapeString(networkWifiSsid()) + "\"";
    out += ",\"wifi_has_password\":"; out += networkWifiPasswordConfigured() ? "true" : "false";
    out += ",\"wifi_trial_pending\":"; out += networkWifiCredentialTrialPending() ? "true" : "false";
    out += ",\"recovery_ap_active\":"; out += networkRecoveryApActive() ? "true" : "false";
    out += ",\"recovery_ap_ssid\":\"" + jsonEscapeString(networkRecoveryApSsid()) + "\"";
    out += ",\"recovery_ap_password\":\"";
    if (networkRecoveryApActive()) out += jsonEscapeString(networkRecoveryApPassword());
    out += "\"}";
    sendNoCache();
    server.send(200, "application/json", out);
}

'''
cpp = replace_function(cpp, "void handleNetworkConfigGet() {", network_get)

network_post = r'''void handleNetworkConfigPost() {
    NetworkRuntimeConfig c = getNetworkConfig();
    if (server.hasArg("hostname")) c.hostname = server.arg("hostname");
    if (server.hasArg("use_static")) c.useStatic = server.arg("use_static") == "1" || server.arg("use_static") == "true" || server.arg("use_static") == "on";
    if (server.hasArg("ip")) c.ip = server.arg("ip");
    if (server.hasArg("gateway")) c.gateway = server.arg("gateway");
    if (server.hasArg("subnet")) c.subnet = server.arg("subnet");
    if (server.hasArg("dns")) c.dns = server.arg("dns");
    if (!validateNetworkConfig(c)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid network configuration\"}");
        return;
    }

    String wifiSsid = networkWifiSsid();
    if (server.hasArg("wifi_ssid")) wifiSsid = server.arg("wifi_ssid");
    const bool clearWifiPassword = server.hasArg("clear_wifi_password") &&
        (server.arg("clear_wifi_password") == "1" || server.arg("clear_wifi_password") == "true" || server.arg("clear_wifi_password") == "on");
    const bool replaceWifiPassword = clearWifiPassword || (server.hasArg("wifi_password") && server.arg("wifi_password").length() > 0U);
    const String wifiPassword = clearWifiPassword ? String("") : (replaceWifiPassword ? server.arg("wifi_password") : String(""));

    bool wifiChanged = false;
    if (!saveWifiCredentials(wifiSsid, wifiPassword, replaceWifiPassword, wifiChanged)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid Wi-Fi credentials or NVS verification failed\"}");
        return;
    }

    bool netChanged = false;
    if (!saveNetworkConfig(c, netChanged)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"network NVS verification failed\"}");
        return;
    }

    const bool rebootRequested = server.hasArg("reboot") && (server.arg("reboot") == "1" || server.arg("reboot") == "true");
    const bool reboot = wifiChanged || (netChanged && rebootRequested);
    if (reboot) rebootAtMs = millis() + 1200UL;
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":"; out += (wifiChanged || netChanged) ? "true" : "false";
    out += ",\"network_changed\":"; out += netChanged ? "true" : "false";
    out += ",\"wifi_changed\":"; out += wifiChanged ? "true" : "false";
    out += ",\"rebooting\":"; out += reboot ? "true" : "false";
    out += ",\"new_ip\":\"" + jsonEscapeString(c.ip) + "\"";
    out += ",\"hostname\":\"" + jsonEscapeString(c.hostname) + "\"";
    out += ",\"mdns\":\"" + jsonEscapeString(c.hostname + ".local") + "\"}";
    server.send(200, "application/json", out);
}

'''
cpp = replace_function(cpp, "void handleNetworkConfigPost() {", network_post)

network_reset = r'''void handleNetworkConfigReset() {
    bool netChanged = false;
    bool wifiChanged = false;
    if (!resetNetworkConfigToDefaults(netChanged) || !resetWifiCredentialsToFirmwareDefaults(wifiChanged)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"network reset failed\"}");
        return;
    }
    const bool changed = netChanged || wifiChanged;
    if (changed) rebootAtMs = millis() + 1200UL;
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":"; out += changed ? "true" : "false";
    out += ",\"network_changed\":"; out += netChanged ? "true" : "false";
    out += ",\"wifi_changed\":"; out += wifiChanged ? "true" : "false";
    out += ",\"rebooting\":"; out += changed ? "true" : "false"; out += "}";
    server.send(200, "application/json", out);
}

'''
cpp = replace_function(cpp, "void handleNetworkConfigReset() {", network_reset)

if "void handleSecurityConfigGet()" not in cpp:
    extra_handlers = r'''
void handleSecurityConfigGet() {
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", webSecurityConfigJson());
}

void handleSecurityConfigPost() {
    const WebSecurityConfig current = getWebSecurityConfig();
    bool enabled = current.enabled;
    String username = current.username;
    if (server.hasArg("enabled")) enabled = server.arg("enabled") == "1" || server.arg("enabled") == "true" || server.arg("enabled") == "on";
    if (server.hasArg("username")) username = server.arg("username");
    const bool replacePassword = server.hasArg("password") && server.arg("password").length() > 0U;
    const String newPassword = replacePassword ? server.arg("password") : String("");
    bool changed = false;
    String error;
    if (!saveWebSecurityConfig(enabled, username, newPassword, replacePassword, changed, error)) {
        String out = "{\"ok\":false,\"error\":\"" + jsonEscapeString(error) + "\"}";
        server.send(400, "application/json", out);
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":"; out += changed ? "true" : "false";
    out += ",\"enabled\":"; out += webSecurityEnabled() ? "true" : "false"; out += "}";
    server.send(200, "application/json", out);
}

void handleFirmwareInfo() {
    String out;
    out.reserve(420);
    out = "{\"board\":\"" + jsonEscapeString(String(BOARD_NAME)) + "\"";
    out += ",\"firmware\":\"" + jsonEscapeString(String(firmwareVersion())) + "\"";
    out += ",\"git_commit\":\"" + jsonEscapeString(String(firmwareGitCommit())) + "\"";
    out += ",\"free_ota_bytes\":" + String(ESP.getFreeSketchSpace());
    out += ",\"auth_enabled\":"; out += webSecurityEnabled() ? "true" : "false";
#if defined(BOARD_T3_S3_SX1278)
    out += ",\"board_family\":\"T3-S3\"";
#elif defined(BOARD_T3_V16_SX1278)
    out += ",\"board_family\":\"T3-V1.6.1\"";
#else
    out += ",\"board_family\":\"UNKNOWN\"";
#endif
    out += "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

bool otaFilenameCompatible(String name) {
    name.toLowerCase();
#if defined(BOARD_T3_S3_SX1278)
    if (name.indexOf("t3-v161") >= 0 || name.indexOf("v1.6.1") >= 0 || name.indexOf("v16") >= 0) return false;
#elif defined(BOARD_T3_V16_SX1278)
    if (name.indexOf("t3-s3") >= 0 || name.indexOf("esp32s3") >= 0 || name.indexOf("esp32-s3") >= 0) return false;
#endif
    return true;
}

void otaFail(const String &reason) {
    otaError = reason;
    otaUploadOk = false;
    if (otaUpdateBegun) {
        Update.end(false);
        otaUpdateBegun = false;
    }
    otaUploadActive = false;
    if (getSdLoggerConfig().enabled) remountSdLogger();
    Serial.print(F("[OTA] ERRORE: ")); Serial.println(reason);
}

void handleFirmwareUpload() {
    HTTPUpload &upload = server.upload();
    if (upload.status == UPLOAD_FILE_START) {
        otaUploadActive = false;
        otaUpdateBegun = false;
        otaUploadOk = false;
        otaAuthorized = false;
        otaFirstChunk = true;
        otaBytes = 0;
        otaMaxBytes = ESP.getFreeSketchSpace();
        otaError = "";

        // Deliberate safety gate: firmware upload is forbidden while the Web
        // interface is configured without authentication, even on the LAN.
        if (!webSecurityEnabled()) {
            otaFail("OTA disabled while Web authentication is OFF");
            return;
        }
        if (!webSecurityAuthorized(server)) {
            otaFail("authentication required");
            return;
        }
        otaAuthorized = true;
        if (!otaFilenameCompatible(upload.filename)) {
            otaFail("firmware filename targets a different board family");
            return;
        }
        if (otaMaxBytes < 65536U) {
            otaFail("OTA partition has insufficient free space");
            return;
        }

        prepareSdLoggerForDeepSleep();
        if (!Update.begin(UPDATE_SIZE_UNKNOWN, U_FLASH)) {
            otaFail(String("Update.begin failed, code ") + String(Update.getError()));
            return;
        }
        otaUpdateBegun = true;
        otaUploadActive = true;
        Serial.print(F("[OTA] upload avviato: ")); Serial.println(upload.filename);
        return;
    }

    if (!otaAuthorized || !otaUploadActive) return;

    if (upload.status == UPLOAD_FILE_WRITE) {
        if (upload.currentSize == 0U) return;
        if (otaFirstChunk) {
            otaFirstChunk = false;
            if (upload.buf[0] != 0xE9U) {
                otaFail("invalid ESP32 application image header");
                return;
            }
        }
        if (otaBytes + upload.currentSize > otaMaxBytes) {
            otaFail("firmware image exceeds OTA partition space");
            return;
        }
        const size_t written = Update.write(upload.buf, upload.currentSize);
        if (written != upload.currentSize) {
            otaFail(String("flash write failed, code ") + String(Update.getError()));
            return;
        }
        otaBytes += written;
        return;
    }

    if (upload.status == UPLOAD_FILE_END) {
        if (!otaUpdateBegun || otaBytes == 0U) {
            otaFail("empty firmware upload");
            return;
        }
        if (!Update.end(true) || Update.hasError()) {
            otaUpdateBegun = false;
            otaFail(String("firmware validation failed, code ") + String(Update.getError()));
            return;
        }
        otaUpdateBegun = false;
        otaUploadActive = false;
        otaUploadOk = true;
        Serial.print(F("[OTA] firmware scritto: ")); Serial.print(static_cast<unsigned long>(otaBytes)); Serial.println(F(" byte"));
        return;
    }

    if (upload.status == UPLOAD_FILE_ABORTED) {
        otaFail("upload aborted by client");
    }
}

void handleFirmwareUploadDone() {
    if (!webSecurityEnabled()) {
        server.send(403, "application/json", "{\"ok\":false,\"error\":\"OTA requires Web authentication\"}");
        return;
    }
    if (!requireWebAuth()) return;
    sendNoCache();
    if (!otaUploadOk) {
        String error = otaError.length() ? otaError : String("firmware upload failed");
        String out = "{\"ok\":false,\"error\":\"" + jsonEscapeString(error) + "\"}";
        server.send(400, "application/json", out);
        return;
    }
    String out = "{\"ok\":true,\"bytes\":" + String(static_cast<unsigned long>(otaBytes)) + ",\"rebooting\":true}";
    server.send(200, "application/json", out);
    rebootAtMs = millis() + 1200UL;
}

'''
    root_anchor = "void handleRoot() {\n"
    if root_anchor not in cpp:
        raise RuntimeError("Web provisioning: root handler anchor missing")
    cpp = cpp.replace(root_anchor, extra_handlers + root_anchor, 1)

# Initialize security before any request can be served.
init_anchor = "    station = &stateRef;\n"
if "    initWebSecurity();\n" not in cpp:
    if init_anchor not in cpp:
        raise RuntimeError("Web provisioning: initWeb station anchor missing")
    cpp = cpp.replace(init_anchor, init_anchor + "    initWebSecurity();\n", 1)

# Protect all normal GET/POST handlers, including routes inserted by prior SD
# scripts. The OTA upload callback is registered separately below because it has
# a second callback and must authenticate before the first flash write.
def protect_route(match):
    url, method, handler = match.group(1), match.group(2), match.group(3)
    return f'server.on({url}, {method}, [](){{ if (!requireWebAuth()) return; {handler}(); }});'

route_re = re.compile(r'server\.on\(("[^"\n]+"),\s*(HTTP_[A-Z]+),\s*([A-Za-z_]\w*)\);')
cpp = route_re.sub(protect_route, cpp)

not_found_old = '    server.onNotFound([](){ server.send(404, "text/plain", "Not found"); });\n'
not_found_new = '    server.onNotFound([](){ if (!requireWebAuth()) return; server.send(404, "text/plain", "Not found"); });\n'
if not_found_old in cpp:
    cpp = cpp.replace(not_found_old, not_found_new, 1)

if 'server.on("/api/security"' not in cpp:
    routes = r'''    server.on("/api/security", HTTP_GET, [](){ if (!requireWebAuth()) return; handleSecurityConfigGet(); });
    server.on("/api/security", HTTP_POST, [](){ if (!requireWebAuth()) return; handleSecurityConfigPost(); });
    server.on("/api/firmware", HTTP_GET, [](){ if (!requireWebAuth()) return; handleFirmwareInfo(); });
    server.on("/api/firmware", HTTP_POST, handleFirmwareUploadDone, handleFirmwareUpload);
'''
    nf_anchor = "    server.onNotFound("
    pos = cpp.find(nf_anchor)
    if pos < 0:
        raise RuntimeError("Web provisioning: onNotFound anchor missing")
    cpp = cpp[:pos] + routes + cpp[pos:]

service_web = r'''void serviceWeb() {
#if WEB_ENABLE
    if (networkWebAvailable()) {
        if (!webStarted) {
            server.begin();
            webStarted = true;
            Serial.print(F("[WEB] HTTP ATTIVO: http://"));
            Serial.print(networkWebIpAddress());
            Serial.println('/');
        }
        server.handleClient();
    }
    if (powerOffAtMs && static_cast<int32_t>(millis() - powerOffAtMs) >= 0) {
        powerOffAtMs = 0;
        Serial.println(F("[WEB] spegnimento controller richiesto"));
        delay(50);
        enterControllerDeepSleep();
    }
    if (rebootAtMs && static_cast<int32_t>(millis() - rebootAtMs) >= 0) {
        Serial.println(F("[WEB] riavvio richiesto dalla configurazione/OTA"));
        delay(80);
        ESP.restart();
    }
#endif
}

'''
cpp = replace_function(cpp, "void serviceWeb() {", service_web)
write("src/web_manager.cpp", cpp)


# ---------------------------------------------------------------------------
# microSD: automatic mount retry after boot or temporary card failure.
# Runs after apply_sdfat_backend.py so retry state controls the real SdFat
# backend, not the Arduino SD placeholder in the committed base source.
# ---------------------------------------------------------------------------
sd = read("src/sd_logger.cpp")

retry_state_anchor = "bool spiStarted = false;\n"
if "SD_MOUNT_RETRY_STEPS_MS" not in sd:
    if retry_state_anchor not in sd:
        raise RuntimeError("Web provisioning: SD retry state anchor missing")
    sd = sd.replace(
        retry_state_anchor,
        retry_state_anchor
        + "constexpr uint32_t SD_MOUNT_RETRY_STEPS_MS[] = {5000UL, 15000UL, 60000UL, 300000UL};\n"
        + "uint8_t mountRetryStage = 0;\n"
        + "uint32_t nextMountRetryMs = 0;\n",
        1,
    )

if "void resetMountRetry()" not in sd:
    retry_helpers = r'''void resetMountRetry() {
    mountRetryStage = 0;
    nextMountRetryMs = 0;
}

void scheduleMountRetry() {
    if (!cfg.enabled || !status.supported || status.mounted) {
        nextMountRetryMs = 0;
        return;
    }
    constexpr uint8_t stepCount = sizeof(SD_MOUNT_RETRY_STEPS_MS) / sizeof(SD_MOUNT_RETRY_STEPS_MS[0]);
    const uint8_t idx = mountRetryStage < stepCount ? mountRetryStage : static_cast<uint8_t>(stepCount - 1U);
    nextMountRetryMs = millis() + SD_MOUNT_RETRY_STEPS_MS[idx];
    if (mountRetryStage + 1U < stepCount) mountRetryStage++;
    Serial.print(F("[SD] nuovo tentativo mount tra "));
    Serial.print(SD_MOUNT_RETRY_STEPS_MS[idx] / 1000UL);
    Serial.println(F(" s"));
}

uint32_t mountRetryRemainingMs() {
    if (!nextMountRetryMs) return 0;
    const int32_t delta = static_cast<int32_t>(nextMountRetryMs - millis());
    return delta > 0 ? static_cast<uint32_t>(delta) : 0U;
}

'''
    defaults_anchor = "SdLoggerConfig defaults() {\n"
    if defaults_anchor not in sd:
        raise RuntimeError("Web provisioning: SD defaults anchor missing")
    sd = sd.replace(defaults_anchor, retry_helpers + defaults_anchor, 1)

remount = r'''bool remountSdLogger() {
#if !SDCARD_SUPPORTED
    status.supported = false;
    nextMountRetryMs = 0;
    return false;
#else
    const bool ok = mountSdFat(false);
    if (ok) resetMountRetry();
    else scheduleMountRetry();
    return ok;
#endif
}

'''
sd = replace_function(sd, "bool remountSdLogger() {", remount)

service_sd = r'''void serviceSdLogger(const StationState &station) {
    status.timeSynced = timeValid();
    const uint32_t now = millis();

    if (cfg.enabled && status.supported && !status.mounted && nextMountRetryMs &&
        static_cast<int32_t>(now - nextMountRetryMs) >= 0) {
        remountSdLogger();
    }
    if (!cfg.enabled || !status.mounted) return;

    const uint32_t snapshotMs = static_cast<uint32_t>(cfg.snapshotIntervalSec) * 1000UL;
    if (snapshotMs && static_cast<uint32_t>(now - lastSnapshotMs) >= snapshotMs) {
        lastSnapshotMs = now;
        queueBmeSnapshot(station);
        queueLightningSnapshot();
    }

    if (static_cast<uint32_t>(now - lastWriteServiceMs) >= WRITE_PERIOD_MS) {
        lastWriteServiceMs = now;
        appendBatch();
    }
    if (static_cast<uint32_t>(now - lastCapacityRefreshMs) >= CAPACITY_REFRESH_MS) refreshCapacity();
}

'''
sd = replace_function(sd, "void serviceSdLogger(const StationState &station) {", service_sd)

prepare_sd = r'''void prepareSdLoggerForDeepSleep() {
    if (status.mounted) {
        for (uint8_t i = 0; i < 4U && queueTail != queueHead; ++i) appendBatch();
    }
    unmount();
    resetMountRetry();
}

'''
sd = replace_function(sd, "void prepareSdLoggerForDeepSleep() {", prepare_sd)

if "bool formatSdLogger() {" in sd:
    format_sd = r'''bool formatSdLogger() {
#if !SDCARD_SUPPORTED
    return false;
#else
    resetMountRetry();
    const bool ok = mountSdFat(true);
    if (ok) {
        resetMountRetry();
        Serial.println(F("[SD] formattazione e rimontaggio completati"));
    } else {
        scheduleMountRetry();
    }
    return ok;
#endif
}

'''
    sd = replace_function(sd, "bool formatSdLogger() {", format_sd)

retry_json_anchor = '    out += ",\\\"last_write_ms\\\":" + String(s.lastWriteMs);\n'
if '\\"retry_pending\\"' not in sd:
    if retry_json_anchor not in sd:
        raise RuntimeError("Web provisioning: SD status JSON anchor missing")
    sd = sd.replace(
        retry_json_anchor,
        retry_json_anchor
        + '    out += ",\\\"retry_pending\\\":"; out += (cfg.enabled && s.supported && !s.mounted && nextMountRetryMs) ? "true" : "false";\n'
        + '    out += ",\\\"retry_in_ms\\\":" + String(mountRetryRemainingMs());\n',
        1,
    )
write("src/sd_logger.cpp", sd)


# ---------------------------------------------------------------------------
# Configuration UI: add Wi-Fi provisioning to RETE and group security + OTA in
# a new SISTEMA page. Keep the rest of the dashboard visually unchanged.
# ---------------------------------------------------------------------------
d = read("web/dashboard.html")
d = d.replace(">RETE / IP</button>", ">RETE / WI-FI</button>")
d = d.replace(">BACKUP / RESTORE</button>", ">ARCHIVIO</button>")

if 'id="netSsid"' not in d:
    net_anchor = '<label><span>Hostname dispositivo</span><input id="netHostname" type="text" maxlength="32" placeholder="oregon-gateway"></label>\n'
    net_fields = r'''<label><span>SSID Wi-Fi 2,4 GHz</span><input id="netSsid" type="text" maxlength="32" placeholder="Nome rete"></label>
<label><span>Nuova password Wi-Fi</span><input id="netWifiPassword" type="password" maxlength="63" placeholder="vuoto = mantieni quella salvata"></label>
<label class="checkLine"><input id="netWifiOpen" type="checkbox"><span>Rete Wi-Fi aperta (cancella password)</span></label>
<label class="cfgWide"><span>AP di recupero</span><input id="netRecovery" type="text" readonly value="si attiva automaticamente se la STA non torna disponibile"></label>
'''
    if net_anchor not in d:
        raise RuntimeError("Web provisioning: network UI anchor missing")
    d = d.replace(net_anchor, net_anchor + net_fields, 1)

# Backup remains intentionally secret-free for Wi-Fi. It no longer incorrectly
# claims that runtime Wi-Fi provisioning does not exist.
d = d.replace(
    "<b>Non incluso:</b> SSID/password Wi-Fi, che in questa versione restano nel firmware/config_private.h.",
    "<b>Non incluso:</b> SSID/password Wi-Fi e credenziali Web. I valori Wi-Fi runtime restano separati dal backup per evitare esportazioni accidentali.",
)

if 'id="tabSystem"' not in d:
    tab_match = re.search(r'(<button id="tabBackup"[^>]*>.*?</button>)', d)
    if not tab_match:
        raise RuntimeError("Web provisioning: backup tab anchor missing")
    system_tab = '<button id="tabSystem" class="cfgTab" onclick="showCfgTab(\'system\')">SISTEMA</button>'
    d = d[:tab_match.end()] + system_tab + d[tab_match.end():]

if 'id="cfgSystem"' not in d:
    system_page = r'''
<div id="cfgSystem" class="cfgPage">
<div class="cfgGrid">
<label class="checkLine"><input id="secEnabled" type="checkbox"><span>Proteggi Dashboard e API con Basic Authentication</span></label>
<label><span>Utente amministratore</span><input id="secUser" type="text" maxlength="24" value="admin"></label>
<label><span>Nuova password amministratore</span><input id="secPassword" type="password" maxlength="63" placeholder="vuoto = mantieni quella salvata"></label>
<label class="cfgWide"><span>Stato sicurezza</span><input id="secState" type="text" readonly></label>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveSecurity()">Salva sicurezza</button><span id="secSummary" class="muted"></span></div>
<div class="cfgGrid">
<label class="cfgWide"><span>Firmware .bin</span><input id="fwFile" type="file" accept="application/octet-stream,.bin"></label>
<label><span>Board / firmware corrente</span><input id="fwBoard" type="text" readonly></label>
<label><span>Spazio slot OTA</span><input id="fwSpace" type="text" readonly></label>
</div>
<div class="cfgActions"><button id="fwUploadBtn" class="modeBtn dangerBtn" onclick="uploadFirmware()">Installa firmware</button><span id="fwSummary" class="muted">Seleziona il firmware.bin prodotto dalla build corretta.</span></div>
<div class="cfgNote"><b>OTA:</b> disponibile solo con autenticazione Web attiva. Prima della scrittura il logger microSD viene chiuso in modo controllato; in caso di errore viene rimontato. Il file deve essere un'immagine applicativa ESP32 valida e deve entrare nello slot OTA. Il nome file viene inoltre controllato per evitare lo scambio evidente tra T3 V1.6.1 e T3-S3. <b>Basic Authentication su HTTP non cifra le credenziali:</b> usare questa interfaccia solo su LAN/VPN o dietro un terminatore HTTPS affidabile.</div>
</div>
'''
    config_end = '</div>\n</section>\n<section id="mainDiag"'
    if config_end not in d:
        raise RuntimeError("Web provisioning: configuration page end anchor missing")
    d = d.replace(config_end, system_page + '</div>\n</section>\n<section id="mainDiag"', 1)

load_network = r'''async function loadNetwork(){try{const n=await (await fetch('/api/network',{cache:'no-store'})).json();E('netHostname').value=n.hostname||'';E('netSsid').value=n.wifi_ssid||'';E('netWifiPassword').value='';E('netWifiOpen').checked=false;E('netMdns').value=n.mdns?('http://'+n.mdns+'/'):'-';E('netStatic').checked=!!n.use_static;E('netIp').value=n.ip||'';E('netGw').value=n.gateway||'';E('netMask').value=n.subnet||'';E('netDns').value=n.dns||'';E('netActual').value=n.actual_ip||n.web_ip||'-';const rec=n.recovery_ap_active?(n.recovery_ap_ssid+' · password '+n.recovery_ap_password+' · IP '+(n.web_ip||'192.168.4.1')):'inattivo · si abilita automaticamente dopo perdita prolungata della STA';E('netRecovery').value=rec;E('netSummary').textContent=(n.use_static?'IP statico':'DHCP')+' · '+(n.mdns_active?'mDNS attivo':'mDNS in attesa')+(n.wifi_trial_pending?' · credenziali Wi-Fi in prova':'')+(n.recovery_ap_active?' · AP RECUPERO ATTIVO':'');}catch(e){E('netSummary').textContent='errore lettura rete'}}'''
d = replace_js_function(d, "async function loadNetwork(){", load_network)

save_network = r'''async function saveNetwork(){const q=new URLSearchParams();q.set('hostname',E('netHostname').value.trim().toLowerCase());q.set('wifi_ssid',E('netSsid').value.trim());q.set('use_static',E('netStatic').checked?'1':'0');q.set('ip',E('netIp').value);q.set('gateway',E('netGw').value);q.set('subnet',E('netMask').value);q.set('dns',E('netDns').value);q.set('reboot','1');const wp=E('netWifiPassword').value;if(E('netWifiOpen').checked)q.set('clear_wifi_password','1');else if(wp)q.set('wifi_password',wp);const r=await fetch('/api/network?'+q.toString(),{method:'POST',cache:'no-store'});if(!r.ok){alert('Rete/Wi-Fi: '+await r.text());return}const j=await r.json();E('netWifiPassword').value='';E('netWifiOpen').checked=false;if(j.rebooting){alert('Configurazione salvata. Riavvio in corso. Le nuove credenziali Wi-Fi verranno provate per 45 secondi; se falliscono il gateway ripristina automaticamente quelle precedenti.');}else{E('netSummary').textContent=j.changed?'Configurazione salvata':'Nessuna modifica: zero scritture NVS';}}'''
d = replace_js_function(d, "async function saveNetwork(){", save_network)

reset_network = r'''async function resetNetwork(){if(!confirm('Ripristinare IP e credenziali Wi-Fi ai valori compilati nel firmware?'))return;const r=await fetch('/api/network/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset rete fallito');return}const j=await r.json();if(j.changed)alert('Rete/Wi-Fi ripristinata ai default firmware. Riavvio in corso.');else E('netSummary').textContent='Gia ai default: zero scritture NVS';}'''
d = replace_js_function(d, "async function resetNetwork(){", reset_network)

if "async function loadSecurity()" not in d:
    system_js = r'''
async function loadSecurity(){try{const s=await (await fetch('/api/security',{cache:'no-store'})).json();E('secEnabled').checked=!!s.enabled;E('secUser').value=s.username||'admin';E('secPassword').value='';E('secState').value=(s.enabled?'PROTETTO':'NON PROTETTO')+(s.password_set?' · password configurata':' · password mancante')+(s.locked?' · BLOCCO TEMPORANEO':'');E('secSummary').textContent=s.enabled?'Basic Authentication attiva':'Autenticazione disattivata · OTA bloccato';}catch(e){if(E('secSummary'))E('secSummary').textContent='errore lettura sicurezza'}}
async function saveSecurity(){const q=new URLSearchParams();q.set('enabled',E('secEnabled').checked?'1':'0');q.set('username',E('secUser').value.trim());const p=E('secPassword').value;if(p)q.set('password',p);const r=await fetch('/api/security?'+q.toString(),{method:'POST',cache:'no-store'});const body=await r.text();if(!r.ok){alert('Sicurezza: '+body);return}const j=JSON.parse(body);E('secPassword').value='';E('secSummary').textContent=j.changed?'Configurazione sicurezza salvata':'Nessuna modifica';if(j.changed&&E('secEnabled').checked&&p)alert('Nuove credenziali amministrative attive. Il browser potrebbe richiedere nuovamente il login al prossimo accesso.');}
function fmtBytes(v){let n=Number(v||0);if(n>=1048576)return(n/1048576).toFixed(2)+' MiB';if(n>=1024)return(n/1024).toFixed(1)+' KiB';return n+' B'}
async function loadFirmwareInfo(){try{const f=await (await fetch('/api/firmware',{cache:'no-store'})).json();E('fwBoard').value=(f.board_family||f.board||'--')+' · '+(f.firmware||'--');E('fwSpace').value=fmtBytes(f.free_ota_bytes);E('fwUploadBtn').disabled=!f.auth_enabled;E('fwSummary').textContent=f.auth_enabled?'OTA pronto · '+fmtBytes(f.free_ota_bytes)+' disponibili':'OTA bloccato: attiva prima l autenticazione Web';}catch(e){if(E('fwSummary'))E('fwSummary').textContent='errore lettura stato OTA'}}
async function uploadFirmware(){const file=E('fwFile').files[0];if(!file){alert('Seleziona un file firmware .bin.');return}if(!file.name.toLowerCase().endsWith('.bin')){alert('Il file deve avere estensione .bin.');return}if(!confirm('Installare '+file.name+' ('+fmtBytes(file.size)+')? Il gateway verra riavviato solo dopo una scrittura OTA completata.'))return;E('fwUploadBtn').disabled=true;E('fwSummary').textContent='Upload e verifica firmware in corso...';try{const form=new FormData();form.append('firmware',file,file.name);const r=await fetch('/api/firmware',{method:'POST',body:form,cache:'no-store'});const body=await r.text();if(!r.ok)throw new Error(body);const j=JSON.parse(body);E('fwSummary').textContent='Firmware scritto · '+fmtBytes(j.bytes)+' · riavvio in corso';alert('Firmware installato correttamente. Il gateway si riavvia.');}catch(e){E('fwSummary').textContent='Aggiornamento fallito';E('fwUploadBtn').disabled=false;alert('OTA fallito: '+e)}}
'''
    script_end = "</script>"
    if script_end not in d:
        raise RuntimeError("Web provisioning: script end anchor missing")
    d = d.replace(script_end, system_js + script_end, 1)

# Extend the existing config-tab dispatcher without disturbing SD tabs that may
# have been inserted by an earlier pre-script.
start, end, show_cfg = function_block(d, "function showCfgTab(t){")
if "'system'" not in show_cfg:
    list_match = re.search(r"for\(const x of \[([^\]]+)\]\)", show_cfg)
    if not list_match:
        raise RuntimeError("Web provisioning: showCfgTab list missing")
    values = list_match.group(1).rstrip()
    show_cfg = show_cfg[:list_match.start(1)] + values + ",'system'" + show_cfg[list_match.end(1):]
if "t==='system'" not in show_cfg:
    show_cfg = show_cfg[:-1] + "else if(t==='system'){loadSecurity();loadFirmwareInfo();}" + show_cfg[-1:]
d = d[:start] + show_cfg + d[end:]

# Startup preload so the SYSTEM page is immediately coherent when selected.
if "loadSecurity();loadFirmwareInfo();" not in d:
    startup_anchor = "loadNetwork();loadMqtt();"
    if startup_anchor not in d:
        raise RuntimeError("Web provisioning: startup network/MQTT anchor missing")
    d = d.replace(startup_anchor, startup_anchor + "loadSecurity();loadFirmwareInfo();", 1)

# SdFat's header function exists at this point. Distinguish a scheduled retry
# from a terminal mount failure rather than showing SD KO immediately at boot.
if "function updateSdHeader(c,s){" in d:
    sd_header = r'''function updateSdHeader(c,s){const e=E('hdrSd');if(!e)return;const n=Number(s.written||0),wrote=sdHeaderWritten!==null&&n>sdHeaderWritten;sdHeaderWritten=n;if(s.mounted){e.className='statusPill '+(wrote?'write':'ok');e.textContent=wrote?'SD SCRIVE':(c.enabled?'SD ON':'SD PRONTA')}else if(c.enabled&&s.retry_pending){e.className='statusPill wait';e.textContent='SD ATTESA'}else{e.className='statusPill '+(c.enabled?'bad':'wait');e.textContent=c.enabled?'SD KO':'SD OFF'}e.title='microSD · scritture '+n+' · coda '+Number(s.queue_depth||0)+' · errori '+Number(s.write_errors||0)+(s.retry_pending?' · retry '+Math.ceil(Number(s.retry_in_ms||0)/1000)+' s':'')+(s.file?' · '+s.file:'')}'''
    d = replace_js_function(d, "function updateSdHeader(c,s){", sd_header)

write("web/dashboard.html", d)

print("Web provisioning/OTA/auth patch applied")
