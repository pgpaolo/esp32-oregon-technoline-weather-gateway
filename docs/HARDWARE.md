# Hardware

## LILYGO T3 / LoRa32 V1.6.1 + SX1278

Default build environment: `t3-v161-433`

| Function | GPIO |
|---|---:|
| I²C SDA | 21 |
| I²C SCL | 22 |
| OLED address | `0x3C` |
| SX1278 SCLK | 5 |
| SX1278 MISO | 19 |
| SX1278 MOSI | 27 |
| SX1278 CS | 18 |
| SX1278 DIO0 | 26 |
| SX1278 RESET | 23 |
| SX1278 DIO1 | 33 |
| SX1278 DIO2 | 32 |
| Board LED | 25 |
| Battery ADC | 35 |

## LILYGO T3-S3 + SX1278

Optional build environment: `t3-s3-433`

The pin mapping is defined in `src/board_config.h` and selected by PlatformIO
build flags.

## BME280

The optional BME280 shares the I²C bus with the SSD1306 OLED and is detected at
`0x76` or `0x77`.

## Power measurement

`BATTERY_ADC_PIN` allows voltage-oriented battery monitoring on supported board
variants, but it is not a current/power monitor. Accurate mA/W telemetry needs
an external shunt monitor such as INA219/INA226.
