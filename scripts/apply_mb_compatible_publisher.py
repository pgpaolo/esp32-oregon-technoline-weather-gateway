Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def js_block(text, signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"MB-compatible: JS function missing: {signature}")
    brace = text.find("{", start)
    depth = 0
    quote = None
    escape = False
    pos = brace
    while pos < len(text):
        ch = text[pos]
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
                    return start, pos + 1, text[start:pos + 1]
        pos += 1
    raise RuntimeError(f"MB-compatible: JS function not closed: {signature}")


# ---------------------------------------------------------------------------
# Main runtime: publisher is independent from MQTT and actual HTTP runs on a
# worker task, so the RF loop only prepares a compact payload when due.
# ---------------------------------------------------------------------------
main = read("src/main.cpp")
if '#include "mb_compatible_publisher.h"' not in main:
    anchor = '#include "mqtt_publisher.h"\n'
    if anchor not in main:
        raise RuntimeError("MB-compatible: main include anchor missing")
    main = main.replace(anchor, anchor + '#include "mb_compatible_publisher.h"\n', 1)
if "initMbCompatiblePublisher(station);" not in main:
    anchor = "    initMQTT(mqttClient, wifiClient);\n"
    if anchor not in main:
        raise RuntimeError("MB-compatible: init anchor missing")
    main = main.replace(anchor, anchor + "    initMbCompatiblePublisher(station);\n", 1)
if "serviceMbCompatiblePublisher();" not in main:
    anchor = "    serviceBarometer(station);\n"
    if anchor not in main:
        raise RuntimeError("MB-compatible: service anchor missing")
    main = main.replace(anchor, anchor + "    serviceMbCompatiblePublisher();\n", 1)
write("src/main.cpp", main)

power = read("src/power_manager.cpp")
if '#include "mb_compatible_publisher.h"' not in power:
    anchor = '#include "mqtt_publisher.h"\n'
    if anchor not in power:
        raise RuntimeError("MB-compatible: power include anchor missing")
    power = power.replace(anchor, anchor + '#include "mb_compatible_publisher.h"\n', 1)
if "prepareMbCompatibleForDeepSleep();" not in power:
    anchor = "    prepareMqttForDeepSleep();\n"
    if anchor not in power:
        raise RuntimeError("MB-compatible: deep-sleep anchor missing")
    power = power.replace(anchor, "    prepareMbCompatibleForDeepSleep();\n" + anchor, 1)
write("src/power_manager.cpp", power)


# ---------------------------------------------------------------------------
# Web API + backup/restore. This script runs after the generic Web-auth patch,
# so all new routes explicitly enforce the same Basic Authentication gate.
# ---------------------------------------------------------------------------
web = read("src/web_manager.cpp")
if '#include "mb_compatible_publisher.h"' not in web:
    anchor = '#include "mqtt_publisher.h"\n'
    if anchor not in web:
        raise RuntimeError("MB-compatible: web include anchor missing")
    web = web.replace(anchor, anchor + '#include "mb_compatible_publisher.h"\n', 1)

