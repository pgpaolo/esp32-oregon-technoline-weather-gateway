from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web_manager.cpp"
MAIN = ROOT / "src" / "main.cpp"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"anchor not found: {label}")
    return text.replace(old, new, 1)


web = WEB.read_text(encoding="utf-8")
if "AS3935_UI_INTEGRATED" in web:
    print("AS3935 UI already integrated")
    raise SystemExit(0)

web = replace_once(
    web,
    '#include "power_manager.h"\n',
    '#include "power_manager.h"\n#include "lightning_manager.h"\n',
    "lightning include",
)

# Backup/export: include the complete persistent AS3935 configuration.
web = replace_once(
    web,
    '    out += ",\\n  \\"display_contrast\\":" + String(d.contrast);\n    out += ",\\n  \\"rf_mode\\":" + String(static_cast<uint8_t>(getRfProtocolMode()));',
    '    out += ",\\n  \\"display_contrast\\":" + String(d.contrast);\n'
    '    const LightningConfig l = getLightningConfig();\n'
    '    out += ",\\n  \\"as3935_enabled\\":"; out += l.enabled ? "true" : "false";\n'
    '    out += ",\\n  \\"as3935_indoor\\":"; out += l.indoor ? "true" : "false";\n'
    '    out += ",\\n  \\"as3935_i2c_address\\":" + String(l.i2cAddress);\n'
    '    out += ",\\n  \\"as3935_irq_pin\\":" + String(static_cast<int>(l.irqPin));\n'
    '    out += ",\\n  \\"as3935_noise_floor\\":" + String(l.noiseFloor);\n'
    '    out += ",\\n  \\"as3935_watchdog_threshold\\":" + String(l.watchdogThreshold);\n'
    '    out += ",\\n  \\"as3935_spike_rejection\\":" + String(l.spikeRejection);\n'
    '    out += ",\\n  \\"as3935_min_strikes\\":" + String(l.minStrikes);\n'
    '    out += ",\\n  \\"as3935_mask_disturbers\\":"; out += l.maskDisturbers ? "true" : "false";\n'
    '    out += ",\\n  \\"as3935_tuning_cap\\":" + String(l.tuningCap);\n'
    '    out += ",\\n  \\"as3935_auto_tune\\":"; out += l.autoTune ? "true" : "false";\n'
    '    out += ",\\n  \\"rf_mode\\":" + String(static_cast<uint8_t>(getRfProtocolMode()));',
    "backup export lightning",
)

# Backup/import: parse and validate AS3935 values before any write.
web = replace_once(
    web,
    '    uint32_t rfMode = static_cast<uint8_t>(getRfProtocolMode());\n',
    '    LightningConfig lightningCfg = getLightningConfig();\n'
    '    if (jsonGetBool(body, "as3935_enabled", tmpBool)) lightningCfg.enabled = tmpBool;\n'
    '    if (jsonGetBool(body, "as3935_indoor", tmpBool)) lightningCfg.indoor = tmpBool;\n'
    '    if (jsonGetUInt(body, "as3935_i2c_address", tmpUInt)) lightningCfg.i2cAddress = static_cast<uint8_t>(tmpUInt);\n'
    '    if (jsonGetUInt(body, "as3935_irq_pin", tmpUInt)) {\n'
    '        if (tmpUInt > 127U) { server.send(400, "application/json", "{\\"ok\\":false,\\"error\\":\\"invalid AS3935 IRQ in backup\\"}"); return; }\n'
    '        lightningCfg.irqPin = static_cast<int8_t>(tmpUInt);\n'
    '    }\n'
    '    if (jsonGetUInt(body, "as3935_noise_floor", tmpUInt)) lightningCfg.noiseFloor = static_cast<uint8_t>(tmpUInt);\n'
    '    if (jsonGetUInt(body, "as3935_watchdog_threshold", tmpUInt)) lightningCfg.watchdogThreshold = static_cast<uint8_t>(tmpUInt);\n'
    '    if (jsonGetUInt(body, "as3935_spike_rejection", tmpUInt)) lightningCfg.spikeRejection = static_cast<uint8_t>(tmpUInt);\n'
    '    if (jsonGetUInt(body, "as3935_min_strikes", tmpUInt)) lightningCfg.minStrikes = static_cast<uint8_t>(tmpUInt);\n'
    '    if (jsonGetBool(body, "as3935_mask_disturbers", tmpBool)) lightningCfg.maskDisturbers = tmpBool;\n'
    '    if (jsonGetUInt(body, "as3935_tuning_cap", tmpUInt)) lightningCfg.tuningCap = static_cast<uint8_t>(tmpUInt);\n'
    '    if (jsonGetBool(body, "as3935_auto_tune", tmpBool)) lightningCfg.autoTune = tmpBool;\n'
    '    if (!validateLightningConfig(lightningCfg)) {\n'
    '        server.send(400, "application/json", "{\\"ok\\":false,\\"error\\":\\"invalid AS3935 backup values\\"}");\n'
    '        return;\n'
    '    }\n\n'
    '    uint32_t rfMode = static_cast<uint8_t>(getRfProtocolMode());\n',
    "backup import lightning parse",
)

