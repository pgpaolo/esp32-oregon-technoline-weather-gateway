#include "lightning_web.h"

#include <Arduino.h>
#include <WebServer.h>

#include "config.h"
#include "lightning_manager.h"

namespace {

constexpr uint16_t LIGHTNING_WEB_PORT = 81;
WebServer server(LIGHTNING_WEB_PORT);
bool started = false;

void noCache() {
    server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    server.sendHeader("Pragma", "no-cache");
}

bool boolArg(const char *name) {
    if (!server.hasArg(name)) return false;
    const String v = server.arg(name);
    return v == "1" || v == "true" || v == "on" || v == "yes";
}

bool parseUIntArg(const char *name, uint32_t &value) {
    if (!server.hasArg(name)) return false;
    const String raw = server.arg(name);
    if (!raw.length()) return false;
    char *end = nullptr;
    const unsigned long parsed = strtoul(raw.c_str(), &end, 0);
    if (!end || *end != '\0') return false;
    value = static_cast<uint32_t>(parsed);
    return true;
}

void handleState() {
    noCache();
    server.send(200, "application/json; charset=utf-8", lightningStateJson());
}

void handleConfigGet() {
    noCache();
    server.send(200, "application/json; charset=utf-8", lightningConfigJson());
}

void handleConfigSave() {
    LightningConfig c = getLightningConfig();
    c.enabled = boolArg("enabled");
    c.indoor = server.hasArg("mode") ? server.arg("mode") != "outdoor" : c.indoor;
    c.maskDisturbers = boolArg("mask_disturbers");
    c.autoTune = boolArg("auto_tune");

    uint32_t v = 0;
    if (!parseUIntArg("i2c_address", v) || v > 255U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid i2c_address\"}");
        return;
    }
    c.i2cAddress = static_cast<uint8_t>(v);
    if (!parseUIntArg("irq_pin", v) || v > 127U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid irq_pin\"}");
        return;
    }
    c.irqPin = static_cast<int8_t>(v);
    if (!parseUIntArg("noise_floor", v) || v > 255U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid noise_floor\"}");
        return;
    }
    c.noiseFloor = static_cast<uint8_t>(v);
    if (!parseUIntArg("watchdog_threshold", v) || v > 255U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid watchdog_threshold\"}");
        return;
    }
    c.watchdogThreshold = static_cast<uint8_t>(v);
    if (!parseUIntArg("spike_rejection", v) || v > 255U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid spike_rejection\"}");
        return;
    }
    c.spikeRejection = static_cast<uint8_t>(v);
    if (!parseUIntArg("min_strikes", v) || v > 255U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid min_strikes\"}");
        return;
    }
    c.minStrikes = static_cast<uint8_t>(v);
    if (!parseUIntArg("tuning_cap", v) || v > 255U) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid tuning_cap\"}");
        return;
    }
    c.tuningCap = static_cast<uint8_t>(v);

    if (!validateLightningConfig(c)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"configuration rejected\"}");
        return;
    }

    bool changed = false;
    if (!saveLightningConfig(c, changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"NVS save failed\"}");
        return;
    }

    noCache();
    String out = "{\"ok\":true,\"changed\":";
    out += changed ? "true" : "false";
    out += ",\"state\":" + lightningStateJson() + "}";
    server.send(200, "application/json; charset=utf-8", out);
}

void handleReset() {
    bool changed = false;
    if (!resetLightningConfigToDefaults(changed)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"reset failed\"}");
        return;
    }
    noCache();
    String out = "{\"ok\":true,\"changed\":";
    out += changed ? "true" : "false";
    out += "}";
    server.send(200, "application/json", out);
}

void handleReinit() {
    const bool ok = reinitializeLightning();
    noCache();
    String out = "{\"ok\":";
    out += ok ? "true" : "false";
    out += ",\"state\":" + lightningStateJson() + "}";
    server.send(ok ? 200 : 503, "application/json", out);
}

