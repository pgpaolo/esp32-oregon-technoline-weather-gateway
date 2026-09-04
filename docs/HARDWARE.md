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

The SX1278 is the single 433.92 MHz receiver for Oregon and Technoline.

## LILYGO T3-S3 + SX1278

Optional PlatformIO environment:

```text
t3-s3-433
```

The board-specific mapping is defined in `src/board_config.h` and selected by PlatformIO build flags. AS3935 is not assumed to be wired on the S3 target unless explicitly configured.

## Shared I2C bus

On the T3 V1.6.1, OLED, optional BME280 and optional AS3935 share one I2C controller.

Typical addresses:

| Device | Address |
|---|---|
| SSD1306 OLED | `0x3C` |
| BME280 | `0x76` or `0x77` |
| AS3935 | configured address, project default `0x03` |

The reviewed develop line intentionally uses:

```text
I2C runtime speed = 100 kHz
Wire timeout      = 80 ms
```

Physical testing showed that long SDA/SCL wiring can add enough bus capacitance to make the BME280 stop ACKing even though both lines measure HIGH at idle. The final installation should therefore use short I2C wiring and avoid unnecessary cable capacitance.

The manual **CONFIGURAZIONE > I2C / HW** scanner performs a 100 kHz runtime scan followed by a 400 kHz margin/stress scan, then restores 100 kHz. See [I2C_HARDWARE_DIAGNOSTICS.md](I2C_HARDWARE_DIAGNOSTICS.md).

## BME280

The optional BME280 is detected at `0x76` or `0x77`; `0x77` is tried first on the current development line while `0x76` remains supported.

It provides:

- local temperature;
- local humidity;
- station pressure;
- sea-level pressure based on configured altitude;
- pressure trend / forecast inputs.

Discovery and recovery are non-blocking. See [BAROMETER_BME280.md](BAROMETER_BME280.md).

## AS3935 lightning detector

T3 V1.6.1 defaults:

- I2C address `0x03`;
- IRQ GPIO34;
- shared 100 kHz I2C bus;
- configurable Indoor/Outdoor AFE and filtering;
- configurable fixed tuning capacitor or auto-tuning;
- IRQ handler kept minimal, with I2C work outside the ISR;
- power-down during controller deep sleep.

The valid configured AS3935 I2C address range is `0x00..0x03`. Normal boot uses the configured address deterministically rather than performing a general address scan.

The Web UI reports detection, IRQ/calibration state, resonance, latest strike, distance, energy and counters.

## microSD

The onboard microSD uses a dedicated HSPI instance and does not share the SX1278 or I2C pins. The project uses Greiman SdFat 2.3.1 with 4 MHz initialization and one 400 kHz fallback after complete SPI bus cleanup.

Mount and explicit FAT format have been confirmed on physical T3 V1.6.1 hardware. Formatting is never automatic.

## OLED

Primary display: SSD1306 128x64 at `0x3C`.

Display power, page selection, field selection, contrast and page interval are configurable from the Web UI and persisted in NVS. The optional **Sensori RF / RSSI / batterie** page rotates compact transmitter rows when required.

## OLED physical button

An optional active-low PRG/BOOT short-press can toggle OLED power-save:

- T3-S3: enabled by default on board-declared BOOT/User GPIO0;
- T3 V1.6.1: disabled by default because a guaranteed runtime user button is not assumed on every revision.

Override with `OLED_BUTTON_ENABLE` / `OLED_BUTTON_PIN` only after checking the actual board revision.

## Soft power-off / wake

The Web `SPEGNI` command performs controlled shutdown and enters ESP32 deep sleep. It is not an electrical power cut.

Before sleep the firmware parks/shuts down MQTT, display, local sensors, radio, storage and Wi-Fi as applicable.

Default wake policy:

- T3 V1.6.1: RESET/EN;
- T3-S3: RESET/EN plus BOOT/User GPIO0 when enabled.

A real load switch/latch is required for near-zero electrical consumption.

## MCU internal temperature

The Hardware monitor and **I2C / HW** page expose the ESP32 internal temperature when `temperatureRead()` returns a plausible value.

This is a **die/internal hardware temperature**, useful as an indicative hardware-health value. It is not a calibrated ambient-air temperature. Unsupported/invalid readings are reported as `N/D` / JSON `null`.

## Board battery ADC

`BATTERY_ADC_PIN` can be used for board-supply/battery-voltage monitoring on supported variants, but it is not a current/power monitor. Accurate mA/W telemetry requires an external device such as INA219/INA226.

Do not confuse the board ADC with Oregon remote-sensor battery flags, which are decoded from RF only when the protocol provides them.

## RF signal status

| RSSI | Display class |
|---|---|
| `>= -100 dBm` | good / green / `G` |
| `-115 .. -101 dBm` | warning / yellow / `Y` |
| `< -115 dBm` | weak / red / `R` |
| unavailable | grey / `-` |

Technoline WS23xx provides usable RF RSSI but no battery-status field, so battery is shown as `N/D` / `B-`.

## Build reference

Both environments use `min_spiffs.csv`: NVS and two OTA application slots remain, while SPIFFS is not used. Each app slot is `0x1E0000` bytes (1,966,080 bytes).

Exact RAM/flash/binary sizes change whenever the embedded Git commit ID changes. Use the latest successful GitHub Actions workflow rather than stale static size numbers.
