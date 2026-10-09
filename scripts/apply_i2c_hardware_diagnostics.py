Import("env")

from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))

# ---------------------------------------------------------------------------
# Final I2C / hardware diagnostics pass.
#
# Runs after the BME280 retry/idempotence passes. It keeps hardware diagnostics
# separate from BAROMETRO, exposes the ESP32 internal die temperature when the
# Arduino core provides a valid reading, and offers a manual authenticated I2C
# scan. The normal shared bus remains at 100 kHz; 400 kHz is diagnostic only.
# ---------------------------------------------------------------------------

web_path = root / "src" / "web_manager.cpp"
web = web_path.read_text(encoding="utf-8")

if "#include <Wire.h>" not in web:
    anchor = "#include <WiFi.h>\n"
    if anchor not in web:
        raise RuntimeError("I2C/HW diagnostics: WiFi include anchor missing")
    web = web.replace(anchor, anchor + "#include <Wire.h>\n", 1)

# handleState() is defined before the diagnostic handlers, so provide a forward
# declaration for the helper used in the system JSON.
forward_anchor = "String jsonEscapeString(const String &in);\n"
if "float hardwareTemperatureC();" not in web:
    if forward_anchor not in web:
        raise RuntimeError("I2C/HW diagnostics: helper forward anchor missing")
    web = web.replace(forward_anchor, forward_anchor + "float hardwareTemperatureC();\n", 1)

if "I2C_HARDWARE_DIAGNOSTICS_V1" not in web:
    handler_anchor = "void handleBarometerConfigGet() {"
    if handler_anchor not in web:
        raise RuntimeError("I2C/HW diagnostics: barometer handler anchor missing")

    handlers = r'''
// I2C_HARDWARE_DIAGNOSTICS_V1
float hardwareTemperatureC() {
#if defined(ARDUINO_ARCH_ESP32)
    const float t = temperatureRead();
    if (isfinite(t) && t > -40.0f && t < 150.0f) return t;
#endif
    return NAN;
}

String runHardwareI2cScanJson() {
    constexpr uint32_t RUNTIME_I2C_HZ = 100000UL;
    constexpr uint32_t STRESS_I2C_HZ = 400000UL;
    const uint32_t startedMs = millis();

    const int sdaInitial = digitalRead(I2C_SDA_PIN);
    const int sclInitial = digitalRead(I2C_SCL_PIN);
    const bool busStuckInitial = (sdaInitial == LOW || sclInitial == LOW);

    String devices100;
    String devices400;
    devices100.reserve(640);
    devices400.reserve(640);

    auto scanBus = [](uint32_t hz, String &list) -> uint16_t {
        Wire.setClock(hz);
        list = "[";
        bool first = true;
        uint16_t count = 0;
        // 0x00 is the I2C general-call address. Do not probe it in a generic
        // scanner; AS3935 configured address is reported separately by /info.
        for (uint8_t addr = 1; addr < 0x7FU; ++addr) {
            Wire.beginTransmission(addr);
            const uint8_t err = Wire.endTransmission(true);
            if (err == 0U) {
                if (!first) list += ',';
                list += String(addr);
                first = false;
                count++;
            }
            delayMicroseconds(40);
        }
        list += "]";
        return count;
    };

    auto readRegister = [](uint8_t addr, uint8_t reg, uint8_t &value) -> bool {
        Wire.beginTransmission(addr);
        Wire.write(reg);
        if (Wire.endTransmission(false) != 0U) return false;
        const uint8_t got = Wire.requestFrom(addr, static_cast<uint8_t>(1));
        if (got != 1U || !Wire.available()) return false;
        value = static_cast<uint8_t>(Wire.read());
        return true;
    };

    uint16_t count100 = 0;
    uint16_t count400 = 0;
    uint8_t chip76 = 0;
    uint8_t chip77 = 0;
    bool chip76Ok = false;
    bool chip77Ok = false;

    if (!busStuckInitial) {
        // Runtime speed first: this is the result that matters for normal use.
        count100 = scanBus(RUNTIME_I2C_HZ, devices100);
        Wire.setClock(RUNTIME_I2C_HZ);
        chip76Ok = readRegister(0x76U, 0xD0U, chip76);
        chip77Ok = readRegister(0x77U, 0xD0U, chip77);

        // 400 kHz is intentionally a manual stress/margin test only.
        count400 = scanBus(STRESS_I2C_HZ, devices400);
    } else {
        devices100 = "[]";
        devices400 = "[]";
    }

    Wire.setClock(RUNTIME_I2C_HZ);
    Wire.setTimeOut(80);

    const int sdaFinal = digitalRead(I2C_SDA_PIN);
    const int sclFinal = digitalRead(I2C_SCL_PIN);
    const bool busStuckFinal = (sdaFinal == LOW || sclFinal == LOW);

    String out;
    out.reserve(1800);
    out = "{\"ok\":true";
    out += ",\"sda\":" + String(I2C_SDA_PIN);
    out += ",\"scl\":" + String(I2C_SCL_PIN);
    out += ",\"runtime_hz\":" + String(RUNTIME_I2C_HZ);
    out += ",\"sda_initial\":" + String(sdaInitial);
    out += ",\"scl_initial\":" + String(sclInitial);
    out += ",\"sda_final\":" + String(sdaFinal);
    out += ",\"scl_final\":" + String(sclFinal);
    out += ",\"bus_stuck_initial\":"; out += busStuckInitial ? "true" : "false";
    out += ",\"bus_stuck_final\":"; out += busStuckFinal ? "true" : "false";
    out += ",\"devices_100khz\":" + devices100;
    out += ",\"count_100khz\":" + String(count100);
    out += ",\"devices_400khz\":" + devices400;
    out += ",\"count_400khz\":" + String(count400);
    out += ",\"chip_id_0x76\":";
    if (chip76Ok) out += String(chip76); else out += "null";
    out += ",\"chip_id_0x77\":";
    if (chip77Ok) out += String(chip77); else out += "null";
    out += ",\"bme280_0x76\":"; out += (chip76Ok && chip76 == 0x60U) ? "true" : "false";
    out += ",\"bme280_0x77\":"; out += (chip77Ok && chip77 == 0x60U) ? "true" : "false";
    out += ",\"duration_ms\":" + String(static_cast<uint32_t>(millis() - startedMs));
    out += "}";
    return out;
}

void handleHardwareInfoGet() {
    const LightningState ls = getLightningState();
    const LightningConfig lc = getLightningConfig();
    const float hwTemp = hardwareTemperatureC();
    String out;
    out.reserve(520);
    out = "{\"board\":\"" + jsonEscapeString(String(BOARD_NAME)) + "\"";
    out += ",\"i2c_sda\":" + String(I2C_SDA_PIN);
    out += ",\"i2c_scl\":" + String(I2C_SCL_PIN);
    out += ",\"i2c_runtime_hz\":100000";
    out += ",\"bme280_detected\":"; out += barometerDetected() ? "true" : "false";
    out += ",\"bme280_address\":" + String(barometerAddress());
    out += ",\"as3935_enabled\":"; out += ls.enabled ? "true" : "false";
    out += ",\"as3935_detected\":"; out += ls.detected ? "true" : "false";
    out += ",\"as3935_address\":" + String(lc.i2cAddress);
    out += ",\"mcu_temperature_c\":" + jsonFloat(hwTemp, 1);
    out += "}";
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", out);
}

void handleHardwareI2cScan() {
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", runHardwareI2cScanJson());
}

'''
    web = web.replace(handler_anchor, handlers + handler_anchor, 1)

