from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Firmware/config: enable Web soft power-off. Wake GPIO is enabled by default
# only on the T3-S3, whose BOOT/User button is explicitly mapped to GPIO0.
# -----------------------------------------------------------------------------
p = Path('src/config.h')
s = p.read_text(encoding='utf-8')
s = replace_once(s,
    '#define FIRMWARE_VERSION         "6.4.0-rc1"',
    '#define FIRMWARE_VERSION         "6.4.0-rc2"',
    'firmware version')
anchor = '''#ifndef OLED_BUTTON_MAX_PRESS_MS
#define OLED_BUTTON_MAX_PRESS_MS 1800UL
#endif
'''
addition = anchor + '''
// Soft power-off: la Web UI puo' mettere il controller in deep sleep senza
// togliere alimentazione. Non e' un sezionamento elettrico vero e proprio.
#ifndef POWER_SOFT_OFF_ENABLE
#define POWER_SOFT_OFF_ENABLE       1
#endif
#ifndef POWER_WAKE_BUTTON_ENABLE
#if defined(BOARD_T3_S3_SX1278)
#define POWER_WAKE_BUTTON_ENABLE    1
#else
// Sul T3 V1.6.1 il pinout usato dal progetto non garantisce un pulsante utente.
// Il risveglio resta quindi affidato a RESET/EN, salvo override verificato.
#define POWER_WAKE_BUTTON_ENABLE    0
#endif
#endif
#ifndef POWER_WAKE_BUTTON_PIN
#define POWER_WAKE_BUTTON_PIN       OLED_BUTTON_PIN
#endif
'''
s = replace_once(s, anchor, addition, 'power config block')
p.write_text(s, encoding='utf-8')


# -----------------------------------------------------------------------------
# OLED: spegnimento runtime senza modificare la preferenza NVS dell'utente.
# -----------------------------------------------------------------------------
p = Path('src/display_manager.cpp')
s = p.read_text(encoding='utf-8')
anchor = '''bool displayEnabled() { return displayOn; }
bool displayPersistenceAvailable() { return displayPrefsReady; }
'''
addition = anchor + '''
void prepareDisplayForDeepSleep() {
    oled.clearBuffer();
    oled.sendBuffer();
    oled.setPowerSave(1);
    Serial.println(F("[OLED] deep-sleep power save"));
}
'''
s = replace_once(s, anchor, addition, 'OLED deep sleep hook')
p.write_text(s, encoding='utf-8')


# -----------------------------------------------------------------------------
# BME280: passa esplicitamente in sleep mode.
# -----------------------------------------------------------------------------
p = Path('src/barometer_manager.cpp')
s = p.read_text(encoding='utf-8')
anchor = '''bool barometerDetected() { return detected; }
'''
addition = '''void prepareBarometerForDeepSleep() {
#if BAROMETER_ENABLE
    if (!detected) return;
    bme.setSampling(Adafruit_BME280::MODE_SLEEP);
    Serial.println(F("[BARO] BME280 -> sleep"));
#endif
}

''' + anchor
s = replace_once(s, anchor, addition, 'BME deep sleep hook')
p.write_text(s, encoding='utf-8')


# -----------------------------------------------------------------------------
# MQTT: pubblica OFFLINE retained e chiude volontariamente la sessione.
# -----------------------------------------------------------------------------
p = Path('src/mqtt_publisher.cpp')
s = p.read_text(encoding='utf-8')
anchor = '''bool mqttConnected(PubSubClient &client) { return mqttCfg.enabled && client.connected(); }
'''
addition = '''void prepareMqttForDeepSleep() {
    if (mqttClientRef && mqttClientRef->connected()) {
        const String statusTopic = topic("status");
        mqttClientRef->publish(statusTopic.c_str(), "offline", true);
        mqttClientRef->loop();
        delay(25);
        mqttClientRef->disconnect();
    }
    mqttSecureClient.stop();
    if (mqttPlainClientRef) mqttPlainClientRef->stop();
    Serial.println(F("[MQTT] arresto per deep sleep"));
}

''' + anchor
s = replace_once(s, anchor, addition, 'MQTT deep sleep hook')
p.write_text(s, encoding='utf-8')


# -----------------------------------------------------------------------------
# SX1278: ferma decoder/IRQ e usa il vero sleep mode del transceiver.
# -----------------------------------------------------------------------------
p = Path('src/oregon_receiver.h')
s = p.read_text(encoding='utf-8')
anchor = '''bool initOregonReceiver();
void serviceOregonReceiver();
'''
addition = '''bool initOregonReceiver();
void serviceOregonReceiver();
bool prepareRadioForDeepSleep();
'''
s = replace_once(s, anchor, addition, 'radio header hook')
p.write_text(s, encoding='utf-8')

