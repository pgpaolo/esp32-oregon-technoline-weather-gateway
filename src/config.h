#pragma once

// Le credenziali reali possono stare in config_private.h, ignorato da Git.
#if __has_include("config_private.h")
#include "config_private.h"
#endif

#ifndef FIRMWARE_VERSION
#define FIRMWARE_VERSION         "6.4.0-rc4"
#endif
#ifndef GIT_COMMIT_HASH
#define GIT_COMMIT_HASH          "source-archive"
#endif

// Pulsante fisico PRG/BOOT: pressione breve = OLED ON/OFF.
// GPIO0 e' il BOOT/User button sulle T3-S3; sulla T3 V1.6.1 il progetto
// Toggle fisico OLED opzionale; la politica di default dipende dalla board.
#ifndef OLED_BUTTON_ENABLE
// Il T3-S3 dichiara ufficialmente BUTTON_PIN=0. Sul T3 V1.6.1 il pinout
// LILYGO non espone un BUTTON_PIN applicativo: per prudenza il toggle fisico
// resta disabilitato di default e puo' essere abilitato esplicitamente da
// config_private.h dopo verifica della propria revisione hardware.
#if defined(BOARD_T3_S3_SX1278)
#define OLED_BUTTON_ENABLE       1
#else
#define OLED_BUTTON_ENABLE       0
#endif
#endif
#ifndef OLED_BUTTON_PIN
#define OLED_BUTTON_PIN          0
#endif
#ifndef OLED_BUTTON_DEBOUNCE_MS
#define OLED_BUTTON_DEBOUNCE_MS  35UL
#endif
#ifndef OLED_BUTTON_MIN_PRESS_MS
#define OLED_BUTTON_MIN_PRESS_MS 45UL
#endif
#ifndef OLED_BUTTON_MAX_PRESS_MS
#define OLED_BUTTON_MAX_PRESS_MS 1800UL
#endif

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

#ifndef WIFI_SSID
#define WIFI_SSID               "NomeReteWiFi"
#endif
#ifndef DEVICE_HOSTNAME
#define DEVICE_HOSTNAME         "oregon-gateway"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD           "PasswordWiFi"
#endif

// IP statico richiesto per la dashboard.
#ifndef WIFI_USE_STATIC_IP
#define WIFI_USE_STATIC_IP      1
#endif
#ifndef WIFI_IP_A
#define WIFI_IP_A               192
#define WIFI_IP_B               168
#define WIFI_IP_C               1
#define WIFI_IP_D               220
#endif
#ifndef WIFI_GW_A
#define WIFI_GW_A               192
#define WIFI_GW_B               168
#define WIFI_GW_C               1
#define WIFI_GW_D               1
#endif
#ifndef WIFI_MASK_A
#define WIFI_MASK_A             255
#define WIFI_MASK_B             255
#define WIFI_MASK_C             255
#define WIFI_MASK_D             0
#endif
#ifndef WIFI_DNS_A
#define WIFI_DNS_A              WIFI_GW_A
#define WIFI_DNS_B              WIFI_GW_B
#define WIFI_DNS_C              WIFI_GW_C
#define WIFI_DNS_D              WIFI_GW_D
#endif

#ifndef MQTT_BROKER
#define MQTT_BROKER             "192.168.1.100"
#endif
#ifndef MQTT_PORT
#define MQTT_PORT               1883
#endif
#ifndef MQTT_USER
#define MQTT_USER               "mqtt_user"
#endif
#ifndef MQTT_PASSWORD
#define MQTT_PASSWORD           "mqtt_password"
#endif
#ifndef MQTT_CLIENT_ID
#define MQTT_CLIENT_ID          "OregonWeatherStation"
#endif
#ifndef MQTT_BASE_TOPIC
#define MQTT_BASE_TOPIC         "weatherstation"
#endif
#ifndef MQTT_TLS_MODE
#define MQTT_TLS_MODE           0   // 0=OFF, 1=TLS+CA, 2=TLS insecure (test)
#endif
#ifndef MQTT_CA_CERT
#define MQTT_CA_CERT            ""
#endif
#ifndef MQTT_FIELDS_MASK
#define MQTT_FIELDS_MASK        0x0FFFFFFFUL
#endif

#define OREGON_PROTOCOL_NAME    "OSV2.1+OSV3"
#define OREGON_PROTOCOL_VERSION "2.1/3.0"
#ifndef OREGON_FREQUENCY_MHZ
#define OREGON_FREQUENCY_MHZ    433.92f
#endif

// Il chip-rate serve al modem SX1278; in raw-edge il bit synchronizer e' disabilitato.
#ifndef OREGON_CHIP_RATE_KBPS
#define OREGON_CHIP_RATE_KBPS   2.048f
#endif

// Profilo RF di default CONSERVATIVO: e' quello piu vicino alla V4.3 che ha
// dimostrato sul campo di ricevere AF/A2/AD. La banda piu stretta della V4.6
// resta disponibile da config_private.h per test, ma non e' piu il default.
#ifndef OREGON_RX_BW_KHZ
#define OREGON_RX_BW_KHZ        125.0f
#endif
#ifndef OREGON_RX_GAIN
#define OREGON_RX_GAIN          0       // 0 = AGC automatico, 1 = massimo guadagno fisso
#endif

// PCR800: 0.001 inch/count = 0.0254 mm/count.
#ifndef OREGON_RAIN_MM_PER_RAW
#define OREGON_RAIN_MM_PER_RAW  0.0254f
#endif

#ifndef OREGON_RAW_EDGE_MODE
#define OREGON_RAW_EDGE_MODE    1
#endif

