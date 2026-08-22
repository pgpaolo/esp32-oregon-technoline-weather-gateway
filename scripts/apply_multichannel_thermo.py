from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def write(path, text):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)

# -----------------------------------------------------------------------------
# Dedicated multichannel state/config. The RF parser is intentionally untouched.
# -----------------------------------------------------------------------------
manager_h = r'''#pragma once
#include <Arduino.h>
#include "oregon_types.h"
#include "station_state.h"

struct ThermoChannelConfig {
    uint8_t enabledMask{0x01};       // bit0=CH1, bit1=CH2, bit2=CH3
    uint8_t primaryChannel{1};       // feeds legacy weather fields/topics
    bool autoDiscover{true};         // detected channels join Web/MQTT automatically
};

struct ThermoChannelState {
    bool detected{false};
    bool valid{false};
    float temperatureC{NAN};
    float humidityPct{NAN};
    uint32_t updatedMs{0};
    uint32_t packetCount{0};
    float lastRssi{NAN};
    OregonSensorStatus sensor{};
};

void initThermoChannels();
void noteThermoChannelReading(const WeatherReading &reading);
ThermoChannelConfig getThermoChannelConfig();
ThermoChannelState getThermoChannelState(uint8_t channel);
uint8_t thermoDetectedMask();
uint8_t thermoEffectiveMask();
bool thermoChannelVisible(uint8_t channel);
bool thermoChannelIsPrimary(uint8_t channel);
bool saveThermoChannelConfig(const ThermoChannelConfig &cfg);
bool resetThermoChannelConfig();
void syncPrimaryThermoState(StationState &station);
'''

