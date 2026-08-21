from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def replace_once(path, old, new, label):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{path}: anchor not found: {label}")
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")

replace_once("src/display_manager.h",
'''static constexpr uint8_t DISPLAY_PAGE_PRESSURE    = 1U << 3;
static constexpr uint8_t DISPLAY_PAGE_STATUS      = 1U << 4;
static constexpr uint8_t DISPLAY_PAGE_ALL         = 0x1FU;
''',
'''static constexpr uint8_t DISPLAY_PAGE_PRESSURE    = 1U << 3;
static constexpr uint8_t DISPLAY_PAGE_STATUS      = 1U << 4;
static constexpr uint8_t DISPLAY_PAGE_LIGHTNING   = 1U << 5;
static constexpr uint8_t DISPLAY_PAGE_ALL         = 0x3FU;
''', "display page lightning")

replace_once("src/display_manager.h",
'''static constexpr uint8_t DISPLAY_STATUS_ALL      = 0x1FU;

struct DisplayRuntimeConfig {
''',
'''static constexpr uint8_t DISPLAY_STATUS_ALL      = 0x1FU;

static constexpr uint8_t DISPLAY_AS_STATUS       = 1U << 0;
static constexpr uint8_t DISPLAY_AS_LAST_STRIKE  = 1U << 1;
static constexpr uint8_t DISPLAY_AS_COUNTERS     = 1U << 2;
static constexpr uint8_t DISPLAY_AS_FILTERS      = 1U << 3;
static constexpr uint8_t DISPLAY_AS_BUS_TUNING   = 1U << 4;
static constexpr uint8_t DISPLAY_AS_ALL          = 0x1FU;

struct DisplayRuntimeConfig {
''', "display AS fields constants")

replace_once("src/display_manager.h",
'''    uint8_t pressureFields{DISPLAY_PRESS_ALL};
    uint8_t statusFields{DISPLAY_STATUS_ALL};
''',
'''    uint8_t pressureFields{DISPLAY_PRESS_ALL};
    uint8_t statusFields{DISPLAY_STATUS_ALL};
    uint8_t lightningFields{DISPLAY_AS_ALL};
''', "display AS runtime field")

replace_once("src/display_manager.cpp",
'''#include "oregon_receiver.h"
''',
'''#include "oregon_receiver.h"
#include "lightning_manager.h"
''', "include lightning manager")

replace_once("src/display_manager.cpp",
'''    c.pressureFields &= DISPLAY_PRESS_ALL;
    c.statusFields &= DISPLAY_STATUS_ALL;
''',
'''    c.pressureFields &= DISPLAY_PRESS_ALL;
    c.statusFields &= DISPLAY_STATUS_ALL;
    c.lightningFields &= DISPLAY_AS_ALL;
''', "normalize lightning fields")

replace_once("src/display_manager.cpp",
'''           a.pressureFields == b.pressureFields &&
           a.statusFields == b.statusFields &&
''',
'''           a.pressureFields == b.pressureFields &&
           a.statusFields == b.statusFields &&
           a.lightningFields == b.lightningFields &&
''', "same config lightning")

replace_once("src/display_manager.cpp",
'''           p.getUChar("press", d.pressureFields) == c.pressureFields &&
           p.getUChar("status", d.statusFields) == c.statusFields &&
''',
'''           p.getUChar("press", d.pressureFields) == c.pressureFields &&
           p.getUChar("status", d.statusFields) == c.statusFields &&
           p.getUChar("as3935", d.lightningFields) == c.lightningFields &&
''', "verify lightning NVS")

replace_once("src/display_manager.cpp",
'''bool pageEnabled(uint8_t p) {
    return p < 5U && (displayCfg.pageMask & static_cast<uint8_t>(1U << p)) != 0U;
}

uint8_t firstEnabledPage() {
    for (uint8_t p = 0; p < 5U; ++p) if (pageEnabled(p)) return p;
    return 0U;
}

uint8_t nextEnabledPage(uint8_t current) {
    for (uint8_t step = 1; step <= 5U; ++step) {
        const uint8_t p = static_cast<uint8_t>((current + step) % 5U);
''',
'''bool pageEnabled(uint8_t p) {
    return p < 6U && (displayCfg.pageMask & static_cast<uint8_t>(1U << p)) != 0U;
}

uint8_t firstEnabledPage() {
    for (uint8_t p = 0; p < 6U; ++p) if (pageEnabled(p)) return p;
    return 0U;
}

uint8_t nextEnabledPage(uint8_t current) {
    for (uint8_t step = 1; step <= 6U; ++step) {
        const uint8_t p = static_cast<uint8_t>((current + step) % 6U);
''', "six display pages")

