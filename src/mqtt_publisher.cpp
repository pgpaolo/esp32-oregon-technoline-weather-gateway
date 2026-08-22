#include "mqtt_publisher.h"
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Preferences.h>
#include "config.h"
#include "network_manager.h"
#include "weather_parser.h"
#include "lacrosse_ws23xx.h"
#include "thermo_channel_manager.h"

namespace {
uint32_t lastAttemptMs = 0;
Preferences mqttPrefs;
PubSubClient *mqttClientRef = nullptr;
Client *mqttPlainClientRef = nullptr;
WiFiClientSecure mqttSecureClient;
MqttRuntimeConfig mqttCfg;

String trimTopic(String value) {
    value.trim();
    while (value.startsWith("/")) value.remove(0, 1);
    while (value.endsWith("/")) value.remove(value.length() - 1);
    return value;
}

MqttRuntimeConfig defaults() {
    MqttRuntimeConfig c;
    c.enabled = true;
    c.broker = MQTT_BROKER;
    c.port = MQTT_PORT;
    c.user = MQTT_USER;
    c.password = MQTT_PASSWORD;
    c.clientId = MQTT_CLIENT_ID;
    c.baseTopic = MQTT_BASE_TOPIC;
#ifdef MQTT_TLS_MODE
    c.tlsMode = static_cast<MqttTlsMode>(MQTT_TLS_MODE);
#else
    c.tlsMode = MqttTlsMode::Off;
#endif
#ifdef MQTT_CA_CERT
    c.caCertificate = MQTT_CA_CERT;
#else
    c.caCertificate = "";
#endif
#ifdef MQTT_FIELDS_MASK
    c.fieldsMask = static_cast<uint32_t>(MQTT_FIELDS_MASK);
#else
    c.fieldsMask = MQTT_FIELDS_ALL;
#endif
    return c;
}

void normalize(MqttRuntimeConfig &c) {
    c.broker.trim();
    c.user.trim();
    c.clientId.trim();
    c.baseTopic = trimTopic(c.baseTopic);
    if (c.port == 0) c.port = 1883;
    if (c.clientId.length() == 0) c.clientId = "WeatherGateway";
    if (c.baseTopic.length() == 0) c.baseTopic = "weatherstation";
    if (static_cast<uint8_t>(c.tlsMode) > static_cast<uint8_t>(MqttTlsMode::Insecure)) c.tlsMode = MqttTlsMode::Off;
    // Limiti conservativi per Preferences/PubSubClient e per la Web UI.
    if (c.broker.length() > 96) c.broker.remove(96);
    if (c.user.length() > 64) c.user.remove(64);
    if (c.password.length() > 96) c.password.remove(96);
    if (c.clientId.length() > 64) c.clientId.remove(64);
    if (c.baseTopic.length() > 96) c.baseTopic.remove(96);
    if (c.caCertificate.length() > 3900) c.caCertificate.remove(3900);
}

void loadConfig() {
    MqttRuntimeConfig d = defaults();
    if (!mqttPrefs.begin("mqttcfg", true)) {
        mqttCfg = d;
        normalize(mqttCfg);
        Serial.println(F("[MQTT] NVS mqttcfg non disponibile: uso valori firmware"));
        return;
    }
    mqttCfg.enabled = mqttPrefs.getBool("enabled", d.enabled);
    mqttCfg.broker = mqttPrefs.getString("broker", d.broker);
    mqttCfg.port = mqttPrefs.getUShort("port", d.port);
    mqttCfg.user = mqttPrefs.getString("user", d.user);
    mqttCfg.password = mqttPrefs.getString("pass", d.password);
    mqttCfg.clientId = mqttPrefs.getString("client", d.clientId);
    mqttCfg.baseTopic = mqttPrefs.getString("topic", d.baseTopic);
    mqttCfg.tlsMode = static_cast<MqttTlsMode>(mqttPrefs.getUChar("tlsmode", static_cast<uint8_t>(d.tlsMode)));
    mqttCfg.caCertificate = mqttPrefs.getString("cacert", d.caCertificate);
    mqttCfg.fieldsMask = mqttPrefs.getUInt("fields", d.fieldsMask);
    mqttPrefs.end();
    normalize(mqttCfg);
}

bool verifyStoredMqttConfig(Preferences &p, const MqttRuntimeConfig &expected) {
    MqttRuntimeConfig d = defaults();
    normalize(d);
    return p.getBool("enabled", d.enabled) == expected.enabled &&
           p.getString("broker", d.broker) == expected.broker &&
           p.getUShort("port", d.port) == expected.port &&
           p.getString("user", d.user) == expected.user &&
           p.getString("pass", d.password) == expected.password &&
           p.getString("client", d.clientId) == expected.clientId &&
           p.getString("topic", d.baseTopic) == expected.baseTopic &&
           p.getUChar("tlsmode", static_cast<uint8_t>(d.tlsMode)) == static_cast<uint8_t>(expected.tlsMode) &&
           p.getString("cacert", d.caCertificate) == expected.caCertificate &&
           p.getUInt("fields", d.fieldsMask) == expected.fieldsMask;
}

void applyClientConfig() {
    if (!mqttClientRef || !mqttPlainClientRef) return;
    if (mqttClientRef->connected()) mqttClientRef->disconnect();

    // Il transport MQTT puo' essere cambiato a runtime senza ricreare PubSubClient.
    // La CA viene applicata soltanto quando TLS e' in modalita' verificata.
    mqttSecureClient.stop();
    if (mqttCfg.tlsMode == MqttTlsMode::CaVerified) {
        if (mqttCfg.caCertificate.length() > 0) mqttSecureClient.setCACert(mqttCfg.caCertificate.c_str());
        mqttClientRef->setClient(mqttSecureClient);
    } else if (mqttCfg.tlsMode == MqttTlsMode::Insecure) {
        mqttSecureClient.setInsecure();
        mqttClientRef->setClient(mqttSecureClient);
    } else {
        mqttClientRef->setClient(*mqttPlainClientRef);
    }

    mqttClientRef->setServer(mqttCfg.broker.c_str(), mqttCfg.port);
    mqttClientRef->setKeepAlive(30);
    mqttClientRef->setSocketTimeout(2);
    mqttClientRef->setBufferSize(2200);
    lastAttemptMs = 0;
}

bool fieldEnabled(uint32_t bit) { return (mqttCfg.fieldsMask & bit) != 0U; }

String topic(const char *suffix) {
    if (!suffix || !*suffix) return mqttCfg.baseTopic;
    return mqttCfg.baseTopic + "/" + suffix;
}

void publishFloat(PubSubClient &client, const char *suffix, float value, uint8_t decimals = 1) {
    if (!mqttCfg.enabled || !client.connected()) return;
    char buf[24];
    dtostrf(value, 0, decimals, buf);
    client.publish(topic(suffix).c_str(), buf, true);
}

void publishInt(PubSubClient &client, const char *suffix, int value) {
    if (!mqttCfg.enabled || !client.connected()) return;
    char buf[16];
    snprintf(buf, sizeof(buf), "%d", value);
    client.publish(topic(suffix).c_str(), buf, true);
}

String effectiveClientId() {
    String id = mqttCfg.clientId;
    const uint64_t mac = ESP.getEfuseMac();
    char suffix[10];
    snprintf(suffix, sizeof(suffix), "-%06llX", static_cast<unsigned long long>(mac & 0xFFFFFFULL));
    id += suffix;
    return id;
}
} // namespace

