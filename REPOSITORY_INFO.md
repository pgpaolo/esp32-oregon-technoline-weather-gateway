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
- `develop` - next development line; current test firmware `6.4.0-dev1` includes **COMPATIBLE MB** realtime publishing.

**COMPATIBLE MB documentation**

See [`docs/MB_COMPATIBLE.md`](docs/MB_COMPATIBLE.md).

**Stable release baseline**

The published stable release remains separate from the `develop` test line until hardware validation is completed and an explicit release promotion is performed.
