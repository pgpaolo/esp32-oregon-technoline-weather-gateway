Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
MARKER = "// MB_PUBLIC_TLS_V1"


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# COMPATIBLE MB public HTTPS trust.
#
# Keep the existing NVS numeric values backward compatible:
#   0 = verified public CA (now uses the firmware ISRG X1/X2 trust bundle)
#   1 = insecure/test mode
#   2 = explicit custom CA from NVS
#
# The public trust bundle is the same one already proven by AdminSensor Remote,
# so normal Let's Encrypt endpoints no longer need a duplicated PEM in NVS.
# ---------------------------------------------------------------------------
hdr_path = "src/mb_compatible_publisher.h"
hdr = read(hdr_path)
old_enum = '''enum class MbCompatibleTlsMode : uint8_t {
    CaVerified = 0,
    Insecure = 1
};'''
new_enum = '''enum class MbCompatibleTlsMode : uint8_t {
    CaVerified = 0, // built-in public ISRG Root X1/X2 trust
    Insecure = 1,   // diagnostics only; preserves legacy NVS value
    CustomCa = 2    // explicit private/custom CA stored in NVS
};'''
if old_enum in hdr:
    hdr = hdr.replace(old_enum, new_enum, 1)
elif "CustomCa = 2" not in hdr:
    raise RuntimeError("MB public TLS: header enum anchor missing")
write(hdr_path, hdr)

cpp_path = "src/mb_compatible_publisher.cpp"
cpp = read(cpp_path)

if '#include "remote_trust.h"' not in cpp:
    anchor = '#include "network_manager.h"\n'
    if anchor not in cpp:
        raise RuntimeError("MB public TLS: remote trust include anchor missing")
    cpp = cpp.replace(anchor, anchor + '#include "remote_trust.h"\n', 1)

if MARKER not in cpp:
    start = cpp.find("void performHttp(const String &url, const String &payload, const MbCompatibleConfig &cfg) {")
    end = cpp.find("\nvoid worker(void *)", start)
    if start < 0 or end < 0:
        raise RuntimeError("MB public TLS: performHttp function anchor missing")

    replacement = r'''void performHttp(const String &url, const String &payload, const MbCompatibleConfig &cfg) {
    // MB_PUBLIC_TLS_V1
    gBusy = true;
    gLastAttemptMs = millis();
    int httpCode = 0;
    String response;
    String error;
    HTTPClient http;

    // Match the proven Davis transport envelope.  A saved shorter timeout is
    // still accepted by the UI/NVS, but HTTPS gets enough time for DNS + TLS.
    const uint32_t connectTimeoutMs = cfg.timeoutMs < 5000U ? 5000U : cfg.timeoutMs;
    const uint32_t requestTimeoutMs = cfg.timeoutMs < 7000U ? 7000U : cfg.timeoutMs;
    http.setConnectTimeout(connectTimeoutMs);
    http.setTimeout(requestTimeoutMs);
    http.setReuse(false);

    const String requestUrl = buildRequestUrl(url, urlEncode(payload));
    bool begun = false;

    if (requestUrl.startsWith("https://")) {
        WiFiClientSecure client;
        if (cfg.tlsMode == MbCompatibleTlsMode::Insecure) {
            client.setInsecure();
        } else if (cfg.tlsMode == MbCompatibleTlsMode::CustomCa) {
            if (cfg.caCertificate.length() == 0U) {
                error = "custom CA required for selected HTTPS mode";
            } else {
                client.setCACert(cfg.caCertificate.c_str());
            }
        } else {
            // Normal Internet HTTPS: reuse the public ISRG X1/X2 bundle already
            // used by AdminSensor Remote.  No PEM copy from NVS is required.
            client.setCACert(REMOTE_TRUST_CA);
        }

        if (error.length() == 0U) {
            client.setTimeout((requestTimeoutMs + 999U) / 1000U);
            begun = http.begin(client, requestUrl);
            if (begun) {
                httpCode = http.GET();
                if (httpCode > 0) response = http.getString();
                else error = String("HTTPS transport error ") + http.errorToString(httpCode);
                http.end();
            } else {
                error = "HTTPS begin failed";
            }
            client.stop();
        }
    } else {
        WiFiClient client;
        client.setTimeout((requestTimeoutMs + 999U) / 1000U);
        begun = http.begin(client, requestUrl);
        if (begun) {
            httpCode = http.GET();
            if (httpCode > 0) response = http.getString();
            else error = String("HTTP transport error ") + http.errorToString(httpCode);
            http.end();
        } else {
            error = "HTTP begin failed";
        }
        client.stop();
    }

    response.trim();
    const bool success = httpCode >= 200 && httpCode < 300 && response.equalsIgnoreCase("success");
    if (!success && error.length() == 0U) {
        error = String("endpoint response ") + httpCode + " / " + (response.length() ? response : String("empty"));
    }

    if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        gLastHttpCode = httpCode;
        gLastResponse = response.substring(0, 96);
        gLastError = success ? String("") : error.substring(0, 160);
        if (success) gLastSuccessMs = millis();
        xSemaphoreGive(gMutex);
    }
    Serial.print(F("[MB-COMPAT] HTTP "));
    Serial.print(httpCode);
    Serial.print(F(" result="));
    Serial.println(success ? F("success") : error);
    gBusy = false;
}
'''
    cpp = cpp[:start] + replacement + cpp[end:]