render_lightning = r'''
void renderLightning(bool wifiOk, bool mqttOk) {
    header("AS3935 FULMINI", wifiOk, mqttOk);
    char line[56];
    oled.setFont(u8g2_font_5x8_tf);
    uint8_t y = 23;
    const LightningState s = getLightningState();
    const LightningConfig c = getLightningConfig();

    if (displayCfg.lightningFields & DISPLAY_AS_STATUS) {
        if (!s.enabled) snprintf(line, sizeof(line), "Sensore DISABILITATO");
        else snprintf(line, sizeof(line), "Sens %s IRQ %s CAL %s",
                      s.detected ? "OK" : "KO", s.irqOk ? "OK" : "KO", s.calibrationOk ? "OK" : "KO");
        drawLine(line, y);
    }
    if (displayCfg.lightningFields & DISPLAY_AS_LAST_STRIKE) {
        if (!s.lastLightningMs) snprintf(line, sizeof(line), "Ultimo fulmine --");
        else if (s.distanceOutOfRange) snprintf(line, sizeof(line), "Ult >40km E%lu", static_cast<unsigned long>(s.lastEnergy));
        else snprintf(line, sizeof(line), "Ult %ukm E%lu", s.lastDistanceKm, static_cast<unsigned long>(s.lastEnergy));
        drawLine(line, y);
    }
    if (displayCfg.lightningFields & DISPLAY_AS_COUNTERS) {
        snprintf(line, sizeof(line), "L%lu N%lu D%lu IRQ%lu",
                 static_cast<unsigned long>(s.lightningTotal), static_cast<unsigned long>(s.noiseTotal),
                 static_cast<unsigned long>(s.disturberTotal), static_cast<unsigned long>(s.irqTotal));
        drawLine(line, y);
    }
    if (displayCfg.lightningFields & DISPLAY_AS_FILTERS) {
        snprintf(line, sizeof(line), "%s NF%u WD%u SP%u M%u",
                 c.indoor ? "IN" : "OUT", c.noiseFloor, c.watchdogThreshold, c.spikeRejection, c.minStrikes);
        drawLine(line, y);
    }
    if (displayCfg.lightningFields & DISPLAY_AS_BUS_TUNING) {
        snprintf(line, sizeof(line), "I2C%02X GPIO%d %ldkHz",
                 c.i2cAddress, static_cast<int>(c.irqPin), static_cast<long>(s.resonanceHz / 1000L));
        drawLine(line, y);
    }
    if (y == 23) drawLine("Nessun campo selezionato", y);
}

'''
replace_once("src/display_manager.cpp",
'''void renderStatus(const StationState &, const OregonRxStats &rx, const LaCrosseRxStats &lc, bool wifiOk, bool mqttOk) {
''',
render_lightning + '''void renderStatus(const StationState &, const OregonRxStats &rx, const LaCrosseRxStats &lc, bool wifiOk, bool mqttOk) {
''', "render lightning page")

replace_once("src/display_manager.cpp",
'''        displayCfg.pressureFields = displayPrefs.getUChar("press", d.pressureFields);
        displayCfg.statusFields = displayPrefs.getUChar("status", d.statusFields);
''',
'''        displayCfg.pressureFields = displayPrefs.getUChar("press", d.pressureFields);
        displayCfg.statusFields = displayPrefs.getUChar("status", d.statusFields);
        displayCfg.lightningFields = displayPrefs.getUChar("as3935", d.lightningFields);
''', "load lightning display fields")

replace_once("src/display_manager.cpp",
'''    if ((cfg.pressureFields & ~DISPLAY_PRESS_ALL) != 0U) return false;
    if ((cfg.statusFields & ~DISPLAY_STATUS_ALL) != 0U) return false;
''',
'''    if ((cfg.pressureFields & ~DISPLAY_PRESS_ALL) != 0U) return false;
    if ((cfg.statusFields & ~DISPLAY_STATUS_ALL) != 0U) return false;
    if ((cfg.lightningFields & ~DISPLAY_AS_ALL) != 0U) return false;
''', "validate lightning display fields")