manager_cpp = r'''#include "thermo_channel_manager.h"
#include <Preferences.h>
#include <math.h>

namespace {
Preferences prefs;
ThermoChannelConfig cfg{};
ThermoChannelState channels[3]{};

ThermoChannelConfig defaults() { return ThermoChannelConfig{}; }

void normalize(ThermoChannelConfig &c) {
    c.enabledMask &= 0x07U;
    if (c.primaryChannel < 1U || c.primaryChannel > 3U) c.primaryChannel = 1U;
    c.enabledMask |= static_cast<uint8_t>(1U << (c.primaryChannel - 1U));
}

bool verifyStored(Preferences &p, const ThermoChannelConfig &expected) {
    const ThermoChannelConfig d = defaults();
    return p.getUChar("enabled", d.enabledMask) == expected.enabledMask &&
           p.getUChar("primary", d.primaryChannel) == expected.primaryChannel &&
           p.getBool("auto", d.autoDiscover) == expected.autoDiscover;
}

void copySensor(OregonSensorStatus &dst, const WeatherReading &r) {
    dst.code = r.sensorCode;
    dst.channel = r.channel;
    dst.channelRaw = r.channelRaw;
    dst.rollingCode = r.rollingCode;
    dst.flags = r.flags;
    dst.batteryKnown = r.batteryStatusValid;
    dst.batteryLow = r.batteryLow;
    dst.updatedMs = r.receivedAtMs;
}
} // namespace

void initThermoChannels() {
    const ThermoChannelConfig d = defaults();
    if (!prefs.begin("thermoch", true)) {
        cfg = d;
        normalize(cfg);
        Serial.println(F("[THERMO] NVS non disponibile: CH1 principale"));
        return;
    }
    cfg.enabledMask = prefs.getUChar("enabled", d.enabledMask);
    cfg.primaryChannel = prefs.getUChar("primary", d.primaryChannel);
    cfg.autoDiscover = prefs.getBool("auto", d.autoDiscover);
    prefs.end();
    normalize(cfg);
    Serial.print(F("[THERMO] primary=CH")); Serial.print(cfg.primaryChannel);
    Serial.print(F(" enabled=0x")); Serial.print(cfg.enabledMask, HEX);
    Serial.print(F(" auto=")); Serial.println(cfg.autoDiscover ? F("ON") : F("OFF"));
}

void noteThermoChannelReading(const WeatherReading &r) {
    if (r.type != SensorType::ThermoHygro || r.channel < 1U || r.channel > 3U) return;
    ThermoChannelState &s = channels[r.channel - 1U];
    s.detected = true;
    s.packetCount++;
    s.updatedMs = r.receivedAtMs;
    s.lastRssi = r.rssi;
    copySensor(s.sensor, r);
    if (r.temperatureValid) s.temperatureC = r.temperatureC;
    if (r.humidityValid) s.humidityPct = r.humidityPct;
    s.valid = r.temperatureValid || r.humidityValid;
}

ThermoChannelConfig getThermoChannelConfig() { return cfg; }

ThermoChannelState getThermoChannelState(uint8_t channel) {
    if (channel < 1U || channel > 3U) return ThermoChannelState{};
    return channels[channel - 1U];
}

uint8_t thermoDetectedMask() {
    uint8_t m = 0;
    for (uint8_t i = 0; i < 3U; ++i) if (channels[i].detected) m |= static_cast<uint8_t>(1U << i);
    return m;
}

uint8_t thermoEffectiveMask() {
    return static_cast<uint8_t>((cfg.enabledMask | (cfg.autoDiscover ? thermoDetectedMask() : 0U)) & 0x07U);
}

bool thermoChannelVisible(uint8_t channel) {
    if (channel < 1U || channel > 3U) return false;
    return (thermoEffectiveMask() & static_cast<uint8_t>(1U << (channel - 1U))) != 0U;
}

bool thermoChannelIsPrimary(uint8_t channel) {
    // Canale 0 = header non decodificabile: mantiene la compatibilita' legacy.
    return channel == 0U || channel == cfg.primaryChannel;
}

bool saveThermoChannelConfig(const ThermoChannelConfig &input) {
    ThermoChannelConfig next = input;
    normalize(next);
    if (next.enabledMask == cfg.enabledMask && next.primaryChannel == cfg.primaryChannel && next.autoDiscover == cfg.autoDiscover) return true;
    if (!prefs.begin("thermoch", false)) return false;
    if (next.enabledMask != cfg.enabledMask) prefs.putUChar("enabled", next.enabledMask);
    if (next.primaryChannel != cfg.primaryChannel) prefs.putUChar("primary", next.primaryChannel);
    if (next.autoDiscover != cfg.autoDiscover) prefs.putBool("auto", next.autoDiscover);
    const bool ok = verifyStored(prefs, next);
    prefs.end();
    if (!ok) return false;
    cfg = next;
    return true;
}

bool resetThermoChannelConfig() {
    ThermoChannelConfig d = defaults();
    normalize(d);
    if (!prefs.begin("thermoch", false)) return false;
    const bool cleared = prefs.clear();
    const bool ok = cleared && verifyStored(prefs, d);
    prefs.end();
    if (!ok) return false;
    cfg = d;
    return true;
}

void syncPrimaryThermoState(StationState &station) {
    const ThermoChannelState &s = channels[cfg.primaryChannel - 1U];
    if (!s.valid) {
        station.temperatureC = NAN;
        station.humidityPct = NAN;
        station.thermoUpdatedMs = 0;
        station.thermoValid = false;
        station.thermoSensor = OregonSensorStatus{};
        refreshDerivedWeather(station);
        return;
    }
    station.temperatureC = s.temperatureC;
    station.humidityPct = s.humidityPct;
    station.thermoUpdatedMs = s.updatedMs;
    station.thermoValid = true;
    station.thermoSensor = s.sensor;
    refreshDerivedWeather(station);
}
'''
write("src/thermo_channel_manager.h", manager_h)
write("src/thermo_channel_manager.cpp", manager_cpp)