void initMQTT(PubSubClient &client, Client &plainClient) {
    mqttClientRef = &client;
    mqttPlainClientRef = &plainClient;
    loadConfig();
    applyClientConfig();
    Serial.print(F("[MQTT] Web/NVS config: "));
    Serial.print(mqttCfg.enabled ? F("ON ") : F("OFF "));
    Serial.print(mqttCfg.broker); Serial.print(':'); Serial.print(mqttCfg.port);
    Serial.print(F(" topic=")); Serial.print(mqttCfg.baseTopic);
    Serial.print(F(" tls=")); Serial.println(mqttTlsModeName(mqttCfg.tlsMode));
}

MqttRuntimeConfig getMqttConfig() { return mqttCfg; }
bool mqttEnabled() { return mqttCfg.enabled; }
bool mqttRuntimeConnected() { return mqttCfg.enabled && mqttClientRef && mqttClientRef->connected(); }

const char *mqttTlsModeName(MqttTlsMode mode) {
    switch (mode) {
        case MqttTlsMode::CaVerified: return "TLS-CA";
        case MqttTlsMode::Insecure: return "TLS-INSECURE";
        default: return "OFF";
    }
}

bool validateMqttConfig(const MqttRuntimeConfig &cfg, bool replacePassword, bool replaceCaCertificate) {
    if (replaceCaCertificate && cfg.caCertificate.length() > 3900U) return false;
    MqttRuntimeConfig next = cfg;
    if (!replacePassword) next.password = mqttCfg.password;
    if (!replaceCaCertificate) next.caCertificate = mqttCfg.caCertificate;
    normalize(next);
    if (next.enabled && next.broker.length() == 0) return false;
    if (next.enabled && next.tlsMode == MqttTlsMode::CaVerified && next.caCertificate.length() == 0) return false;
    return true;
}