#ifndef OREGON_HEADER_ONES
#define OREGON_HEADER_ONES      15
#endif

// Decoder principale: invariato rispetto alla V4.3 stabile.
#ifndef OREGON_STRONG_PREAMBLE_MIN_SHORTS
#define OREGON_STRONG_PREAMBLE_MIN_SHORTS  28
#endif

// WGR800 1984 resta un normale sensore Oregon Protocol 3.0.
// La V6.3 non abbassa il requisito di preambolo: la diagnosi RF e' separata
// e lo scanner A1 scorrevole resta solo come fallback checksum-gated.

// Scanner scorrevole A1 + checksum, ulteriore fallback indipendente dal preambolo.

#ifndef OREGON_EDGE_MIN_US
#define OREGON_EDGE_MIN_US      120
#endif
#ifndef OREGON_EDGE_MAX_US
#define OREGON_EDGE_MAX_US      1600
#endif
#ifndef OREGON_EDGE_MAX_TIMING_ERROR_US
#define OREGON_EDGE_MAX_TIMING_ERROR_US 260
#endif

#ifndef WEB_ENABLE
#define WEB_ENABLE              1
#endif

// Pressione locale hardware BME280 sullo stesso bus I2C dell'OLED.
#ifndef BAROMETER_ENABLE
#define BAROMETER_ENABLE        1
#endif
#ifndef BAROMETER_ALTITUDE_M
#define BAROMETER_ALTITUDE_M    584.0f
#endif
#ifndef BAROMETER_READ_MS
#define BAROMETER_READ_MS       5000UL
#endif
#ifndef BAROMETER_TREND_SAMPLE_MS
#define BAROMETER_TREND_SAMPLE_MS 600000UL   // 10 minuti
#endif

#define RF_DIAGNOSTIC_INTERVAL_MS 10000UL
#define WIFI_RETRY_MS           15000UL
#define MQTT_RETRY_MS           5000UL
#define DISPLAY_REFRESH_MS      1000UL
#define DISPLAY_PAGE_MS         7000UL
#define SENSOR_STALE_MS         180000UL
#define SERIAL_PACKET_DUMP      1

// V4.8 decoder state-aware: soglie documentate per protocolli OS 2.1/3.0.
// Per OSV3 i valori ideali sono ON 349/837 us e OFF 628/1116 us.
#ifndef OREGON_STATE_PREAMBLE_MIN_SHORTS
#define OREGON_STATE_PREAMBLE_MIN_SHORTS  28
#endif

// OS V2.1 trasmette i 16 bit di preambolo come 32 bit fisici alternati.
// Nel decoder a intervalli questo appare come una sequenza di long. Una
// rtl_433 usa 16 bit fisici stabili prima della ricerca del sync: la stessa
// soglia tollera il preambolo UVR128 troncato dall'avvio tardivo del data
// slicer. Coppie, Sensor ID, lunghezza completa e checksum restano obbligatori.
#ifndef OREGON_V21_PREAMBLE_MIN_LONGS
#define OREGON_V21_PREAMBLE_MIN_LONGS     15
#endif
#ifndef OREGON_STATE_ON_SHORT_MIN_US
#define OREGON_STATE_ON_SHORT_MIN_US       200
#define OREGON_STATE_ON_SHORT_MAX_US       615
#define OREGON_STATE_ON_LONG_MIN_US        615
#define OREGON_STATE_ON_LONG_MAX_US        1100
#endif
#ifndef OREGON_STATE_OFF_SHORT_MIN_US
#define OREGON_STATE_OFF_SHORT_MIN_US      400
#define OREGON_STATE_OFF_SHORT_MAX_US      850
#define OREGON_STATE_OFF_LONG_MIN_US       850
#define OREGON_STATE_OFF_LONG_MAX_US       1400
#endif

// -----------------------------------------------------------------------------
// Technoline WS230x / La Crosse WS-23xx compatibility mode sullo stesso SX1278.
// Il decoder usa il framing OOK/PWM WS-2310 documentato da rtl_433: short
// 368 us, long 1464 us, fixed gap 1336 us, 52 bit. La compatibilita' esatta
// del singolo Technoline viene verificata sul campo tramite checksum + raw bins.
// -----------------------------------------------------------------------------
#ifndef LACROSSE_WS23XX_ENABLE
#define LACROSSE_WS23XX_ENABLE             1
#endif
#ifndef LACROSSE_SHORT_PULSE_US
#define LACROSSE_SHORT_PULSE_US            368U
#endif
#ifndef LACROSSE_LONG_PULSE_US
#define LACROSSE_LONG_PULSE_US             1464U
#endif
#ifndef LACROSSE_FIXED_GAP_US
#define LACROSSE_FIXED_GAP_US              1336U
#endif
// WS-2310/WS-230x: timing di riferimento rtl_433: short 368 us, long 1464 us, gap 1336 us, reset 8000 us.
// Il decoder V6.3 mantiene finestre ampie per compensare la deformazione del data slicer SX1278 e auto-calibra dopo frame valido.
#ifndef LACROSSE_INTERVAL_MIN_US
#define LACROSSE_INTERVAL_MIN_US           60U
#endif
#ifndef LACROSSE_INTERVAL_MAX_US
#define LACROSSE_INTERVAL_MAX_US           4000U
#endif
#ifndef LACROSSE_PERIOD_TOLERANCE_US
#define LACROSSE_PERIOD_TOLERANCE_US       500U
#endif
#ifndef LACROSSE_RESET_MIN_US
#define LACROSSE_RESET_MIN_US              8000U
#endif
#ifndef LACROSSE_SENSOR_STALE_MS
#define LACROSSE_SENSOR_STALE_MS           300000UL
#endif