# -----------------------------------------------------------------------------
# Station state: count every valid THGN frame but only let the configured primary
# channel update the legacy weather fields and derived values.
# -----------------------------------------------------------------------------
p = "src/station_state.h"
s = read(p)
s = replace_once(s,
    "void applyWeatherReading(StationState &state, const WeatherReading &reading);",
    "void applyWeatherReading(StationState &state, const WeatherReading &reading, bool applyThermoToPrimary = true);",
    "station_state.h signature")
write(p, s)

p = "src/station_state.cpp"
s = read(p)
s = replace_once(s,
    "void applyWeatherReading(StationState &state, const WeatherReading &reading) {",
    "void applyWeatherReading(StationState &state, const WeatherReading &reading, bool applyThermoToPrimary) {",
    "station_state.cpp signature")
s = replace_once(s,
'''        case SensorType::ThermoHygro:
            state.thermoPacketCount++;
            updateSensorStatus(state.thermoSensor, reading);
            break;''',
'''        case SensorType::ThermoHygro:
            state.thermoPacketCount++;
            if (applyThermoToPrimary) updateSensorStatus(state.thermoSensor, reading);
            break;''',
    "station_state thermo status")
s = replace_once(s,
    "    if (reading.temperatureValid || reading.humidityValid) {",
    "    if ((reading.type != SensorType::ThermoHygro || applyThermoToPrimary) && (reading.temperatureValid || reading.humidityValid)) {",
    "station_state thermo values")
write(p, s)

# -----------------------------------------------------------------------------
# Main loop: record every THGN channel, then route only primary to StationState.
# -----------------------------------------------------------------------------
p = "src/main.cpp"
s = read(p)
s = replace_once(s, '#include "lightning_manager.h"\n', '#include "lightning_manager.h"\n#include "thermo_channel_manager.h"\n', "main include")
s = replace_once(s, "    initDisplay();\n", "    initThermoChannels();\n    initDisplay();\n", "main init")
s = replace_once(s,
    "            applyWeatherReading(station, reading);\n",
'''            bool applyThermoPrimary = true;
            if (reading.type == SensorType::ThermoHygro) {
                noteThermoChannelReading(reading);
                applyThermoPrimary = thermoChannelIsPrimary(reading.channel);
            }
            applyWeatherReading(station, reading, applyThermoPrimary);
''',
    "main apply reading")
write(p, s)

# -----------------------------------------------------------------------------
# MQTT: legacy temperature/humidity follow primary; visible CH1..CH3 get their
# own retained temperature/humidity and a compact retained state JSON.
# -----------------------------------------------------------------------------
p = "src/mqtt_publisher.cpp"
s = read(p)
s = replace_once(s, '#include "lacrosse_ws23xx.h"\n', '#include "lacrosse_ws23xx.h"\n#include "thermo_channel_manager.h"\n', "mqtt include")
s = replace_once(s,
'''    if (reading.temperatureValid && fieldEnabled(MQTT_F_OR_TEMP)) publishFloat(client, "oregon/temperature", reading.temperatureC, 1);
    if (reading.humidityValid && fieldEnabled(MQTT_F_OR_HUM)) publishFloat(client, "oregon/humidity", reading.humidityPct, 0);''',
'''    const bool thermo = reading.type == SensorType::ThermoHygro;
    const bool primaryThermo = !thermo || thermoChannelIsPrimary(reading.channel);
    if (reading.temperatureValid && primaryThermo && fieldEnabled(MQTT_F_OR_TEMP)) publishFloat(client, "oregon/temperature", reading.temperatureC, 1);
    if (reading.humidityValid && primaryThermo && fieldEnabled(MQTT_F_OR_HUM)) publishFloat(client, "oregon/humidity", reading.humidityPct, 0);

    if (thermo && reading.channel >= 1U && reading.channel <= 3U && thermoChannelVisible(reading.channel)) {
        char suffix[48];
        if (reading.temperatureValid && fieldEnabled(MQTT_F_OR_TEMP)) {
            snprintf(suffix, sizeof(suffix), "oregon/thermo/ch%u/temperature", reading.channel);
            publishFloat(client, suffix, reading.temperatureC, 1);
        }
        if (reading.humidityValid && fieldEnabled(MQTT_F_OR_HUM)) {
            snprintf(suffix, sizeof(suffix), "oregon/thermo/ch%u/humidity", reading.channel);
            publishFloat(client, suffix, reading.humidityPct, 0);
        }
        if (fieldEnabled(MQTT_F_RF_META)) {
            String j;
            j.reserve(190);
            j = "{\"channel\":" + String(reading.channel);
            j += ",\"temperature_c\":" + String(reading.temperatureC, 1);
            j += ",\"humidity_pct\":" + String(reading.humidityPct, 0);
            j += ",\"sensor_code\":\"" + String(reading.sensorCode, HEX) + "\"";
            j += ",\"rolling_code\":" + String(reading.rollingCode);
            j += ",\"battery\":\"" + String(batteryStatusName(reading)) + "\"";
            j += ",\"rssi\":" + String(reading.rssi, 1) + "}";
            snprintf(suffix, sizeof(suffix), "oregon/thermo/ch%u/state", reading.channel);
            client.publish(topic(suffix).c_str(), j.c_str(), true);
        }
    }''',
    "mqtt thermo publish")