old_name = '''const char *mbCompatibleTlsModeName(MbCompatibleTlsMode mode) {
    return mode == MbCompatibleTlsMode::Insecure ? "INSECURE" : "CA_VERIFIED";
}'''
new_name = '''const char *mbCompatibleTlsModeName(MbCompatibleTlsMode mode) {
    if (mode == MbCompatibleTlsMode::Insecure) return "INSECURE";
    if (mode == MbCompatibleTlsMode::CustomCa) return "CUSTOM_CA";
    return "PUBLIC_CA";
}'''
if old_name in cpp:
    cpp = cpp.replace(old_name, new_name, 1)
elif 'return "PUBLIC_CA";' not in cpp:
    raise RuntimeError("MB public TLS: TLS mode name anchor missing")

old_validation = '''    if (static_cast<uint8_t>(cfg.tlsMode) > static_cast<uint8_t>(MbCompatibleTlsMode::Insecure)) return false;
    if (cfg.caCertificate.length() > MAX_CA_LEN) return false;'''
new_validation = '''    if (static_cast<uint8_t>(cfg.tlsMode) > static_cast<uint8_t>(MbCompatibleTlsMode::CustomCa)) return false;
    if (cfg.caCertificate.length() > MAX_CA_LEN) return false;
    if (cfg.tlsMode == MbCompatibleTlsMode::CustomCa && cfg.caCertificate.length() == 0U) return false;'''
if old_validation in cpp:
    cpp = cpp.replace(old_validation, new_validation, 1)
elif "MbCompatibleTlsMode::CustomCa && cfg.caCertificate.length() == 0U" not in cpp:
    raise RuntimeError("MB public TLS: validation anchor missing")

write(cpp_path, cpp)

# ---------------------------------------------------------------------------
# Web UI: value 0 stays backward compatible and now clearly means public CA.
# Value 1 remains insecure; value 2 explicitly opts into the NVS custom PEM.
# ---------------------------------------------------------------------------
dash_path = "web/dashboard.html"
dash = read(dash_path)
old_select = '<label><span>HTTPS / TLS</span><select id="mbTls"><option value="0">Verifica CA</option><option value="1">Senza verifica (solo test)</option></select></label>'
new_select = '<label><span>HTTPS / TLS</span><select id="mbTls"><option value="0">CA pubblica (ISRG X1/X2)</option><option value="2">CA personalizzata</option><option value="1">Senza verifica (solo test)</option></select></label>'
if old_select in dash:
    dash = dash.replace(old_select, new_select, 1)
elif 'CA pubblica (ISRG X1/X2)' not in dash:
    raise RuntimeError("MB public TLS: dashboard TLS select anchor missing")

old_label = '<label class="cfgWide"><span>CA certificate PEM (vuoto = mantieni)</span><textarea id="mbCa" maxlength="3600" placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"></textarea></label>'
new_label = '<label class="cfgWide"><span>CA personalizzata PEM (solo modalita CA personalizzata; vuoto = mantieni)</span><textarea id="mbCa" maxlength="3600" placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"></textarea></label>'
if old_label in dash:
    dash = dash.replace(old_label, new_label, 1)

old_note = 'HTTPS verificato richiede una CA PEM; la modalita senza verifica e solo diagnostica.'
new_note = 'HTTPS pubblico usa automaticamente ISRG Root X1/X2 gia presenti nel firmware; la CA PEM serve solo per server privati/personalizzati. La modalita senza verifica e solo diagnostica.'
if old_note in dash:
    dash = dash.replace(old_note, new_note, 1)

write(dash_path, dash)
print("MB-compatible TLS: public ISRG trust + Davis-style HTTP transport enabled")