bool saveMqttConfig(const MqttRuntimeConfig &cfg, bool replacePassword, bool replaceCaCertificate) {
    // Una stringa NVS e' limitata a 4000 byte incluso il terminatore.
    // Rifiutiamo una CA troppo grande invece di troncarla silenziosamente.
    if (!validateMqttConfig(cfg, replacePassword, replaceCaCertificate)) return false;
    MqttRuntimeConfig next = cfg;
    if (!replacePassword) next.password = mqttCfg.password;
    if (!replaceCaCertificate) next.caCertificate = mqttCfg.caCertificate;
    normalize(next);
    if (next.enabled && next.broker.length() == 0) return false;
    if (next.enabled && next.tlsMode == MqttTlsMode::CaVerified && next.caCertificate.length() == 0) return false;

    const MqttRuntimeConfig old = mqttCfg;
    const bool changed = next.enabled != old.enabled || next.broker != old.broker ||
                         next.port != old.port || next.user != old.user ||
                         next.password != old.password || next.clientId != old.clientId ||
                         next.baseTopic != old.baseTopic || next.tlsMode != old.tlsMode ||
                         next.caCertificate != old.caCertificate || next.fieldsMask != old.fieldsMask;
    if (!changed) return true; // nessuna scrittura NVS e nessun reconnect inutile

    // NVS e' gia' wear-levelled da ESP-IDF. In piu', V6.3 scrive soltanto le
    // chiavi realmente modificate e solo su azione esplicita dell'utente.
    if (!mqttPrefs.begin("mqttcfg", false)) {
        Serial.println(F("[MQTT] ERRORE apertura NVS mqttcfg in scrittura"));
        return false;
    }
    if (next.enabled != old.enabled) mqttPrefs.putBool("enabled", next.enabled);
    if (next.broker != old.broker) mqttPrefs.putString("broker", next.broker);
    if (next.port != old.port) mqttPrefs.putUShort("port", next.port);
    if (next.user != old.user) mqttPrefs.putString("user", next.user);
    if (next.password != old.password) mqttPrefs.putString("pass", next.password);
    if (next.clientId != old.clientId) mqttPrefs.putString("client", next.clientId);
    if (next.baseTopic != old.baseTopic) mqttPrefs.putString("topic", next.baseTopic);
    if (next.tlsMode != old.tlsMode) mqttPrefs.putUChar("tlsmode", static_cast<uint8_t>(next.tlsMode));
    if (next.caCertificate != old.caCertificate) mqttPrefs.putString("cacert", next.caCertificate);
    if (next.fieldsMask != old.fieldsMask) mqttPrefs.putUInt("fields", next.fieldsMask);
    const bool verified = verifyStoredMqttConfig(mqttPrefs, next);
    mqttPrefs.end();
    if (!verified) {
        Serial.println(F("[MQTT] ERRORE verifica NVS mqttcfg: configurazione non confermata"));
        return false;
    }
    mqttCfg = next;
    applyClientConfig();
    Serial.println(F("[MQTT] configurazione Web verificata in NVS"));
    return true;
}