write(p, s)

# -----------------------------------------------------------------------------
# Web UI/API.
# -----------------------------------------------------------------------------
p = "src/web_manager.cpp"
s = read(p)
s = replace_once(s, '#include "lightning_manager.h"\n', '#include "lightning_manager.h"\n#include "thermo_channel_manager.h"\n', "web include")

# Add multichannel state after the existing primary/other sensor metadata.
state_anchor = '''    out += ",\\\"sensors\\\":{";
    appendSensorJson(out, "thermo", station->thermoSensor, false);
    appendSensorJson(out, "wind", station->windSensor, true);
    appendSensorJson(out, "rain", station->rainSensor, true);
    appendSensorJson(out, "uv", station->uvSensor, true);
    out += "}";'''
state_new = state_anchor + r'''

    const ThermoChannelConfig thermoCfg = getThermoChannelConfig();
    const uint8_t thermoDetected = thermoDetectedMask();
    const uint8_t thermoVisible = thermoEffectiveMask();
    out += ",\"oregon_thermo\":{";
    out += "\"enabled_mask\":" + String(thermoCfg.enabledMask);
    out += ",\"detected_mask\":" + String(thermoDetected);
    out += ",\"visible_mask\":" + String(thermoVisible);
    out += ",\"primary_channel\":" + String(thermoCfg.primaryChannel);
    out += ",\"auto_discover\":"; out += thermoCfg.autoDiscover ? "true" : "false";
    out += ",\"channels\":[";
    for (uint8_t ch = 1; ch <= 3; ++ch) {
        if (ch > 1) out += ",";
        const ThermoChannelState ts = getThermoChannelState(ch);
        const uint8_t bit = static_cast<uint8_t>(1U << (ch - 1U));
        out += "{\"channel\":" + String(ch);
        out += ",\"detected\":"; out += (thermoDetected & bit) ? "true" : "false";
        out += ",\"enabled\":"; out += (thermoCfg.enabledMask & bit) ? "true" : "false";
        out += ",\"visible\":"; out += (thermoVisible & bit) ? "true" : "false";
        out += ",\"valid\":"; out += ts.valid ? "true" : "false";
        out += ",\"fresh\":"; out += (ts.valid && sensorFresh(ts.updatedMs, now)) ? "true" : "false";
        out += ",\"session_acquired\":"; out += timestampInSession(ts.updatedMs, rfSession.startedMs) ? "true" : "false";
        out += ",\"temperature_c\":" + jsonFloat(ts.temperatureC, 1);
        out += ",\"humidity_pct\":" + jsonFloat(ts.humidityPct, 0);
        out += ",\"age_s\":" + String(ageSeconds(ts.updatedMs, now));
        out += ",\"rssi\":" + jsonFloat(ts.lastRssi, 1);
        out += ",\"code\":\"" + hex4(ts.sensor.code) + "\"";
        out += ",\"model\":\"" + String(sensorModelName(ts.sensor.code)) + "\"";
        out += ",\"rolling_code\":" + String(ts.sensor.rollingCode);
        out += ",\"battery\":\"" + String(sensorBatteryName(ts.sensor)) + "\"";
        out += ",\"packet_count\":" + String(ts.packetCount) + "}";
    }
    out += "]}";'''
