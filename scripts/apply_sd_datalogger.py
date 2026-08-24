Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def patch_once(path, old, new, label):
    p = root / path
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"SD datalogger patch anchor missing: {label} in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"SD datalogger: patched {path} ({label})")


# ---- main.cpp: init, enqueue only, deferred SD service ----
patch_once(
    "src/main.cpp",
    '#include "thermo_channel_manager.h"\n',
    '#include "thermo_channel_manager.h"\n#include "sd_logger.h"\n',
    "main include",
)
patch_once(
    "src/main.cpp",
    '    initThermoChannels();\n    Serial.println(F("[BOOT] thermo multichannel initialized"));\n',
    '    initThermoChannels();\n    Serial.println(F("[BOOT] thermo multichannel initialized"));\n    initSdLogger();\n',
    "SD init after RF",
)
patch_once(
    "src/main.cpp",
    '            publishWeatherReading(mqttClient, reading, packet);\n            digitalWrite(BOARD_LED_PIN, BOARD_LED_ON);',
    '            publishWeatherReading(mqttClient, reading, packet);\n            enqueueSdOregon(reading, packet);\n            digitalWrite(BOARD_LED_PIN, BOARD_LED_ON);',
    "Oregon enqueue",
)
patch_once(
    "src/main.cpp",
    '            publishLaCrosseReading(mqttClient, lcReading, lcPacket);\n            digitalWrite(BOARD_LED_PIN, BOARD_LED_ON);',
    '            publishLaCrosseReading(mqttClient, lcReading, lcPacket);\n            enqueueSdTechnoline(lcReading, lcPacket);\n            digitalWrite(BOARD_LED_PIN, BOARD_LED_ON);',
    "Technoline enqueue",
)
patch_once(
    "src/main.cpp",
    '    serviceBarometer(station);\n',
    '    serviceBarometer(station);\n    serviceSdLogger(station);\n    // Una scrittura SD puo richiedere alcuni ms: svuota subito il ring RF.\n    serviceOregonReceiver();\n',
    "deferred SD service",
)


# ---- power_manager.cpp: flush/unmount before sleeping ----
patch_once(
    "src/power_manager.cpp",
    '#include "lightning_manager.h"\n',
    '#include "lightning_manager.h"\n#include "sd_logger.h"\n',
    "power include",
)
patch_once(
    "src/power_manager.cpp",
    '    prepareLightningForDeepSleep();\n    const bool radioOk = prepareRadioForDeepSleep();',
    '    prepareLightningForDeepSleep();\n    prepareSdLoggerForDeepSleep();\n    const bool radioOk = prepareRadioForDeepSleep();',
    "SD shutdown",
)


# ---- web_manager.cpp: state + config/remount endpoints ----
patch_once(
    "src/web_manager.cpp",
    '#include "web_ui_generated.h"\n',
    '#include "web_ui_generated.h"\n#include "sd_logger.h"\n',
    "web include",
)
patch_once(
    "src/web_manager.cpp",
    '    const uint32_t heapSize = ESP.getHeapSize();\n',
    '    out += ",\\\"sd\\\":" + sdLoggerStatusJson();\n\n    const uint32_t heapSize = ESP.getHeapSize();\n',
    "state SD object",
)