bool resetMqttConfigToDefaults() {
    MqttRuntimeConfig d = defaults();
    normalize(d);
    const bool already = mqttCfg.enabled == d.enabled && mqttCfg.broker == d.broker && mqttCfg.port == d.port &&
        mqttCfg.user == d.user && mqttCfg.password == d.password && mqttCfg.clientId == d.clientId &&
        mqttCfg.baseTopic == d.baseTopic && mqttCfg.tlsMode == d.tlsMode &&
        mqttCfg.caCertificate == d.caCertificate && mqttCfg.fieldsMask == d.fieldsMask;
    if (already) return true;
    if (!mqttPrefs.begin("mqttcfg", false)) {
        Serial.println(F("[MQTT] ERRORE apertura NVS mqttcfg per reset"));
        return false;
    }
    const bool cleared = mqttPrefs.clear();
    const bool verified = cleared && verifyStoredMqttConfig(mqttPrefs, d);
    mqttPrefs.end();
    if (!verified) {
        Serial.println(F("[MQTT] ERRORE reset/verifica NVS mqttcfg"));
        return false;
    }
    mqttCfg = d;
    applyClientConfig();
    Serial.println(F("[MQTT] default firmware verificati dopo reset NVS"));
    return true;
}

void serviceMQTT(PubSubClient &client) {
    if (!mqttCfg.enabled) {
        if (client.connected()) client.disconnect();
        return;
    }
    if (!wifiConnected() || mqttCfg.broker.length() == 0) return;
    if (client.connected()) { client.loop(); return; }

    const uint32_t now = millis();
    if (static_cast<uint32_t>(now - lastAttemptMs) < MQTT_RETRY_MS) return;
    lastAttemptMs = now;

    const String statusTopic = topic("status");
    const String clientId = effectiveClientId();
    Serial.print(F("[MQTT] connessione ")); Serial.print(mqttCfg.broker); Serial.print(':'); Serial.print(mqttCfg.port);
    Serial.print(F(" come ")); Serial.print(clientId); Serial.print(F(" tls=")); Serial.print(mqttTlsModeName(mqttCfg.tlsMode)); Serial.print(F("... "));

    bool ok;
    if (mqttCfg.user.length() > 0) {
        ok = client.connect(clientId.c_str(), mqttCfg.user.c_str(), mqttCfg.password.c_str(),
                            statusTopic.c_str(), 1, true, "offline");
    } else {
        ok = client.connect(clientId.c_str(), statusTopic.c_str(), 1, true, "offline");
    }
    if (ok) {
        Serial.println(F("OK"));
        client.publish(statusTopic.c_str(), "online", true);
        client.publish(topic("ip").c_str(), wifiIpAddress().c_str(), true);
        client.publish(topic("rf/protocol").c_str(), "Oregon-OSV3+Technoline-WS23xx", true);
    } else {
        Serial.print(F("fallita rc=")); Serial.println(client.state());
    }
}

