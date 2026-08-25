# ESP32 Oregon Scientific + Technoline 433 MHz Weather Gateway

![ESP32](https://img.shields.io/badge/ESP32-Arduino-00979D)
![PlatformIO](https://img.shields.io/badge/PlatformIO-ready-orange)
![RF](https://img.shields.io/badge/RF-433.92%20MHz-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

A standalone **433.92 MHz weather-sensor gateway** for ESP32/LILYGO T3 boards with an SX1278 radio.
It receives **Oregon Scientific OSV2.1/OSV3** and **Technoline / La Crosse WS23xx** sensors, exposes a responsive Web UI, publishes selected values to MQTT with optional TLS, and can use local BME280 and AS3935 sensors.

Current provisioning/security development branch:

```text
codex/web-provisioning-ota-auth
```

The firmware macro on this line is **6.4.0-rc2**. This branch is based on the hardware-validated SdFat line and adds Web provisioning/security/OTA without changing the RF decoder architecture.

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
- Hardware-validated microSD datalogger using SdFat, FAT reformat support and a live `SD ON` / `SD SCRIVE` header badge.
- Automatic microSD mount retry after boot or temporary mount failure: 5 s, 15 s, 60 s, then every 5 minutes. RF acquisition remains independent.
- Wi-Fi SSID/password configurable from the Web UI and persisted in NVS. New credentials are tried after reboot and automatically roll back if they do not associate.
- Recovery AP after prolonged STA loss; it is automatically shut down when the primary Wi-Fi connection returns.
- Web Basic Authentication enabled by default. On the first boot a random administrator password is generated, stored in NVS, printed to Serial and shown on OLED for 60 seconds when the display is enabled.
- Authenticated Web OTA installation of the PlatformIO/GitHub `firmware.bin`, with ESP image-header, OTA-space and obvious board-family checks. microSD is closed before flashing and remounted after a failed upload.
- Configuration reorganized around `RETE / WI-FI`, sensors, `MQTT / TLS`, display, `ARCHIVIO` and `SISTEMA`.
- Deterministic gzip Web asset generated during PlatformIO build.

Full provisioning/security reference: [docs/WEB_PROVISIONING_OTA_AUTH.md](docs/WEB_PROVISIONING_OTA_AUTH.md).
RF recovery reference: [docs/UVR128_RECOVERY.md](docs/UVR128_RECOVERY.md).

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
3. **Configuration** - `RETE / WI-FI`, sensors, MQTT/TLS, display, archive/microSD, AS3935, backup/restore and `SISTEMA` security/firmware controls.
4. **Diagnostics** - RF mode/gain/profile, session quality, RAW frames and burst diagnostics.

When Web authentication is enabled, Dashboard and API endpoints require the administrator credentials. OTA is deliberately disabled if authentication is turned off.

Oregon sensor cards use the same RSSI and battery language across thermo/hygro, wind, rain and UV. Technoline uses the same RSSI thresholds and reports battery as unavailable.

Multiple UVN800 (`D874`) transmitters are kept independent by sensor code, channel and rolling ID. The Dashboard prints the rolling ID on every UV card, including when two units use the same channel. The shared live registry holds up to ten Oregon transmitters across all sensor families.

## Wi-Fi provisioning and recovery

The firmware defaults in `src/config_private.h` remain the initial/fallback values. The Web UI can subsequently store a new SSID and password in NVS without rebuilding the firmware.

A changed Wi-Fi pair is saved as a trial configuration. After reboot the gateway attempts the new network for 45 seconds. If it cannot connect and a previous valid pair exists, the old credentials are restored automatically. If the STA remains unavailable for one minute, a recovery AP is started so the Web configuration remains locally reachable; the AP is shut down automatically as soon as the primary STA reconnects.

The primary Wi-Fi password is never returned by the HTTP API and is never exported by configuration backup.

## Web authentication and OTA

Basic Authentication is enabled by default. On a device without an existing Web password, the firmware generates a random 14-character administrator password and stores it in NVS. It is printed to Serial and, when the OLED is on, displayed for 60 seconds during first boot. Change it from **Configuration > SISTEMA**.

After ten failed authentication attempts, the Web layer applies a 30-second temporary lockout.

The OTA form accepts a `firmware.bin` produced by the correct PlatformIO environment or downloaded from the GitHub Actions artifact. Before writing, the firmware checks that authentication is enabled and successful, that the file has an ESP application image header, that the OTA slot has enough space and that the filename does not obviously refer to the other T3 board family. The microSD logger is closed before flashing; on failure it is remounted when enabled. Reboot occurs only after `Update.end()` validates the completed image.

Basic Authentication over plain HTTP provides access control but **not transport confidentiality**. Keep the UI on a trusted LAN/VPN or place it behind a trusted HTTPS terminator. Do not expose port 80 directly to the Internet.

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

## microSD datalogger

The onboard microSD uses its dedicated HSPI wiring and the Greiman SdFat backend. Valid Oregon and Technoline frames, plus optional BME280/AS3935 snapshots, are queued in RAM and written outside the RF-critical path to daily UTC CSV files under `/weather/`.

If the logger was enabled in NVS, boot automatically attempts the mount and acquisition starts without Web intervention. A failed mount is retried non-blockingly after 5, 15 and 60 seconds and then every 5 minutes. No automatic formatting is performed.

The header badge reports `SD OFF`, `SD PRONTA`, `SD ATTESA`, `SD ON`, `SD SCRIVE`, `SD KO` or `SD ERR`. Its tooltip includes the cumulative write count, queue depth, errors, current file and retry information. The Web configuration can remount or explicitly format the card; an invalid/missing FAT is handled only after the card transport has initialized successfully.

Full reference: [docs/SD_DATALOGGER.md](docs/SD_DATALOGGER.md).

Updated technical RF PDF: [RF encoding guide V6.4.0 - Edition 3](output/pdf/Guida_Codifiche_RF_Oregon_Technoline_V6.4.0_Edizione_3.pdf).

## Quick start

```bash
git clone https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway.git
cd esp32-oregon-technoline-weather-gateway
git checkout codex/web-provisioning-ota-auth
cp src/config_private.example.h src/config_private.h
pio run -e t3-v161-433
pio run -e t3-v161-433 -t upload
pio device monitor -b 115200
```

`src/config_private.h` is ignored by Git. Never commit Wi-Fi/MQTT credentials or private CA material. After the first boot, save the generated Web administrator password shown on Serial/OLED and replace it from **SISTEMA**.

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

The provisioning/security branch is continuously checked through draft PR #20. The validated code cycle passed:

- Validate: PASS;
- AS3935 Integration Guard: PASS;
- Oregon V2.1 host vectors: PASS;
- `t3-v161-433`: PASS;
- `t3-s3-433`: PASS;
- second `t3-v161-433` build in the same workspace: PASS, verifying pre-script idempotence.

The branch uses `min_spiffs.csv`, giving each OTA application slot `0x1E0000` bytes (`1,966,080` bytes). CI verifies the physical `firmware.bin` against that real slot size before publishing artifacts.

Because the firmware embeds the Git commit identifier, documentation-only commits change the generated binary identifier even when application logic is unchanged; use the latest successful workflow for exact current binary sizes.

## HTTP API

The Web UI uses REST-style endpoints for live state, raw/burst diagnostics, RF settings, MQTT/TLS, network/Wi-Fi, Oregon channels, display, AS3935, microSD, Web security, firmware OTA, backup/restore, restart and soft power-off.

Reference: [docs/API.md](docs/API.md).

## Backup / restore

The JSON configuration backup includes persistent network addressing/hostname, MQTT/TLS, MQTT field mask, Oregon channel configuration, display settings, AS3935 and persistent RF settings. Wi-Fi credentials and Web administrator credentials are never exported; the MQTT password is omitted unless explicitly requested.

Reference: [docs/CONFIG_BACKUP.md](docs/CONFIG_BACKUP.md).

## Security notes

- Never publish `src/config_private.h`.
- Change the generated first-boot Web administrator password.
- Basic Authentication on HTTP does not encrypt credentials; prefer LAN/VPN or a trusted HTTPS reverse proxy/terminator.
- OTA is available only while Web authentication is enabled and after successful authentication.
- Prefer CA-verified MQTT TLS outside a trusted LAN.
- `TLS insecure` is diagnostic only.
- Do not expose the ESP32 HTTP service directly to the Internet.

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
- `codex/sdfat-write-status` - hardware-validated microSD/SdFat base line;
- `codex/web-provisioning-ota-auth` - isolated provisioning, authentication, OTA and recovery line under validation.

Historical pull requests remain available as development history after intermediate branches are removed.
