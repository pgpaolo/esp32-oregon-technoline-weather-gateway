Import("env")

from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))

# ---------------------------------------------------------------------------
# Compile-order guard for the retry pass.
# ---------------------------------------------------------------------------
path = root / "src" / "barometer_manager.cpp"
text = path.read_text(encoding="utf-8")

marker = "// BME280_DETECTION_RETRY_V1\n"
prototype = "bool tryBme(uint8_t addr);\n"

if marker not in text:
    raise RuntimeError("BME280 detection compile fix: retry marker missing")

if prototype not in text:
    text = text.replace(marker, marker + prototype, 1)
    print("Added BME280 tryBme forward declaration")
else:
    print("BME280 tryBme forward declaration already present")

# The deep I2C scanner uses the board-level SDA/SCL definitions directly.
# barometer_manager.cpp historically only included config.h, so make the pin
# source explicit here instead of relying on an indirect include.
if '#include "board_config.h"' not in text:
    include_anchor = '#include "config.h"\n'
    if include_anchor not in text:
        raise RuntimeError("BME280 I2C scan: config include anchor missing")
    text = text.replace(include_anchor, include_anchor + '#include "board_config.h"\n', 1)
    print("Added board_config.h for BME280 I2C scanner pin definitions")

path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Manual deep I2C scanner for CONFIGURAZIONE > BAROMETRO.
#
# It is deliberately on-demand only: the normal RF/network loop is not burdened
# by a full 1..126 scan. The diagnostic checks the bus first at 400 kHz and
# then at 100 kHz, reads Bosch chip-id register 0xD0 at 0x76/0x77, and restores
# the normal 400 kHz bus speed before returning.
# ---------------------------------------------------------------------------
header_path = root / "src" / "barometer_manager.h"
header = header_path.read_text(encoding="utf-8")
if "#include <Arduino.h>" not in header:
    header = header.replace("#pragma once\n", "#pragma once\n#include <Arduino.h>\n", 1)
if "String runBarometerI2cScanJson();" not in header:
    header += "\n// BME280_I2C_DEEP_SCAN_V1\nString runBarometerI2cScanJson();\n"
header_path.write_text(header, encoding="utf-8")

cpp_path = root / "src" / "barometer_manager.cpp"
cpp = cpp_path.read_text(encoding="utf-8")
if "BME280_I2C_DEEP_SCAN_V1" not in cpp:
    public_anchor = "uint8_t barometerAddress() { return address; }\n"
    if public_anchor not in cpp:
        raise RuntimeError("BME280 I2C scan: public API anchor missing")

    scanner = r'''
    
// BME280_I2C_DEEP_SCAN_V1
String runBarometerI2cScanJson() {
    constexpr uint32_t NORMAL_I2C_HZ = 400000UL;
    constexpr uint32_t SAFE_I2C_HZ = 100000UL;
    const uint32_t startedMs = millis();

    const int sdaInitial = digitalRead(I2C_SDA_PIN);
    const int sclInitial = digitalRead(I2C_SCL_PIN);
    const bool busStuckInitial = (sdaInitial == LOW || sclInitial == LOW);

    String devices400;
    String devices100;
    devices400.reserve(640);
    devices100.reserve(640);

    auto scanBus = [](uint32_t hz, String &list) -> uint16_t {
        Wire.setClock(hz);
        list = "[";
        bool first = true;
        uint16_t count = 0;
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

    uint16_t count400 = 0;
    uint16_t count100 = 0;
    uint8_t chip76 = 0;
    uint8_t chip77 = 0;
    bool chip76Ok = false;
    bool chip77Ok = false;

    if (!busStuckInitial) {
        count400 = scanBus(NORMAL_I2C_HZ, devices400);
        count100 = scanBus(SAFE_I2C_HZ, devices100);

        Wire.setClock(SAFE_I2C_HZ);
        chip76Ok = readRegister(0x76U, 0xD0U, chip76);
        chip77Ok = readRegister(0x77U, 0xD0U, chip77);
    } else {
        devices400 = "[]";
        devices100 = "[]";
    }

    Wire.setClock(NORMAL_I2C_HZ);

    const int sdaFinal = digitalRead(I2C_SDA_PIN);
    const int sclFinal = digitalRead(I2C_SCL_PIN);
    const bool busStuckFinal = (sdaFinal == LOW || sclFinal == LOW);

    String out;
    out.reserve(1700);
    out = "{\"ok\":true";
    out += ",\"sda\":" + String(I2C_SDA_PIN);
    out += ",\"scl\":" + String(I2C_SCL_PIN);
    out += ",\"sda_initial\":" + String(sdaInitial);
    out += ",\"scl_initial\":" + String(sclInitial);
    out += ",\"sda_final\":" + String(sdaFinal);
    out += ",\"scl_final\":" + String(sclFinal);
    out += ",\"bus_stuck_initial\":"; out += busStuckInitial ? "true" : "false";
    out += ",\"bus_stuck_final\":"; out += busStuckFinal ? "true" : "false";
    out += ",\"devices_400khz\":" + devices400;
    out += ",\"count_400khz\":" + String(count400);
    out += ",\"devices_100khz\":" + devices100;
    out += ",\"count_100khz\":" + String(count100);
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
'''
    cpp = cpp.replace(public_anchor, public_anchor + scanner, 1)
    cpp_path.write_text(cpp, encoding="utf-8")
    print("Added manual 400/100 kHz I2C scanner and BME280 chip-id probe")