const char PAGE[] PROGMEM = R"HTML(
<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AS3935 Lightning</title>
<style>
:root{color-scheme:dark light;font-family:system-ui,-apple-system,Segoe UI,sans-serif}body{margin:0;background:#111827;color:#e5e7eb}.wrap{max-width:980px;margin:auto;padding:22px}.top{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}h1{margin:0;font-size:1.55rem}.tag{padding:5px 9px;border-radius:999px;background:#1f2937}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:18px}.card{background:#1f2937;border:1px solid #374151;border-radius:14px;padding:16px;box-shadow:0 8px 25px #0003}.kv{display:grid;grid-template-columns:1fr auto;gap:8px 14px}.v{font-weight:700}.ok{color:#34d399}.bad{color:#f87171}.warn{color:#fbbf24}label{display:block;margin:10px 0 4px}input,select{width:100%;box-sizing:border-box;padding:9px;border-radius:8px;border:1px solid #4b5563;background:#111827;color:#e5e7eb}.check{display:flex;gap:8px;align-items:center}.check input{width:auto}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}button{padding:9px 13px;border:0;border-radius:8px;cursor:pointer;font-weight:650}.primary{background:#2563eb;color:white}.secondary{background:#4b5563;color:white}.danger{background:#991b1b;color:white}.note{font-size:.9rem;color:#9ca3af;line-height:1.4}.msg{min-height:1.3em;margin-top:10px}.strike{font-size:1.8rem;font-weight:800}.link{color:#93c5fd;cursor:pointer;text-decoration:underline}@media(prefers-color-scheme:light){body{background:#f3f4f6;color:#111827}.card{background:white;border-color:#d1d5db}.tag{background:#e5e7eb}input,select{background:white;color:#111827;border-color:#d1d5db}.note{color:#6b7280}}
</style></head><body><div class="wrap">
<div class="top"><div><h1>⚡ AS3935 Lightning Detector</h1><div class="note">Branch sperimentale · interfaccia isolata dalla dashboard Oregon/Technoline</div></div><div><span class="tag" id="statusTag">lettura...</span> · <span class="link" onclick="location.href='http://'+location.hostname+'/'">dashboard meteo</span></div></div>
<div class="grid">
<section class="card"><h2>Stato</h2><div class="kv">
<span>Sensore</span><span class="v" id="detected">-</span><span>IRQ</span><span class="v" id="irq">-</span><span>Calibrazione</span><span class="v" id="cal">-</span><span>Risonanza</span><span class="v" id="freq">-</span><span>Modalità</span><span class="v" id="mode">-</span><span>I²C / IRQ</span><span class="v" id="bus">-</span></div>
<div class="actions"><button class="secondary" onclick="reinitSensor()">Rileva / reinizializza</button></div></section>
<section class="card"><h2>Eventi</h2><div class="strike" id="lastStrike">Nessun fulmine</div><div class="kv" style="margin-top:12px"><span>Energia</span><span class="v" id="energy">-</span><span>Ultimo evento</span><span class="v" id="lastType">-</span><span>IRQ totali</span><span class="v" id="irqTotal">0</span><span>Noise</span><span class="v" id="noise">0</span><span>Disturber</span><span class="v" id="dist">0</span><span>Fulmini</span><span class="v" id="strikes">0</span></div></section>
<section class="card"><h2>Configurazione</h2><form id="cfgForm">
<div class="check"><input id="enabled" name="enabled" type="checkbox"><label for="enabled">Abilita AS3935</label></div>
<label>Modalità AFE</label><select id="modeCfg" name="mode"><option value="indoor">Indoor</option><option value="outdoor">Outdoor</option></select>
<label>Indirizzo I²C</label><select id="addr" name="i2c_address"><option value="1">0x01</option><option value="2">0x02</option><option value="3">0x03</option></select>
<label>GPIO IRQ</label><input id="irqPin" name="irq_pin" type="number" min="0" max="48">
<label>Noise floor (0-7)</label><input id="noiseFloor" name="noise_floor" type="number" min="0" max="7">
<label>Watchdog threshold (0-15)</label><input id="watchdog" name="watchdog_threshold" type="number" min="0" max="15">
<label>Spike rejection (0-15)</label><input id="spike" name="spike_rejection" type="number" min="0" max="15">
<label>Minimo fulmini</label><select id="minStrikes" name="min_strikes"><option>1</option><option>5</option><option>9</option><option>16</option></select>
<div class="check"><input id="maskDist" name="mask_disturbers" type="checkbox"><label for="maskDist">Maschera disturber</label></div>
<div class="check"><input id="autoTune" name="auto_tune" type="checkbox"><label for="autoTune">Auto-tuning antenna all'avvio</label></div>
<label>Tuning capacitor fisso (0-15)</label><input id="tuneCap" name="tuning_cap" type="number" min="0" max="15">
<div class="actions"><button class="primary" type="submit">Salva e applica</button><button class="danger" type="button" onclick="resetCfg()">Default</button></div><div class="msg" id="msg"></div></form></section>
<section class="card"><h2>MQTT</h2><p class="note">La configurazione broker/TLS resta quella già usata dal gateway. Questo modulo aggiunge soltanto due topic, senza modificare Oregon o Technoline.</p><div class="kv"><span>Stato retained</span><span class="v"><code>…/as3935/state</code></span><span>Eventi</span><span class="v"><code>…/as3935/event</code></span></div><p class="note">Lo stato viene pubblicato ogni 30 s e immediatamente dopo ogni IRQ. Il topic event non è retained.</p></section>
</div></div>
<script>
const $=id=>document.getElementById(id);const setClass=(el,ok,warn=false)=>{el.className='v '+(ok?'ok':warn?'warn':'bad')};
async function loadConfig(){const c=await fetch('/api/config',{cache:'no-store'}).then(r=>r.json());$('enabled').checked=c.enabled;$('modeCfg').value=c.indoor?'indoor':'outdoor';$('addr').value=c.i2c_address;$('irqPin').value=c.irq_pin;$('noiseFloor').value=c.noise_floor;$('watchdog').value=c.watchdog_threshold;$('spike').value=c.spike_rejection;$('minStrikes').value=c.min_strikes;$('maskDist').checked=c.mask_disturbers;$('autoTune').checked=c.auto_tune;$('tuneCap').value=c.tuning_cap;}
async function refresh(){try{const s=await fetch('/api/state',{cache:'no-store'}).then(r=>r.json());$('statusTag').textContent=!s.enabled?'DISABLED':s.detected?'ONLINE':'NOT FOUND';$('detected').textContent=s.detected?'RILEVATO':'NON RILEVATO';setClass($('detected'),s.detected,!s.enabled);$('irq').textContent=s.irq_ok?'OK':'KO';setClass($('irq'),s.irq_ok);$('cal').textContent=s.calibration_ok?'OK':'VERIFICARE';setClass($('cal'),s.calibration_ok,true);$('freq').textContent=s.resonance_hz?s.resonance_hz+' Hz':'-';$('mode').textContent=s.mode.toUpperCase();$('bus').textContent='0x'+Number(s.i2c_address).toString(16).padStart(2,'0')+' / GPIO'+s.irq_pin;$('energy').textContent=s.last_energy||'-';$('lastType').textContent=s.last_type;$('irqTotal').textContent=s.irq_total;$('noise').textContent=s.noise_total;$('dist').textContent=s.disturber_total;$('strikes').textContent=s.lightning_total;if(s.last_lightning_ms){$('lastStrike').textContent=s.distance_out_of_range?'>40 km':s.last_distance_km+' km';}else $('lastStrike').textContent='Nessun fulmine';}catch(e){$('statusTag').textContent='UI OFFLINE';}}
$('cfgForm').addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(e.target);const p=new URLSearchParams();for(const [k,v] of fd)p.append(k,v);try{const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:p});const j=await r.json();$('msg').textContent=j.ok?'Configurazione salvata e applicata':'Errore: '+(j.error||r.status);await loadConfig();await refresh();}catch(e){$('msg').textContent='Errore di comunicazione';}});
async function reinitSensor(){const r=await fetch('/api/reinit',{method:'POST'});const j=await r.json();$('msg').textContent=j.ok?'Sensore reinizializzato':'Sensore non rilevato / inizializzazione fallita';await refresh();}
async function resetCfg(){if(!confirm('Ripristinare i default AS3935?'))return;const r=await fetch('/api/reset',{method:'POST'});const j=await r.json();$('msg').textContent=j.ok?'Default ripristinati':'Reset fallito';await loadConfig();await refresh();}
loadConfig().then(refresh);setInterval(refresh,2000);
</script></body></html>
)HTML";

void handleRoot() {
    noCache();
    server.send_P(200, "text/html; charset=utf-8", PAGE);
}

} // namespace

void initLightningWeb() {
#if WEB_ENABLE
    server.on("/", HTTP_GET, handleRoot);
    server.on("/api/state", HTTP_GET, handleState);
    server.on("/api/config", HTTP_GET, handleConfigGet);
    server.on("/api/config", HTTP_POST, handleConfigSave);
    server.on("/api/reset", HTTP_POST, handleReset);
    server.on("/api/reinit", HTTP_POST, handleReinit);
    server.begin();
    started = true;
    Serial.print(F("[AS3935-WEB] HTTP diagnostica/config su porta "));
    Serial.println(LIGHTNING_WEB_PORT);
#else
    Serial.println(F("[AS3935-WEB] disabilitato: WEB_ENABLE=0"));
#endif
}

void serviceLightningWeb() {
#if WEB_ENABLE
    if (started) server.handleClient();
#endif
}
