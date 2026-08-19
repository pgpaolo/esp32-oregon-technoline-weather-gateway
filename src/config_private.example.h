#pragma once

#define WIFI_SSID               "nome_wifi_2_4GHz"
#define WIFI_PASSWORD           "password_wifi"
#define DEVICE_HOSTNAME         "oregon-gateway"

// Toggle fisico OLED. T3-S3: GPIO0 e' il BUTTON_PIN ufficiale.
// T3 V1.6.1: abilitare solo dopo verifica della propria revisione hardware.
// #define OLED_BUTTON_ENABLE   1
// #define OLED_BUTTON_PIN      0

#define WIFI_USE_STATIC_IP      1
#define WIFI_IP_A 192
#define WIFI_IP_B 168
#define WIFI_IP_C 1
#define WIFI_IP_D 220
#define WIFI_GW_A 192
#define WIFI_GW_B 168
#define WIFI_GW_C 1
#define WIFI_GW_D 1
#define WIFI_MASK_A 255
#define WIFI_MASK_B 255
#define WIFI_MASK_C 255
#define WIFI_MASK_D 0
#define WIFI_DNS_A 192
#define WIFI_DNS_B 168
#define WIFI_DNS_C 1
#define WIFI_DNS_D 1

#define MQTT_BROKER             "192.168.1.100"
#define MQTT_PORT               1883
#define MQTT_USER               "mqtt_user"
#define MQTT_PASSWORD           "mqtt_password"
#define MQTT_CLIENT_ID          "OregonWeatherStation"
#define MQTT_BASE_TOPIC         "weatherstation"
// TLS MQTT opzionale: 0=OFF, 1=TLS con CA, 2=TLS senza verifica (solo test)
#define MQTT_TLS_MODE           0
// Per una CA compilata nel firmware usare una stringa PEM C; normalmente e'
// piu comodo inserirla dalla Web.
#define MQTT_CA_CERT            ""
// Tutti i campi MQTT abilitati. Dalla Web e' possibile selezionarli singolarmente.
#define MQTT_FIELDS_MASK        0x0FFFFFFFUL

// BME280 locale. Impostare la quota reale della stazione per ottenere
// l'altimetro/pressione ridotta al livello del mare.
#define BAROMETER_ENABLE        1
#define BAROMETER_ALTITUDE_M    584.0f

// RF - profilo stabile consigliato.
#define OREGON_RX_BW_KHZ        125.0f
#define OREGON_RX_GAIN          0
#define OREGON_STRONG_PREAMBLE_MIN_SHORTS 28
// WGR800 1984 trattato come normale Oregon Protocol 3.0; nessuna soglia speciale.

// Profilo piu aggressivo da provare solo se necessario:
// #define OREGON_RX_BW_KHZ     83.3f
// #define OREGON_RX_GAIN       1

// Technoline WS230x / WS-2310 compatibility: normalmente NON modificare.
// #define LACROSSE_WS23XX_ENABLE        1
// Doppio decoder live (rtl_433 pulse-window + PracticalArduino leader 00001).
// #define LACROSSE_PERIOD_TOLERANCE_US 500U
// #define LACROSSE_RESET_MIN_US        8000U