web = replace_once(
    web,
    '    bool displayChanged = false;\n    if (!saveDisplayConfig(displayCfg, displayChanged)) {\n        server.send(500, "application/json", "{\\"ok\\":false,\\"error\\":\\"could not save display configuration\\"}");\n        return;\n    }\n\n    // Per rendere persistente il profilo Oregon',
    '    bool displayChanged = false;\n    if (!saveDisplayConfig(displayCfg, displayChanged)) {\n        server.send(500, "application/json", "{\\"ok\\":false,\\"error\\":\\"could not save display configuration\\"}");\n        return;\n    }\n    bool lightningChanged = false;\n    if (!saveLightningConfig(lightningCfg, lightningChanged)) {\n        server.send(500, "application/json", "{\\"ok\\":false,\\"error\\":\\"could not save AS3935 configuration\\"}");\n        return;\n    }\n\n    // Per rendere persistente il profilo Oregon',
    "backup import lightning save",
)

# AS3935 REST handlers on the existing port-80 WebServer.
handlers = r'''
// AS3935_UI_INTEGRATED: il rilevatore fulmini usa lo stesso WebServer della dashboard.
bool lightningBoolArg(const char *name) {
    if (!server.hasArg(name)) return false;
    const String v = server.arg(name);
    return v == "1" || v == "true" || v == "on" || v == "yes";
}

bool lightningUIntArg(const char *name, uint32_t &value) {
    if (!server.hasArg(name)) return false;
    const String raw = server.arg(name);
    if (!raw.length()) return false;
    char *end = nullptr;
    const unsigned long parsed = strtoul(raw.c_str(), &end, 0);
    if (!end || *end != '\0') return false;
    value = static_cast<uint32_t>(parsed);
    return true;
}

void handleLightningState() {
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", lightningStateJson());
}

void handleLightningConfigGet() {
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", lightningConfigJson());
}

void handleLightningConfigPost() {
    LightningConfig c = getLightningConfig();
    if (server.hasArg("enabled")) c.enabled = lightningBoolArg("enabled");
    if (server.hasArg("mode")) c.indoor = server.arg("mode") != "outdoor";
    if (server.hasArg("mask_disturbers")) c.maskDisturbers = lightningBoolArg("mask_disturbers");
    if (server.hasArg("auto_tune")) c.autoTune = lightningBoolArg("auto_tune");

    uint32_t v = 0;
    if (server.hasArg("i2c_address")) {
        if (!lightningUIntArg("i2c_address", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid i2c_address\"}"); return; }
        c.i2cAddress = static_cast<uint8_t>(v);
    }
    if (server.hasArg("irq_pin")) {
        if (!lightningUIntArg("irq_pin", v) || v > 127U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid irq_pin\"}"); return; }
        c.irqPin = static_cast<int8_t>(v);
    }
    if (server.hasArg("noise_floor")) {
        if (!lightningUIntArg("noise_floor", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid noise_floor\"}"); return; }
        c.noiseFloor = static_cast<uint8_t>(v);
    }
    if (server.hasArg("watchdog_threshold")) {
        if (!lightningUIntArg("watchdog_threshold", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid watchdog_threshold\"}"); return; }
        c.watchdogThreshold = static_cast<uint8_t>(v);
    }
    if (server.hasArg("spike_rejection")) {
        if (!lightningUIntArg("spike_rejection", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid spike_rejection\"}"); return; }
        c.spikeRejection = static_cast<uint8_t>(v);
    }
    if (server.hasArg("min_strikes")) {
        if (!lightningUIntArg("min_strikes", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid min_strikes\"}"); return; }
        c.minStrikes = static_cast<uint8_t>(v);
    }
    if (server.hasArg("tuning_cap")) {
        if (!lightningUIntArg("tuning_cap", v) || v > 255U) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid tuning_cap\"}"); return; }
        c.tuningCap = static_cast<uint8_t>(v);
    }

    if (!validateLightningConfig(c)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"configuration rejected\"}");
        return;
    }
    bool changed = false;
    if (!saveLightningConfig(c, changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"NVS save failed\"}");
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":";
    out += changed ? "true" : "false";
    out += ",\"state\":" + lightningStateJson() + "}";
    server.send(200, "application/json; charset=utf-8", out);
}

void handleLightningReset() {
    bool changed = false;
    if (!resetLightningConfigToDefaults(changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"reset failed\"}");
        return;
    }
    sendNoCache();
    String out = "{\"ok\":true,\"changed\":";
    out += changed ? "true" : "false";
    out += "}";
    server.send(200, "application/json", out);
}

void handleLightningReinit() {
    const bool ok = reinitializeLightning();
    sendNoCache();
    String out = "{\"ok\":";
    out += ok ? "true" : "false";
    out += ",\"state\":" + lightningStateJson() + "}";
    server.send(ok ? 200 : 503, "application/json", out);
}

'''
web = replace_once(web, "void handleBursts() {\n", handlers + "void handleBursts() {\n", "AS3935 handlers")

