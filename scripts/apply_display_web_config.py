from pathlib import Path

p = Path('src/web_manager.cpp')
s = p.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str):
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one anchor, found {count}')
    s = s.replace(old, new, 1)

# 1) API GET/POST/reset per configurazione OLED.
anchor = '''void handleDisplayPower() {
    if (!server.hasArg("on")) {
        server.send(400, "application/json", "{\\\"ok\\\":false,\\\"error\\\":\\\"missing on\\\"}");
        return;
    }
    const String arg = server.arg("on");
    const bool enabled = arg == "1" || arg == "true" || arg == "on";
    setDisplayEnabled(enabled);
    sendNoCache();
    String out = String("{\\\"ok\\\":true,\\\"display_on\\\":") + (displayEnabled() ? "true" : "false") + "}";
    server.send(200, "application/json", out);
}
'''
replacement = anchor + r'''

void handleDisplayConfigGet() {
    const DisplayRuntimeConfig c = getDisplayConfig();
    String out;
    out.reserve(420);
    out = "{\"on\":"; out += displayEnabled() ? "true" : "false";
    out += ",\"page_mask\":" + String(c.pageMask);
    out += ",\"environment_fields\":" + String(c.environmentFields);
    out += ",\"wind_rain_fields\":" + String(c.windRainFields);
    out += ",\"technoline_fields\":" + String(c.technolineFields);
    out += ",\"pressure_fields\":" + String(c.pressureFields);
    out += ",\"status_fields\":" + String(c.statusFields);
    out += ",\"page_interval_sec\":" + String(c.pageIntervalSec);
    out += ",\"contrast\":" + String(c.contrast);
    out += ",\"current_page\":" + String(displayCurrentPage());
    out += "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleDisplayConfigPost() {
    DisplayRuntimeConfig c = getDisplayConfig();
    if (server.hasArg("page_mask")) c.pageMask = static_cast<uint8_t>(server.arg("page_mask").toInt());
    if (server.hasArg("environment_fields")) c.environmentFields = static_cast<uint8_t>(server.arg("environment_fields").toInt());
    if (server.hasArg("wind_rain_fields")) c.windRainFields = static_cast<uint8_t>(server.arg("wind_rain_fields").toInt());
    if (server.hasArg("technoline_fields")) c.technolineFields = static_cast<uint8_t>(server.arg("technoline_fields").toInt());
    if (server.hasArg("pressure_fields")) c.pressureFields = static_cast<uint8_t>(server.arg("pressure_fields").toInt());
    if (server.hasArg("status_fields")) c.statusFields = static_cast<uint8_t>(server.arg("status_fields").toInt());
    if (server.hasArg("page_interval_sec")) {
        const long v = server.arg("page_interval_sec").toInt();
        if (v < 2 || v > 60) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"page interval must be 2..60 seconds\"}"); return; }
        c.pageIntervalSec = static_cast<uint16_t>(v);
    }
    if (server.hasArg("contrast")) {
        const long v = server.arg("contrast").toInt();
        if (v < 8 || v > 255) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"contrast must be 8..255\"}"); return; }
        c.contrast = static_cast<uint8_t>(v);
    }
    if (!validateDisplayConfig(c)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid display configuration; enable at least one page\"}");
        return;
    }
    bool changed = false;
    if (!saveDisplayConfig(c, changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"display configuration rejected\"}");
        return;
    }
    if (server.hasArg("on")) {
        const String v = server.arg("on");
        setDisplayEnabled(v == "1" || v == "true" || v == "on");
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":"; out += changed ? "true" : "false";
    out += ",\"display_on\":"; out += displayEnabled() ? "true" : "false";
    out += "}";
    server.send(200, "application/json", out);
}

void handleDisplayConfigReset() {
    bool changed = false;
    if (!resetDisplayConfigToDefaults(changed)) {
        server.send(500, "application/json", "{\"ok\":false}");
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":"; out += changed ? "true" : "false"; out += "}";
    server.send(200, "application/json", out);
}
'''
replace_once(anchor, replacement, 'display API insertion')