# Add MCU die temperature to the already existing Hardware monitor payload.
sys_anchor = '    out += ",\\\"cpu_mhz\\\":" + String(ESP.getCpuFreqMHz());\n'
if '\\"hardware_temperature_c\\"' not in web:
    if sys_anchor not in web:
        raise RuntimeError("I2C/HW diagnostics: system JSON CPU anchor missing")
    web = web.replace(
        sys_anchor,
        sys_anchor + '    out += ",\\\"hardware_temperature_c\\\":" + jsonFloat(hardwareTemperatureC(), 1);\n',
        1,
    )

# Authenticated API routes. Use a generated BAROMETRO route as a stable anchor.
route_anchor = '    server.on("/api/barometer/config", HTTP_GET, [](){ if (!requireWebAuth()) return; handleBarometerConfigGet(); });'
if 'server.on("/api/hardware/info"' not in web:
    if route_anchor not in web:
        raise RuntimeError("I2C/HW diagnostics: Web route anchor missing")
    routes = (
        '\n    server.on("/api/hardware/info", HTTP_GET, [](){ if (!requireWebAuth()) return; handleHardwareInfoGet(); });'
        '\n    server.on("/api/hardware/i2c-scan", HTTP_POST, [](){ if (!requireWebAuth()) return; handleHardwareI2cScan(); });'
    )
    web = web.replace(route_anchor, route_anchor + routes, 1)

web_path.write_text(web, encoding="utf-8")

# ---------------------------------------------------------------------------
# Web UI: dedicated CONFIGURAZIONE > I2C / HW page.
# ---------------------------------------------------------------------------
dash_path = root / "web" / "dashboard.html"
html = dash_path.read_text(encoding="utf-8")