# CSS accents and responsive grid.
web = replace_once(web, '--bme:#f0b24a}', '--bme:#f0b24a;--lightning:#ffd166}', "CSS color")
web = replace_once(
    web,
    '.stationBme .panelHead{box-shadow:inset 3px 0 0 var(--bme)}',
    '.stationBme .panelHead{box-shadow:inset 3px 0 0 var(--bme)}.stationLightning .panelHead{box-shadow:inset 3px 0 0 var(--lightning)}',
    "CSS lightning panel",
)
web = replace_once(
    web,
    '.bmeGrid{grid-template-columns:repeat(2,minmax(0,1fr))}',
    '.bmeGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.lightningGrid{grid-template-columns:repeat(3,minmax(0,1fr))}',
    "CSS lightning grid",
)
web = replace_once(
    web,
    '.stationBme .cardTitle{border-top:2px solid #f0b24a40}',
    '.stationBme .cardTitle{border-top:2px solid #f0b24a40}.stationLightning .cardTitle{border-top:2px solid #ffd16640}',
    "CSS lightning cards",
)
web = replace_once(
    web,
    '@media(max-width:1220px){.weatherGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.bmeGrid{grid-template-columns:repeat(2,minmax(0,1fr))}',
    '@media(max-width:1220px){.weatherGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.bmeGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.lightningGrid{grid-template-columns:repeat(2,minmax(0,1fr))}',
    "CSS responsive tablet",
)
web = replace_once(
    web,
    '@media(max-width:760px){main{padding:9px}',
    '@media(max-width:760px){main{padding:9px}',
    "CSS mobile anchor",
)
web = replace_once(
    web,
    '.weatherGrid,.bmeGrid{grid-template-columns:1fr;padding:10px}',
    '.weatherGrid,.bmeGrid,.lightningGrid{grid-template-columns:1fr;padding:10px}',
    "CSS responsive mobile",
)

