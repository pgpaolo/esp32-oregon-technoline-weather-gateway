from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Network NVS: verify against effective compiled defaults. Unchanged keys may
# legitimately be absent from NVS, so sentinel values would produce false KO.
# -----------------------------------------------------------------------------
p = Path("src/network_manager.cpp")
s = p.read_text(encoding="utf-8")
old = '''bool verifyStoredConfig(Preferences &p, const NetworkRuntimeConfig &expected) {
    return p.getString("host", "") == expected.hostname &&
           p.getBool("static", !expected.useStatic) == expected.useStatic &&
           p.getString("ip", "") == expected.ip &&
           p.getString("gw", "") == expected.gateway &&
           p.getString("mask", "") == expected.subnet &&
           p.getString("dns", "") == expected.dns;
}
'''
new = '''bool verifyStoredConfig(Preferences &p, const NetworkRuntimeConfig &expected) {
    NetworkRuntimeConfig d = defaults();
    normalize(d);
    return p.getString("host", d.hostname) == expected.hostname &&
           p.getBool("static", d.useStatic) == expected.useStatic &&
           p.getString("ip", d.ip) == expected.ip &&
           p.getString("gw", d.gateway) == expected.gateway &&
           p.getString("mask", d.subnet) == expected.subnet &&
           p.getString("dns", d.dns) == expected.dns;
}
'''
s = replace_once(s, old, new, "network effective-default verification")
p.write_text(s, encoding="utf-8")


# -----------------------------------------------------------------------------
# Display NVS: same effective-default rule. A fresh board can have only the
# modified keys stored; defaults for all other fields must still verify OK.
# -----------------------------------------------------------------------------
p = Path("src/display_manager.cpp")
s = p.read_text(encoding="utf-8")
old = '''bool verifyStoredConfig(Preferences &p, const DisplayRuntimeConfig &c) {
    return p.getUChar("pages", 0) == c.pageMask &&
           p.getUChar("env", 0xFF) == c.environmentFields &&
           p.getUChar("wind", 0xFF) == c.windRainFields &&
           p.getUChar("tech", 0xFF) == c.technolineFields &&
           p.getUChar("press", 0xFF) == c.pressureFields &&
           p.getUChar("status", 0xFF) == c.statusFields &&
           p.getUShort("page_s", 0) == c.pageIntervalSec &&
           p.getUChar("contrast", 0) == c.contrast;
}
'''
new = '''bool verifyStoredConfig(Preferences &p, const DisplayRuntimeConfig &c) {
    DisplayRuntimeConfig d = defaults();
    normalize(d);
    return p.getUChar("pages", d.pageMask) == c.pageMask &&
           p.getUChar("env", d.environmentFields) == c.environmentFields &&
           p.getUChar("wind", d.windRainFields) == c.windRainFields &&
           p.getUChar("tech", d.technolineFields) == c.technolineFields &&
           p.getUChar("press", d.pressureFields) == c.pressureFields &&
           p.getUChar("status", d.statusFields) == c.statusFields &&
           p.getUShort("page_s", d.pageIntervalSec) == c.pageIntervalSec &&
           p.getUChar("contrast", d.contrast) == c.contrast;
}
'''
s = replace_once(s, old, new, "display effective-default verification")
p.write_text(s, encoding="utf-8")


# -----------------------------------------------------------------------------
# MQTT NVS: check namespace open, verify read-back before changing runtime, and
# make reset report a real success/failure result to the Web API.
# -----------------------------------------------------------------------------
p = Path("src/mqtt_publisher.cpp")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    '''    mqttPrefs.begin("mqttcfg", true);
    mqttCfg.enabled = mqttPrefs.getBool("enabled", d.enabled);
''',
    '''    if (!mqttPrefs.begin("mqttcfg", true)) {
        mqttCfg = d;
        normalize(mqttCfg);
        Serial.println(F("[MQTT] NVS mqttcfg non disponibile: uso valori firmware"));
        return;
    }
    mqttCfg.enabled = mqttPrefs.getBool("enabled", d.enabled);
''',
    "mqtt load begin",
)

marker = "void applyClientConfig() {"
helper = '''bool verifyStoredMqttConfig(Preferences &p, const MqttRuntimeConfig &expected) {
    MqttRuntimeConfig d = defaults();
    normalize(d);
    return p.getBool("enabled", d.enabled) == expected.enabled &&
           p.getString("broker", d.broker) == expected.broker &&
           p.getUShort("port", d.port) == expected.port &&
           p.getString("user", d.user) == expected.user &&
           p.getString("pass", d.password) == expected.password &&
           p.getString("client", d.clientId) == expected.clientId &&
           p.getString("topic", d.baseTopic) == expected.baseTopic &&
           p.getUChar("tlsmode", static_cast<uint8_t>(d.tlsMode)) == static_cast<uint8_t>(expected.tlsMode) &&
           p.getString("cacert", d.caCertificate) == expected.caCertificate &&
           p.getUInt("fields", d.fieldsMask) == expected.fieldsMask;
}

'''
s = replace_once(s, marker, helper + marker, "mqtt verification helper")