sd_handlers = r'''void handleSdConfigGet() {
    String out = "{\"config\":" + sdLoggerConfigJson() + ",\"status\":" + sdLoggerStatusJson() + "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

bool sdBoolArg(const char *name, bool fallback) {
    if (!server.hasArg(name)) return fallback;
    const String v = server.arg(name);
    return v == "1" || v == "true" || v == "on" || v == "yes";
}

void handleSdConfigPost() {
    SdLoggerConfig c = getSdLoggerConfig();
    c.enabled = sdBoolArg("enabled", c.enabled);
    c.logOregon = sdBoolArg("oregon", c.logOregon);
    c.logTechnoline = sdBoolArg("technoline", c.logTechnoline);
    c.logBme280 = sdBoolArg("bme280", c.logBme280);
    c.logAs3935 = sdBoolArg("as3935", c.logAs3935);
    if (server.hasArg("snapshot_interval_s")) {
        const long v = server.arg("snapshot_interval_s").toInt();
        if (v < 30 || v > 3600) {
            server.send(400, "application/json", "{\"ok\":false,\"error\":\"snapshot interval must be 30..3600 seconds\"}");
            return;
        }
        c.snapshotIntervalSec = static_cast<uint16_t>(v);
    }
    bool changed = false;
    if (!saveSdLoggerConfig(c, changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"SD logger configuration rejected\"}");
        return;
    }
    String out = "{\"ok\":true,\"changed\":";
    out += changed ? "true" : "false";
    out += ",\"config\":" + sdLoggerConfigJson() + ",\"status\":" + sdLoggerStatusJson() + "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleSdConfigReset() {
    bool changed = false;
    if (!resetSdLoggerConfigToDefaults(changed)) {
        server.send(500, "application/json", "{\"ok\":false}");
        return;
    }
    handleSdConfigGet();
}

void handleSdRemount() {
    const bool ok = remountSdLogger();
    String out = "{\"ok\":";
    out += ok ? "true" : "false";
    out += ",\"status\":" + sdLoggerStatusJson() + "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

'''
patch_once(
    "src/web_manager.cpp",
    'void handleThermoConfigGet() {\n',
    sd_handlers + 'void handleThermoConfigGet() {\n',
    "SD handlers",
)
patch_once(
    "src/web_manager.cpp",
    '    server.on("/api/network/reset", HTTP_POST, handleNetworkConfigReset);\n',
    '    server.on("/api/network/reset", HTTP_POST, handleNetworkConfigReset);\n'
    '    server.on("/api/sd", HTTP_GET, handleSdConfigGet);\n'
    '    server.on("/api/sd", HTTP_POST, handleSdConfigPost);\n'
    '    server.on("/api/sd/reset", HTTP_POST, handleSdConfigReset);\n'
    '    server.on("/api/sd/remount", HTTP_POST, handleSdRemount);\n',
    "SD routes",
)


# ---- Dashboard: dedicated SD configuration/status tab ----
patch_once(
    "web/dashboard.html",
    '<button id="tabDisplay" class="cfgTab" onclick="showCfgTab(\'display\')">DISPLAY</button><button id="tabLightning"',
    '<button id="tabDisplay" class="cfgTab" onclick="showCfgTab(\'display\')">DISPLAY</button><button id="tabSd" class="cfgTab" onclick="showCfgTab(\'sd\')">MICROSD</button><button id="tabLightning"',
    "SD tab",
)

sd_page = '''<div id="cfgSd" class="cfgPage">
<div class="resourceHeroGrid">
<section class="resourceHero"><div class="heroLabel">microSD</div><div class="heroValue" id="sdMountState">--</div><div class="heroState" id="sdCardSize">--</div></section>
<section class="resourceHero"><div class="heroLabel">Archivio corrente</div><div class="heroValue" style="font-size:1rem" id="sdFile">--</div><div class="heroState" id="sdTimeState">--</div></section>
<section class="resourceHero"><div class="heroLabel">Scritture</div><div class="heroValue" id="sdWritten">--</div><div class="heroState" id="sdQueue">--</div></section>
</div>
<div class="cfgGrid">
<label class="checkLine"><input id="sdEnabled" type="checkbox"><span>Abilita datalogger microSD</span></label>
<label><span>Snapshot BME280 / AS3935 (secondi)</span><input id="sdSnapshot" type="number" min="30" max="3600" value="300"></label>
<label class="checkLine"><input id="sdOregon" type="checkbox"><span>Registra ogni frame Oregon valido</span></label>
<label class="checkLine"><input id="sdTechnoline" type="checkbox"><span>Registra ogni frame Technoline valido</span></label>
<label class="checkLine"><input id="sdBme" type="checkbox"><span>Registra snapshot BME280</span></label>
<label class="checkLine"><input id="sdAs3935" type="checkbox"><span>Registra snapshot AS3935</span></label>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveSd()">Salva microSD</button><button class="modeBtn" onclick="remountSd()">Rimonta scheda</button><button class="modeBtn" onclick="resetSd()">Default firmware</button><span id="sdSummary" class="muted"></span></div>
<div class="cfgNote">CSV giornalieri UTC in <code>/weather/YYYY/MM/YYYY-MM-DD.csv</code>. Prima della sincronizzazione NTP usa <code>/weather/unsynced.csv</code>. La scrittura e differita: il decoder RF non scrive mai direttamente sulla SD.</div>
</div>
'''
patch_once(
    "web/dashboard.html",
    '<div id="cfgLightning" class="cfgPage">\n',
    sd_page + '<div id="cfgLightning" class="cfgPage">\n',
    "SD page",
)
patch_once(
    "web/dashboard.html",
    "for(const x of ['net','thermo','mqtt','display','lightning','backup'])",
    "for(const x of ['net','thermo','mqtt','display','sd','lightning','backup'])",
    "SD cfg loop",
)
patch_once(
    "web/dashboard.html",
    "else if(t==='display')loadDisplay();else if(t==='lightning')loadLightning();",
    "else if(t==='display')loadDisplay();else if(t==='sd')loadSd();else if(t==='lightning')loadLightning();",
    "SD tab loader",
)