# Dashboard AS3935 panel, after BME280 and before HARDWARE.
lightning_panel = r'''</div></div>
<div class="panel stationLightning" id="lightningPanel"><div class="panelHead">Rilevatore fulmini · AS3935 <span id="lgBadge" class="badge off">rilevamento...</span></div><div class="weatherGrid lightningGrid">
<section class="card good" id="lgStatusCard"><div class="cardTitle">Stato sensore</div><div class="body">
<div class="row"><div class="name">Sensore</div><div class="value" id="lgDetected">--</div></div>
<div class="row"><div class="name">IRQ</div><div class="value" id="lgIrq">--</div></div>
<div class="row"><div class="name">Calibrazione</div><div class="value" id="lgCal">--</div></div>
<div class="row"><div class="name">Risonanza</div><div class="value" id="lgFreq">--</div></div>
</div><div class="foot">Sensore locale I²C · acquisizione indipendente dai decoder RF.</div></section>
<section class="card good"><div class="cardTitle">Eventi</div><div class="body">
<div class="row"><div class="name">Ultimo fulmine</div><div class="value" id="lgStrike">Nessuno</div></div>
<div class="row"><div class="name">Energia</div><div class="value" id="lgEnergy">--</div></div>
<div class="row"><div class="name">Ultimo evento</div><div class="value" id="lgLastType">none</div></div>
<div class="row"><div class="name">Fulmini / IRQ</div><div class="value"><span id="lgCount">0</span> / <span id="lgIrqTotal">0</span></div></div>
</div><div class="foot">Distanza = stima del fronte temporalesco, non triangolazione del singolo fulmine.</div></section>
<section class="card good"><div class="cardTitle">Ambiente / diagnostica</div><div class="body">
<div class="row"><div class="name">Noise</div><div class="value" id="lgNoise">0</div></div>
<div class="row"><div class="name">Disturber</div><div class="value" id="lgDist">0</div></div>
<div class="row"><div class="name">Modalità</div><div class="value" id="lgMode">--</div></div>
<div class="row"><div class="name">I²C / IRQ</div><div class="value" id="lgBus">--</div></div>
</div><div class="foot">MQTT: <code>…/as3935/state</code> + <code>…/as3935/event</code>.</div></section>
</div></div>
</section>
<section id="mainHardware"'''
web = replace_once(
    web,
    '</div></div>\n</section>\n<section id="mainHardware"',
    lightning_panel,
    "dashboard lightning panel",
)

# New AS3935 configuration tab.
web = replace_once(
    web,
    '<button id="tabDisplay" class="cfgTab" onclick="showCfgTab(\'display\')">DISPLAY</button><button id="tabBackup" class="cfgTab" onclick="showCfgTab(\'backup\')">BACKUP / RESTORE</button>',
    '<button id="tabDisplay" class="cfgTab" onclick="showCfgTab(\'display\')">DISPLAY</button><button id="tabLightning" class="cfgTab" onclick="showCfgTab(\'lightning\')">⚡ AS3935</button><button id="tabBackup" class="cfgTab" onclick="showCfgTab(\'backup\')">BACKUP / RESTORE</button>',
    "config lightning tab",
)

lightning_cfg = r'''<div id="cfgLightning" class="cfgPage">
<div class="cfgGrid">
<label class="checkLine"><input id="lgEnabled" type="checkbox"><span>Abilita AS3935</span></label>
<label><span>Modalità AFE</span><select id="lgModeCfg"><option value="indoor">Indoor</option><option value="outdoor">Outdoor</option></select></label>
<label><span>Indirizzo I²C</span><select id="lgAddr"><option value="1">0x01</option><option value="2">0x02</option><option value="3">0x03</option></select></label>
<label><span>GPIO IRQ</span><input id="lgIrqPin" type="number" min="0" max="48"></label>
<label><span>Noise floor (0-7)</span><input id="lgNoiseFloor" type="number" min="0" max="7"></label>
<label><span>Watchdog threshold (0-15)</span><input id="lgWatchdog" type="number" min="0" max="15"></label>
<label><span>Spike rejection (0-15)</span><input id="lgSpike" type="number" min="0" max="15"></label>
<label><span>Minimo fulmini</span><select id="lgMinStrikes"><option value="1">1</option><option value="5">5</option><option value="9">9</option><option value="16">16</option></select></label>
<label><span>Tuning capacitor fisso (0-15)</span><input id="lgTuneCap" type="number" min="0" max="15"></label>
<label class="checkLine"><input id="lgMaskDist" type="checkbox"><span>Maschera disturber</span></label>
<label class="checkLine"><input id="lgAutoTune" type="checkbox"><span>Auto-tuning antenna all'avvio</span></label>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveLightning()">Salva AS3935</button><button class="modeBtn" onclick="reinitLightning()">Rileva / reinizializza</button><button class="modeBtn dangerBtn" onclick="resetLightning()">Default firmware</button><span id="lightningSummary" class="muted"></span></div>
<div class="cfgNote">Il sensore condivide il bus I²C con OLED/BME280, ma la gestione IRQ e MQTT resta indipendente dalla ricezione Oregon/Technoline. I parametri sono persistenti in NVS e vengono inclusi nel backup generale.</div>
</div>
'''
web = replace_once(web, '<div id="cfgBackup" class="cfgPage">', lightning_cfg + '<div id="cfgBackup" class="cfgPage">', "config lightning page")
web = web.replace(
    '<b>Incluso:</b> hostname/IP, MQTT/TLS, campi MQTT, configurazione OLED (pagine, campi, intervallo, contrasto) e configurazione RF persistente.',
    '<b>Incluso:</b> hostname/IP, MQTT/TLS, campi MQTT, configurazione OLED, AS3935 e configurazione RF persistente.',
    1,
)