p = Path('src/oregon_receiver.cpp')
s = p.read_text(encoding='utf-8')
anchor = '''bool wgrProbeEnabled() {
    return wgrProbeOn;
}
'''
addition = '''bool prepareRadioForDeepSleep() {
    burstStats.autoActive = false;
    finalizeRfBurst();
    if (wgrProbeOn) resetWgrProbeStatsInternal();
#if OREGON_RAW_EDGE_MODE
    detachInterrupt(digitalPinToInterrupt(RADIO_DIO2_PIN));
    noInterrupts();
    edgeTail = edgeHead;
    interrupts();
#endif
    packetHead = packetTail = 0;
    resetLaCrosseDecoderState();

    if (!radioReady) return true;
    const int16_t state = radio.sleep();
    if (state != RADIOLIB_ERR_NONE) {
        lastError = String("sleep: ") + state;
        return false;
    }
    radioReady = false;
    lastError = "SLEEP";
    Serial.println(F("[RF] SX1278 -> sleep"));
    return true;
}

''' + anchor
s = replace_once(s, anchor, addition, 'radio deep sleep hook')
p.write_text(s, encoding='utf-8')


# -----------------------------------------------------------------------------
# Web UI/API: pulsante SPEGNI, conferma e arresto differito dopo la risposta.
# -----------------------------------------------------------------------------
p = Path('src/web_manager.cpp')
s = p.read_text(encoding='utf-8')
s = replace_once(s,
    '#include "firmware_info.h"\n',
    '#include "firmware_info.h"\n#include "power_manager.h"\n',
    'power manager include')
s = replace_once(s,
    'uint32_t rebootAtMs = 0;\n',
    'uint32_t rebootAtMs = 0;\nuint32_t powerOffAtMs = 0;\n',
    'poweroff timer')

anchor = '''void handleDeviceRestart() {
    rebootAtMs = millis() + 900UL;
    sendNoCache();
    server.send(200, "application/json", "{\\"ok\\":true,\\"rebooting\\":true}");
}
'''
addition = anchor + '''
void handleDevicePowerOff() {
    if (!controllerSoftPowerOffEnabled()) {
        server.send(403, "application/json", "{\\"ok\\":false,\\"error\\":\\"soft power-off disabled\\"}");
        return;
    }
    powerOffAtMs = millis() + 900UL;
    sendNoCache();
    String out = "{\\"ok\\":true,\\"powering_off\\":true,\\"mode\\":\\"deep_sleep\\",\\"wake_hint\\":\\"";
    out += jsonEscapeString(controllerWakeHint());
    out += "\\"}";
    server.send(200, "application/json", out);
}
'''
s = replace_once(s, anchor, addition, 'poweroff handler')

old = '''<div class="top"><div class="brand"><div class="title">Oregon + Technoline 433 Gateway</div><div class="sub">LILYGO T3 · SX1278 OOK 433.92 MHz · decoder Oregon OSV3 + Technoline WS230x</div></div><div class="headerActions"><span id="hdrRf" class="statusPill wait">RF --</span><span id="net" class="statusPill wait">Wi-Fi...</span><span id="hdrMqtt" class="statusPill wait">MQTT...</span><button id="displayBtn" class="modeBtn" onclick="toggleDisplay()" title="Accende o spegne il display OLED; RF, Wi-Fi, Web e MQTT restano attivi">OLED --</button><button class="modeBtn dangerBtn" onclick="restartDevice()" title="Riavvia ESP32 senza cancellare la configurazione">⟳ RIAVVIA</button></div></div>
'''
new = '''<div class="top"><div class="brand"><div class="title">Oregon + Technoline 433 Gateway</div><div class="sub">LILYGO T3 · SX1278 OOK 433.92 MHz · decoder Oregon OSV3 + Technoline WS230x</div></div><div class="headerActions"><span id="hdrRf" class="statusPill wait">RF --</span><span id="net" class="statusPill wait">Wi-Fi...</span><span id="hdrMqtt" class="statusPill wait">MQTT...</span><button id="displayBtn" class="modeBtn" onclick="toggleDisplay()" title="Accende o spegne il display OLED; RF, Wi-Fi, Web e MQTT restano attivi">OLED --</button><button class="modeBtn dangerBtn" onclick="powerOffDevice()" title="Arresta servizi e periferiche e mette ESP32 in deep sleep">⏻ SPEGNI</button><button class="modeBtn dangerBtn" onclick="restartDevice()" title="Riavvia ESP32 senza cancellare la configurazione">⟳ RIAVVIA</button></div></div>
'''
s = replace_once(s, old, new, 'Web power button')

