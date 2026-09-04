# Suggested GitHub repository metadata

**Repository name**

`esp32-oregon-technoline-weather-gateway`

**Description**

`ESP32/SX1278 433.92 MHz gateway for Oregon OSV2.1/OSV3 and Technoline WS23xx sensors with Web UI, MQTT/TLS, optional MB-compatible HTTP realtime publishing, SdFat microSD logging and OLED.`

**Suggested topics**

`esp32`, `lilygo`, `sx1278`, `433mhz`, `oregon-scientific`, `technoline`, `lacrosse`, `weather-station`, `mqtt`, `meteobridge`, `platformio`, `sdfat`, `microsd`, `iot`, `bme280`, `rtl-433`

**Active branches**

- `main` - stable line.
- `release/6.4.0-rc3` - frozen release candidate / hardware validation.
- `develop` - next development line; current test firmware `6.4.0-dev2` includes **COMPATIBLE MB**, runtime BME280 altitude calibration, selectable pressure units, WMR200-style forecast presentation, collapsed local-sensor panels and the larger title forecast tile.

**Develop documentation**

- [`docs/MB_COMPATIBLE.md`](docs/MB_COMPATIBLE.md) - COMPATIBLE MB realtime publisher.
- [`docs/BAROMETER_BME280.md`](docs/BAROMETER_BME280.md) - BME280 wiring, altitude calibration, units, trend and forecast tile.
- [`docs/DEVELOP_6.4.0_RC4_NOTES.md`](docs/DEVELOP_6.4.0_RC4_NOTES.md) - validation notes for the future RC4 line.

**Stable release baseline**

The published stable release remains separate from the `develop` test line until hardware validation is completed and an explicit release promotion is performed. The existing `release/6.4.0-rc3` branch is not modified by develop-only work.