s = replace_once(s, state_anchor, state_new, "web state thermo JSON")

# API handlers before display handlers.
handler_anchor = "\nvoid handleDisplayPower() {"
handlers = r'''

void handleThermoConfigGet() {
    const ThermoChannelConfig c = getThermoChannelConfig();
    String out = "{\"enabled_mask\":" + String(c.enabledMask);
    out += ",\"detected_mask\":" + String(thermoDetectedMask());
    out += ",\"visible_mask\":" + String(thermoEffectiveMask());
    out += ",\"primary_channel\":" + String(c.primaryChannel);
    out += ",\"auto_discover\":"; out += c.autoDiscover ? "true" : "false";
    out += "}";
    sendNoCache();
    server.send(200, "application/json", out);
}

void handleThermoConfigPost() {
    ThermoChannelConfig c = getThermoChannelConfig();
    if (server.hasArg("enabled_mask")) c.enabledMask = static_cast<uint8_t>(server.arg("enabled_mask").toInt());
    if (server.hasArg("primary_channel")) c.primaryChannel = static_cast<uint8_t>(server.arg("primary_channel").toInt());
    if (server.hasArg("auto_discover")) {
        const String v = server.arg("auto_discover");
        c.autoDiscover = v == "1" || v == "true" || v == "on";
    }
    if (c.primaryChannel < 1U || c.primaryChannel > 3U || (c.enabledMask & 0xF8U)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid thermo channel configuration\"}");
        return;
    }
    if (!saveThermoChannelConfig(c)) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"thermo NVS verification failed\"}");
        return;
    }
    if (station) syncPrimaryThermoState(*station);
    handleThermoConfigGet();
}

void handleThermoConfigReset() {
    if (!resetThermoChannelConfig()) {
        server.send(500, "application/json", "{\"ok\":false}");
        return;
    }
    if (station) syncPrimaryThermoState(*station);
    handleThermoConfigGet();
}
'''
s = replace_once(s, handler_anchor, handlers + handler_anchor, "web thermo handlers")

# Small tab styling; reuses existing modeBtn colors.
css_anchor = "@media(max-width:760px)"
css = ".thermoTabs{display:flex;gap:4px;margin-left:auto}.thermoTab{display:none;padding:3px 7px;font-size:.68rem}.thermoTab.show{display:inline-flex}.cardTitle:has(.thermoTabs){gap:6px;flex-wrap:wrap}\n"
s = replace_once(s, css_anchor, css + css_anchor, "web thermo css")

# Dashboard THGN card tabs + hideable derived rows.
card_anchor = '<section class=\\"card good\\"><div class=\\"cardTitle\\">Temperatura e umidita<svg class=\\"spark\\" id=\\"spTemp\\"></svg></div><div class=\\"body\\">'
card_new = '<section class=\\"card good\\"><div class=\\"cardTitle\\"><span>Temperatura e umidita</span><span class=\\"thermoTabs\\"><button id=\\"tch1\\" class=\\"modeBtn thermoTab\\" onclick=\\"selectThermoChannel(1)\\">CH1</button><button id=\\"tch2\\" class=\\"modeBtn thermoTab\\" onclick=\\"selectThermoChannel(2)\\">CH2</button><button id=\\"tch3\\" class=\\"modeBtn thermoTab\\" onclick=\\"selectThermoChannel(3)\\">CH3</button></span><svg class=\\"spark\\" id=\\"spTemp\\"></svg></div><div class=\\"body\\">'
s = replace_once(s, card_anchor, card_new, "web thermo dashboard tabs")
s = replace_once(s, '<div class=\\"row\\"><div class=\\"name\\">Heat index esterno</div>', '<div class=\\"row\\" id=\\"thermoDerivedHeat\\"><div class=\\"name\\">Heat index esterno</div>', "web heat row id")
s = replace_once(s, '<div class=\\"row\\"><div class=\\"name\\">Punto di rugiada</div>', '<div class=\\"row\\" id=\\"thermoDerivedDew\\"><div class=\\"name\\">Punto di rugiada</div>', "web dew row id")

