# Suggested GitHub repository metadata

**Repository name**

`esp32-oregon-technoline-weather-gateway`

**Description**

`ESP32/SX1278 433.92 MHz gateway for Oregon OSV2.1/OSV3 and Technoline WS23xx sensors with Web UI, MQTT/TLS, COMPATIBLE MB realtime publishing, SdFat microSD logging, BME280/AS3935, AdminSensor Remote and OLED.`

**Suggested topics**

`esp32`, `lilygo`, `sx1278`, `433mhz`, `oregon-scientific`, `technoline`, `lacrosse`, `weather-station`, `mqtt`, `platformio`, `sdfat`, `microsd`, `iot`, `bme280`, `as3935`, `rtl-433`

## Project authorship

- Project author and maintainer: **Gianpaolo P.** (`pgpaolo`).
- Copyright © 2026 Gianpaolo P.
- License: **GNU GPL v3 or later (`GPL-3.0-or-later`)**.
- Citation metadata: [`CITATION.cff`](CITATION.cff).
- Detailed attribution: [`AUTHORS.md`](AUTHORS.md) and [`NOTICE`](NOTICE).

## Active branches

- `main` — stable/production line; contains the selective BME280/I2C reliability backport merged through PR #23.
- `release/6.4.0-rc3` — frozen historical RC/hardware-validation line.
- `release/6.4.0-rc4` — frozen previous complete release candidate.
- `release/6.4.0-rc5` — current complete release candidate, firmware identity `6.4.0-rc5`, promoted from validated `develop` commit `4310a5097c0097df4b32ae08f548ceef57957c7b`.
- `develop` — next-development line, firmware identity `6.4.0-dev3`.

## RC5 feature set

RC5 retains the complete RC4 feature set and adds:

- AdminSensor Remote outbound HTTPS enrollment and authenticated WSS management tunnel;
- no router port-forward requirement;
- guarded remote OTA with size, SHA-256, strict chunk sequence and ESP application-image validation;
- zero-copy root dashboard streaming from embedded gzip flash;
- 2 KiB raw chunks for dynamic remote HTTP responses;
- Oregon-specific post-reserve heap validation for the larger `/api/state` response;
- remote-aware non-overlapping Web polling and checked HTTP/JSON parsing;
- repeat-build/source-archive repair for SD and Remote generated pre-script state;
- CI second-build idempotence guard and unambiguous OTA-only artifacts.

The RC4 baseline retained by RC5 includes COMPATIBLE MB, BME280 altitude/pressure/forecast, the validated 100 kHz / 80 ms shared I2C runtime, I2C/HW diagnostics, Oregon V2.1/OSV3 + Technoline RF reception, SdFat logging, MQTT/TLS, AS3935 and OLED/Web integration.

## Documentation

- [`docs/RELEASE_6.4.0_RC5.md`](docs/RELEASE_6.4.0_RC5.md) — current RC5 release scope and validation reference.
- [`docs/REMOTE_ACCESS.md`](docs/REMOTE_ACCESS.md) — AdminSensor Remote/WSS architecture and OTA.
- [`docs/MB_COMPATIBLE.md`](docs/MB_COMPATIBLE.md) — COMPATIBLE MB publisher.
- [`docs/BAROMETER_BME280.md`](docs/BAROMETER_BME280.md) — BME280, altitude, units, trend and forecast.
- [`docs/I2C_HARDWARE_DIAGNOSTICS.md`](docs/I2C_HARDWARE_DIAGNOSTICS.md) — shared-bus scanner, cable-margin diagnosis and MCU temperature.
- [`docs/API.md`](docs/API.md) — embedded HTTP API.
- [`docs/RELEASE_6.4.0_RC4.md`](docs/RELEASE_6.4.0_RC4.md) — frozen RC4 release scope.
- [`AUTHORS.md`](AUTHORS.md) / [`CITATION.cff`](CITATION.cff) / [`NOTICE`](NOTICE) — authorship, citation and upstream acknowledgements.

## Promotion policy

RC5 remains unmerged into `main` until final physical validation and an explicit release decision. RC4 and RC3 remain frozen. Future development continues on `develop` and is not implicitly promoted to RC5.