void prepareMqttForDeepSleep() {
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

bool mqttConnected(PubSubClient &client) { return mqttCfg.enabled && client.connected(); }

void publishWeatherReading(PubSubClient &client, const WeatherReading &reading, const OregonPacket &packet) {
    if (!mqttCfg.enabled || !client.connected()) return;

    const bool thermo = reading.type == SensorType::ThermoHygro;
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
        if (reading.batteryStatusValid) {
            snprintf(suffix, sizeof(suffix), "oregon/thermo/ch%u/battery", reading.channel);
            client.publish(topic(suffix).c_str(), reading.batteryLow ? "LOW" : "OK", true);
        }
        if (!isnan(reading.rssi)) {
            snprintf(suffix, sizeof(suffix), "oregon/thermo/ch%u/rssi", reading.channel);
            publishFloat(client, suffix, reading.rssi, 1);
        }
    }
    }
    if (reading.windAverageValid && fieldEnabled(MQTT_F_OR_WIND_AVG)) publishFloat(client, "oregon/wind/average", reading.windAverageKmh, 1);
    if (reading.windGustValid && fieldEnabled(MQTT_F_OR_WIND_GUST)) {
        // Il campo Oregon viene mantenuto come "gust/current" per compatibilita' storica.
        publishFloat(client, "oregon/wind/current", reading.windGustKmh, 1);
        publishFloat(client, "oregon/wind/gust", reading.windGustKmh, 1);
    }
    if (reading.windDirectionValid && fieldEnabled(MQTT_F_OR_WIND_DIR)) {
        publishFloat(client, "oregon/wind/direction_deg", reading.windDirectionDeg, 1);
        client.publish(topic("oregon/wind/direction").c_str(), windDirectionName(reading.windDirectionIndex), true);
    }
    if (reading.rainTotalValid && fieldEnabled(MQTT_F_OR_RAIN_TOTAL)) publishFloat(client, "oregon/rain/total", reading.rainTotalMm, 2);
    if (reading.rainRateValid && fieldEnabled(MQTT_F_OR_RAIN_RATE)) publishFloat(client, "oregon/rain/rate", reading.rainRateMmH, 2);
    if (reading.uvValid && fieldEnabled(MQTT_F_OR_UV)) publishInt(client, "oregon/uv", reading.uvIndex);

    if (fieldEnabled(MQTT_F_RF_META)) {
        char sensorId[8]; snprintf(sensorId, sizeof(sensorId), "0x%02X", reading.sensorId);
        client.publish(topic("oregon/rf/sensor_id").c_str(), sensorId, true);
        client.publish(topic("oregon/rf/sensor_type").c_str(), sensorTypeName(reading.type), true);
        client.publish(topic("oregon/rf/sensor_model").c_str(), sensorModelName(reading.sensorCode), true);
        char sensorCode[8]; snprintf(sensorCode, sizeof(sensorCode), "%04X", reading.sensorCode);
        client.publish(topic("oregon/rf/sensor_code").c_str(), sensorCode, true);
        if (reading.channel) publishInt(client, "oregon/rf/channel", reading.channel);
        if (reading.batteryStatusValid) client.publish(topic("oregon/rf/battery").c_str(), reading.batteryLow ? "LOW" : "OK", true);
        if (!isnan(reading.rssi)) publishFloat(client, "oregon/rf/rssi", reading.rssi, 1);

        char raw[OREGON_MAX_PACKET_BYTES * 2 + 1]; size_t pos = 0;
        for (uint8_t i = 0; i < packet.length && pos + 2 < sizeof(raw); ++i)
            pos += snprintf(raw + pos, sizeof(raw) - pos, "%02X", packet.bytes[i]);
        client.publish(topic("oregon/rf/raw").c_str(), raw, false);
    }
}