# New OREGON configuration tab/page.
tab_anchor = '<button id=\\"tabMqtt\\" class=\\"cfgTab\\" onclick=\\"showCfgTab(\'mqtt\')\\">MQTT / TLS</button>'
tab_new = '<button id=\\"tabThermo\\" class=\\"cfgTab\\" onclick=\\"showCfgTab(\'thermo\')\\">OREGON</button>' + tab_anchor
s = replace_once(s, tab_anchor, tab_new, "web config tab")

mqtt_page_anchor = '<div id=\\"cfgMqtt\\" class=\\"cfgPage\\">'
thermo_page = r'''<div id=\"cfgThermo\" class=\"cfgPage\">
<div class=\"cfgGrid\">
<label><span>Canale meteo principale</span><select id=\"thPrimary\"><option value=\"1\">CH1</option><option value=\"2\">CH2</option><option value=\"3\">CH3</option></select></label>
<label class=\"checkLine\"><input id=\"thAuto\" type=\"checkbox\"><span>Mostra/pubblica automaticamente i canali rilevati</span></label>
</div>
<div class=\"fieldGrid\"><div class=\"fieldGroup\"><b>Canali termoigrometrici</b>
<label class=\"fieldCheck\"><input id=\"thCh1\" type=\"checkbox\">CH1 <span id=\"thSt1\" class=\"muted\">--</span></label>
<label class=\"fieldCheck\"><input id=\"thCh2\" type=\"checkbox\">CH2 <span id=\"thSt2\" class=\"muted\">--</span></label>
<label class=\"fieldCheck\"><input id=\"thCh3\" type=\"checkbox\">CH3 <span id=\"thSt3\" class=\"muted\">--</span></label>
</div></div>
<div class=\"cfgActions\"><button class=\"modeBtn\" onclick=\"saveThermo()\">Salva OREGON</button><button class=\"modeBtn\" onclick=\"resetThermo()\">Default firmware</button><span id=\"thermoSummary\" class=\"muted\"></span></div>
<div class=\"cfgNote\"><b>Canale principale:</b> alimenta temperatura/umidita legacy, dew point, heat index, wind chill e i topic MQTT storici. I canali abilitati restano visibili anche senza segnale. Con auto-rilevamento attivo, CH2/CH3 compaiono e vengono pubblicati MQTT appena ricevuti.</div>
</div>
'''
s = replace_once(s, mqtt_page_anchor, thermo_page + mqtt_page_anchor, "web thermo config page")

# MQTT note: tell the user where channel selection lives.
s = s.replace("Password, CA e mask campi vengono scritti in NVS soltanto se cambiano.", "I canali THGN CH1-CH3 seguono CONFIGURAZIONE &gt; OREGON. Password, CA e mask campi vengono scritti in NVS soltanto se cambiano.", 1)

# JS config navigation and functions.
s = replace_once(s,
    "for(const x of ['net','mqtt','display','lightning','backup'])",
    "for(const x of ['net','thermo','mqtt','display','lightning','backup'])",
    "web cfg tab array")
s = replace_once(s,
    "if(t==='net')loadNetwork();else if(t==='mqtt')loadMqtt();else if(t==='display')loadDisplay();else if(t==='lightning')loadLightning();",
    "if(t==='net')loadNetwork();else if(t==='thermo')loadThermo();else if(t==='mqtt')loadMqtt();else if(t==='display')loadDisplay();else if(t==='lightning')loadLightning();",
    "web cfg tab loader")