if "void handleMbCompatibleGet()" not in web:
    anchor = "} // namespace\n\nvoid initWeb(StationState &stateRef) {\n"
    if anchor not in web:
        raise RuntimeError("MB-compatible: namespace anchor missing")
    handlers = r'''void handleMbCompatibleGet() {
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", mbCompatibleConfigStatusJson());
}

void handleMbCompatiblePost() {
    MbCompatibleConfig cfg = getMbCompatibleConfig();
    if (server.hasArg("enabled")) cfg.enabled = server.arg("enabled") == "1" || server.arg("enabled") == "true" || server.arg("enabled") == "on";
    if (server.hasArg("url")) cfg.url = server.arg("url");
    if (server.hasArg("interval_sec")) cfg.intervalSec = static_cast<uint16_t>(server.arg("interval_sec").toInt());
    if (server.hasArg("timeout_ms")) cfg.timeoutMs = static_cast<uint16_t>(server.arg("timeout_ms").toInt());
    if (server.hasArg("tls_mode")) cfg.tlsMode = static_cast<MbCompatibleTlsMode>(server.arg("tls_mode").toInt());
    if (server.hasArg("source_priority")) cfg.sourcePriority = static_cast<uint8_t>(server.arg("source_priority").toInt());

    const bool clearCa = server.hasArg("clear_ca") && (server.arg("clear_ca") == "1" || server.arg("clear_ca") == "true" || server.arg("clear_ca") == "on");
    const bool replaceCa = clearCa || (server.hasArg("ca_certificate") && server.arg("ca_certificate").length() > 0U);
    if (clearCa) cfg.caCertificate = "";
    else if (replaceCa) cfg.caCertificate = server.arg("ca_certificate");

    if (!validateMbCompatibleConfig(cfg, replaceCa)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid MB-compatible configuration\"}");
        return;
    }
    if (!saveMbCompatibleConfig(cfg, replaceCa)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"MB-compatible NVS verification failed\"}");
        return;
    }
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", mbCompatibleConfigStatusJson());
}

void handleMbCompatibleTest() {
    const MbCompatibleConfig cfg = getMbCompatibleConfig();
    if (cfg.url.length() == 0U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"endpoint URL missing\"}");
        return;
    }
    requestMbCompatibleTest();
    sendNoCache();
    server.send(202, "application/json", "{\"ok\":true,\"queued\":true}");
}

void handleMbCompatibleReset() {
    if (!resetMbCompatibleConfig()) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"MB-compatible reset failed\"}");
        return;
    }
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", mbCompatibleConfigStatusJson());
}

'''
    web = web.replace(anchor, handlers + anchor, 1)

if 'server.on("/api/mbcompatible"' not in web:
    anchor = "    server.onNotFound("
    pos = web.find(anchor)
    if pos < 0:
        raise RuntimeError("MB-compatible: route anchor missing")
    routes = '''    server.on("/api/mbcompatible", HTTP_GET, [](){ if (!requireWebAuth()) return; handleMbCompatibleGet(); });
    server.on("/api/mbcompatible", HTTP_POST, [](){ if (!requireWebAuth()) return; handleMbCompatiblePost(); });
    server.on("/api/mbcompatible/test", HTTP_POST, [](){ if (!requireWebAuth()) return; handleMbCompatibleTest(); });
    server.on("/api/mbcompatible/reset", HTTP_POST, [](){ if (!requireWebAuth()) return; handleMbCompatibleReset(); });
'''
    web = web[:pos] + routes + web[pos:]

# Backup export.
if "const MbCompatibleConfig mb = getMbCompatibleConfig();" not in web:
    anchor = "    const MqttRuntimeConfig m = getMqttConfig();\n"
    if anchor not in web:
        raise RuntimeError("MB-compatible: backup config anchor missing")
    web = web.replace(anchor, anchor + "    const MbCompatibleConfig mb = getMbCompatibleConfig();\n", 1)

if '\"mb_compatible_enabled\"' not in web:
    anchor = '    out += ",\\n  \\\"mqtt_fields_mask\\\":" + String(m.fieldsMask);\n'
    if anchor not in web:
        raise RuntimeError("MB-compatible: backup output anchor missing")
    fields = anchor + '''    out += ",\\n  \\\"mb_compatible_enabled\\\":"; out += mb.enabled ? "true" : "false";
    out += ",\\n  \\\"mb_compatible_url\\\":\\\"" + jsonEscapeString(mb.url) + "\\\"";
    out += ",\\n  \\\"mb_compatible_interval_sec\\\":" + String(mb.intervalSec);
    out += ",\\n  \\\"mb_compatible_timeout_ms\\\":" + String(mb.timeoutMs);
    out += ",\\n  \\\"mb_compatible_tls_mode\\\":" + String(static_cast<uint8_t>(mb.tlsMode));
    out += ",\\n  \\\"mb_compatible_ca_certificate\\\":\\\"" + jsonEscapeString(mb.caCertificate) + "\\\"";
    out += ",\\n  \\\"mb_compatible_source_priority\\\":" + String(mb.sourcePriority);
'''
    web = web.replace(anchor, fields, 1)