void publishLaCrosseReading(PubSubClient &client, const LaCrosseReading &reading, const LaCrossePacket &packet) {
    if (!mqttCfg.enabled || !client.connected()) return;
    const String base = mqttCfg.baseTopic + "/technoline";
    auto pubf=[&](const char *suffix, float v, uint8_t d){ char b[24]; dtostrf(v,0,d,b); client.publish((base+"/"+suffix).c_str(),b,true); };
    auto pubi=[&](const char *suffix, int v){ char b[16]; snprintf(b,sizeof(b),"%d",v); client.publish((base+"/"+suffix).c_str(),b,true); };

    if (reading.temperatureValid && fieldEnabled(MQTT_F_LC_TEMP)) pubf("temperature", reading.temperatureC, 1);
    if (reading.humidityValid && fieldEnabled(MQTT_F_LC_HUM)) pubf("humidity", reading.humidityPct, 0);
    if (reading.rainValid && fieldEnabled(MQTT_F_LC_RAIN)) pubf("rain/total", reading.rainTotalMm, 2);
    if (reading.windValid && fieldEnabled(MQTT_F_LC_WIND)) pubf("wind/speed", reading.windKmh, 1);
    if (reading.gustValid && fieldEnabled(MQTT_F_LC_GUST)) pubf("wind/gust", reading.gustKmh, 1);
    if (reading.directionValid && fieldEnabled(MQTT_F_LC_DIR)) {
        pubf("wind/direction_deg", reading.directionDeg, 1);
        client.publish((base+"/wind/direction").c_str(), laCrosseWindDirectionName(reading.directionIndex), true);
    }
    if (fieldEnabled(MQTT_F_RF_META)) {
        client.publish((base+"/model").c_str(), laCrosseModelName(reading.wsId), true);
        pubi("sensor_id", reading.sensorId);
        client.publish((base+"/type").c_str(), laCrosseTypeName(reading.type), false);
        if (!isnan(reading.rssi)) pubf("rf/rssi", reading.rssi, 1);
        client.publish((base+"/next_update").c_str(), laCrosseNextUpdateName(reading.nextUpdateCode), true);
        char raw[14]; for(uint8_t i=0;i<13;i++) snprintf(raw+i,2,"%X",packet.nibbles[i]&0xF); raw[13]='\0';
        client.publish((base+"/rf/raw").c_str(), raw, false);
    }
}