# 2) Backup: aggiungi impostazioni display mantenendo schema 1 compatibile.
old = '''    out += ",\\n  \\\"display_on\\\":"; out += displayEnabled() ? "true" : "false";
    out += ",\\n  \\\"rf_mode\\\":" + String(static_cast<uint8_t>(getRfProtocolMode()));
'''
new = '''    out += ",\\n  \\\"display_on\\\":"; out += displayEnabled() ? "true" : "false";
    const DisplayRuntimeConfig d = getDisplayConfig();
    out += ",\\n  \\\"display_page_mask\\\":" + String(d.pageMask);
    out += ",\\n  \\\"display_environment_fields\\\":" + String(d.environmentFields);
    out += ",\\n  \\\"display_wind_rain_fields\\\":" + String(d.windRainFields);
    out += ",\\n  \\\"display_technoline_fields\\\":" + String(d.technolineFields);
    out += ",\\n  \\\"display_pressure_fields\\\":" + String(d.pressureFields);
    out += ",\\n  \\\"display_status_fields\\\":" + String(d.statusFields);
    out += ",\\n  \\\"display_page_interval_sec\\\":" + String(d.pageIntervalSec);
    out += ",\\n  \\\"display_contrast\\\":" + String(d.contrast);
    out += ",\\n  \\\"rf_mode\\\":" + String(static_cast<uint8_t>(getRfProtocolMode()));
'''
replace_once(old, new, 'backup export display fields')

old = '''    bool displayOn = displayEnabled();
    jsonGetBool(body, "display_on", displayOn);

    uint32_t rfMode = static_cast<uint8_t>(getRfProtocolMode());
'''
new = '''    bool displayOn = displayEnabled();
    jsonGetBool(body, "display_on", displayOn);
    DisplayRuntimeConfig displayCfg = getDisplayConfig();
    if (jsonGetUInt(body, "display_page_mask", tmpUInt)) displayCfg.pageMask = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_environment_fields", tmpUInt)) displayCfg.environmentFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_wind_rain_fields", tmpUInt)) displayCfg.windRainFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_technoline_fields", tmpUInt)) displayCfg.technolineFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_pressure_fields", tmpUInt)) displayCfg.pressureFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_status_fields", tmpUInt)) displayCfg.statusFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_page_interval_sec", tmpUInt)) displayCfg.pageIntervalSec = static_cast<uint16_t>(tmpUInt);
    if (jsonGetUInt(body, "display_contrast", tmpUInt)) displayCfg.contrast = static_cast<uint8_t>(tmpUInt);
    if (!validateDisplayConfig(displayCfg)) {
        server.send(400, "application/json", "{\\\"ok\\\":false,\\\"error\\\":\\\"invalid display backup values\\\"}");
        return;
    }

    uint32_t rfMode = static_cast<uint8_t>(getRfProtocolMode());
'''
replace_once(old, new, 'backup import parse display')

old = '''    setDisplayEnabled(displayOn);

    // Per rendere persistente il profilo Oregon anche se il backup proviene da
'''
new = '''    setDisplayEnabled(displayOn);
    bool displayChanged = false;
    if (!saveDisplayConfig(displayCfg, displayChanged)) {
        server.send(500, "application/json", "{\\\"ok\\\":false,\\\"error\\\":\\\"could not save display configuration\\\"}");
        return;
    }

    // Per rendere persistente il profilo Oregon anche se il backup proviene da
'''
replace_once(old, new, 'backup import save display')