else:
    print("BME280 deep I2C scanner already present")


# ---------------------------------------------------------------------------
# Authenticated manual scan endpoint.
# ---------------------------------------------------------------------------
web_path = root / "src" / "web_manager.cpp"
web = web_path.read_text(encoding="utf-8")

if "void handleBarometerI2cScan()" not in web:
    handler_anchor = "void handleBarometerConfigGet() {"
    if handler_anchor not in web:
        raise RuntimeError("BME280 I2C scan: barometer config handler missing")
    handler = r'''void handleBarometerI2cScan() {
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", runBarometerI2cScanJson());
}

'''
    web = web.replace(handler_anchor, handler + handler_anchor, 1)

if 'server.on("/api/barometer/i2c-scan"' not in web:
    route_anchor = '    server.on("/api/barometer/config", HTTP_GET, [](){ if (!requireWebAuth()) return; handleBarometerConfigGet(); });'
    if route_anchor not in web:
        raise RuntimeError("BME280 I2C scan: barometer route anchor missing")
    route = '    server.on("/api/barometer/i2c-scan", HTTP_POST, [](){ if (!requireWebAuth()) return; handleBarometerI2cScan(); });\n'
    web = web.replace(route_anchor, route_anchor + "\n" + route, 1)

web_path.write_text(web, encoding="utf-8")


# ---------------------------------------------------------------------------
# BAROMETRO page: manual button + readable result. No background polling.
# ---------------------------------------------------------------------------
dash_path = root / "web" / "dashboard.html"
html = dash_path.read_text(encoding="utf-8")

if 'id="baroScanBtn"' not in html:
    old = '<button class="modeBtn" onclick="resetBarometer()">Default firmware</button>'
    if old not in html:
        raise RuntimeError("BME280 I2C scan: BAROMETRO action anchor missing")
    new = old + '<button id="baroScanBtn" class="modeBtn" onclick="scanBarometerI2c()">Scanner I2C</button>'
    html = html.replace(old, new, 1)

if 'id="baroI2cScan"' not in html:
    m = re.search(r'(<div id="baroDiag"[^>]*>.*?</div>)', html, flags=re.S)
    if not m:
        raise RuntimeError("BME280 I2C scan: baroDiag anchor missing")
    result = (
        '<div id="baroI2cScan" class="cfgNote" style="white-space:pre-wrap">'
        'Scanner I2C manuale non eseguito.</div>'
    )
    html = html[:m.end()] + result + html[m.end():]

if "async function scanBarometerI2c()" not in html:
    js_anchor = "async function loadBarometer()"
    if js_anchor not in html:
        raise RuntimeError("BME280 I2C scan: loadBarometer JS anchor missing")
    js = r'''async function scanBarometerI2c(){const b=E('baroScanBtn'),e=E('baroI2cScan');if(!e)return;if(b)b.disabled=true;e.textContent='Scanner I2C in corso: 400 kHz + 100 kHz...';try{const r=await fetch('/api/barometer/i2c-scan',{method:'POST',cache:'no-store'});if(!r.ok)throw new Error(await r.text());const d=await r.json(),hx=v=>'0x'+Number(v).toString(16).toUpperCase().padStart(2,'0'),lst=a=>(Array.isArray(a)&&a.length?a.map(hx).join(', '):'nessuno'),cid=v=>v==null?'--':hx(v);let verdict='';if(d.bus_stuck_initial||d.bus_stuck_final)verdict='BUS BLOCCATO: SDA o SCL e bassa. Controllare corto, pull-up e cablaggio.';else if(d.bme280_0x76||d.bme280_0x77)verdict='BME280 confermato dal chip ID Bosch 0x60.';else{const a400=Array.isArray(d.devices_400khz)?d.devices_400khz:[],a100=Array.isArray(d.devices_100khz)?d.devices_100khz:[],bmeAck=a100.includes(0x76)||a100.includes(0x77)||a400.includes(0x76)||a400.includes(0x77);if(bmeAck)verdict='Dispositivo presente a 0x76/0x77, ma chip ID diverso da 0x60 o non leggibile.';else verdict='Nessun dispositivo a 0x76/0x77: il BME280 non e visibile sul bus.';if(!a400.includes(0x76)&&!a400.includes(0x77)&&(a100.includes(0x76)||a100.includes(0x77)))verdict+=' Risponde solo a 100 kHz: verificare cavetti/pull-up.';}e.textContent='400 kHz: '+lst(d.devices_400khz)+'\n100 kHz: '+lst(d.devices_100khz)+'\nChip ID 0x76: '+cid(d.chip_id_0x76)+' · 0x77: '+cid(d.chip_id_0x77)+'\nSDA/SCL iniziali: '+String(d.sda_initial)+'/'+String(d.scl_initial)+' · finali: '+String(d.sda_final)+'/'+String(d.scl_final)+'\nDurata: '+String(d.duration_ms||0)+' ms\n'+verdict;}catch(err){e.textContent='Scanner I2C fallito: '+String(err);}finally{if(b)b.disabled=false;}}\n'''
    html = html.replace(js_anchor, js + js_anchor, 1)

dash_path.write_text(html, encoding="utf-8")
print("Added authenticated manual I2C scanner UI for BAROMETRO")
