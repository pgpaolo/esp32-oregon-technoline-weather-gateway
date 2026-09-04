# Suggested GitHub repository metadata

**Repository name**

`esp32-oregon-technoline-weather-gateway`

**Description**

`ESP32/SX1278 433.92 MHz gateway for Oregon OSV2.1/OSV3 and Technoline WS23xx sensors with Web UI, MQTT/TLS, COMPATIBLE MB realtime publishing, SdFat microSD logging, BME280/AS3935 and OLED.`

**Suggested topics**

`esp32`, `lilygo`, `sx1278`, `433mhz`, `oregon-scientific`, `technoline`, `lacrosse`, `weather-station`, `mqtt`, `platformio`, `sdfat`, `microsd`, `iot`, `bme280`, `as3935`, `rtl-433`

## Active branches

- `main` — stable/production line.
- `release/6.4.0-rc3` — frozen historical RC/hardware-validation line.
- `release/6.4.0-rc4` — current release candidate; updated only after explicit promotion of validated develop changes.
- `develop` — next-development line, firmware identity `6.4.0-dev2`.

## Current develop additions under validation

- COMPATIBLE MB with dedicated HTTP/HTTPS worker and strict Oregon/Technoline single-source behavior.
- Runtime BME280 altitude calibration and selectable pressure units.
- WMR200-style forecast presentation and larger title forecast tile.
- Collapsed BME280/AS3935 Dashboard panels.
- Non-blocking BME280 detection/recovery.
- Shared I2C runtime fixed at 100 kHz / 80 ms after hardware validation showed excessive cable length/capacitance was responsible for lost BME280 ACKs.
- Dedicated **CONFIGURAZIONE > I2C / HW** scanner/diagnostics page.
- ESP32 internal MCU/die temperature in Hardware monitoring when available.
- Generated-output CI guard for I2C/HW integration and same-workspace build idempotence.

## Documentation

- [`docs/MB_COMPATIBLE.md`](docs/MB_COMPATIBLE.md) — COMPATIBLE MB publisher.
- [`docs/BAROMETER_BME280.md`](docs/BAROMETER_BME280.md) — BME280, altitude, units, trend and forecast.
- [`docs/I2C_HARDWARE_DIAGNOSTICS.md`](docs/I2C_HARDWARE_DIAGNOSTICS.md) — shared-bus scanner, cable-margin diagnosis and MCU temperature.
- [`docs/API.md`](docs/API.md) — embedded HTTP API.
- [`docs/DEVELOP_6.4.0_RC4_NOTES.md`](docs/DEVELOP_6.4.0_RC4_NOTES.md) — develop-to-RC4 validation notes.

## Promotion policy

`develop` is not merged wholesale into `main`. Hardware/CI-validated changes are first promoted into `release/6.4.0-rc4`; RC4 remains unmerged until final hardware validation and an explicit release decision. The frozen RC3 line is not modified.
