# Hardware

## LILYGO T3 / LoRa32 V1.6.1 + SX1278

Primary target and default PlatformIO environment:

```text
t3-v161-433
```

| Function | GPIO / address |
|---|---:|
| I2C SDA | 21 |
| I2C SCL | 22 |
| OLED SSD1306 | `0x3C` |
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
| AS3935 default I2C | `0x03` |
| AS3935 default IRQ | 34 |
| microSD MOSI | 15 |
| microSD MISO | 2 |
| microSD SCLK | 14 |
| microSD CS | 13 |

The SX1278 remains the single 433.92 MHz receiver for Oregon and Technoline.

## LILYGO T3-S3 + SX1278

Optional PlatformIO environment:

```text
t3-s3-433
```

The board-specific mapping is defined in `src/board_config.h` and selected by PlatformIO build flags.

AS3935 is not assumed to be wired on the S3 target unless explicitly configured for that hardware.

## I2C bus

On the classic T3 V1.6.1 the OLED, optional BME280 and optional AS3935 share the I2C bus.

Typical addresses:

| Device | Address |
|---|---|
| SSD1306 OLED | `0x3C` |
| BME280 | `0x76` or `0x77` |
| AS3935 | default `0x03` |

Check for address conflicts when adding other I2C hardware.

## AS3935 lightning detector

The consolidated `codex/sdfat-write-status` branch includes the AS3935 integration inherited from the intermediate development branch.

## microSD

The onboard microSD uses a dedicated HSPI instance and does not share the SX1278 pin set. The current branch uses Greiman SdFat 2.3.1 with 4 MHz initialization and one 400 kHz fallback after complete bus cleanup.

Mount and explicit FAT format were confirmed on the physical T3 V1.6.1 setup. The formatter is allowed to run when the card transport is initialized but FAT is missing/invalid; it is not run against a card that failed transport initialization.

Classic T3 V1.6.1 defaults:

- I2C address `0x03`;
- IRQ GPIO34;
- shared I2C bus;
- configurable Indoor/Outdoor AFE and filtering;
- configurable fixed tuning capacitor or auto-tuning;
- IRQ handler kept minimal, with I2C work performed outside the ISR;
- power-down during controller deep sleep.

The Web UI reports detection, IRQ/calibration state, resonance, last strike, distance, energy and counters.

## OLED

Primary display: SSD1306 128x64 at `0x3C`.

Display power, page selection, field selection, contrast and page interval are configurable from the Web UI and persisted in NVS.

The consolidated branch includes the optional **Sensori RF / RSSI / batterie** page. It is designed for the small 128x64 display and rotates compact transmitter rows rather than trying to render every sensor on one screen.

## OLED physical button

The development line supports an optional active-low PRG/BOOT short-press for OLED power-save toggle.

- T3-S3: enabled by default on the board-declared BOOT/User GPIO0.
- T3 V1.6.1: disabled by default because the project does not assume a guaranteed runtime user button on every revision.

The feature can be overridden in `config_private.h` with `OLED_BUTTON_ENABLE` and `OLED_BUTTON_PIN` after verifying the actual board revision.

## Soft power-off / wake

The Web `SPEGNI` command performs controlled shutdown and enters ESP32 deep sleep. It is not an electrical power cut.

Before sleep the firmware shuts down/parks the relevant services including MQTT, display, local sensors, radio and Wi-Fi.

Default wake policy:

- T3 V1.6.1: RESET/EN;
- T3-S3: RESET/EN plus BOOT/User GPIO0 when enabled.

For near-zero current a real external load switch/latch is still required.

## BME280

The optional BME280 is detected at `0x76` or `0x77` and shares the I2C bus with OLED/AS3935.

It can provide local temperature, humidity, station pressure, altimeter pressure and pressure trend data.

## Board battery ADC

`BATTERY_ADC_PIN` can be used for board-supply/battery-voltage oriented monitoring on supported variants, but it is **not** a current/power monitor.

Accurate mA/W telemetry requires an external current monitor such as INA219/INA226.

Do not confuse the board battery ADC with Oregon remote-sensor battery state. Oregon battery flags are decoded from RF only when the corresponding sensor protocol provides them.

## RF signal status

The Web/OLED presentation uses these common RSSI classes for supported received sensors:

| RSSI | Display class |
|---|---|
| `>= -100 dBm` | good / green / `G` |
| `-115 .. -101 dBm` | warning / yellow / `Y` |
| `< -115 dBm` | weak / red / `R` |
| unavailable | grey / `-` |

Technoline WS23xx provides usable RF RSSI but does not provide a battery-status field, therefore battery is shown as `N/D` / `B-`.

## Build reference

The current SdFat/write-status code passed local PlatformIO builds on both targets after hardware mount/format confirmation.

T3 V1.6.1:

- RAM: 100,592 / 327,680 B;
- application ELF: 1,276,881 / 1,966,080 B;
- real firmware.bin: 1,283,584 B;
- app-partition margin: 689,199 B.

T3-S3:

- RAM: 99,552 / 327,680 B;
- application ELF: 1,220,809 / 1,966,080 B;
- real firmware.bin: 1,221,232 B.

Both environments use `min_spiffs.csv`. NVS and two OTA application slots remain; SPIFFS is not used by this project.