mqtt_js_anchor = "function mqttSelectAll(v){"
thermo_js = r'''async function loadThermo(){try{const c=await (await fetch('/api/thermo/config',{cache:'no-store'})).json();E('thPrimary').value=String(c.primary_channel||1);E('thAuto').checked=!!c.auto_discover;for(let ch=1;ch<=3;ch++){const bit=1<<(ch-1);E('thCh'+ch).checked=(Number(c.enabled_mask)&bit)!==0;const det=(Number(c.detected_mask)&bit)!==0;E('thSt'+ch).textContent=det?'RILEVATO':'non rilevato';E('thSt'+ch).className=det?'ok':'muted'}E('thermoSummary').textContent='principale CH'+c.primary_channel+' · manuali 0x'+Number(c.enabled_mask).toString(16).toUpperCase()+' · visibili/MQTT 0x'+Number(c.visible_mask).toString(16).toUpperCase();}catch(e){E('thermoSummary').textContent='errore lettura canali Oregon'}}
async function saveThermo(){let m=0;for(let ch=1;ch<=3;ch++)if(E('thCh'+ch).checked)m|=1<<(ch-1);const p=Number(E('thPrimary').value||1);m|=1<<(p-1);const q=new URLSearchParams();q.set('enabled_mask',String(m));q.set('primary_channel',String(p));q.set('auto_discover',E('thAuto').checked?'1':'0');const r=await fetch('/api/thermo/config',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});if(!r.ok){alert('OREGON: '+await r.text());return}await loadThermo();}
async function resetThermo(){if(!confirm('Ripristinare CH1 come canale principale e auto-rilevamento attivo?'))return;const r=await fetch('/api/thermo/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset canali Oregon fallito');return}await loadThermo();}

'''
s = replace_once(s, mqtt_js_anchor, thermo_js + mqtt_js_anchor, "web thermo JS config")

# Dashboard selector state.
hist_anchor = "const hist={temp:[],bmeTemp:[],press:[],wind:[],rain:[],uv:[],lcTemp:[],lcWind:[],lcRain:[]};"
s = replace_once(s, hist_anchor, hist_anchor + "let thermoViewChannel=1;function selectThermoChannel(c){thermoViewChannel=Number(c)||1}", "web thermo view state")

# Add API state object to refresh destructuring.
s = replace_once(s,
    "wp=s.wgr_probe||{},sys=s.system||{};",
    "wp=s.wgr_probe||{},sys=s.system||{},th=s.oregon_thermo||{};",
    "web refresh thermo object")