void publishStationState(PubSubClient &client, const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats) {
    if (!mqttCfg.enabled || !client.connected()) return;

    if (fieldEnabled(MQTT_F_STATE_JSON)) {
        char json[1800];
        const uint32_t now = millis();
        const String temperature = state.thermoValid ? String(state.temperatureC, static_cast<unsigned int>(1)) : String("null");
        const String humidity = state.thermoValid ? String(state.humidityPct, static_cast<unsigned int>(0)) : String("null");
        const String heatIndex = state.heatIndexValid ? String(state.heatIndexC, static_cast<unsigned int>(1)) : String("null");
        const String dewPoint = state.dewPointValid ? String(state.dewPointC, static_cast<unsigned int>(1)) : String("null");
        const String windAverage = state.windValid ? String(state.windAverageKmh, static_cast<unsigned int>(1)) : String("null");
        const String windGust = state.windValid ? String(state.windGustKmh, static_cast<unsigned int>(1)) : String("null");
        const String windDirection = state.windValid ? String(state.windDirectionDeg, static_cast<unsigned int>(1)) : String("null");
        const String windChill = state.windChillValid ? String(state.windChillC, static_cast<unsigned int>(1)) : String("null");
        const String rainTotal = state.rainValid ? String(state.rainTotalMm, static_cast<unsigned int>(2)) : String("null");
        const String rainRate = state.rainValid ? String(state.rainRateMmH, static_cast<unsigned int>(2)) : String("null");
        const String rainInc = state.rainIncrementValid ? String(state.rainIncrementMm, static_cast<unsigned int>(2)) : String("null");
        const String rain1h = state.rainLastHourValid ? String(state.rainLastHourMm, static_cast<unsigned int>(2)) : String("null");
        const String rain24h = state.rainLast24hValid ? String(state.rainLast24hMm, static_cast<unsigned int>(2)) : String("null");
        const String pressureAbs = state.pressureValid ? String(state.pressureAbsoluteHpa, static_cast<unsigned int>(1)) : String("null");
        const String pressureSea = state.pressureValid ? String(state.pressureSeaLevelHpa, static_cast<unsigned int>(1)) : String("null");
        const String pressureTrend = state.pressureTrendValid ? String(state.pressureTrendHpa3h, static_cast<unsigned int>(1)) : String("null");
        const String indoorTemp = state.indoorTemperatureValid ? String(state.indoorTemperatureC, static_cast<unsigned int>(1)) : String("null");
        const String indoorHum = state.indoorHumidityValid ? String(state.indoorHumidityPct, static_cast<unsigned int>(0)) : String("null");

        snprintf(json, sizeof(json),
            "{\"temperature_c\":%s,\"humidity_pct\":%s,\"heat_index_c\":%s,\"dew_point_c\":%s,"
            "\"indoor_temperature_c\":%s,\"indoor_humidity_pct\":%s,"
            "\"wind_average_kmh\":%s,\"wind_gust_kmh\":%s,\"wind_direction_deg\":%s,\"wind_chill_c\":%s,"
            "\"rain_total_mm\":%s,\"rain_rate_mmh\":%s,\"rain_increment_mm\":%s,\"rain_1h_mm\":%s,\"rain_24h_mm\":%s,"
            "\"uv\":%d,\"pressure_station_hpa\":%s,\"altimeter_hpa\":%s,\"pressure_trend_hpa_3h\":%s,"
            "\"thermo_fresh\":%s,\"wind_fresh\":%s,\"rain_fresh\":%s,\"uv_fresh\":%s,"
            "\"packets\":%lu,\"rejected\":%lu,\"raw_A1\":%lu,\"wind_recovery\":%lu,\"wind_recovery_starts\":%lu,"
            "\"edges\":%lu,\"overflows\":%lu,\"wifi_rssi\":%ld,"
            "\"battery_thermo\":\"%s\",\"battery_wind\":\"%s\",\"battery_rain\":\"%s\",\"battery_uv\":\"%s\"}",
            temperature.c_str(), humidity.c_str(), heatIndex.c_str(), dewPoint.c_str(),
            indoorTemp.c_str(), indoorHum.c_str(),
            windAverage.c_str(), windGust.c_str(), windDirection.c_str(), windChill.c_str(),
            rainTotal.c_str(), rainRate.c_str(), rainInc.c_str(), rain1h.c_str(), rain24h.c_str(),
            state.uvValid ? state.uvIndex : -1,
            pressureAbs.c_str(), pressureSea.c_str(), pressureTrend.c_str(),
            sensorFresh(state.thermoUpdatedMs, now) ? "true" : "false",
            sensorFresh(state.windUpdatedMs, now) ? "true" : "false",
            sensorFresh(state.rainUpdatedMs, now) ? "true" : "false",
            sensorFresh(state.uvUpdatedMs, now) ? "true" : "false",
            static_cast<unsigned long>(state.validPacketCount),
            static_cast<unsigned long>(state.rejectedPacketCount),
            static_cast<unsigned long>(rxStats.rawWindFrames),
            static_cast<unsigned long>(rxStats.windRecoverySuccess),
            static_cast<unsigned long>(rxStats.windRecoveryStarts),
            static_cast<unsigned long>(rxStats.edgesCaptured),
            static_cast<unsigned long>(rxStats.ringOverflows),
            static_cast<long>(wifiRssi()),
            sensorBatteryName(state.thermoSensor),
            sensorBatteryName(state.windSensor),
            sensorBatteryName(state.rainSensor),
            sensorBatteryName(state.uvSensor));

        client.publish(topic("state").c_str(), json, true);

    }

    // V6.3: BME280 separato logicamente dai due protocolli RF.
    // I topic /local/bme280/* sono quelli raccomandati; manteniamo i vecchi
    // /pressure/* come alias di compatibilita' per installazioni esistenti.
    if (state.indoorTemperatureValid && fieldEnabled(MQTT_F_BME_TEMP)) publishFloat(client, "local/bme280/temperature", state.indoorTemperatureC, 1);
    if (state.indoorHumidityValid && fieldEnabled(MQTT_F_BME_HUM)) publishFloat(client, "local/bme280/humidity", state.indoorHumidityPct, 0);
    if (state.pressureValid) {
        if (fieldEnabled(MQTT_F_BME_PRESS)) {
            publishFloat(client, "local/bme280/pressure_station_hpa", state.pressureAbsoluteHpa, 1);
            publishFloat(client, "pressure/station_hpa", state.pressureAbsoluteHpa, 1);
        }
        if (fieldEnabled(MQTT_F_BME_ALTIMETER)) {
            publishFloat(client, "local/bme280/altimeter_hpa", state.pressureSeaLevelHpa, 1);
            publishFloat(client, "pressure/altimeter_hpa", state.pressureSeaLevelHpa, 1);
        }
    }
    if (state.pressureTrendValid && fieldEnabled(MQTT_F_BME_TREND)) {
        publishFloat(client, "local/bme280/trend_hpa_3h", state.pressureTrendHpa3h, 1);
        publishFloat(client, "pressure/trend_hpa_3h", state.pressureTrendHpa3h, 1);
    }
    if (state.rainLastHourValid && fieldEnabled(MQTT_F_OR_RAIN_1H)) publishFloat(client, "oregon/rain/last_hour", state.rainLastHourMm, 2);
    if (state.rainLast24hValid && fieldEnabled(MQTT_F_OR_RAIN_24H)) publishFloat(client, "oregon/rain/last_24h", state.rainLast24hMm, 2);
    if (state.rainIncrementValid && fieldEnabled(MQTT_F_OR_RAIN_INC)) publishFloat(client, "oregon/rain/increment", state.rainIncrementMm, 2);
    if (state.heatIndexValid && fieldEnabled(MQTT_F_OR_HEAT_INDEX)) publishFloat(client, "oregon/heat_index", state.heatIndexC, 1);
    if (state.dewPointValid && fieldEnabled(MQTT_F_OR_DEW_POINT)) publishFloat(client, "oregon/dew_point", state.dewPointC, 1);
    if (state.windChillValid && fieldEnabled(MQTT_F_OR_WIND_CHILL)) publishFloat(client, "oregon/wind/chill", state.windChillC, 1);
    if (fieldEnabled(MQTT_F_RF_META)) {
        if (state.thermoSensor.batteryKnown) client.publish(topic("oregon/battery/thermo").c_str(), sensorBatteryName(state.thermoSensor), true);
        if (state.windSensor.batteryKnown) client.publish(topic("oregon/battery/wind").c_str(), sensorBatteryName(state.windSensor), true);
        if (state.rainSensor.batteryKnown) client.publish(topic("oregon/battery/rain").c_str(), sensorBatteryName(state.rainSensor), true);
        if (state.uvSensor.batteryKnown) client.publish(topic("oregon/battery/uv").c_str(), sensorBatteryName(state.uvSensor), true);
    }

    if (state.lacrosse.temperatureValid && fieldEnabled(MQTT_F_LC_TEMP)) publishFloat(client, "technoline/temperature", state.lacrosse.temperatureC, 1);
    if (state.lacrosse.humidityValid && fieldEnabled(MQTT_F_LC_HUM)) publishFloat(client, "technoline/humidity", state.lacrosse.humidityPct, 0);
    if (state.lacrosse.rainValid && fieldEnabled(MQTT_F_LC_RAIN)) publishFloat(client, "technoline/rain/total", state.lacrosse.rainTotalMm, 2);
    if (state.lacrosse.windValid && fieldEnabled(MQTT_F_LC_WIND)) publishFloat(client, "technoline/wind/speed", state.lacrosse.windKmh, 1);
    if (state.lacrosse.gustValid && fieldEnabled(MQTT_F_LC_GUST)) publishFloat(client, "technoline/wind/gust", state.lacrosse.gustKmh, 1);
    if (state.lacrosse.directionValid && fieldEnabled(MQTT_F_LC_DIR)) publishFloat(client, "technoline/wind/direction_deg", state.lacrosse.windDirectionDeg, 1);
    if (fieldEnabled(MQTT_F_RF_META)) {
        publishInt(client, "technoline/packets", state.lacrosse.validPacketCount);
        publishInt(client, "technoline/rf/valid", lcStats.validFrames);
    }
    if (fieldEnabled(MQTT_F_SYSTEM)) {
        publishInt(client, "system/cpu_mhz", ESP.getCpuFreqMHz());
        publishInt(client, "system/heap_free", ESP.getFreeHeap());
        publishInt(client, "system/heap_min_free", ESP.getMinFreeHeap());
        publishInt(client, "system/wifi_rssi", wifiRssi());
        publishInt(client, "system/rf_overflows", rxStats.ringOverflows);
        publishInt(client, "system/uptime_s", millis() / 1000UL);
    }
}