# Backup import config object. There are two occurrences of MqttRuntimeConfig;
# only the import one is followed by temp variables and lacks const.
if "MbCompatibleConfig mbImport = getMbCompatibleConfig();" not in web:
    anchor = "    MqttRuntimeConfig m = getMqttConfig();\n    bool tmpBool = false;\n"
    if anchor not in web:
        raise RuntimeError("MB-compatible: import object anchor missing")
    web = web.replace(anchor, "    MqttRuntimeConfig m = getMqttConfig();\n    MbCompatibleConfig mbImport = getMbCompatibleConfig();\n    bool tmpBool = false;\n", 1)

if "replaceMbCa" not in web:
    anchor = "    if (jsonGetUInt(body, \"mqtt_fields_mask\", tmpUInt)) m.fieldsMask = tmpUInt & MQTT_FIELDS_ALL;\n"
    if anchor not in web:
        raise RuntimeError("MB-compatible: import MQTT anchor missing")
    block = anchor + '''
    if (jsonGetBool(body, "mb_compatible_enabled", tmpBool)) mbImport.enabled = tmpBool;
    if (jsonGetString(body, "mb_compatible_url", tmpString)) mbImport.url = tmpString;
    if (jsonGetUInt(body, "mb_compatible_interval_sec", tmpUInt)) mbImport.intervalSec = static_cast<uint16_t>(tmpUInt);
    if (jsonGetUInt(body, "mb_compatible_timeout_ms", tmpUInt)) mbImport.timeoutMs = static_cast<uint16_t>(tmpUInt);
    if (jsonGetUInt(body, "mb_compatible_tls_mode", tmpUInt)) mbImport.tlsMode = static_cast<MbCompatibleTlsMode>(tmpUInt);
    const bool replaceMbCa = jsonGetString(body, "mb_compatible_ca_certificate", tmpString);
    if (replaceMbCa) mbImport.caCertificate = tmpString;
    if (jsonGetUInt(body, "mb_compatible_source_priority", tmpUInt)) mbImport.sourcePriority = static_cast<uint8_t>(tmpUInt);
'''
    web = web.replace(anchor, block, 1)

old_validate = "    if (!validateNetworkConfig(n) || !validateMqttConfig(m, replacePassword, replaceCa)) {\n"
new_validate = "    if (!validateNetworkConfig(n) || !validateMqttConfig(m, replacePassword, replaceCa) || !validateMbCompatibleConfig(mbImport, replaceMbCa)) {\n"
if old_validate in web:
    web = web.replace(old_validate, new_validate, 1)
elif new_validate not in web:
    raise RuntimeError("MB-compatible: import validation anchor missing")

old_save = "    if (!saveMqttConfig(m, replacePassword, replaceCa) || !saveNetworkConfig(n, netChanged)) {\n"
new_save = "    if (!saveMqttConfig(m, replacePassword, replaceCa) || !saveMbCompatibleConfig(mbImport, replaceMbCa) || !saveNetworkConfig(n, netChanged)) {\n"
if old_save in web:
    web = web.replace(old_save, new_save, 1)
elif new_save not in web:
    raise RuntimeError("MB-compatible: import save anchor missing")

write("src/web_manager.cpp", web)


# ---------------------------------------------------------------------------
# Dashboard. Keep the historical SD config-tab loop untouched: MB-compatible,
# like SYSTEM, uses explicit toggles so repeated PlatformIO builds stay stable.
# ---------------------------------------------------------------------------
dash = read("web/dashboard.html")
if 'id="tabMbcompatible"' not in dash:
    anchor = '<button id="tabMqtt" class="cfgTab" onclick="showCfgTab(\'mqtt\')">MQTT / TLS</button>'
    if anchor not in dash:
        raise RuntimeError("MB-compatible: dashboard MQTT tab anchor missing")
    dash = dash.replace(anchor, anchor + '<button id="tabMbcompatible" class="cfgTab" onclick="showCfgTab(\'mbcompatible\')">COMPATIBLE MB</button>', 1)