replace_once("src/display_manager.cpp",
'''    if (next.pressureFields != displayCfg.pressureFields) displayPrefs.putUChar("press", next.pressureFields);
    if (next.statusFields != displayCfg.statusFields) displayPrefs.putUChar("status", next.statusFields);
''',
'''    if (next.pressureFields != displayCfg.pressureFields) displayPrefs.putUChar("press", next.pressureFields);
    if (next.statusFields != displayCfg.statusFields) displayPrefs.putUChar("status", next.statusFields);
    if (next.lightningFields != displayCfg.lightningFields) displayPrefs.putUChar("as3935", next.lightningFields);
''', "save lightning display fields")

replace_once("src/display_manager.cpp",
'''    else if (page == 3) renderPressure(state, wifiOk, mqttOk);
    else renderStatus(state, rxStats, lcStats, wifiOk, mqttOk);
''',
'''    else if (page == 3) renderPressure(state, wifiOk, mqttOk);
    else if (page == 4) renderStatus(state, rxStats, lcStats, wifiOk, mqttOk);
    else renderLightning(wifiOk, mqttOk);
''', "display lightning switch")

replace_once("src/mqtt_publisher.h",
'''    MQTT_F_STATE_JSON     = 1UL << 25,
    MQTT_F_RF_META        = 1UL << 26,
    MQTT_F_SYSTEM         = 1UL << 27
};

static constexpr uint32_t MQTT_FIELDS_ALL = 0x0FFFFFFFUL;
''',
'''    MQTT_F_STATE_JSON     = 1UL << 25,
    MQTT_F_RF_META        = 1UL << 26,
    MQTT_F_SYSTEM         = 1UL << 27,
    MQTT_F_AS_STATE       = 1UL << 28,
    MQTT_F_AS_EVENT       = 1UL << 29,
    MQTT_F_AS_LAST_STRIKE = 1UL << 30,
    MQTT_F_AS_DIAG        = 1UL << 31
};

static constexpr uint32_t MQTT_FIELDS_ALL = 0xFFFFFFFFUL;
''', "MQTT AS fields")