old = '''    mqttPrefs.begin("mqttcfg", false);
    if (next.enabled != old.enabled) mqttPrefs.putBool("enabled", next.enabled);
    if (next.broker != old.broker) mqttPrefs.putString("broker", next.broker);
    if (next.port != old.port) mqttPrefs.putUShort("port", next.port);
    if (next.user != old.user) mqttPrefs.putString("user", next.user);
    if (next.password != old.password) mqttPrefs.putString("pass", next.password);
    if (next.clientId != old.clientId) mqttPrefs.putString("client", next.clientId);
    if (next.baseTopic != old.baseTopic) mqttPrefs.putString("topic", next.baseTopic);
    if (next.tlsMode != old.tlsMode) mqttPrefs.putUChar("tlsmode", static_cast<uint8_t>(next.tlsMode));
    if (next.caCertificate != old.caCertificate) mqttPrefs.putString("cacert", next.caCertificate);
    if (next.fieldsMask != old.fieldsMask) mqttPrefs.putUInt("fields", next.fieldsMask);
    mqttPrefs.end();
    mqttCfg = next;
    applyClientConfig();
    return true;
'''
new = '''    if (!mqttPrefs.begin("mqttcfg", false)) {
        Serial.println(F("[MQTT] ERRORE apertura NVS mqttcfg in scrittura"));
        return false;
    }
    if (next.enabled != old.enabled) mqttPrefs.putBool("enabled", next.enabled);
    if (next.broker != old.broker) mqttPrefs.putString("broker", next.broker);
    if (next.port != old.port) mqttPrefs.putUShort("port", next.port);
    if (next.user != old.user) mqttPrefs.putString("user", next.user);
    if (next.password != old.password) mqttPrefs.putString("pass", next.password);
    if (next.clientId != old.clientId) mqttPrefs.putString("client", next.clientId);
    if (next.baseTopic != old.baseTopic) mqttPrefs.putString("topic", next.baseTopic);
    if (next.tlsMode != old.tlsMode) mqttPrefs.putUChar("tlsmode", static_cast<uint8_t>(next.tlsMode));
    if (next.caCertificate != old.caCertificate) mqttPrefs.putString("cacert", next.caCertificate);
    if (next.fieldsMask != old.fieldsMask) mqttPrefs.putUInt("fields", next.fieldsMask);
    const bool verified = verifyStoredMqttConfig(mqttPrefs, next);
    mqttPrefs.end();
    if (!verified) {
        Serial.println(F("[MQTT] ERRORE verifica NVS mqttcfg: configurazione non confermata"));
        return false;
    }
    mqttCfg = next;
    applyClientConfig();
    Serial.println(F("[MQTT] configurazione Web verificata in NVS"));
    return true;
'''
s = replace_once(s, old, new, "mqtt save verification")

pattern = re.compile(r"void resetMqttConfigToDefaults\(\) \{.*?\n\}\n\nvoid serviceMQTT", re.S)
replacement = '''bool resetMqttConfigToDefaults() {
    MqttRuntimeConfig d = defaults();
    normalize(d);
    const bool already = mqttCfg.enabled == d.enabled && mqttCfg.broker == d.broker && mqttCfg.port == d.port &&
        mqttCfg.user == d.user && mqttCfg.password == d.password && mqttCfg.clientId == d.clientId &&
        mqttCfg.baseTopic == d.baseTopic && mqttCfg.tlsMode == d.tlsMode &&
        mqttCfg.caCertificate == d.caCertificate && mqttCfg.fieldsMask == d.fieldsMask;
    if (already) return true;
    if (!mqttPrefs.begin("mqttcfg", false)) {
        Serial.println(F("[MQTT] ERRORE apertura NVS mqttcfg per reset"));
        return false;
    }
    const bool cleared = mqttPrefs.clear();
    const bool verified = cleared && verifyStoredMqttConfig(mqttPrefs, d);
    mqttPrefs.end();
    if (!verified) {
        Serial.println(F("[MQTT] ERRORE reset/verifica NVS mqttcfg"));
        return false;
    }
    mqttCfg = d;
    applyClientConfig();
    Serial.println(F("[MQTT] default firmware verificati dopo reset NVS"));
    return true;
}

void serviceMQTT'''
s, count = pattern.subn(replacement, s, count=1)
if count != 1:
    raise SystemExit(f"mqtt reset function: expected 1 match, found {count}")
