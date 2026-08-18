#pragma once

// Pinout ufficiale LILYGO LilyGo-LoRa-Series.
// Il profilo viene selezionato dal build_flags di platformio.ini.

#if defined(BOARD_T3_S3_SX1278)

#define BOARD_NAME              "LILYGO T3-S3 SX1278"
#define I2C_SDA_PIN             18
#define I2C_SCL_PIN             17
#define OLED_ADDRESS            0x3C

#define RADIO_SCLK_PIN          5
#define RADIO_MISO_PIN          3
#define RADIO_MOSI_PIN          6
#define RADIO_CS_PIN            7
#define RADIO_DIO0_PIN          9
#define RADIO_RST_PIN           8
#define RADIO_DIO1_PIN          33
#define RADIO_DIO2_PIN          34
#define BOARD_LED_PIN           37
#define BOARD_LED_ON            HIGH
#define BATTERY_ADC_PIN         1

#else

// Default: T3/LoRa32 V1.6.1 ESP32 + SX1278 433 MHz.
#define BOARD_NAME              "LILYGO T3 V1.6.1 SX1278"
#define I2C_SDA_PIN             21
#define I2C_SCL_PIN             22
#define OLED_ADDRESS            0x3C

#define RADIO_SCLK_PIN          5
#define RADIO_MISO_PIN          19
#define RADIO_MOSI_PIN          27
#define RADIO_CS_PIN            18
#define RADIO_DIO0_PIN          26
#define RADIO_RST_PIN           23
#define RADIO_DIO1_PIN          33
#define RADIO_DIO2_PIN          32
#define BOARD_LED_PIN           25
#define BOARD_LED_ON            HIGH
#define BATTERY_ADC_PIN         35

#endif

#define BOARD_LED_OFF           (!BOARD_LED_ON)