# JS configuration-tab navigation.
web = replace_once(
    web,
    "function showCfgTab(t){for(const x of ['net','mqtt','display','backup']){const on=t===x;E('cfg'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on);E('tab'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on)}if(t==='net')loadNetwork();else if(t==='mqtt')loadMqtt();else if(t==='display')loadDisplay();}",
    "function showCfgTab(t){for(const x of ['net','mqtt','display','lightning','backup']){const on=t===x;E('cfg'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on);E('tab'+x[0].toUpperCase()+x.slice(1)).classList.toggle('active',on)}if(t==='net')loadNetwork();else if(t==='mqtt')loadMqtt();else if(t==='display')loadDisplay();else if(t==='lightning')loadLightning();}",
    "JS config tabs",
)

lightning_js = r'''
function updateLightningUi(l){if(!l)return;const badge=E('lgBadge');if(badge){badge.className='badge '+(!l.enabled?'off':(l.detected&&l.irq_ok&&l.calibration_ok?'ok':'wait'));badge.textContent=!l.enabled?'AS3935 OFF':(!l.detected?'AS3935 NON RILEVATO':(l.irq_ok&&l.calibration_ok?'AS3935 OK':'AS3935 VERIFICA'));}const set=(id,v)=>{const e=E(id);if(e)e.textContent=v};set('lgDetected',l.detected?'RILEVATO':'NON RILEVATO');set('lgIrq',l.irq_ok?'OK':'KO');set('lgCal',l.calibration_ok?'OK':'VERIFICARE');set('lgFreq',l.resonance_hz?l.resonance_hz+' Hz':'--');set('lgStrike',l.last_lightning_ms?(l.distance_out_of_range?'>40 km':(l.last_distance_km==null?'N/D':l.last_distance_km+' km')):'Nessun fulmine');set('lgEnergy',l.last_lightning_ms?(l.last_energy||'--'):'--');set('lgLastType',l.last_type||'none');set('lgCount',l.lightning_total||0);set('lgIrqTotal',l.irq_total||0);set('lgNoise',l.noise_total||0);set('lgDist',l.disturber_total||0);set('lgMode',String(l.mode||'--').toUpperCase());set('lgBus','0x'+Number(l.i2c_address||0).toString(16).padStart(2,'0').toUpperCase()+' / GPIO'+l.irq_pin);const card=E('lgStatusCard');if(card){card.classList.remove('fresh','aging','stale','nodata');card.classList.add(l.detected&&l.irq_ok&&l.calibration_ok?'fresh':(l.enabled?'aging':'nodata'));}}
async function refreshLightning(){try{const l=await (await fetch('/api/as3935/state',{cache:'no-store'})).json();updateLightningUi(l);}catch(e){const badge=E('lgBadge');if(badge){badge.className='badge wait';badge.textContent='AS3935 UI ERR';}}}
async function loadLightning(){try{const c=await (await fetch('/api/as3935/config',{cache:'no-store'})).json();E('lgEnabled').checked=!!c.enabled;E('lgModeCfg').value=c.indoor?'indoor':'outdoor';E('lgAddr').value=String(c.i2c_address);E('lgIrqPin').value=c.irq_pin;E('lgNoiseFloor').value=c.noise_floor;E('lgWatchdog').value=c.watchdog_threshold;E('lgSpike').value=c.spike_rejection;E('lgMinStrikes').value=String(c.min_strikes);E('lgMaskDist').checked=!!c.mask_disturbers;E('lgAutoTune').checked=!!c.auto_tune;E('lgTuneCap').value=c.tuning_cap;const l=await (await fetch('/api/as3935/state',{cache:'no-store'})).json();updateLightningUi(l);E('lightningSummary').textContent=(l.detected?'RILEVATO':'NON RILEVATO')+' · IRQ '+(l.irq_ok?'OK':'KO')+' · CAL '+(l.calibration_ok?'OK':'VERIFICA')+(l.resonance_hz?' · '+l.resonance_hz+' Hz':'');}catch(e){E('lightningSummary').textContent='errore lettura AS3935';}}
async function saveLightning(){const q=new URLSearchParams();q.set('enabled',E('lgEnabled').checked?'1':'0');q.set('mode',E('lgModeCfg').value);q.set('i2c_address',E('lgAddr').value);q.set('irq_pin',E('lgIrqPin').value);q.set('noise_floor',E('lgNoiseFloor').value);q.set('watchdog_threshold',E('lgWatchdog').value);q.set('spike_rejection',E('lgSpike').value);q.set('min_strikes',E('lgMinStrikes').value);q.set('mask_disturbers',E('lgMaskDist').checked?'1':'0');q.set('auto_tune',E('lgAutoTune').checked?'1':'0');q.set('tuning_cap',E('lgTuneCap').value);const r=await fetch('/api/as3935/config',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});if(!r.ok){alert('AS3935: '+await r.text());return}await loadLightning();}
async function reinitLightning(){const r=await fetch('/api/as3935/reinit',{method:'POST',cache:'no-store'});const t=await r.text();if(!r.ok){alert('AS3935 reinizializzazione: '+t);return}await loadLightning();}
async function resetLightning(){if(!confirm('Ripristinare i default AS3935?'))return;const r=await fetch('/api/as3935/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset AS3935 fallito: '+await r.text());return}await loadLightning();}
'''
web = replace_once(web, 'async function powerOffDevice(){', lightning_js + '\nasync function powerOffDevice(){', "JS lightning functions")