if 'id="cfgMbcompatible"' not in dash:
    anchor = '<div id="cfgDisplay" class="cfgPage">'
    if anchor not in dash:
        raise RuntimeError("MB-compatible: dashboard page anchor missing")
    page = '''<div id="cfgMbcompatible" class="cfgPage">
<div class="cfgGrid">
<label class="checkLine"><input id="mbEnabled" type="checkbox"><span>Abilita invio realtime</span></label>
<label class="cfgWide"><span>URL endpoint</span><input id="mbUrl" type="text" maxlength="384" placeholder="https://server.example/path/mb.php"></label>
<label><span>Intervallo invio (s)</span><input id="mbInterval" type="number" min="10" max="3600" value="60"></label>
<label><span>Timeout HTTP (ms)</span><input id="mbTimeout" type="number" min="500" max="10000" value="2500"></label>
<label><span>Sorgente primaria</span><select id="mbPriority"><option value="0">Oregon, fallback Technoline</option><option value="1">Technoline, fallback Oregon</option></select></label>
<label><span>HTTPS / TLS</span><select id="mbTls"><option value="0">Verifica CA</option><option value="1">Senza verifica (solo test)</option></select></label>
<label class="cfgWide"><span>CA certificate PEM (vuoto = mantieni)</span><textarea id="mbCa" maxlength="3600" placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"></textarea></label>
<label class="checkLine"><input id="mbClearCa" type="checkbox"><span>Cancella CA salvata</span></label>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveMbCompatible()">Salva COMPATIBLE MB</button><button class="modeBtn" onclick="testMbCompatible()">Test invio</button><button class="modeBtn" onclick="resetMbCompatible()">Default</button><span id="mbSummary" class="muted"></span></div>
<div class="cfgNote">Publisher HTTP separato da MQTT. L'URL e completamente modificabile: se non contiene <code>{data}</code> il gateway aggiunge automaticamente <code>?d=...</code> (o <code>&amp;d=...</code>). Pacchetto Meteobridge/Aurora-compatible a 192 campi: i valori realmente disponibili vengono inviati, gli altri restano <code>--</code>. HTTPS verificato richiede una CA PEM; la modalita senza verifica e solo diagnostica.</div>
<div class="cfgNote" id="mbStatus">Stato: non ancora letto.</div>
</div>
'''
    dash = dash.replace(anchor, page + anchor, 1)

# Explicit tab toggle without touching the stable ['net',...,'backup'] loop.
start, end, block = js_block(dash, "function showCfgTab(t){")
if "cfgMbcompatible" not in block:
    marker = "if(t==='net')"
    if marker not in block:
        raise RuntimeError("MB-compatible: showCfgTab loader anchor missing")
    inject = "E('cfgMbcompatible').classList.toggle('active',t==='mbcompatible');E('tabMbcompatible').classList.toggle('active',t==='mbcompatible');if(t==='mbcompatible')loadMbCompatible();"
    block = block.replace(marker, inject + marker, 1)
    dash = dash[:start] + block + dash[end:]