# Remove the legacy scanner controls from BAROMETRO if an older workspace had
# already been transformed by the previous development pass.
html = re.sub(r'<button\s+id="baroScanBtn"[^>]*>Scanner I2C</button>', '', html, count=1)
html = re.sub(r'<div\s+id="baroI2cScan"[^>]*>.*?</div>', '', html, count=1, flags=re.S)

if ".hwDiagGrid" not in html:
    css = r'''
.hwDiagGrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:12px}.hwDiagBox{border:1px solid var(--border);border-radius:10px;background:#0d1929;padding:11px}.hwDiagBox b{display:block;font-size:.82rem}.hwDiagBox span{display:block;color:var(--muted);font-size:.72rem;margin-top:5px}.hwScanResult{margin:0 14px 14px;padding:11px;border:1px solid var(--border);border-radius:10px;background:#081423;color:#b9cee8;font:12px ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;line-height:1.5}@media(max-width:900px){.hwDiagGrid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.hwDiagGrid{grid-template-columns:1fr}}
'''
    if "</style>" not in html:
        raise RuntimeError("I2C/HW diagnostics: CSS end anchor missing")
    html = html.replace("</style>", css + "</style>", 1)

if 'id="tabHardwareDiag"' not in html:
    tab_anchor = r'(<button\s+id="tabBarometer"[^>]*>BAROMETRO</button>)'
    m = re.search(tab_anchor, html)
    if not m:
        raise RuntimeError("I2C/HW diagnostics: BAROMETRO tab anchor missing")
    tab = '<button id="tabHardwareDiag" class="cfgTab" onclick="showCfgTab(\'hardwareDiag\')">I2C / HW</button>'
    html = html[:m.end()] + tab + html[m.end():]

if 'id="cfgHardwareDiag"' not in html:
    page_anchor = '<div id="cfgLightning" class="cfgPage">'
    if page_anchor not in html:
        raise RuntimeError("I2C/HW diagnostics: AS3935 config page anchor missing")
    page = r'''<div id="cfgHardwareDiag" class="cfgPage">
<div class="cfgExplain">
<section class="cfgSection"><div class="cfgSectionHead">Diagnostica hardware / I²C<span class="cfgSectionSub">Scanner manuale del bus condiviso e stato dei sensori locali. Nessuna scrittura NVS.</span></div>
<div class="hwDiagGrid">
<div class="hwDiagBox"><b id="hwTemp">--</b><span>Temperatura MCU interna · indicativa, non temperatura ambiente</span></div>
<div class="hwDiagBox"><b id="hwBus">--</b><span>Bus I²C runtime</span></div>
<div class="hwDiagBox"><b id="hwBme">--</b><span>BME280 locale</span></div>
<div class="hwDiagBox"><b id="hwAs">--</b><span>AS3935 locale</span></div>
</div>
<div class="cfgActions"><button id="hwScanBtn" class="modeBtn" onclick="scanHardwareI2c()">Scanner I2C</button><span id="hwSummary" class="muted"></span></div>
<div id="hwI2cScan" class="hwScanResult">Scanner I²C manuale non eseguito.</div>
<div class="cfgNote">Il gateway usa normalmente 100 kHz per aumentare il margine con più dispositivi sul bus. La scansione a 400 kHz è solo un test manuale di margine. Cavi I²C lunghi possono causare ACK mancanti anche con SDA/SCL correttamente alte a riposo.</div>
</section>
</div>
</div>
'''
    html = html.replace(page_anchor, page + page_anchor, 1)

# Add MCU temperature to the main Hardware monitor as well.
if 'id="sysHwTemp"' not in html:
    core_line = '<div class="resourceLine"><span class="name">Core</span><span class="value" id="sysCores">--</span></div>'
    if core_line not in html:
        raise RuntimeError("I2C/HW diagnostics: Hardware monitor Core anchor missing")
    temp_line = '<div class="resourceLine"><span class="name">Temperatura MCU</span><span class="value" id="sysHwTemp">--</span></div>'
    html = html.replace(core_line, core_line + temp_line, 1)