web = replace_once(
    web,
    'bindDisplayFieldAutoPages();loadNetwork();loadMqtt();refresh();setInterval(refresh,2000);',
    'bindDisplayFieldAutoPages();loadNetwork();loadMqtt();refreshLightning();refresh();setInterval(refresh,2000);setInterval(refreshLightning,2000);',
    "JS lightning refresh",
)

# Port-80 routes.
web = replace_once(
    web,
    '    server.on("/api/display/reset", HTTP_POST, handleDisplayConfigReset);\n    server.on("/api/poweroff", HTTP_POST, handleDevicePowerOff);',
    '    server.on("/api/display/reset", HTTP_POST, handleDisplayConfigReset);\n'
    '    server.on("/api/as3935/state", HTTP_GET, handleLightningState);\n'
    '    server.on("/api/as3935/config", HTTP_GET, handleLightningConfigGet);\n'
    '    server.on("/api/as3935/config", HTTP_POST, handleLightningConfigPost);\n'
    '    server.on("/api/as3935/reset", HTTP_POST, handleLightningReset);\n'
    '    server.on("/api/as3935/reinit", HTTP_POST, handleLightningReinit);\n'
    '    server.on("/api/poweroff", HTTP_POST, handleDevicePowerOff);',
    "AS3935 routes",
)

WEB.write_text(web, encoding="utf-8", newline="\n")

main = MAIN.read_text(encoding="utf-8")
main = main.replace('#include "lightning_web.h"\n', '', 1)
main = main.replace('    initLightningWeb();\n', '', 1)
main = main.replace('    serviceLightningWeb();\n', '', 1)
MAIN.write_text(main, encoding="utf-8", newline="\n")

print("AS3935 integrated into the main port-80 UI")