sd_js = r'''
function sdBytes(v){v=Number(v||0);if(v<=0)return '--';const u=['B','KB','MB','GB','TB'];let i=0;while(v>=1024&&i<u.length-1){v/=1024;i++}return v.toFixed(i<2?0:1)+' '+u[i]}
async function loadSd(){try{const j=await (await fetch('/api/sd',{cache:'no-store'})).json(),c=j.config||{},s=j.status||{};E('sdEnabled').checked=!!c.enabled;E('sdOregon').checked=!!c.oregon;E('sdTechnoline').checked=!!c.technoline;E('sdBme').checked=!!c.bme280;E('sdAs3935').checked=!!c.as3935;E('sdSnapshot').value=c.snapshot_interval_s||300;E('sdMountState').textContent=s.mounted?'MONTATA':(s.supported?'NON MONTATA':'N/D');E('sdMountState').className='heroValue '+(s.mounted?'ok':'bad');E('sdCardSize').textContent=s.mounted?(sdBytes(s.card_size)+' · usati '+sdBytes(s.used_bytes)):'scheda assente o mount fallito';E('sdFile').textContent=s.file||'--';E('sdTimeState').textContent=s.time_synced?'UTC/NTP sincronizzato':'ora non sincronizzata';E('sdWritten').textContent=String(s.written||0);E('sdQueue').textContent='coda '+(s.queue_depth||0)+' · drop '+(s.dropped||0)+' · errori '+(s.write_errors||0);E('sdSummary').textContent=(c.enabled?'logger ON':'logger OFF')+' · mount tentativi '+(s.mount_attempts||0);}catch(e){E('sdSummary').textContent='errore lettura microSD'}}
async function saveSd(){const q=new URLSearchParams();q.set('enabled',E('sdEnabled').checked?'1':'0');q.set('oregon',E('sdOregon').checked?'1':'0');q.set('technoline',E('sdTechnoline').checked?'1':'0');q.set('bme280',E('sdBme').checked?'1':'0');q.set('as3935',E('sdAs3935').checked?'1':'0');q.set('snapshot_interval_s',E('sdSnapshot').value);const r=await fetch('/api/sd',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});if(!r.ok){alert('microSD: '+await r.text());return}await loadSd();}
async function remountSd(){const r=await fetch('/api/sd/remount',{method:'POST',cache:'no-store'});if(!r.ok){alert('Rimonta microSD fallita');return}await loadSd();}
async function resetSd(){if(!confirm('Ripristinare la configurazione microSD ai default firmware?'))return;const r=await fetch('/api/sd/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset microSD fallito');return}await loadSd();}
'''
patch_once(
    "web/dashboard.html",
    'function dSet(attr,mask){',
    sd_js + '\nfunction dSet(attr,mask){',
    "SD javascript",
)