# 3) Tab DISPLAY nella pagina configurazione.
old = '''<div class="panel cfgPanel"><div class="panelHead">Configurazione dispositivo <span class="muted">NVS solo su modifica</span></div><div class="cfgTabs"><button id="tabNet" class="cfgTab active" onclick="showCfgTab('net')">RETE / IP</button><button id="tabMqtt" class="cfgTab" onclick="showCfgTab('mqtt')">MQTT / TLS</button><button id="tabBackup" class="cfgTab" onclick="showCfgTab('backup')">BACKUP / RESTORE</button></div><div id="cfgNet" class="cfgPage active">
'''
new = '''<div class="panel cfgPanel"><div class="panelHead">Configurazione dispositivo <span class="muted">NVS solo su modifica</span></div><div class="cfgTabs"><button id="tabNet" class="cfgTab active" onclick="showCfgTab('net')">RETE / IP</button><button id="tabMqtt" class="cfgTab" onclick="showCfgTab('mqtt')">MQTT / TLS</button><button id="tabDisplay" class="cfgTab" onclick="showCfgTab('display')">DISPLAY</button><button id="tabBackup" class="cfgTab" onclick="showCfgTab('backup')">BACKUP / RESTORE</button></div><div id="cfgNet" class="cfgPage active">
'''
replace_once(old, new, 'display tab button')

marker = '''<div id="cfgBackup" class="cfgPage">
'''
display_html = r'''<div id="cfgDisplay" class="cfgPage">
<div class="cfgGrid">
<label class="checkLine"><input id="dispOn" type="checkbox"><span>OLED acceso</span></label>
<label><span>Cambio pagina (secondi)</span><input id="dispInterval" type="number" min="2" max="60" value="7"></label>
<label><span>Contrasto OLED (8-255)</span><input id="dispContrast" type="number" min="8" max="255" value="255"></label>
</div>
<div class="cfgActions"><b>Pagine da mostrare</b><button class="modeBtn" onclick="displaySelectPages(true)">Tutte</button><button class="modeBtn" onclick="displaySelectPages(false)">Nessuna</button></div>
<div class="fieldGrid">
<div class="fieldGroup"><b>Pagine OLED</b>
<label class="fieldCheck"><input data-dpagebit="0" type="checkbox">Esterno</label><label class="fieldCheck"><input data-dpagebit="1" type="checkbox">Vento / Pioggia</label><label class="fieldCheck"><input data-dpagebit="2" type="checkbox">Technoline</label><label class="fieldCheck"><input data-dpagebit="3" type="checkbox">Barometro</label><label class="fieldCheck"><input data-dpagebit="4" type="checkbox">RF / Status</label>
</div>
<div class="fieldGroup"><b>Esterno</b>
<label class="fieldCheck"><input data-denvbit="0" type="checkbox">Temperatura + umidita</label><label class="fieldCheck"><input data-denvbit="1" type="checkbox">Punto di rugiada</label><label class="fieldCheck"><input data-denvbit="2" type="checkbox">Heat index + UV</label><label class="fieldCheck"><input data-denvbit="3" type="checkbox">Stato batterie</label>
</div>
<div class="fieldGroup"><b>Vento / Pioggia</b>
<label class="fieldCheck"><input data-dwindbit="0" type="checkbox">Vento + raffica</label><label class="fieldCheck"><input data-dwindbit="1" type="checkbox">Direzione</label><label class="fieldCheck"><input data-dwindbit="2" type="checkbox">Pioggia</label><label class="fieldCheck"><input data-dwindbit="3" type="checkbox">Stato batterie</label>
</div>
<div class="fieldGroup"><b>Technoline</b>
<label class="fieldCheck"><input data-dtechbit="0" type="checkbox">Temperatura + umidita</label><label class="fieldCheck"><input data-dtechbit="1" type="checkbox">Vento + Gust</label><label class="fieldCheck"><input data-dtechbit="2" type="checkbox">Direzione</label><label class="fieldCheck"><input data-dtechbit="3" type="checkbox">Pioggia</label><label class="fieldCheck"><input data-dtechbit="4" type="checkbox">ID + pacchetti</label>
</div>
<div class="fieldGroup"><b>Barometro</b>
<label class="fieldCheck"><input data-dpressbit="0" type="checkbox">Pressione stazione</label><label class="fieldCheck"><input data-dpressbit="1" type="checkbox">Altimetro</label><label class="fieldCheck"><input data-dpressbit="2" type="checkbox">Trend 3 h</label><label class="fieldCheck"><input data-dpressbit="3" type="checkbox">Previsione</label>
</div>
<div class="fieldGroup"><b>RF / Status</b>
<label class="fieldCheck"><input data-dstatusbit="0" type="checkbox">Conteggi Oregon</label><label class="fieldCheck"><input data-dstatusbit="1" type="checkbox">Decoder / WGR scan</label><label class="fieldCheck"><input data-dstatusbit="2" type="checkbox">Timing / run</label><label class="fieldCheck"><input data-dstatusbit="3" type="checkbox">Statistiche Technoline</label><label class="fieldCheck"><input data-dstatusbit="4" type="checkbox">IP / rete</label>
</div>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveDisplayConfig()">Salva DISPLAY</button><button class="modeBtn" onclick="resetDisplayConfig()">Default firmware</button><span id="displaySummary" class="muted"></span></div>
<div class="cfgNote">Le pagine disabilitate vengono saltate automaticamente. Intervallo e campi sono persistenti in NVS e vengono scritti solo quando cambiano. Se il Gust Technoline non e' stato ricevuto il display mostra <code>G --</code>, mai uno zero artificiale.</div>
</div>
'''
replace_once(marker, display_html + marker, 'display config HTML')

