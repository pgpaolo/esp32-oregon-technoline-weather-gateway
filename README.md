# ESP32 Oregon Scientific + Technoline 433 MHz Weather Gateway

![ESP32](https://img.shields.io/badge/ESP32-Arduino-00979D)
![PlatformIO](https://img.shields.io/badge/PlatformIO-ready-orange)
![RF](https://img.shields.io/badge/RF-433.92%20MHz-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

A standalone **433.92 MHz weather-sensor gateway** for ESP32/LILYGO T3 boards with an SX1278 radio.
It receives **Oregon Scientific OSV2.1/OSV3** and **Technoline / La Crosse WS23xx** sensors simultaneously, exposes a responsive Web UI, publishes selected values to MQTT, supports configurable MQTT TLS, and can use a local BME280 sensor.

> Release candidate firmware line: **V6.4.0-rc1** (stable release: **V6.3.0**)

[Italiano / README_IT](README_IT.md)

## Highlights

- Dual RF reception on a single SX1278 at **433.92 MHz**
- Oregon Scientific OSV3 plus bounded V2.1 thermo/hygro, wind, rain and UV decoding (`EC40`, `1D20`, `1D30`, `3D00`, `2D10`, `EC70`)
- Technoline / La Crosse WS230x / WS-2310 compatible decoder
- Responsive embedded Web UI with:
  - Oregon and Technoline dashboards
  - compact wind compasses
  - data freshness indicators
  - dedicated Hardware tab
  - RF diagnostics and RAW frames
  - restart control
  - OLED ON/OFF power-save control
  - configurable hostname + mDNS (`hostname.local`)
  - JSON configuration backup / restore
- Deterministic gzip Web asset generated during the build to reduce application flash usage
- Local BME280 temperature / humidity / pressure support
- MQTT with per-field publishing selection
- MQTT TLS modes:
  - disabled
  - CA-verified TLS
  - insecure TLS for diagnostics only
- Runtime RF profile / gain selection
- Persistent settings through ESP32 Preferences/NVS
- Physical PRG/BOOT short press for OLED ON/OFF fallback
- Firmware/build/Git/reset metadata in the Hardware view
- No telemetry writes to flash during normal operation

## Supported hardware

### Primary target

- **LILYGO T3 / LoRa32 V1.6.1**
- ESP32
- SX1278 433 MHz
- SSD1306 128×64 OLED

### Optional target

- **LILYGO T3-S3 V1.2/V1.3** with SX1278 433 MHz

### Optional sensor

- BME280 on the board I²C bus (`0x76` / `0x77`)

See [docs/HARDWARE.md](docs/HARDWARE.md) for pinout and notes.

## Supported weather data

### Oregon Scientific OSV2.1 / OSV3

Depending on the sensor model:

- temperature
- relative humidity
- dew point
- heat index
- average wind speed
- current/gust wind field
- wind direction
- wind chill
- rainfall total / rate / rolling values
- UV index
- RF metadata and battery state when available

### Technoline / La Crosse WS23xx

- temperature
- humidity
- rain total
- wind speed
- gust
- wind direction
- sensor/model metadata
- RF RSSI and RAW frame diagnostics

## Web interface

The embedded UI is split into four main sections:

1. **Dashboard** — live Oregon, Technoline and BME280 values
2. **Hardware** — ESP32 CPU, heap, flash, OTA space, RSSI, uptime, firmware/build/reset metadata and OLED state
3. **Configuration** — hostname/network, MQTT/TLS and configuration backup/restore
4. **Diagnostics** — RF mode, gain/profile controls, acquisition state, RAW frames and burst diagnostics

The OLED can be placed in **power-save mode** from the Web UI or toggled with a short press of the configured PRG/BOOT button. While disabled, display refreshes are suspended; RF reception, Wi-Fi, MQTT and the Web UI continue to operate normally. The OLED preference is persisted in NVS. The device hostname is also persistent and, when mDNS is available on the client network, the UI can be reached as `http://<hostname>.local/`.

## Quick start

### 1. Clone

```bash
git clone https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway.git
cd esp32-oregon-technoline-weather-gateway
```

### 2. Create the private configuration

```bash
cp src/config_private.example.h src/config_private.h
```

Edit `src/config_private.h` with your Wi-Fi, network and MQTT defaults. `DEVICE_HOSTNAME`, `OLED_BUTTON_ENABLE` and `OLED_BUTTON_PIN` can also be overridden there when required.

> `src/config_private.h` is intentionally ignored by Git. Never commit credentials or private CA material.

### 3. Build with PlatformIO

Primary target:

```bash
pio run -e t3-v161-433
```

Upload:

```bash
pio run -e t3-v161-433 -t upload
```

Serial monitor:

```bash
pio device monitor -b 115200
```

Optional T3-S3 build:

```bash
pio run -e t3-s3-433
```

## Default RF profile

Recommended normal-operation settings:

| Setting | Value |
|---|---|
| RF mode | `DUAL` |
| Frequency | `433.92 MHz` |
| Bandwidth | `125 kHz` |
| Gain | `AGC` |
| RF profile | `STABILE` |
| Burst Extra | OFF |
| WGR Probe | OFF |

## MQTT

MQTT configuration can be changed from the Web UI and persisted in NVS.
The firmware can publish only the fields you select, avoiding unnecessary traffic.

Example base topic:

```text
weatherstation/
├── status
├── ip
├── state
├── oregon/...
├── technoline/...
├── local/bme280/...
└── system/...
```

Full topic reference: [docs/MQTT.md](docs/MQTT.md).

## HTTP API

The Web UI uses a small REST-style API including:

- `GET /api/state`
- `GET /api/raw`
- `GET /api/bursts`
- `POST /api/rfmode`
- `POST /api/rfgain`
- `POST /api/rfprofile`
- `GET/POST /api/mqtt`
- `GET/POST /api/network`
- `GET /api/config/export`
- `POST /api/config/import`
- `POST /api/display`
- `POST /api/restart`

Details: [docs/API.md](docs/API.md).

Configuration backup reference: [docs/CONFIG_BACKUP.md](docs/CONFIG_BACKUP.md).

## Power monitoring

The supported LILYGO board exposes a **battery ADC pin**, which can be used for voltage measurement, but the current firmware does **not** provide true current/power measurement in mA/W.
For real power telemetry, an external current monitor such as an INA219/INA226 can be added on I²C in a future extension.

The current power-saving feature is OLED shutdown/power-save from the Web UI or the configured physical button.

## Security notes

- Do not publish `src/config_private.h`.
- Use CA-verified MQTT TLS when the broker is outside a trusted LAN.
- The `TLS insecure` mode is intended for diagnostics only.
- The embedded Web UI currently assumes a trusted local network; do not expose it directly to the public Internet without an authenticated reverse proxy/VPN/firewall policy.

See [SECURITY.md](SECURITY.md).

## Project structure

```text
.
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/
├── docs/
├── src/
│   ├── oregon_receiver.*
│   ├── lacrosse_ws23xx.*
│   ├── weather_parser.*
│   ├── station_state.*
│   ├── mqtt_publisher.*
│   ├── network_manager.*
│   ├── web_manager.*
│   ├── display_manager.*
│   ├── firmware_info.*
│   └── barometer_manager.*
├── platformio.ini
├── CHANGELOG.md
├── CONTRIBUTING.md
├── NOTICE
└── LICENSE
```

## Decoder provenance and acknowledgements

The Technoline / La Crosse WS23xx implementation was developed using published protocol/timing knowledge and code-derived logic from:

- **rtl_433**, especially the La Crosse WS-2310 / WS-3600 decoder
- **PracticalArduino WeatherStationReceiver**, for the WS-2300-25S / WS-2355 pulse/state-machine approach

Both upstream projects are GPL-licensed. Attribution and licensing notes are included in [NOTICE](NOTICE).

## License

This repository is distributed under **GNU GPL v3 or later (GPL-3.0-or-later)**. See [LICENSE](LICENSE).

### OLED button board note

Web UI OLED control is available on both boards. The physical toggle is enabled by default only on T3-S3, where LILYGO declares `BUTTON_PIN = 0`. On T3 V1.6.1 it is disabled by default and can be explicitly enabled in `config_private.h` after checking the actual hardware revision.