old_publish = r'''void publishMqttState(PubSubClient &client) {
    const MqttRuntimeConfig mqtt = getMqttConfig();
    if (!mqtt.enabled || !client.connected()) return;
    const String topic = mqtt.baseTopic + "/as3935/state";
    const String json = lightningStateJson();
    client.publish(topic.c_str(), json.c_str(), true);
}

void publishMqttEvent(PubSubClient &client, uint8_t source) {
    const MqttRuntimeConfig mqtt = getMqttConfig();
    if (!mqtt.enabled || !client.connected()) return;

    String json;
    json.reserve(320);
    json = "{\"type\":\"" + String(lightningInterruptName(source)) + "\"";
    json += ",\"source\":" + String(source);
    json += ",\"uptime_ms\":" + String(state.lastEventMs);
    json += ",\"irq_total\":" + String(state.irqTotal);
    json += ",\"noise_total\":" + String(state.noiseTotal);
    json += ",\"disturber_total\":" + String(state.disturberTotal);
    json += ",\"lightning_total\":" + String(state.lightningTotal);
    if (source == AS3935MI::AS3935_INT_L) {
        if (state.distanceOutOfRange) json += ",\"distance_km\":null";
        else json += ",\"distance_km\":" + String(state.lastDistanceKm);
        json += ",\"distance_out_of_range\":";
        json += state.distanceOutOfRange ? "true" : "false";
        json += ",\"energy\":" + String(state.lastEnergy);
    }
    json += "}";

    client.publish((mqtt.baseTopic + "/as3935/event").c_str(), json.c_str(), false);
    publishMqttState(client);
}
'''
new_publish = r'''bool mqttFieldEnabled(const MqttRuntimeConfig &mqtt, uint32_t bit) {
    return (mqtt.fieldsMask & bit) != 0U;
}

void publishMqttState(PubSubClient &client) {
    const MqttRuntimeConfig mqtt = getMqttConfig();
    if (!mqtt.enabled || !client.connected()) return;

    if (mqttFieldEnabled(mqtt, MQTT_F_AS_STATE)) {
        const String json = lightningStateJson();
        client.publish((mqtt.baseTopic + "/as3935/state").c_str(), json.c_str(), true);
    }

    if (mqttFieldEnabled(mqtt, MQTT_F_AS_LAST_STRIKE)) {
        String json;
        json.reserve(150);
        json = "{\"last_lightning_ms\":" + String(state.lastLightningMs);
        if (!state.lastLightningMs || state.distanceOutOfRange) json += ",\"distance_km\":null";
        else json += ",\"distance_km\":" + String(state.lastDistanceKm);
        json += ",\"distance_out_of_range\":";
        json += state.distanceOutOfRange ? "true" : "false";
        json += ",\"energy\":" + String(state.lastEnergy) + "}";
        client.publish((mqtt.baseTopic + "/as3935/last_strike").c_str(), json.c_str(), true);
    }

    if (mqttFieldEnabled(mqtt, MQTT_F_AS_DIAG)) {
        String json;
        json.reserve(240);
        json = "{\"detected\":";
        json += state.detected ? "true" : "false";
        json += ",\"irq_ok\":"; json += state.irqOk ? "true" : "false";
        json += ",\"calibration_ok\":"; json += state.calibrationOk ? "true" : "false";
        json += ",\"resonance_hz\":" + String(state.resonanceHz);
        json += ",\"irq_total\":" + String(state.irqTotal);
        json += ",\"noise_total\":" + String(state.noiseTotal);
        json += ",\"disturber_total\":" + String(state.disturberTotal);
        json += ",\"lightning_total\":" + String(state.lightningTotal);
        json += ",\"last_type\":\"" + String(state.lastEventMs ? lightningInterruptName(state.lastInterruptSource) : "none") + "\"}";
        client.publish((mqtt.baseTopic + "/as3935/diagnostics").c_str(), json.c_str(), true);
    }
}

void publishMqttEvent(PubSubClient &client, uint8_t source) {
    const MqttRuntimeConfig mqtt = getMqttConfig();
    if (!mqtt.enabled || !client.connected()) return;

    if (mqttFieldEnabled(mqtt, MQTT_F_AS_EVENT)) {
        String json;
        json.reserve(320);
        json = "{\"type\":\"" + String(lightningInterruptName(source)) + "\"";
        json += ",\"source\":" + String(source);
        json += ",\"uptime_ms\":" + String(state.lastEventMs);
        json += ",\"irq_total\":" + String(state.irqTotal);
        json += ",\"noise_total\":" + String(state.noiseTotal);
        json += ",\"disturber_total\":" + String(state.disturberTotal);
        json += ",\"lightning_total\":" + String(state.lightningTotal);
        if (source == AS3935MI::AS3935_INT_L) {
            if (state.distanceOutOfRange) json += ",\"distance_km\":null";
            else json += ",\"distance_km\":" + String(state.lastDistanceKm);
            json += ",\"distance_out_of_range\":";
            json += state.distanceOutOfRange ? "true" : "false";
            json += ",\"energy\":" + String(state.lastEnergy);
        }
        json += "}";
        client.publish((mqtt.baseTopic + "/as3935/event").c_str(), json.c_str(), false);
    }
    publishMqttState(client);
}
'''
replace_once("src/lightning_manager.cpp", old_publish, new_publish, "selectable AS MQTT")

replace_once("src/web_manager.cpp",
'''    out += ",\\\"pressure_fields\\\":" + String(c.pressureFields);
    out += ",\\\"status_fields\\\":" + String(c.statusFields);
''',
'''    out += ",\\\"pressure_fields\\\":" + String(c.pressureFields);
    out += ",\\\"status_fields\\\":" + String(c.statusFields);
    out += ",\\\"lightning_fields\\\":" + String(c.lightningFields);
''', "web display get lightning")

