# ESP32 Oregon Scientific + Technoline 433 MHz Weather Gateway

![ESP32](https://img.shields.io/badge/ESP32-Arduino-00979D)
![PlatformIO](https://img.shields.io/badge/PlatformIO-ready-orange)
![RF](https://img.shields.io/badge/RF-433.92%20MHz-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

Standalone **433.92 MHz weather-sensor gateway** for ESP32/LILYGO T3 boards with SX1278. It receives **Oregon Scientific OSV2.1/OSV3** and **Technoline / La Crosse WS23xx**, exposes a responsive authenticated Web UI, publishes selected data through MQTT/TLS, and supports optional local BME280 and AS3935 sensors.

Project author and maintainer: **Gianpaolo P.** (`pgpaolo`) · Copyright © 2026 Gianpaolo P.

[Italiano / README_IT](README_IT.md)

## Current release candidate

```text
main                 stable / production + selective BME280/I2C reliability backport (PR #23)
release/6.4.0-rc3    frozen historical RC validation line
release/6.4.0-rc4    current complete release candidate (firmware 6.4.0-rc4)
develop               next-development line (6.4.0-dev2)
```

`release/6.4.0-rc4` has been fully refreshed from the reviewed `develop` solution at commit `68c1adc7df3e4e7a56b24b13bc6bdfc80bd247f3`. RC3 remains frozen. `main` now contains the selective BME280/I2C reliability backport merged through PR #23, while the complete RC4 feature set remains isolated in this release branch until an explicit promotion decision.

## Main features

- One SX1278 at **433.92 MHz** receiving Oregon + Technoline.
- Oregon OSV3 plus bounded Oregon V2.1 support.
- Dedicated UVR128 / EC70 recovery for clipped preambles / uncertain phase captures.
- Oregon thermo/hygro CH1-CH3 with configurable primary channel and auto-discovery.
- Multiple independent UV transmitters, including UVN800 (`D874`) and UVR128 (`EC70`).
- Technoline WS23xx temperature, humidity, rain, wind and gust support.
- Uniform RSSI and battery presentation where the source protocol provides battery information.
- MQTT with selectable field groups and optional CA-verified TLS.
- **COMPATIBLE MB** 192-field output with exclusive Oregon/Technoline source selection.
- Configurable OLED pages and fields.
- Optional local **BME280** barometer / temperature / humidity.
- Optional local **AS3935** lightning detector with Web, MQTT and OLED integration.
- Hardware monitor for CPU, heap, flash, uptime, reset/build information and ESP32 internal MCU temperature when available.
- Dedicated **CONFIGURAZIONE > I2C / HW** diagnostics page with manual bus scan and BME280 chip-ID check.
- SdFat microSD logger with mount retry, FAT formatting tools and live status.
- Web Wi-Fi provisioning, asynchronous SSID scan, credential trial/rollback and recovery AP.
- Web Basic Authentication, configuration backup/restore and authenticated OTA.
- Restart and controlled deep-sleep power-off.
- Low-profile Web attribution showing copyright, GPL identifier and the **installed firmware version** without extra polling.

## Supported boards

### Primary target

- **LILYGO T3 / LoRa32 V1.6.1**
- ESP32 + SX1278 433 MHz
- SSD1306 128x64 OLED
- PlatformIO environment: `t3-v161-433`

### Optional target

- **LILYGO T3-S3 V1.2/V1.3** + SX1278 433 MHz
- PlatformIO environment: `t3-s3-433`

See [docs/HARDWARE.md](docs/HARDWARE.md).

## Local I2C sensors

### BME280

The BME280 is detected at `0x76` or `0x77`. On the T3 V1.6.1:

```text
SDA = GPIO21
SCL = GPIO22
```

OLED, BME280 and AS3935 share the same I2C controller. Physical validation showed that **excessive cable length/capacitance** can cause missing BME280 ACKs even while SDA/SCL are both HIGH at idle. The normal shared bus is therefore kept at **100 kHz** with an **80 ms** Wire timeout.

BME280 discovery retries non-blockingly after approximately 5 s, 15 s, 60 s and then every 5 minutes. Six consecutive invalid pressure reads restart rediscovery.

Full barometer reference: [docs/BAROMETER_BME280.md](docs/BAROMETER_BME280.md).

### I2C / hardware diagnostics

The manual scanner is separated from BAROMETRO and is available under:

```text
CONFIGURAZIONE > I2C / HW
```

It scans the standard 7-bit bus first at the real **100 kHz runtime speed**, reads Bosch BME280 chip ID `0xD0` at `0x76/0x77`, then performs a **400 kHz stress/margin scan** and restores 100 kHz before returning. No periodic full-bus scan is added.

The same page shows local-sensor state and the ESP32 internal MCU/die temperature when the Arduino core provides a plausible value. This temperature is **indicative hardware temperature, not ambient temperature**.

Reference: [docs/I2C_HARDWARE_DIAGNOSTICS.md](docs/I2C_HARDWARE_DIAGNOSTICS.md).

### AS3935

The AS3935 uses its configured I2C address; the T3 V1.6.1 project default is `0x03`, IRQ GPIO34. The Web UI exposes sensor/IRQ/calibration/resonance state, latest lightning distance/energy, counters and configuration.

## Barometer and forecast

The BME280 provides station pressure, sea-level pressure, local temperature/humidity and pressure trend. Station altitude is configurable in NVS; the project default is 584 m. Web display units can be hPa, mbar, inHg, mmHg or kPa while internal/MQTT/COMPATIBLE MB values remain canonical hPa.

The title area contains a larger WMR200-style forecast tile. The available Oregon protocol documents forecast categories, not the proprietary Oregon forecasting formula, so the gateway implements a category-compatible presentation based on sea-level pressure, 3-hour trend and outdoor temperature where required.

## Web interface

The embedded Web UI is divided into:

1. **Dashboard** — Oregon, Technoline and local sensors.
2. **Hardware** — CPU/SoC, heap, flash, uptime, MCU temperature and network/runtime information.
3. **Configuration** — network/Wi-Fi, Oregon, MQTT/TLS, display, BAROMETRO, I2C/HW, AS3935, microSD/archive, backup/restore and system/security/OTA controls.
4. **Diagnostics** — RF mode/gain/profile, session quality, RAW frames and burst diagnostics.

BME280 and AS3935 detailed Dashboard panels are collapsed by default and expand on title click.

The title area also contains a deliberately small attribution line:

```text
© 2026 Gianpaolo P. · firmware <installed version> · GPL-3.0-or-later
```

The version is taken from the existing `/api/state` response, so the attribution introduces **no additional HTTP polling**.

## MQTT

Legacy topics are retained for compatibility. Oregon transmitters can also publish under an independent namespace keyed by sensor code, channel and rolling ID:

```text
<base>/oregon/sensor/<CODE>/ch<CHANNEL>/id<ROLLING>/...
```

The existing 32-bit persistent field mask selects Oregon, Technoline, BME280, AS3935 and gateway/system groups.

Reference: [docs/MQTT.md](docs/MQTT.md).

## COMPATIBLE MB

COMPATIBLE MB emits exactly 192 whitespace-separated fields to a configurable `mb.php`-style receiver. Missing values are `--`. Oregon and Technoline selection is exclusive: the publisher never fills missing selected-station values from the other station. BME280 local pressure/indoor data can be included independently.

HTTP/HTTPS publishing runs in a separate FreeRTOS worker so the RF loop does not wait for the remote endpoint.

## microSD

The onboard microSD uses SdFat on the board HSPI wiring. Valid frames and configured local-sensor snapshots are queued in RAM and written outside the RF-critical path. A failed mount retries after approximately 5 s, 15 s, 60 s and then every 5 minutes. Formatting is always explicit/manual.

Reference: [docs/SD_DATALOGGER.md](docs/SD_DATALOGGER.md).

## Web provisioning, authentication and OTA

Wi-Fi SSID/password can be configured from the authenticated Web UI and stored in NVS. New credentials are treated as a trial and can roll back after failed association. A recovery AP is available after prolonged STA loss.

Web Basic Authentication is enabled by default. Factory first-access credentials are:

```text
user: admin
password: admin
```

Change them immediately from **CONFIGURAZIONE > SISTEMA**. Basic Authentication on plain HTTP does not provide transport encryption; keep the device on a trusted LAN/VPN or behind a trusted HTTPS terminator.

Authenticated OTA accepts the correct PlatformIO/GitHub `firmware.bin`, checks ESP image header/space/basic board-family mismatch and only reboots after a valid completed update.

Reference: [docs/WEB_PROVISIONING_OTA_AUTH.md](docs/WEB_PROVISIONING_OTA_AUTH.md).

## Quick start from RC4

```bash
git clone https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway.git
cd esp32-oregon-technoline-weather-gateway
git checkout release/6.4.0-rc4
cp src/config_private.example.h src/config_private.h
pio run -e t3-v161-433
pio run -e t3-v161-433 -t upload
pio device monitor -b 115200
```

`src/config_private.h` is ignored by Git. Never commit Wi-Fi/MQTT credentials or private CA material.

## Recommended RF baseline

| Setting | Value |
|---|---|
| RF mode | `DUAL` |
| Frequency | `433.92 MHz` |
| Gain | `AGC` |
| RF profile | `STABILE` |
| Burst Extra | OFF for normal operation |
| WGR Probe | OFF for normal operation |

## CI / release validation

The build matrix checks:

- PCR800 rain-rate regression vector;
- Oregon V2.1 host vectors;
- COMPATIBLE MB mapping;
- `t3-v161-433` build;
- `t3-s3-433` build;
- a second same-workspace T3 V1.6.1 build to detect non-idempotent pre-scripts;
- generated I2C/HW integration guard;
- project attribution + installed-version UI guard;
- real `firmware.bin` size against the `0x1E0000` OTA application slot.

The exact source promoted from `develop` passed Validate #192 and PlatformIO Build #268. The RC4 branch must also remain green after its release-identity and attribution/documentation commits before any merge to `main`.

Because the firmware embeds its Git commit ID, use the latest successful workflow for exact current binary sizes.

## API and backup

HTTP API: [docs/API.md](docs/API.md)  
Configuration backup: [docs/CONFIG_BACKUP.md](docs/CONFIG_BACKUP.md)  
RC4 release notes: [docs/RELEASE_6.4.0_RC4.md](docs/RELEASE_6.4.0_RC4.md)

## Security

- Never publish `src/config_private.h`.
- Change `admin / admin` after first access.
- Do not expose the ESP32 HTTP service directly to the Internet.
- Prefer CA-verified MQTT TLS outside a trusted LAN.
- Treat TLS-insecure mode as diagnostic only.

See [SECURITY.md](SECURITY.md).

## Decoder provenance

Technoline / La Crosse WS23xx implementation uses published protocol/timing knowledge and GPL-compatible code-derived logic from **rtl_433** and **PracticalArduino WeatherStationReceiver**. See [NOTICE](NOTICE).

## Authorship and citation

Project author and maintainer: **Gianpaolo P.** (`pgpaolo`)  
Copyright © 2026 Gianpaolo P.

- Author record: [AUTHORS.md](AUTHORS.md)
- Citation metadata: [CITATION.cff](CITATION.cff)
- Third-party acknowledgements: [NOTICE](NOTICE)

## License

GNU GPL v3 or later (`GPL-3.0-or-later`). See [LICENSE](LICENSE). The GPL license text itself is kept unmodified; project attribution and third-party acknowledgements are maintained separately in `AUTHORS.md`, `CITATION.cff` and `NOTICE`.
