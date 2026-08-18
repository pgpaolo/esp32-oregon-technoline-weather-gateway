#pragma once
#include <Arduino.h>
#include <Client.h>
#include <PubSubClient.h>
#include "station_state.h"
#include "oregon_types.h"
#include "oregon_receiver.h"
#include "lacrosse_ws23xx.h"

// Modalita' TLS configurabile da Web.
// 0 = nessun TLS, 1 = TLS con verifica CA, 2 = TLS senza verifica (solo test/LAN fidata).
enum class MqttTlsMode : uint8_t {
    Off = 0,
    CaVerified = 1,
    Insecure = 2
};

// Campi MQTT selezionabili. Il mask resta a 32 bit per essere semplice da
// salvare in NVS e compatibile con Preferences::putUInt/getUInt.
enum MqttField : uint32_t {
    MQTT_F_OR_TEMP        = 1UL << 0,
    MQTT_F_OR_HUM         = 1UL << 1,
    MQTT_F_OR_HEAT_INDEX  = 1UL << 2,
    MQTT_F_OR_DEW_POINT   = 1UL << 3,
    MQTT_F_OR_WIND_AVG    = 1UL << 4,
    MQTT_F_OR_WIND_GUST   = 1UL << 5,
    MQTT_F_OR_WIND_DIR    = 1UL << 6,
    MQTT_F_OR_WIND_CHILL  = 1UL << 7,
    MQTT_F_OR_RAIN_TOTAL  = 1UL << 8,
    MQTT_F_OR_RAIN_RATE   = 1UL << 9,
    MQTT_F_OR_RAIN_1H     = 1UL << 10,
    MQTT_F_OR_RAIN_24H    = 1UL << 11,
    MQTT_F_OR_RAIN_INC    = 1UL << 12,
    MQTT_F_OR_UV          = 1UL << 13,
    MQTT_F_LC_TEMP        = 1UL << 14,
    MQTT_F_LC_HUM         = 1UL << 15,
    MQTT_F_LC_RAIN        = 1UL << 16,
    MQTT_F_LC_WIND        = 1UL << 17,
    MQTT_F_LC_GUST        = 1UL << 18,
    MQTT_F_LC_DIR         = 1UL << 19,
    MQTT_F_BME_TEMP       = 1UL << 20,
    MQTT_F_BME_HUM        = 1UL << 21,
    MQTT_F_BME_PRESS      = 1UL << 22,
    MQTT_F_BME_ALTIMETER  = 1UL << 23,
    MQTT_F_BME_TREND      = 1UL << 24,
    MQTT_F_STATE_JSON     = 1UL << 25,
    MQTT_F_RF_META        = 1UL << 26,
    MQTT_F_SYSTEM         = 1UL << 27
};

static constexpr uint32_t MQTT_FIELDS_ALL = 0x0FFFFFFFUL;

struct MqttRuntimeConfig {
    bool enabled{true};
    String broker;
    uint16_t port{1883};
    String user;
    String password;
    String clientId;
    String baseTopic;
    MqttTlsMode tlsMode{MqttTlsMode::Off};
    String caCertificate;
    uint32_t fieldsMask{MQTT_FIELDS_ALL};
};

void initMQTT(PubSubClient &client, Client &plainClient);
void serviceMQTT(PubSubClient &client);
bool mqttConnected(PubSubClient &client);
bool mqttEnabled();
bool mqttRuntimeConnected();
MqttRuntimeConfig getMqttConfig();
bool saveMqttConfig(const MqttRuntimeConfig &cfg, bool replacePassword, bool replaceCaCertificate);
void resetMqttConfigToDefaults();
const char *mqttTlsModeName(MqttTlsMode mode);

void publishWeatherReading(PubSubClient &client, const WeatherReading &reading, const OregonPacket &packet);
void publishLaCrosseReading(PubSubClient &client, const LaCrosseReading &reading, const LaCrossePacket &packet);
void publishStationState(PubSubClient &client, const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats);
