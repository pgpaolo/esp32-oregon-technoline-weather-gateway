# ESP32 Oregon Scientific + Technoline 433 MHz Weather Gateway

![ESP32](https://img.shields.io/badge/ESP32-Arduino-00979D)
![PlatformIO](https://img.shields.io/badge/PlatformIO-ready-orange)
![RF](https://img.shields.io/badge/RF-433.92%20MHz-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

A standalone **433.92 MHz weather-sensor gateway** for ESP32/LILYGO T3 boards with an SX1278 radio.
It receives **Oregon Scientific OSV2.1/OSV3** and **Technoline / La Crosse WS23xx** sensors, exposes a responsive Web UI, publishes selected values to MQTT with optional TLS, and can use local BME280 and AS3935 sensors.

Current consolidated development branch:

```text
feature/uvr128-v21-recovery
```

The firmware macro on this line is **6.4.0-rc2**. The branch contains additional hardware-validation work not yet merged into `main`.

[Italiano / README_IT](README_IT.md)

## Current branch highlights

- Single SX1278 receiving Oregon + Technoline at **433.92 MHz**.
- Oregon OSV3 plus bounded Oregon V2.1 support.
- Dedicated hardware-validated **UVR128 / EC70 recovery** for clipped preamble / uncertain phase captures.
- Oregon thermo/hygro **CH1-CH3** with configurable primary channel and auto-discovery.
- Independent multi-transmitter UV presentation, including UVN800 (`D874`) and UVR128 (`EC70`).
- Uniform RSSI state on Oregon and Technoline:
  - green >= -100 dBm;
  - yellow -115..-101 dBm;
  - red < -115 dBm;
  - grey when unavailable.
- Uniform battery state where the protocol provides it: `BAT OK`, `BAT LOW`, `BAT N/D`.
- Technoline WS23xx battery is intentionally `N/D`; the protocol does not transmit it.
- Per-transmitter Oregon MQTT namespaces keyed by sensor code + channel + rolling code.
- Selectable MQTT groups for Oregon thermo/hygro, wind, rain, UV, Technoline, BME280, AS3935 and gateway/system data.
- MQTT TLS: OFF, CA-verified, or insecure diagnostic mode.
- Configurable OLED pages and fields, including a compact **SENSORI RF / RSSI / BATTERIE** page.
- Optional local AS3935 lightning detector with Web, MQTT and OLED integration.
- Optional local BME280.
- Configurable hostname + mDNS, JSON backup/restore, restart and soft power-off/deep sleep.
- Deterministic gzip Web asset generated during PlatformIO build.

Full consolidated branch reference: [docs/UVR128_RECOVERY.md](docs/UVR128_RECOVERY.md).

## Supported hardware

### Primary target

- **LILYGO T3 / LoRa32 V1.6.1**
- ESP32
- SX1278 433 MHz
- SSD1306 128x64 OLED

PlatformIO environment:

```text
t3-v161-433
```

### Optional target

- **LILYGO T3-S3 V1.2/V1.3** with SX1278 433 MHz

PlatformIO environment:

```text
t3-s3-433
```

### Optional local sensors

- BME280 on I2C (`0x76` / `0x77`).
- AS3935 lightning detector. Classic T3 V1.6.1 defaults: I2C `0x03`, IRQ GPIO34.

See [docs/HARDWARE.md](docs/HARDWARE.md).

## Supported weather data

### Oregon Scientific OSV2.1 / OSV3

Depending on model:

- temperature and humidity;
- dew point and heat index;
- average wind, current/gust field, wind direction and wind chill;
- rain total, rate, local rolling values and frame increment;
- UV index;
- channel / rolling code / model / protocol metadata;
- RF RSSI and battery state when available.

V2.1 details and boundaries: [docs/OREGON_V21.md](docs/OREGON_V21.md).

### Technoline / La Crosse WS23xx

- temperature;
- humidity;
- rain total;
- wind speed;
- gust when announced by the protocol;
- wind direction;
- model/ID metadata;
- RF RSSI and RAW diagnostics.

## Web interface

The embedded UI is divided into:

1. **Dashboard** - Oregon, Technoline, local sensors and live status.
2. **Hardware** - ESP32 CPU/heap/flash/uptime/reset/build information.
3. **Configuration** - network, MQTT/TLS, Oregon channels, display, AS3935 and backup/restore.
4. **Diagnostics** - RF mode/gain/profile, session quality, RAW frames and burst diagnostics.

Oregon sensor cards use the same RSSI and battery language across thermo/hygro, wind, rain and UV. Technoline uses the same RSSI thresholds and reports battery as unavailable.

## MQTT

MQTT configuration is persistent in NVS and selectable by function group.

Legacy topics remain for compatibility. In addition, every accepted Oregon transmitter can publish in its own retained namespace:

```text
<base>/oregon/sensor/<CODE>/ch<CHANNEL>/id<ROLLING>/...
```

Examples:

```text
weatherstation/oregon/sensor/F824/ch1/id165/temperature
weatherstation/oregon/sensor/1D20/ch3/id114/humidity
weatherstation/oregon/sensor/D874/ch1/id245/uv
weatherstation/oregon/sensor/EC70/ch1/id158/uv
weatherstation/oregon/sensor/1984/ch0/id170/wind_average
weatherstation/oregon/sensor/2914/ch0/id189/rain_total
```

The existing 32-bit field mask is preserved. Selection is by station/sensor family and function; individual rolling IDs are separated by topic namespace rather than by new persistent enable bits.

Full reference: [docs/MQTT.md](docs/MQTT.md).

## OLED

Display pages and fields are configurable from the Web UI.

The consolidated branch includes a selectable **SENSORI RF / RSSI / BATTERIE** page. It stores no history, tracks up to ten recent Oregon transmitters and displays five compact rows at a time, rotating when necessary.

Example:

```text
T1 F824 -116R B+
U1 EC70 -122R B+
```

`G/Y/R` is the RSSI class; `B+` = OK, `B!` = low, `B-` = unavailable.

Technoline uses the same convention, for example `ID79 -113dBm Y B-`.

## AS3935 lightning detector

AS3935 is an optional local I2C/IRQ sensor with:

- Web state and guided configuration;
- IRQ/calibration/resonance diagnostics;
- distance/energy for the latest lightning event;
- selectable MQTT state/event/last-strike/diagnostic outputs;
- selectable OLED page;
- configuration included in backup/restore.

## Quick start

```bash
git clone https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway.git
cd esp32-oregon-technoline-weather-gateway
git checkout feature/uvr128-v21-recovery
cp src/config_private.example.h src/config_private.h
pio run -e t3-v161-433
pio run -e t3-v161-433 -t upload
pio device monitor -b 115200
```

`src/config_private.h` is ignored by Git. Never commit Wi-Fi/MQTT credentials or private CA material.

## Recommended RF profile

| Setting | Value |
|---|---|
| RF mode | `DUAL` |
| Frequency | `433.92 MHz` |
| Gain | `AGC` |
| RF profile | `STABILE` |
| Burst Extra | OFF for normal operation |
| WGR Probe | OFF for normal operation |

UVR128 recovery uses the minimum raw interval collection needed by the dedicated EC70 fallback even when optional Burst Extra diagnostics are disabled.

## Build / CI status

Functional code was validated by **PlatformIO Build #92** before the final documentation cleanup commits:

- Validate: PASS;
- AS3935 Integration Guard: PASS;
- `t3-v161-433`: PASS;
- `t3-s3-433`: PASS;
- Oregon V2.1 host vectors: PASS.

T3 V1.6.1 Build #92:

- RAM: `92,560 / 327,680 B` = 28.2%;
- application ELF: `1,226,765 / 1,310,720 B` = 93.6%;
- real `firmware.bin`: `1,233,472 B`;
- real application-partition margin: `77,248 B`.

Artifact ID: `9498796327`.

Because the firmware embeds the Git commit identifier, a documentation-only commit changes the generated binary identifier even when application logic is unchanged.

## HTTP API

The Web UI uses REST-style endpoints for live state, raw/burst diagnostics, RF settings, MQTT/TLS, network, Oregon channels, display, AS3935, backup/restore, restart and soft power-off.

Reference: [docs/API.md](docs/API.md).

## Backup / restore

The JSON configuration backup includes persistent network, MQTT/TLS, MQTT field mask, Oregon channel configuration, display settings, AS3935 and persistent RF settings. Wi-Fi credentials are never exported; the MQTT password is omitted unless explicitly requested.

Reference: [docs/CONFIG_BACKUP.md](docs/CONFIG_BACKUP.md).

## Security notes

- Never publish `src/config_private.h`.
- Prefer CA-verified MQTT TLS outside a trusted LAN.
- `TLS insecure` is diagnostic only.
- The embedded Web UI assumes a trusted local network; do not expose it directly to the Internet without VPN/authenticated reverse proxy/firewall controls.

See [SECURITY.md](SECURITY.md).

## Decoder provenance and acknowledgements

Technoline / La Crosse WS23xx implementation uses published protocol/timing knowledge and GPL-compatible code-derived logic from:

- **rtl_433**;
- **PracticalArduino WeatherStationReceiver**.

Attribution and licensing notes are in [NOTICE](NOTICE).

## License

GNU GPL v3 or later (`GPL-3.0-or-later`). See [LICENSE](LICENSE).

## Active development policy

The intended simplified branch layout after repository cleanup is:

- `main` - integrated/stable line;
- `feature/uvr128-v21-recovery` - current hardware-validation line.

Historical pull requests remain available as development history after intermediate branches are removed.
