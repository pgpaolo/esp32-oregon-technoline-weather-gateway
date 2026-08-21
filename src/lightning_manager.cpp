#include "lightning_manager.h"

#include <AS3935I2C.h>
#include <Preferences.h>
#include <Wire.h>

#include "board_config.h"
#include "mqtt_publisher.h"

namespace {

#if defined(BOARD_T3_S3_SX1278)
constexpr int8_t DEFAULT_IRQ_PIN = -1; // richiede override dopo verifica pinout della revisione S3
constexpr bool DEFAULT_ENABLED = false;
#else
constexpr int8_t DEFAULT_IRQ_PIN = 34; // T3 V1.6.1: input-only, libero nel pinout del gateway
constexpr bool DEFAULT_ENABLED = true;
#endif

constexpr uint32_t IRQ_SETTLE_US = 2000UL;
constexpr uint32_t STATE_PUBLISH_MS = 30000UL;
constexpr uint8_t DISTANCE_OUT_OF_RANGE = 0x3FU;

Preferences prefs;
LightningConfig cfg{};
LightningState state{};
AS3935I2C *sensor = nullptr;
volatile bool irqPending = false;
volatile uint32_t irqRaisedUs = 0;
uint32_t lastStatePublishMs = 0;

void IRAM_ATTR lightningIsr() {
    irqRaisedUs = micros();
    irqPending = true;
}

LightningConfig defaults() {
    LightningConfig c;
    c.enabled = DEFAULT_ENABLED;
    c.indoor = true;
    c.i2cAddress = 0x03;
    c.irqPin = DEFAULT_IRQ_PIN;
    c.noiseFloor = 2;
    c.watchdogThreshold = 2;
    c.spikeRejection = 2;
    c.minStrikes = 1;
    c.maskDisturbers = false;
    c.tuningCap = 6;
    c.autoTune = false;
    return c;
}

bool isAllowedMinStrikes(uint8_t value) {
    return value == 1U || value == 5U || value == 9U || value == 16U;
}

uint8_t minStrikesCode(uint8_t value) {
    switch (value) {
        case 5: return AS3935MI::AS3935_MNL_5;
        case 9: return AS3935MI::AS3935_MNL_9;
        case 16: return AS3935MI::AS3935_MNL_16;
        default: return AS3935MI::AS3935_MNL_1;
    }
}

bool pinReserved(int8_t pin) {
    if (pin < 0) return false;
    if (pin == I2C_SDA_PIN || pin == I2C_SCL_PIN) return true;
    if (pin == RADIO_SCLK_PIN || pin == RADIO_MISO_PIN || pin == RADIO_MOSI_PIN ||
        pin == RADIO_CS_PIN || pin == RADIO_DIO0_PIN || pin == RADIO_RST_PIN ||
        pin == RADIO_DIO1_PIN || pin == RADIO_DIO2_PIN || pin == BOARD_LED_PIN ||
        pin == BATTERY_ADC_PIN) return true;
#if !defined(BOARD_T3_S3_SX1278)
    // ESP32 classic: GPIO6..11 sono collegati alla flash.
    if (pin >= 6 && pin <= 11) return true;
#endif
    return false;
}

void normalize(LightningConfig &c) {
    if (c.i2cAddress < 0x01 || c.i2cAddress > 0x03) c.i2cAddress = 0x03;
    if (c.noiseFloor > 7U) c.noiseFloor = 7U;
    if (c.watchdogThreshold > 15U) c.watchdogThreshold = 15U;
    if (c.spikeRejection > 15U) c.spikeRejection = 15U;
    if (!isAllowedMinStrikes(c.minStrikes)) c.minStrikes = 1U;
    if (c.tuningCap > 15U) c.tuningCap = 15U;
}

void loadConfig() {
    const LightningConfig d = defaults();
    cfg = d;
    if (!prefs.begin("as3935cfg", true)) {
        Serial.println(F("[AS3935] NVS non disponibile: uso default firmware"));
        normalize(cfg);
        return;
    }
    cfg.enabled = prefs.getBool("enabled", d.enabled);
    cfg.indoor = prefs.getBool("indoor", d.indoor);
    cfg.i2cAddress = prefs.getUChar("addr", d.i2cAddress);
    cfg.irqPin = prefs.getChar("irq", d.irqPin);
    cfg.noiseFloor = prefs.getUChar("noise", d.noiseFloor);
    cfg.watchdogThreshold = prefs.getUChar("watchdog", d.watchdogThreshold);
    cfg.spikeRejection = prefs.getUChar("spike", d.spikeRejection);
    cfg.minStrikes = prefs.getUChar("minstrike", d.minStrikes);
    cfg.maskDisturbers = prefs.getBool("maskdist", d.maskDisturbers);
    cfg.tuningCap = prefs.getUChar("tuncap", d.tuningCap);
    cfg.autoTune = prefs.getBool("autotune", d.autoTune);
    prefs.end();
    normalize(cfg);
}

bool verifyStored(Preferences &p, const LightningConfig &expected) {
    const LightningConfig d = defaults();
    return p.getBool("enabled", d.enabled) == expected.enabled &&
           p.getBool("indoor", d.indoor) == expected.indoor &&
           p.getUChar("addr", d.i2cAddress) == expected.i2cAddress &&
           p.getChar("irq", d.irqPin) == expected.irqPin &&
           p.getUChar("noise", d.noiseFloor) == expected.noiseFloor &&
           p.getUChar("watchdog", d.watchdogThreshold) == expected.watchdogThreshold &&
           p.getUChar("spike", d.spikeRejection) == expected.spikeRejection &&
           p.getUChar("minstrike", d.minStrikes) == expected.minStrikes &&
           p.getBool("maskdist", d.maskDisturbers) == expected.maskDisturbers &&
           p.getUChar("tuncap", d.tuningCap) == expected.tuningCap &&
           p.getBool("autotune", d.autoTune) == expected.autoTune;
}

void stopSensor() {
    if (cfg.irqPin >= 0) detachInterrupt(digitalPinToInterrupt(cfg.irqPin));
    irqPending = false;
    if (sensor) {
        sensor->writePowerDown(true);
        delete sensor;
        sensor = nullptr;
    }
    state.detected = false;
    state.irqOk = false;
}

void publishMqttState(PubSubClient &client) {
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

bool configureSensor() {
    stopSensor();
    state.enabled = cfg.enabled;
    state.calibrationOk = false;
    state.resonanceHz = 0;

    if (!cfg.enabled) {
        Serial.println(F("[AS3935] disabilitato da configurazione"));
        return true;
    }
    if (cfg.irqPin < 0 || pinReserved(cfg.irqPin)) {
        Serial.print(F("[AS3935] IRQ non valido o riservato: GPIO"));
        Serial.println(cfg.irqPin);
        return false;
    }

    pinMode(cfg.irqPin, INPUT);
    sensor = new AS3935I2C(cfg.i2cAddress, static_cast<uint8_t>(cfg.irqPin));
    if (!sensor) {
        Serial.println(F("[AS3935] allocazione sensore fallita"));
        return false;
    }

    if (!sensor->begin() || !sensor->checkConnection()) {
        Serial.print(F("[AS3935] non rilevato su I2C 0x"));
        Serial.println(cfg.i2cAddress, HEX);
        delete sensor;
        sensor = nullptr;
        return false;
    }

    state.detected = true;
    state.irqOk = sensor->checkIRQ();

    bool resonanceOk = false;
    int32_t frequency = 0;
    if (cfg.autoTune) {
        resonanceOk = sensor->calibrateResonanceFrequency(frequency, AS3935MI::AS3935_DR_16);
    } else {
        sensor->writeAntennaTuning(cfg.tuningCap);
        resonanceOk = sensor->validateCurrentResonanceFrequency(frequency);
    }
    state.resonanceHz = frequency;
    const bool rcoOk = sensor->calibrateRCO();
    state.calibrationOk = resonanceOk && rcoOk;

    sensor->writeAFE(cfg.indoor ? AS3935MI::AS3935_INDOORS : AS3935MI::AS3935_OUTDOORS);
    sensor->writeNoiseFloorThreshold(cfg.noiseFloor);
    sensor->writeWatchdogThreshold(cfg.watchdogThreshold);
    sensor->writeSpikeRejection(cfg.spikeRejection);
    sensor->writeMinLightnings(minStrikesCode(cfg.minStrikes));
    sensor->writeMaskDisturbers(cfg.maskDisturbers);
    sensor->clearStatistics();

    attachInterrupt(digitalPinToInterrupt(cfg.irqPin), lightningIsr, RISING);

    Serial.print(F("[AS3935] OK I2C=0x")); Serial.print(cfg.i2cAddress, HEX);
    Serial.print(F(" IRQ=GPIO")); Serial.print(cfg.irqPin);
    Serial.print(F(" mode=")); Serial.print(cfg.indoor ? F("INDOOR") : F("OUTDOOR"));
    Serial.print(F(" noise=")); Serial.print(cfg.noiseFloor);
    Serial.print(F(" watchdog=")); Serial.print(cfg.watchdogThreshold);
    Serial.print(F(" spike=")); Serial.print(cfg.spikeRejection);
    Serial.print(F(" min=")); Serial.print(cfg.minStrikes);
    Serial.print(F(" tune=")); Serial.print(cfg.autoTune ? F("AUTO") : F("FIXED"));
    Serial.print('/'); Serial.print(cfg.tuningCap);
    Serial.print(F(" freq=")); Serial.print(state.resonanceHz);
    Serial.print(F("Hz IRQ=")); Serial.print(state.irqOk ? F("OK") : F("KO"));
    Serial.print(F(" CAL=")); Serial.println(state.calibrationOk ? F("OK") : F("KO"));
    return true;
}

} // namespace

void initLightning() {
    loadConfig();
    state = LightningState{};
    state.enabled = cfg.enabled;
    configureSensor();
}

void serviceLightning(PubSubClient &mqttClient) {
    const uint32_t now = millis();

    if (cfg.enabled && sensor && state.detected && irqPending) {
        const uint32_t raisedUs = irqRaisedUs;
        if (static_cast<uint32_t>(micros() - raisedUs) >= IRQ_SETTLE_US) {
            noInterrupts();
            irqPending = false;
            interrupts();

            state.irqTotal++;
            state.lastEventMs = now;
            const uint8_t source = sensor->readInterruptSource();
            state.lastInterruptSource = source;

            switch (source) {
                case AS3935MI::AS3935_INT_NH:
                    state.noiseTotal++;
                    Serial.print(F("[AS3935] NOISE total=")); Serial.println(state.noiseTotal);
                    break;
                case AS3935MI::AS3935_INT_D:
                    state.disturberTotal++;
                    Serial.print(F("[AS3935] DISTURBER total=")); Serial.println(state.disturberTotal);
                    break;
                case AS3935MI::AS3935_INT_L: {
                    state.lightningTotal++;
                    state.lastLightningMs = now;
                    const uint8_t distance = sensor->readStormDistance();
                    state.distanceOutOfRange = distance == DISTANCE_OUT_OF_RANGE;
                    state.lastDistanceKm = state.distanceOutOfRange ? 0U : distance;
                    state.lastEnergy = sensor->readEnergy();
                    Serial.print(F("[AS3935] LIGHTNING #")); Serial.print(state.lightningTotal);
                    Serial.print(F(" distance="));
                    if (state.distanceOutOfRange) Serial.print(F(">40")); else Serial.print(state.lastDistanceKm);
                    Serial.print(F("km energy=")); Serial.println(state.lastEnergy);
                    break;
                }
                default:
                    Serial.print(F("[AS3935] IRQ source=0x")); Serial.println(source, HEX);
                    break;
            }
            publishMqttEvent(mqttClient, source);
        }
    }

    if (mqttClient.connected() && static_cast<uint32_t>(now - lastStatePublishMs) >= STATE_PUBLISH_MS) {
        lastStatePublishMs = now;
        publishMqttState(mqttClient);
    }
}

void prepareLightningForDeepSleep() {
    stopSensor();
    Serial.println(F("[AS3935] power down"));
}

LightningConfig getLightningConfig() { return cfg; }
LightningState getLightningState() { return state; }

bool validateLightningConfig(const LightningConfig &input) {
    LightningConfig c = input;
    normalize(c);
    if (c.i2cAddress != input.i2cAddress || c.noiseFloor != input.noiseFloor ||
        c.watchdogThreshold != input.watchdogThreshold || c.spikeRejection != input.spikeRejection ||
        c.minStrikes != input.minStrikes || c.tuningCap != input.tuningCap) return false;
    if (c.enabled && (c.irqPin < 0 || pinReserved(c.irqPin))) return false;
#if defined(BOARD_T3_S3_SX1278)
    if (c.irqPin > 48) return false;
#else
    if (c.irqPin > 39) return false;
#endif
    return true;
}

bool saveLightningConfig(const LightningConfig &input, bool &changed) {
    changed = false;
    if (!validateLightningConfig(input)) return false;
    LightningConfig next = input;
    normalize(next);

    const bool same = next.enabled == cfg.enabled && next.indoor == cfg.indoor &&
        next.i2cAddress == cfg.i2cAddress && next.irqPin == cfg.irqPin &&
        next.noiseFloor == cfg.noiseFloor && next.watchdogThreshold == cfg.watchdogThreshold &&
        next.spikeRejection == cfg.spikeRejection && next.minStrikes == cfg.minStrikes &&
        next.maskDisturbers == cfg.maskDisturbers && next.tuningCap == cfg.tuningCap &&
        next.autoTune == cfg.autoTune;
    if (same) return true;

    if (!prefs.begin("as3935cfg", false)) return false;
    prefs.putBool("enabled", next.enabled);
    prefs.putBool("indoor", next.indoor);
    prefs.putUChar("addr", next.i2cAddress);
    prefs.putChar("irq", next.irqPin);
    prefs.putUChar("noise", next.noiseFloor);
    prefs.putUChar("watchdog", next.watchdogThreshold);
    prefs.putUChar("spike", next.spikeRejection);
    prefs.putUChar("minstrike", next.minStrikes);
    prefs.putBool("maskdist", next.maskDisturbers);
    prefs.putUChar("tuncap", next.tuningCap);
    prefs.putBool("autotune", next.autoTune);
    const bool ok = verifyStored(prefs, next);
    prefs.end();
    if (!ok) return false;

    cfg = next;
    changed = true;
    configureSensor();
    return true;
}

bool resetLightningConfigToDefaults(bool &changed) {
    const LightningConfig d = defaults();
    changed = !(cfg.enabled == d.enabled && cfg.indoor == d.indoor && cfg.i2cAddress == d.i2cAddress &&
        cfg.irqPin == d.irqPin && cfg.noiseFloor == d.noiseFloor && cfg.watchdogThreshold == d.watchdogThreshold &&
        cfg.spikeRejection == d.spikeRejection && cfg.minStrikes == d.minStrikes &&
        cfg.maskDisturbers == d.maskDisturbers && cfg.tuningCap == d.tuningCap && cfg.autoTune == d.autoTune);

    if (!prefs.begin("as3935cfg", false)) return false;
    const bool cleared = prefs.clear();
    const bool verified = cleared && verifyStored(prefs, d);
    prefs.end();
    if (!verified) return false;
    cfg = d;
    configureSensor();
    return true;
}

bool reinitializeLightning() { return configureSensor(); }

const char *lightningInterruptName(uint8_t source) {
    switch (source) {
        case AS3935MI::AS3935_INT_NH: return "noise";
        case AS3935MI::AS3935_INT_D: return "disturber";
        case AS3935MI::AS3935_INT_L: return "lightning";
        case AS3935MI::AS3935_INT_DUPDATE: return "distance_update";
        default: return "unknown";
    }
}

String lightningConfigJson() {
    String out;
    out.reserve(360);
    out = "{\"enabled\":"; out += cfg.enabled ? "true" : "false";
    out += ",\"indoor\":"; out += cfg.indoor ? "true" : "false";
    out += ",\"i2c_address\":" + String(cfg.i2cAddress);
    out += ",\"irq_pin\":" + String(cfg.irqPin);
    out += ",\"noise_floor\":" + String(cfg.noiseFloor);
    out += ",\"watchdog_threshold\":" + String(cfg.watchdogThreshold);
    out += ",\"spike_rejection\":" + String(cfg.spikeRejection);
    out += ",\"min_strikes\":" + String(cfg.minStrikes);
    out += ",\"mask_disturbers\":"; out += cfg.maskDisturbers ? "true" : "false";
    out += ",\"tuning_cap\":" + String(cfg.tuningCap);
    out += ",\"auto_tune\":"; out += cfg.autoTune ? "true" : "false";
    out += "}";
    return out;
}

String lightningStateJson() {
    String out;
    out.reserve(620);
    out = "{\"enabled\":"; out += state.enabled ? "true" : "false";
    out += ",\"detected\":"; out += state.detected ? "true" : "false";
    out += ",\"irq_ok\":"; out += state.irqOk ? "true" : "false";
    out += ",\"calibration_ok\":"; out += state.calibrationOk ? "true" : "false";
    out += ",\"resonance_hz\":" + String(state.resonanceHz);
    out += ",\"mode\":\"" + String(cfg.indoor ? "indoor" : "outdoor") + "\"";
    out += ",\"i2c_address\":" + String(cfg.i2cAddress);
    out += ",\"irq_pin\":" + String(cfg.irqPin);
    out += ",\"irq_total\":" + String(state.irqTotal);
    out += ",\"noise_total\":" + String(state.noiseTotal);
    out += ",\"disturber_total\":" + String(state.disturberTotal);
    out += ",\"lightning_total\":" + String(state.lightningTotal);
    out += ",\"last_event_ms\":" + String(state.lastEventMs);
    out += ",\"last_lightning_ms\":" + String(state.lastLightningMs);
    out += ",\"last_source\":" + String(state.lastInterruptSource);
    out += ",\"last_type\":\"" + String(lightningInterruptName(state.lastInterruptSource)) + "\"";
    if (state.lastLightningMs == 0 || state.distanceOutOfRange) out += ",\"last_distance_km\":null";
    else out += ",\"last_distance_km\":" + String(state.lastDistanceKm);
    out += ",\"distance_out_of_range\":"; out += state.distanceOutOfRange ? "true" : "false";
    out += ",\"last_energy\":" + String(state.lastEnergy);
    out += ",\"noise_floor\":" + String(cfg.noiseFloor);
    out += ",\"watchdog_threshold\":" + String(cfg.watchdogThreshold);
    out += ",\"spike_rejection\":" + String(cfg.spikeRejection);
    out += ",\"min_strikes\":" + String(cfg.minStrikes);
    out += ",\"mask_disturbers\":"; out += cfg.maskDisturbers ? "true" : "false";
    out += ",\"tuning_cap\":" + String(cfg.tuningCap);
    out += ",\"auto_tune\":"; out += cfg.autoTune ? "true" : "false";
    out += "}";
    return out;
}
