# Changelog

## Unreleased - Oregon V2.1 / compact Web asset

- Added bounded Oregon Scientific V2.1 decoding for EC40/1D20/1D30 thermo sensors, WGR968 wind, RGR968 rain and UVR128 UV.
- Reused the existing dashboard cards and MQTT fields for legacy sensor families, without adding graphical components.
- Made Oregon session quality sensor-aware: absent families are excluded, multiple thermo channels have separate expectations, and V2.1 legacy links no longer receive invented OSV3 cadence percentages.
- Added V2.1 diagnostics and host-side protocol vectors.
- Moved the full dashboard source to `web/dashboard.html` and gzip-compress it at build time.
- Corrected temperature-only channel rendering, backup range validation and MQTT retained cleanup.

## 6.4.0-rc2

- Aggiunto pulsante Web `SPEGNI` con arresto controllato in ESP32 deep sleep.
- Prima del deep sleep vengono arrestati MQTT, OLED, BME280 e SX1278; Wi-Fi viene disabilitato.
- T3-S3: wake opzionale di default dal pulsante BOOT/User GPIO0 oppure RESET/EN.
- T3 V1.6.1: wake di default tramite RESET/EN, senza assumere un pulsante utente non garantito dal pinout.
- Lo spegnimento software non sostituisce un vero sezionatore/load-switch: la scheda resta elettricamente alimentata.


All notable project changes are documented here.

## [6.4.0-rc1] - 2026-08-19
- Physical OLED button default made board-aware: enabled on T3-S3, conservative OFF on T3 V1.6.1 until hardware verification.

### Added

- Configurable device hostname persisted in NVS.
- mDNS discovery through `<hostname>.local`.
- Physical PRG/BOOT short-press fallback for OLED ON/OFF, configurable by GPIO.
- Firmware, Git commit, build timestamp, board and last reset reason in the Hardware tab.
- JSON configuration export/import for network, MQTT/TLS, MQTT field mask, OLED and persistent RF settings.
- Optional inclusion of the MQTT password in configuration backups; Wi-Fi credentials remain excluded.

### Changed

- OLED boot splash now reports the firmware version from `FIRMWARE_VERSION`.
- PlatformIO builds inject the short Git commit into the firmware when built from a Git checkout.

### Security

- Configuration export omits MQTT credentials by default and always excludes Wi-Fi credentials.
- Imported backups are validated before persistent network/MQTT settings are applied.

## [6.3.0] - 2026-08-18

### Added

- Simultaneous Oregon OSV3 + Technoline/La Crosse WS23xx reception.
- Web UI with separate Dashboard, Hardware, Configuration and Diagnostics tabs.
- Compact wind compasses for Oregon and Technoline.
- Data freshness indicators.
- Hardware resource dashboard for CPU, heap, flash, OTA space, RSSI and uptime.
- MQTT TLS configuration from Web UI.
- Selectable MQTT field publishing through a persistent bitmask.
- Technoline Gust handling and explicit "gust not announced" state.
- Runtime RF mode, gain and profile controls.
- OLED ON/OFF Web control using U8g2 power-save.
- Persistent OLED state in NVS.
- REST-style endpoints for network, MQTT, RF controls, display and restart.
- GitHub-ready documentation, CI and contribution templates.

### Changed

- RF diagnostics moved away from the main dashboard to reduce visual clutter.
- RAW/burst diagnostic requests are performed only while Diagnostics is open.
- Hardware monitor moved to its own main tab.
- Restart control moved to the header.
- Dashboard reorganized into responsive four-column weather cards.

### Security

- Removed private local configuration from the distributable repository.
- `src/config_private.h` remains ignored by Git.