replace_once("src/web_manager.cpp",
'''    if (server.hasArg("pressure_fields")) c.pressureFields = static_cast<uint8_t>(server.arg("pressure_fields").toInt());
    if (server.hasArg("status_fields")) c.statusFields = static_cast<uint8_t>(server.arg("status_fields").toInt());
''',
'''    if (server.hasArg("pressure_fields")) c.pressureFields = static_cast<uint8_t>(server.arg("pressure_fields").toInt());
    if (server.hasArg("status_fields")) c.statusFields = static_cast<uint8_t>(server.arg("status_fields").toInt());
    if (server.hasArg("lightning_fields")) c.lightningFields = static_cast<uint8_t>(server.arg("lightning_fields").toInt());
''', "web display post lightning")

replace_once("src/web_manager.cpp",
'''    out += ",\\n  \\\"display_pressure_fields\\\":" + String(d.pressureFields);
    out += ",\\n  \\\"display_status_fields\\\":" + String(d.statusFields);
''',
'''    out += ",\\n  \\\"display_pressure_fields\\\":" + String(d.pressureFields);
    out += ",\\n  \\\"display_status_fields\\\":" + String(d.statusFields);
    out += ",\\n  \\\"display_lightning_fields\\\":" + String(d.lightningFields);
''', "backup display lightning")

replace_once("src/web_manager.cpp",
'''    if (jsonGetUInt(body, "display_pressure_fields", tmpUInt)) displayCfg.pressureFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_status_fields", tmpUInt)) displayCfg.statusFields = static_cast<uint8_t>(tmpUInt);
''',
'''    if (jsonGetUInt(body, "display_pressure_fields", tmpUInt)) displayCfg.pressureFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_status_fields", tmpUInt)) displayCfg.statusFields = static_cast<uint8_t>(tmpUInt);
    if (jsonGetUInt(body, "display_lightning_fields", tmpUInt)) displayCfg.lightningFields = static_cast<uint8_t>(tmpUInt);
''', "restore display lightning")

replace_once("src/web_manager.cpp",
'''.cfgPanel{padding-bottom:2px}.cfgGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:14px}.cfgGrid label{display:flex;flex-direction:column;gap:6px;color:var(--muted);font-size:.78rem}.cfgGrid input[type=text],.cfgGrid input[type=password],.cfgGrid input[type=number],.cfgGrid select,.cfgGrid textarea{background:#081423;border:1px solid var(--border);color:var(--text);border-radius:8px;padding:9px}.cfgGrid textarea{min-height:150px;resize:vertical;font:11px ui-monospace,SFMono-Regular,Consolas,monospace}.cfgWide{grid-column:1/-1}.fieldGrid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:8px;padding:0 14px 14px}.fieldGroup{border:1px solid var(--border);border-radius:10px;padding:10px;background:#0b1727}.fieldGroup b{display:block;margin-bottom:7px}.fieldCheck{display:flex;gap:7px;align-items:center;color:#b5c8e1;font-size:.78rem;padding:3px 0}.cfgGrid .checkLine{flex-direction:row;align-items:center}.cfgActions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:0 14px 14px}.cfgTabs{display:flex;gap:8px;padding:12px 14px 0;overflow:auto}.cfgTab{border:1px solid var(--border);background:#111d2d;color:var(--text);padding:8px 14px;border-radius:9px;cursor:pointer;font-weight:700;white-space:nowrap}.cfgTab.active{background:#174d66;border-color:#4aaad8}.cfgPage{display:none}.cfgPage.active{display:block}.cfgNote{padding:0 14px 12px;color:var(--muted);font-size:.78rem;line-height:1.45}
''',
'''.cfgPanel{padding-bottom:2px}.cfgGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:14px}.cfgGrid label{display:flex;flex-direction:column;gap:6px;color:var(--muted);font-size:.78rem}.cfgGrid input[type=text],.cfgGrid input[type=password],.cfgGrid input[type=number],.cfgGrid select,.cfgGrid textarea{background:#081423;border:1px solid var(--border);color:var(--text);border-radius:8px;padding:9px}.cfgGrid textarea{min-height:150px;resize:vertical;font:11px ui-monospace,SFMono-Regular,Consolas,monospace}.cfgWide{grid-column:1/-1}.fieldGrid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:8px;padding:0 14px 14px}.fieldGroup{border:1px solid var(--border);border-radius:10px;padding:10px;background:#0b1727}.fieldGroup b{display:block;margin-bottom:7px}.fieldCheck{display:flex;gap:7px;align-items:center;color:#b5c8e1;font-size:.78rem;padding:3px 0}.cfgGrid .checkLine{flex-direction:row;align-items:center}.cfgActions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:0 14px 14px}.cfgTabs{display:flex;gap:8px;padding:12px 14px 0;overflow:auto}.cfgTab{border:1px solid var(--border);background:#111d2d;color:var(--text);padding:8px 14px;border-radius:9px;cursor:pointer;font-weight:700;white-space:nowrap}.cfgTab.active{background:#174d66;border-color:#4aaad8}.cfgPage{display:none}.cfgPage.active{display:block}.cfgNote{padding:0 14px 12px;color:var(--muted);font-size:.78rem;line-height:1.45}.cfgExplain{display:grid;gap:12px;padding:14px}.cfgSection{border:1px solid var(--border);border-radius:12px;background:#0b1727;overflow:hidden}.cfgSectionHead{padding:11px 13px;background:#0e1b2d;border-bottom:1px solid var(--border);font-weight:800}.cfgSectionSub{display:block;color:var(--muted);font-size:.72rem;font-weight:500;margin-top:3px}.cfgOptionGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:12px}.cfgOption{border:1px solid #213249;border-radius:10px;padding:10px;background:#0d1929}.cfgOption label{display:flex;flex-direction:column;gap:6px;font-weight:750;font-size:.8rem}.cfgOption input[type=number],.cfgOption select{background:#081423;border:1px solid var(--border);color:var(--text);border-radius:8px;padding:9px;width:100%}.cfgOption .cfgCheck{flex-direction:row;align-items:center}.cfgHelp{color:var(--muted);font-size:.72rem;line-height:1.38;margin-top:6px}
''', "guided AS config CSS")