if "async function loadHardwareDiag()" not in html:
    js_anchor = "async function loadBarometer()"
    if js_anchor not in html:
        raise RuntimeError("I2C/HW diagnostics: loadBarometer JS anchor missing")
    js = r'''async function loadHardwareDiag(){try{const r=await fetch('/api/hardware/info',{cache:'no-store'});if(!r.ok)throw new Error(await r.text());const d=await r.json(),hx=v=>'0x'+Number(v||0).toString(16).toUpperCase().padStart(2,'0');E('hwTemp').textContent=d.mcu_temperature_c==null?'N/D':Number(d.mcu_temperature_c).toFixed(1)+' °C';E('hwBus').textContent='SDA '+d.i2c_sda+' / SCL '+d.i2c_scl+' · '+Math.round(Number(d.i2c_runtime_hz||0)/1000)+' kHz';E('hwBme').textContent=d.bme280_detected?('OK @'+hx(d.bme280_address)):'NON RILEVATO';E('hwAs').textContent=!d.as3935_enabled?'DISABILITATO':(d.as3935_detected?('OK @'+hx(d.as3935_address)):'NON RILEVATO');E('hwSummary').textContent=d.board||'';}catch(e){if(E('hwSummary'))E('hwSummary').textContent='errore diagnostica hardware';}}
async function scanHardwareI2c(){const b=E('hwScanBtn'),e=E('hwI2cScan');if(!e)return;if(b)b.disabled=true;e.textContent='Scanner I²C in corso: runtime 100 kHz + stress 400 kHz...';try{const r=await fetch('/api/hardware/i2c-scan',{method:'POST',cache:'no-store'});if(!r.ok)throw new Error(await r.text());const d=await r.json(),hx=v=>'0x'+Number(v).toString(16).toUpperCase().padStart(2,'0'),lst=a=>(Array.isArray(a)&&a.length?a.map(hx).join(', '):'nessuno'),cid=v=>v==null?'--':hx(v);const a100=Array.isArray(d.devices_100khz)?d.devices_100khz:[],a400=Array.isArray(d.devices_400khz)?d.devices_400khz:[];let verdict='';if(d.bus_stuck_initial||d.bus_stuck_final)verdict='BUS BLOCCATO: SDA o SCL è bassa. Controllare corto, pull-up e cablaggio.';else if(d.bme280_0x76||d.bme280_0x77){verdict='BME280 confermato dal chip ID Bosch 0x60.';if((a100.includes(0x76)||a100.includes(0x77))&&!(a400.includes(0x76)||a400.includes(0x77)))verdict+=' Funziona a 100 kHz ma non a 400 kHz: margine I²C ridotto, tipicamente cavi lunghi/capacità del bus.';}else if(a100.includes(0x76)||a100.includes(0x77)||a400.includes(0x76)||a400.includes(0x77))verdict='Dispositivo presente a 0x76/0x77, ma chip ID diverso da 0x60 o non leggibile.';else verdict='Nessun BME280 visibile a 0x76/0x77.';e.textContent='100 kHz (runtime): '+lst(d.devices_100khz)+'\n400 kHz (stress):  '+lst(d.devices_400khz)+'\nChip ID 0x76: '+cid(d.chip_id_0x76)+' · 0x77: '+cid(d.chip_id_0x77)+'\nSDA/SCL iniziali: '+String(d.sda_initial)+'/'+String(d.scl_initial)+' · finali: '+String(d.sda_final)+'/'+String(d.scl_final)+'\nDurata: '+String(d.duration_ms||0)+' ms\n'+verdict;}catch(err){e.textContent='Scanner I²C fallito: '+String(err);}finally{if(b)b.disabled=false;await loadHardwareDiag();}}
'''
    html = html.replace(js_anchor, js + js_anchor, 1)

# Hook the new page into the existing configuration switch without changing the
# historical base array used by earlier idempotence passes.
if "cfgHardwareDiag').classList.toggle" not in html:
    sig = "function showCfgTab(t){"
    if sig not in html:
        raise RuntimeError("I2C/HW diagnostics: showCfgTab missing")
    injected = (
        sig
        + "E('cfgHardwareDiag').classList.toggle('active',t==='hardwareDiag');"
        + "E('tabHardwareDiag').classList.toggle('active',t==='hardwareDiag');"
        + "if(t==='hardwareDiag')loadHardwareDiag();"
    )
    html = html.replace(sig, injected, 1)

# Update the main Hardware monitor from the already existing /api/state payload.
if "sysHwTemp').textContent" not in html:
    hw_anchor = "E('sysCores').textContent=sys.cores??'--';"
    if hw_anchor not in html:
        raise RuntimeError("I2C/HW diagnostics: Hardware refresh anchor missing")
    hw_update = "E('sysHwTemp').textContent=sys.hardware_temperature_c==null?'N/D':Number(sys.hardware_temperature_c).toFixed(1)+' °C';"
    html = html.replace(hw_anchor, hw_anchor + hw_update, 1)

dash_path.write_text(html, encoding="utf-8")
print("Applied dedicated I2C/HW diagnostics page and MCU temperature monitor")