old = '''<div class="cfgNote"><b>Incluso:</b> hostname/IP, MQTT/TLS, campi MQTT, stato OLED e configurazione RF persistente. <b>Non incluso:</b> SSID/password Wi-Fi, che in questa versione restano nel firmware/config_private.h. Per sicurezza la password MQTT e' esclusa salvo selezione esplicita. L'import valida il file e riavvia il gateway.</div>
'''
new = '''<div class="cfgNote"><b>Incluso:</b> hostname/IP, MQTT/TLS, campi MQTT, configurazione OLED (pagine, campi, intervallo, contrasto) e configurazione RF persistente. <b>Non incluso:</b> SSID/password Wi-Fi, che in questa versione restano nel firmware/config_private.h. Per sicurezza la password MQTT e' esclusa salvo selezione esplicita. L'import valida il file e riavvia il gateway.</div>
'''
replace_once(old, new, 'backup note')

# 4) JS tab + funzioni DISPLAY.
old = "function showCfgTab(t){for(const x of ['net','mqtt','backup']){const on=t===x;E('cfg'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on);E('tab'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on)}if(t==='net')loadNetwork();else if(t==='mqtt')loadMqtt();}"
new = "function showCfgTab(t){for(const x of ['net','mqtt','display','backup']){const on=t===x;E('cfg'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on);E('tab'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on)}if(t==='net')loadNetwork();else if(t==='mqtt')loadMqtt();else if(t==='display')loadDisplay();}"
replace_once(old, new, 'showCfgTab JS')