anchor = '''async function restartDevice(){if(!confirm('Riavviare ora la scheda ESP32?'))return;const r=await fetch('/api/restart',{method:'POST',cache:'no-store'});if(r.ok)alert('Riavvio ESP32 avviato. La pagina tornera disponibile tra pochi secondi.');else alert('Riavvio fallito');}'''
addition = '''async function powerOffDevice(){if(!confirm('Spegnere il controller? Entrera in DEEP SLEEP: RF, Wi-Fi, Web, MQTT, OLED e BME280 verranno arrestati.'))return;try{const r=await fetch('/api/poweroff',{method:'POST',cache:'no-store'});const t=await r.text();if(!r.ok)throw new Error(t);const j=JSON.parse(t);alert('Controller in spegnimento. Per riaccenderlo: '+(j.wake_hint||'usa RESET/EN.'));}catch(e){alert('Spegnimento fallito: '+e)}}
''' + anchor
s = replace_once(s, anchor, addition, 'Web power JS')

s = replace_once(s,
    '    server.on("/api/restart", HTTP_POST, handleDeviceRestart);\n',
    '    server.on("/api/poweroff", HTTP_POST, handleDevicePowerOff);\n    server.on("/api/restart", HTTP_POST, handleDeviceRestart);\n',
    'poweroff route')

old = '''    if (rebootAtMs && static_cast<int32_t>(millis() - rebootAtMs) >= 0) {
        Serial.println(F("[WEB] riavvio richiesto dalla configurazione"));
        delay(80);
        ESP.restart();
    }
'''
new = '''    if (powerOffAtMs && static_cast<int32_t>(millis() - powerOffAtMs) >= 0) {
        powerOffAtMs = 0;
        Serial.println(F("[WEB] spegnimento controller richiesto"));
        delay(50);
        enterControllerDeepSleep();
    }
    if (rebootAtMs && static_cast<int32_t>(millis() - rebootAtMs) >= 0) {
        Serial.println(F("[WEB] riavvio richiesto dalla configurazione"));
        delay(80);
        ESP.restart();
    }
'''
s = replace_once(s, old, new, 'poweroff service')
p.write_text(s, encoding='utf-8')


# -----------------------------------------------------------------------------
# Changelog / README IT.
# -----------------------------------------------------------------------------
p = Path('CHANGELOG.md')
s = p.read_text(encoding='utf-8')
entry = '''## 6.4.0-rc2

- Aggiunto pulsante Web `SPEGNI` con arresto controllato in ESP32 deep sleep.
- Prima del deep sleep vengono arrestati MQTT, OLED, BME280 e SX1278; Wi-Fi viene disabilitato.
- T3-S3: wake opzionale di default dal pulsante BOOT/User GPIO0 oppure RESET/EN.
- T3 V1.6.1: wake di default tramite RESET/EN, senza assumere un pulsante utente non garantito dal pinout.
- Lo spegnimento software non sostituisce un vero sezionatore/load-switch: la scheda resta elettricamente alimentata.

'''
if '## 6.4.0-rc2' not in s:
    if s.startswith('#'):
        pos = s.find('\n') + 1
        s = s[:pos] + '\n' + entry + s[pos:]
    else:
        s = entry + s
p.write_text(s, encoding='utf-8')

p = Path('README_IT.md')
s = p.read_text(encoding='utf-8')
section = '''
## Spegnimento software del controller

La Web UI espone il pulsante **SPEGNI**. Il comando esegue un arresto controllato e porta l'ESP32 in **deep sleep** senza scollegare il cavo di alimentazione. Prima dello sleep il firmware pubblica MQTT `offline`, spegne l'OLED, porta il BME280 e l'SX1278 in sleep e disabilita il Wi-Fi.

Sul **T3 V1.6.1** il risveglio predefinito avviene con **RESET/EN**; il progetto non presume l'esistenza di un pulsante utente applicativo su quella revisione. Sul **T3-S3** il BOOT/User button GPIO0 puo' essere usato come sorgente di wake oltre a RESET/EN. Lo stato deep sleep riduce fortemente i consumi ma non equivale a un'interruzione fisica dell'alimentazione; per consumo praticamente nullo serve un load-switch/latch hardware esterno.
'''
if '## Spegnimento software del controller' not in s:
    s = s.rstrip() + '\n' + section + '\n'
p.write_text(s, encoding='utf-8')

print('soft power-off patch applied')