replace_once("src/web_manager.cpp",
'''<div class="fieldGroup"><b>Gateway</b>
<label class="fieldCheck"><input data-mqbit="25" type="checkbox">JSON state completo</label><label class="fieldCheck"><input data-mqbit="26" type="checkbox">Metadati RF / RAW / batterie</label><label class="fieldCheck"><input data-mqbit="27" type="checkbox">Risorse ESP32</label>
</div>
''',
'''<div class="fieldGroup"><b>AS3935 fulmini</b>
<label class="fieldCheck"><input data-mqbit="28" type="checkbox">Stato JSON retained</label><label class="fieldCheck"><input data-mqbit="29" type="checkbox">Eventi IRQ / fulmine</label><label class="fieldCheck"><input data-mqbit="30" type="checkbox">Ultimo fulmine: distanza + energia</label><label class="fieldCheck"><input data-mqbit="31" type="checkbox">Diagnostica / contatori</label>
</div>
<div class="fieldGroup"><b>Gateway</b>
<label class="fieldCheck"><input data-mqbit="25" type="checkbox">JSON state completo</label><label class="fieldCheck"><input data-mqbit="26" type="checkbox">Metadati RF / RAW / batterie</label><label class="fieldCheck"><input data-mqbit="27" type="checkbox">Risorse ESP32</label>
</div>
''', "MQTT AS group")

replace_once("src/web_manager.cpp",
'''<label class="fieldCheck"><input data-dpagebit="0" type="checkbox">Esterno</label><label class="fieldCheck"><input data-dpagebit="1" type="checkbox">Vento / Pioggia</label><label class="fieldCheck"><input data-dpagebit="2" type="checkbox">Technoline</label><label class="fieldCheck"><input data-dpagebit="3" type="checkbox">Barometro</label><label class="fieldCheck"><input data-dpagebit="4" type="checkbox">RF / Status</label>
''',
'''<label class="fieldCheck"><input data-dpagebit="0" type="checkbox">Esterno</label><label class="fieldCheck"><input data-dpagebit="1" type="checkbox">Vento / Pioggia</label><label class="fieldCheck"><input data-dpagebit="2" type="checkbox">Technoline</label><label class="fieldCheck"><input data-dpagebit="3" type="checkbox">Barometro</label><label class="fieldCheck"><input data-dpagebit="4" type="checkbox">RF / Status</label><label class="fieldCheck"><input data-dpagebit="5" type="checkbox">AS3935 fulmini</label>
''', "OLED AS page checkbox")