if "async function loadMbCompatible()" not in dash:
    anchor = "async function powerOffDevice()"
    if anchor not in dash:
        raise RuntimeError("MB-compatible: JS insertion anchor missing")
    js = r'''function mbAge(v){return !Number.isFinite(Number(v))||Number(v)>=4294967295?'mai':(Number(v)<60?Number(v)+' s fa':Math.floor(Number(v)/60)+' min fa')}
function renderMbStatus(m){const e=E('mbStatus');if(!e)return;let s='Stato: '+(m.enabled?'ABILITATO':'disabilitato')+' · tempo '+(m.time_synced?'OK':'NTP attesa');if(m.busy)s+=' · INVIO IN CORSO';else if(m.pending)s+=' · in coda';if(Number(m.last_http_code))s+=' · HTTP '+m.last_http_code;if(m.last_response)s+=' · risposta '+m.last_response;if(m.last_error)s+=' · ERRORE '+m.last_error;s+=' · ultimo tentativo '+mbAge(m.last_attempt_age_s)+' · ultimo OK '+mbAge(m.last_success_age_s);if(Number(m.payload_fields))s+=' · '+m.payload_fields+' campi / '+m.payload_bytes+' B';e.textContent=s;e.className='cfgNote '+(m.last_error?'bad':'');}
async function refreshMbCompatibleStatus(){try{const m=await (await fetch('/api/mbcompatible',{cache:'no-store'})).json();renderMbStatus(m);return m}catch(e){const s=E('mbStatus');if(s)s.textContent='Stato: errore lettura '+e;return null}}
async function loadMbCompatible(){const m=await refreshMbCompatibleStatus();if(!m)return;E('mbEnabled').checked=!!m.enabled;E('mbUrl').value=m.url||'';E('mbInterval').value=m.interval_sec||60;E('mbTimeout').value=m.timeout_ms||2500;E('mbPriority').value=String(m.source_priority||0);E('mbTls').value=String(m.tls_mode||0);E('mbCa').value='';E('mbCa').placeholder=m.ca_set?'CA salvata · vuoto = mantieni':'nessuna CA salvata';E('mbClearCa').checked=false;E('mbSummary').textContent=(m.enabled?'ON':'OFF')+' · '+(m.url||'URL non impostato')+' · ogni '+m.interval_sec+' s';}
async function saveMbCompatible(){const q=new URLSearchParams();q.set('enabled',E('mbEnabled').checked?'1':'0');q.set('url',E('mbUrl').value.trim());q.set('interval_sec',E('mbInterval').value);q.set('timeout_ms',E('mbTimeout').value);q.set('source_priority',E('mbPriority').value);q.set('tls_mode',E('mbTls').value);if(E('mbCa').value.trim())q.set('ca_certificate',E('mbCa').value);if(E('mbClearCa').checked)q.set('clear_ca','1');const r=await fetch('/api/mbcompatible',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});if(!r.ok){alert('COMPATIBLE MB: '+await r.text());return}await loadMbCompatible();}
async function testMbCompatible(){const saveQ=new URLSearchParams();saveQ.set('enabled',E('mbEnabled').checked?'1':'0');saveQ.set('url',E('mbUrl').value.trim());saveQ.set('interval_sec',E('mbInterval').value);saveQ.set('timeout_ms',E('mbTimeout').value);saveQ.set('source_priority',E('mbPriority').value);saveQ.set('tls_mode',E('mbTls').value);if(E('mbCa').value.trim())saveQ.set('ca_certificate',E('mbCa').value);if(E('mbClearCa').checked)saveQ.set('clear_ca','1');let r=await fetch('/api/mbcompatible',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:saveQ.toString(),cache:'no-store'});if(!r.ok){alert('COMPATIBLE MB: salva prima una configurazione valida. '+await r.text());return}r=await fetch('/api/mbcompatible/test',{method:'POST',cache:'no-store'});if(!r.ok){alert('Test COMPATIBLE MB: '+await r.text());return}E('mbStatus').textContent='Stato: test accodato...';setTimeout(refreshMbCompatibleStatus,700);setTimeout(refreshMbCompatibleStatus,1800);setTimeout(refreshMbCompatibleStatus,3500);}
async function resetMbCompatible(){if(!confirm('Disabilitare COMPATIBLE MB e ripristinare i default?'))return;const r=await fetch('/api/mbcompatible/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset COMPATIBLE MB fallito');return}await loadMbCompatible();}

'''
    dash = dash.replace(anchor, js + anchor, 1)

# Refresh status only while the page is visible; never overwrite form fields.
if "mbcompatible-status-poll" not in dash:
    anchor = "</script>"
    poll = "\n// mbcompatible-status-poll\nsetInterval(()=>{if(mainTab==='config'&&E('cfgMbcompatible')&&E('cfgMbcompatible').classList.contains('active'))refreshMbCompatibleStatus();},5000);\n"
    if anchor not in dash:
        raise RuntimeError("MB-compatible: script-end anchor missing")
    dash = dash.replace(anchor, poll + anchor, 1)

write("web/dashboard.html", dash)
print("MB-compatible publisher: runtime, authenticated API, backup and Web UI enabled")