# Replace old single-thermo rendering with tab-aware rendering.
old_render = "if(isO&&!sess.thermo_acquired){showOrWait(temp,false,'');showOrWait(hum,false,'');showOrWait(hi,false,'');showOrWait(dew,false,'');ageT.textContent='ultimo dato '+age(a.thermo_age_s)}else{showOrWait(temp,true,f(w.temperature_c,1,' °C'));showOrWait(hum,true,f(w.humidity_pct,0,' %'));showOrWait(hi,true,w.heat_index_c==null?'N/A':f(w.heat_index_c,1,' °C'));showOrWait(dew,true,f(w.dew_point_c,1,' °C'));ageT.textContent=age(a.thermo_age_s)}footT.innerHTML='AF: '+p.AF+' · sessione '+sess.thermo_received+' · '+ss.thermo.model+' '+ss.thermo.code+' · '+batt(ss.thermo);setFresh('ageT',a.thermo_age_s,isO&&sess.thermo_acquired);"
new_render = r'''const thMask=Number(th.visible_mask||0),thPrimary=Number(th.primary_channel||1);if(!(thMask&(1<<(thermoViewChannel-1))))thermoViewChannel=thPrimary;for(let ch=1;ch<=3;ch++){const bt=E('tch'+ch),vis=(thMask&(1<<(ch-1)))!==0;if(bt){bt.classList.toggle('show',vis);bt.classList.toggle('active',ch===thermoViewChannel);bt.textContent='CH'+ch+(ch===thPrimary?'*':'')}}const tv=((th.channels||[])[thermoViewChannel-1])||{},primaryView=thermoViewChannel===thPrimary,tvOk=isO&&!!tv.valid&&!!tv.session_acquired;E('thermoDerivedHeat').style.display=primaryView?'flex':'none';E('thermoDerivedDew').style.display=primaryView?'flex':'none';E('spTemp').style.display=primaryView?'block':'none';if(!tvOk){showOrWait(temp,false,'');showOrWait(hum,false,'');if(primaryView){showOrWait(hi,false,'');showOrWait(dew,false,'')}ageT.textContent='ultimo dato '+age(tv.age_s)}else{showOrWait(temp,true,f(tv.temperature_c,1,' °C'));showOrWait(hum,true,f(tv.humidity_pct,0,' %'));if(primaryView){showOrWait(hi,true,w.heat_index_c==null?'N/A':f(w.heat_index_c,1,' °C'));showOrWait(dew,true,f(w.dew_point_c,1,' °C'))}ageT.textContent=age(tv.age_s)}footT.innerHTML='CH'+thermoViewChannel+(primaryView?' principale':'')+' · '+(tv.model||'OSV3')+' '+(tv.code||'----')+' · BAT '+(tv.battery||'N/D')+' · RSSI '+f(tv.rssi,1,' dBm')+' · pkt '+(tv.packet_count||0);setFresh('ageT',tv.age_s,tvOk);'''
s = replace_once(s, old_render, new_render, "web thermo dashboard render")

# Backup/export: persist routing config.
backup_export_anchor = "    const LightningConfig l = getLightningConfig();\n"
backup_export = r'''    const ThermoChannelConfig tc = getThermoChannelConfig();
    out += ",\n  \"thermo_enabled_mask\":" + String(tc.enabledMask);
    out += ",\n  \"thermo_primary_channel\":" + String(tc.primaryChannel);
    out += ",\n  \"thermo_auto_discover\":"; out += tc.autoDiscover ? "true" : "false";
'''
s = replace_once(s, backup_export_anchor, backup_export + backup_export_anchor, "web backup export thermo")

backup_import_anchor = "    LightningConfig lightningCfg = getLightningConfig();\n"
backup_import = r'''    ThermoChannelConfig thermoCfg = getThermoChannelConfig();
    if (jsonGetUInt(body, "thermo_enabled_mask", tmpUInt)) thermoCfg.enabledMask = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "thermo_primary_channel", tmpUInt)) thermoCfg.primaryChannel = static_cast<uint8_t>(tmpUInt);
    if (jsonGetBool(body, "thermo_auto_discover", tmpBool)) thermoCfg.autoDiscover = tmpBool;
    if (!saveThermoChannelConfig(thermoCfg)) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid thermo channel backup values\"}");
        return;
    }
    if (station) syncPrimaryThermoState(*station);

'''
s = replace_once(s, backup_import_anchor, backup_import + backup_import_anchor, "web backup import thermo")

# API routes.
route_anchor = '    server.on("/api/display", HTTP_POST, handleDisplayPower);\n'
routes = '    server.on("/api/thermo/config", HTTP_GET, handleThermoConfigGet);\n    server.on("/api/thermo/config", HTTP_POST, handleThermoConfigPost);\n    server.on("/api/thermo/reset", HTTP_POST, handleThermoConfigReset);\n'
s = replace_once(s, route_anchor, routes + route_anchor, "web thermo routes")
write(p, s)

# Remove staging files from the final branch; the workflow commits only product code.
for rel in ["scripts/apply_multichannel_thermo.py", ".github/workflows/multichannel-thermo-integrate.yml"]:
    target = ROOT / rel
    if target.exists():
        target.unlink()

print("Multichannel Oregon thermo integration applied successfully")