replace_once("src/web_manager.cpp",
'''<div class="fieldGroup"><b>RF / Status</b>
<label class="fieldCheck"><input data-dstatusbit="0" type="checkbox">Conteggi Oregon</label><label class="fieldCheck"><input data-dstatusbit="1" type="checkbox">Decoder / WGR scan</label><label class="fieldCheck"><input data-dstatusbit="2" type="checkbox">Timing / run</label><label class="fieldCheck"><input data-dstatusbit="3" type="checkbox">Statistiche Technoline</label><label class="fieldCheck"><input data-dstatusbit="4" type="checkbox">IP / rete</label>
</div>
''',
'''<div class="fieldGroup"><b>RF / Status</b>
<label class="fieldCheck"><input data-dstatusbit="0" type="checkbox">Conteggi Oregon</label><label class="fieldCheck"><input data-dstatusbit="1" type="checkbox">Decoder / WGR scan</label><label class="fieldCheck"><input data-dstatusbit="2" type="checkbox">Timing / run</label><label class="fieldCheck"><input data-dstatusbit="3" type="checkbox">Statistiche Technoline</label><label class="fieldCheck"><input data-dstatusbit="4" type="checkbox">IP / rete</label>
</div>
<div class="fieldGroup"><b>AS3935 fulmini</b>
<label class="fieldCheck"><input data-dasbit="0" type="checkbox">Stato sensore / IRQ / calibrazione</label><label class="fieldCheck"><input data-dasbit="1" type="checkbox">Ultimo fulmine + energia</label><label class="fieldCheck"><input data-dasbit="2" type="checkbox">Contatori fulmini / noise / disturber</label><label class="fieldCheck"><input data-dasbit="3" type="checkbox">Modalita e filtri</label><label class="fieldCheck"><input data-dasbit="4" type="checkbox">I2C / GPIO / risonanza</label>
</div>
''', "OLED AS field group")