p.write_text(s, encoding="utf-8")


# -----------------------------------------------------------------------------
# Web API + Web UI.
# -----------------------------------------------------------------------------
p = Path("src/web_manager.cpp")
s = p.read_text(encoding="utf-8")

s = replace_once(
    s,
    '''    setDisplayEnabled(enabled);
    sendNoCache();
''',
    '''    if (!setDisplayEnabled(enabled)) {
        server.send(500, "application/json", "{\\"ok\\":false,\\"error\\":\\"display NVS verification failed\\"}");
        return;
    }
    sendNoCache();
''',
    "display power API verification",
)

s = replace_once(
    s,
    '''    out += ",\\"current_page\\":" + String(displayCurrentPage());
    out += "}";
''',
    '''    out += ",\\"current_page\\":" + String(displayCurrentPage());
    out += ",\\"nvs_ok\\":"; out += displayPersistenceAvailable() ? "true" : "false";
    out += "}";
''',
    "display config GET NVS status",
)

s = replace_once(
    s,
    '''        setDisplayEnabled(v == "1" || v == "true" || v == "on");
    }
    sendNoCache();
''',
    '''        if (!setDisplayEnabled(v == "1" || v == "true" || v == "on")) {
            server.send(500, "application/json", "{\\"ok\\":false,\\"error\\":\\"display power NVS verification failed\\"}");
            return;
        }
    }
    sendNoCache();
''',
    "display config POST power verification",
)

s = replace_once(
    s,
    '''    setDisplayEnabled(displayOn);
    bool displayChanged = false;
''',
    '''    if (!setDisplayEnabled(displayOn)) {
        server.send(500, "application/json", "{\\"ok\\":false,\\"error\\":\\"could not persist display power setting\\"}");
        return;
    }
    bool displayChanged = false;
''',
    "backup import display power verification",
)

s = replace_once(
    s,
    '''void handleMqttConfigReset() {
    resetMqttConfigToDefaults();
    sendNoCache();
''',
    '''void handleMqttConfigReset() {
    if (!resetMqttConfigToDefaults()) {
        server.send(500, "application/json", "{\\"ok\\":false,\\"error\\":\\"MQTT NVS reset verification failed\\"}");
        return;
    }
    sendNoCache();
''',
    "mqtt reset Web API verification",
)

old = "function displaySelectPages(v){document.querySelectorAll('[data-dpagebit]').forEach(x=>x.checked=!!v)}"
new = old + "function displayAutoEnablePages(){const groups=[['data-denvbit',0],['data-dwindbit',1],['data-dtechbit',2],['data-dpressbit',3],['data-dstatusbit',4]];for(const [attr,bit] of groups){if([...document.querySelectorAll('['+attr+']')].some(x=>x.checked)){const p=document.querySelector('[data-dpagebit=\\\"'+bit+'\\\"]');if(p)p.checked=true;}}}"
s = replace_once(s, old, new, "display auto-enable helper")

s = replace_once(
    s,
    "async function saveDisplayConfig(){const pageMask=dGet('data-dpagebit');",
    "async function saveDisplayConfig(){displayAutoEnablePages();const pageMask=dGet('data-dpagebit');",
    "display auto-enable call",
)

s = replace_once(
    s,
    "if(cfg)cfg.checked=displayOn;",
    "if(cfg&&!(mainTab==='config'&&E('cfgDisplay')&&E('cfgDisplay').classList.contains('active')))cfg.checked=displayOn;",
    "protect display form from live refresh",
)

s = replace_once(
    s,
    "E('displaySummary').textContent=(d.on?'OLED ON':'OLED OFF')+' · pagina '+(Number(d.current_page)+1)+' · cambio '+d.page_interval_sec+' s · contrasto '+d.contrast;",
    "E('displaySummary').textContent=(d.on?'OLED ON':'OLED OFF')+' · pagina '+(Number(d.current_page)+1)+' · cambio '+d.page_interval_sec+' s · contrasto '+d.contrast+' · NVS '+(d.nvs_ok?'OK':'KO');",
    "display NVS summary",
)

s = replace_once(
    s,
    "loadNetwork();loadMqtt();refresh();setInterval(refresh,2000);setInterval(loadMqtt,10000);",
    "loadNetwork();loadMqtt();refresh();setInterval(refresh,2000);setInterval(()=>{const editing=mainTab==='config'&&E('cfgMqtt')&&E('cfgMqtt').classList.contains('active');if(!editing)loadMqtt();},10000);",
    "protect MQTT form from periodic refresh",
)

p.write_text(s, encoding="utf-8")

print("Web UI / NVS persistence patch applied successfully")
