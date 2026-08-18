# Changelog

All notable project changes are documented here.

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