anchor = '''async function resetMqtt(){if(!confirm('Ripristinare i valori MQTT compilati nel firmware?'))return;const r=await fetch('/api/mqtt/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset MQTT fallito');return}await loadMqtt();}'''
js = r'''
function dSet(attr,mask){const m=Number(mask)>>>0;document.querySelectorAll('['+attr+']').forEach(x=>x.checked=(m&(1<<Number(x.getAttribute(attr))))!==0)}
function dGet(attr){let m=0;document.querySelectorAll('['+attr+']').forEach(x=>{if(x.checked)m|=(1<<Number(x.getAttribute(attr)))});return m>>>0}
function displaySelectPages(v){document.querySelectorAll('[data-dpagebit]').forEach(x=>x.checked=!!v)}
async function loadDisplay(){try{const d=await (await fetch('/api/display/config',{cache:'no-store'})).json();E('dispOn').checked=!!d.on;E('dispInterval').value=d.page_interval_sec||7;E('dispContrast').value=d.contrast||255;dSet('data-dpagebit',d.page_mask==null?31:d.page_mask);dSet('data-denvbit',d.environment_fields==null?15:d.environment_fields);dSet('data-dwindbit',d.wind_rain_fields==null?15:d.wind_rain_fields);dSet('data-dtechbit',d.technoline_fields==null?31:d.technoline_fields);dSet('data-dpressbit',d.pressure_fields==null?15:d.pressure_fields);dSet('data-dstatusbit',d.status_fields==null?31:d.status_fields);E('displaySummary').textContent=(d.on?'OLED ON':'OLED OFF')+' · pagina '+(Number(d.current_page)+1)+' · cambio '+d.page_interval_sec+' s · contrasto '+d.contrast;}catch(e){E('displaySummary').textContent='errore lettura display'}}
async function saveDisplayConfig(){const pageMask=dGet('data-dpagebit');if(!pageMask){alert('Seleziona almeno una pagina OLED.');return}const q=new URLSearchParams();q.set('on',E('dispOn').checked?'1':'0');q.set('page_mask',String(pageMask));q.set('environment_fields',String(dGet('data-denvbit')));q.set('wind_rain_fields',String(dGet('data-dwindbit')));q.set('technoline_fields',String(dGet('data-dtechbit')));q.set('pressure_fields',String(dGet('data-dpressbit')));q.set('status_fields',String(dGet('data-dstatusbit')));q.set('page_interval_sec',E('dispInterval').value);q.set('contrast',E('dispContrast').value);const r=await fetch('/api/display/config',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});if(!r.ok){alert('DISPLAY: '+await r.text());return}const j=await r.json();displayOn=!!j.display_on;updateDisplayUi();await loadDisplay();}
async function resetDisplayConfig(){if(!confirm('Ripristinare pagine/campi/intervallo/contrasto OLED ai default firmware?'))return;const r=await fetch('/api/display/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset DISPLAY fallito');return}await loadDisplay();}
'''
replace_once(anchor, anchor + js, 'display JS functions')

# Allinea checkbox del tab Display quando si usa il pulsante OLED in testata.
old = "function updateDisplayUi(){const btn=E('displayBtn'),st=E('sysDisplay');if(btn){btn.textContent=displayOn?'OLED ON':'OLED OFF';btn.classList.toggle('active',!displayOn);btn.title=displayOn?'Clic per spegnere il display OLED':'Clic per riaccendere il display OLED';}if(st){st.textContent=displayOn?'ON':'POWER SAVE';st.className='value '+(displayOn?'ok':'muted');}}"
new = "function updateDisplayUi(){const btn=E('displayBtn'),st=E('sysDisplay'),cfg=E('dispOn');if(btn){btn.textContent=displayOn?'OLED ON':'OLED OFF';btn.classList.toggle('active',!displayOn);btn.title=displayOn?'Clic per spegnere il display OLED':'Clic per riaccendere il display OLED';}if(st){st.textContent=displayOn?'ON':'POWER SAVE';st.className='value '+(displayOn?'ok':'muted');}if(cfg)cfg.checked=displayOn;}"
replace_once(old, new, 'updateDisplayUi JS')

# 5) Route HTTP.
old = '''    server.on("/api/display", HTTP_POST, handleDisplayPower);
    server.on("/api/restart", HTTP_POST, handleDeviceRestart);
'''
new = '''    server.on("/api/display", HTTP_POST, handleDisplayPower);
    server.on("/api/display/config", HTTP_GET, handleDisplayConfigGet);
    server.on("/api/display/config", HTTP_POST, handleDisplayConfigPost);
    server.on("/api/display/reset", HTTP_POST, handleDisplayConfigReset);
    server.on("/api/restart", HTTP_POST, handleDeviceRestart);
'''
replace_once(old, new, 'display routes')

p.write_text(s, encoding='utf-8')
print('web_manager.cpp patched successfully')