p = ROOT / "src/web_manager.cpp"
text = p.read_text(encoding="utf-8")
start = text.index('<div id="cfgLightning" class="cfgPage">')
end = text.index('<div id="cfgBackup" class="cfgPage">', start)
guided = r'''<div id="cfgLightning" class="cfgPage">
<div class="cfgExplain">
<section class="cfgSection"><div class="cfgSectionHead">1 · Attivazione e collegamento<span class="cfgSectionSub">Parametri hardware e sensibilita di base del front-end AS3935.</span></div><div class="cfgOptionGrid">
<div class="cfgOption"><label class="cfgCheck"><input id="lgEnabled" type="checkbox"><span>Abilita AS3935</span></label><div class="cfgHelp">Se disattivato il chip viene messo in power-down e non genera IRQ o pubblicazioni MQTT.</div></div>
<div class="cfgOption"><label>Modalita AFE<select id="lgModeCfg"><option value="indoor">Indoor</option><option value="outdoor">Outdoor</option></select></label><div class="cfgHelp">Indoor riduce il guadagno per ambienti elettricamente rumorosi; Outdoor aumenta la sensibilita.</div></div>
<div class="cfgOption"><label>Indirizzo I2C<select id="lgAddr"><option value="1">0x01</option><option value="2">0x02</option><option value="3">0x03</option></select></label><div class="cfgHelp">Default del modulo: 0x03. Cambialo solo se i pin di indirizzo del breakout sono configurati diversamente.</div></div>
<div class="cfgOption"><label>GPIO IRQ<input id="lgIrqPin" type="number" min="0" max="48"></label><div class="cfgHelp">Ingresso interrupt dedicato all'AS3935. Sul T3 V1.6.1 il default e GPIO34; i pin usati da radio, I2C, LED e flash sono rifiutati.</div></div>
</div></section>
<section class="cfgSection"><div class="cfgSectionHead">2 · Filtri di rilevazione<span class="cfgSectionSub">Servono a bilanciare sensibilita e falsi eventi dovuti a disturbi elettrici.</span></div><div class="cfgOptionGrid">
<div class="cfgOption"><label>Noise floor · 0-7<input id="lgNoiseFloor" type="number" min="0" max="7"></label><div class="cfgHelp">Soglia del rumore ambientale. Aumentala solo se il contatore Noise cresce troppo; valori alti riducono la sensibilita.</div></div>
<div class="cfgOption"><label>Watchdog threshold · 0-15<input id="lgWatchdog" type="number" min="0" max="15"></label><div class="cfgHelp">Rende piu severa la qualificazione del segnale. Aumentarlo aiuta contro impulsi deboli o spurii.</div></div>
<div class="cfgOption"><label>Spike rejection · 0-15<input id="lgSpike" type="number" min="0" max="15"></label><div class="cfgHelp">Filtro contro picchi impulsivi brevi. Un valore maggiore scarta piu facilmente disturbi non atmosferici.</div></div>
<div class="cfgOption"><label>Minimo fulmini<select id="lgMinStrikes"><option value="1">1</option><option value="5">5</option><option value="9">9</option><option value="16">16</option></select></label><div class="cfgHelp">Soglia di conferma interna del chip: 1 e la piu reattiva, 5/9/16 sono piu conservative.</div></div>
<div class="cfgOption"><label class="cfgCheck"><input id="lgMaskDist" type="checkbox"><span>Maschera Disturber</span></label><div class="cfgHelp">Impedisce ai disturbi classificati come Disturber di generare IRQ. Per la fase di test conviene lasciarlo spento per misurare l'EMI reale.</div></div>
</div></section>
<section class="cfgSection"><div class="cfgSectionHead">3 · Taratura antenna<span class="cfgSectionSub">La rete LC del sensore deve essere centrata vicino a 500 kHz.</span></div><div class="cfgOptionGrid">
<div class="cfgOption"><label class="cfgCheck"><input id="lgAutoTune" type="checkbox"><span>Auto-tuning all'avvio</span></label><div class="cfgHelp">Fa cercare automaticamente al driver il condensatore di tuning piu vicino alla risonanza nominale.</div></div>
<div class="cfgOption"><label>Tuning capacitor fisso · 0-15<input id="lgTuneCap" type="number" min="0" max="15"></label><div class="cfgHelp">Usato solo con Auto-tuning disattivato. Dopo la modifica controlla il valore di risonanza mostrato nello stato.</div></div>
</div></section>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveLightning()">Salva e applica</button><button class="modeBtn" onclick="reinitLightning()">Rileva / reinizializza</button><button class="modeBtn dangerBtn" onclick="resetLightning()">Default firmware</button><span id="lightningSummary" class="muted"></span></div>
<div class="cfgNote">Suggerimento di collaudo: prima verifica <b>RILEVATO / IRQ OK / CAL OK</b>, poi osserva Noise e Disturber per qualche ora prima di irrigidire i filtri. La ricezione Oregon/Technoline resta indipendente.</div>
</div>
'''
text = text[:start] + guided + text[end:]
p.write_text(text, encoding="utf-8")

replace_once("src/web_manager.cpp",
'''mqttSetMask(m.fields_mask==null?268435455:m.fields_mask);''',
'''mqttSetMask(m.fields_mask==null?4294967295:m.fields_mask);''', "MQTT 32bit fallback")

replace_once("src/web_manager.cpp",
'''const groups=[['data-denvbit',0],['data-dwindbit',1],['data-dtechbit',2],['data-dpressbit',3],['data-dstatusbit',4]];''',
'''const groups=[['data-denvbit',0],['data-dwindbit',1],['data-dtechbit',2],['data-dpressbit',3],['data-dstatusbit',4],['data-dasbit',5]];''', "display auto page AS")

replace_once("src/web_manager.cpp",
'''dSet('data-dpagebit',d.page_mask==null?31:d.page_mask);''',
'''dSet('data-dpagebit',d.page_mask==null?63:d.page_mask);''', "display page default 63")

replace_once("src/web_manager.cpp",
'''dSet('data-dstatusbit',d.status_fields==null?31:d.status_fields);''',
'''dSet('data-dstatusbit',d.status_fields==null?31:d.status_fields);dSet('data-dasbit',d.lightning_fields==null?31:d.lightning_fields);''', "display AS load")

replace_once("src/web_manager.cpp",
'''q.set('status_fields',String(dGet('data-dstatusbit')));q.set('page_interval_sec',E('dispInterval').value);''',
'''q.set('status_fields',String(dGet('data-dstatusbit')));q.set('lightning_fields',String(dGet('data-dasbit')));q.set('page_interval_sec',E('dispInterval').value);''', "display AS save")

print("AS3935 phase2 transformations applied")
