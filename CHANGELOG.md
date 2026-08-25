# Changelog

All notable project changes are documented here.

## Unreleased - SdFat microSD and write-status branch

This development line is consolidated in:

```text
codex/sdfat-write-status
```

It supersedes the intermediate AS3935, Oregon multichannel and legacy V2.1 feature branches. PR #15 now targets `main` directly.

### microSD / Web status

- Replaced the Arduino-ESP32 `SD` transport with Greiman SdFat 2.3.1 after hardware showed a valid `CMD0` response followed by library initialization failure.
- Kept the official LILYGO HSPI pin mapping, using 4 MHz first and one clean 400 kHz fallback.
- Added explicit FAT formatting through SdFat, including the card-ready/filesystem-invalid state that previously prevented the formatter from starting.
- Added SdFat error-code/data diagnostics to the Web API and format-failure messages.
- Added the top-bar `SD OFF` / `SD PRONTA` / `SD ON` / `SD SCRIVE` / `SD KO` / `SD ERR` badge with queue, error, current-file and write-count tooltip.
- Confirmed mount and format on the physical T3 V1.6.1 setup.
- Switched both targets to `min_spiffs.csv`: NVS and two OTA slots remain, while each application slot grows to 1,966,080 bytes.
- Rebuilt both PlatformIO targets and reran the Oregon V2.1 vector suite after the storage change.

### Oregon RF / UVR128

- Added bounded Oregon Scientific V2.1 decoding for EC40/1D20/1D30 thermo sensors, WGR968 wind, RGR968 rain and UVR128 UV.
- Added dedicated UVR128/EC70 recovery for real SX1278 captures with clipped short preamble or uncertain initial phase.
- Recovery scans bounded burst intervals across candidate starts and both physical polarities, but still requires EC70 identity, valid Manchester pairs and normal V2.1 checksum.
- Confirmed real UVR128 reception on target hardware.
- Preserved separate OSV3, Technoline and normal V2.1 decoder paths.
- Added/kept V2.1 diagnostics and host-side protocol vectors; Build #92 reported 6 valid vectors accepted and 6 corrupt vectors rejected.

### Oregon CH1-CH3

- Added separate live state for Oregon thermo/hygro CH1, CH2 and CH3.
- Added configurable primary channel for legacy temperature/humidity and derived station values.
- Added channel auto-discovery and persistent manual enable mask.
- Accepted both observed channel conventions: one-hot `1/2/4` and direct `1/2/3`.
- Added per-channel MQTT topics while preserving legacy primary-channel aliases.
- Added backup/restore of thermo-channel configuration.

### Multi-sensor Dashboard

- Added compact simultaneous UV display for UVN800 (`D874`), UVR128 (`EC70`) and future supported UV transmitters.
- Made Oregon session quality transmitter-aware using sensor type/code/channel/rolling ID.
- Unified RSSI presentation across Oregon thermo, wind, rain, UV and Technoline:
  - green >= -100 dBm;
  - yellow -115..-101 dBm;
  - red < -115 dBm;
  - grey when unavailable.
- Unified battery presentation where available: `BAT OK`, `BAT LOW`, `BAT N/D`.
- Technoline reports real RSSI but intentionally shows battery as unavailable because WS23xx does not transmit battery state.
- Reorganized the Technoline Dashboard to temperature/humidity, wind and rain; removed the invalid Technoline UV card.

### MQTT

- Kept existing legacy topics for compatibility.
- Added generic per-transmitter Oregon namespaces:
  `oregon/sensor/<CODE>/ch<CHANNEL>/id<ROLLING>/...`.
- Added separate UV compatibility namespaces for supported UV codes such as D874 and EC70.
- Reorganized Web MQTT selection by Oregon thermo/hygro, wind, rain, UV, Technoline, BME280, AS3935 and gateway/system.
- Preserved the existing 32-bit persistent field mask; no extra per-rolling-ID enable bits were added.
- RF metadata can publish model/type/protocol/RSSI/battery in per-transmitter namespaces.

### AS3935

- Integrated optional local AS3935 lightning detector on the shared I2C bus.
- Classic T3 V1.6.1 defaults: address `0x03`, IRQ GPIO34.
- Added Web state/config/reinit/reset, calibration/resonance diagnostics, lightning distance/energy and counters.
- Added selectable AS3935 OLED page.
- Added four selectable MQTT groups using the remaining upper bits of the existing 32-bit mask: state, event, last strike and diagnostics.
- Added AS3935 configuration to backup/restore and deep-sleep power-down behavior.

### OLED

- Added configurable **Sensori RF / RSSI / batterie** page.
- Added compact live registry for up to ten recent Oregon transmitters; displays five rows and rotates automatically when required.
- Added common G/Y/R RSSI and B+/B!/B- battery notation.
- Kept a compact UV summary on the normal external page.
- Added the same RSSI notation to the Technoline OLED page; battery remains B- because it is not transmitted.

### Web / flash

- Moved the full Dashboard source to `web/dashboard.html` and gzip-compresses it during build.
- Reused compact live/session structures instead of adding telemetry history for the new sensor-status views.
- Replaced the previous near-full application layout with `min_spiffs.csv`; the project does not use SPIFFS and retains NVS plus two OTA slots.

### Validation reference

Current SdFat branch validation:

- Validate: PASS;
- AS3935 Integration Guard: PASS;
- `t3-v161-433`: PASS;
- `t3-s3-433`: PASS.

T3 V1.6.1:

- RAM: 100,592 / 327,680 B = 30.7%;
- application ELF: 1,276,881 / 1,966,080 B = 64.9%;
- real firmware.bin: 1,283,584 B;
- application-partition margin: 689,199 B.

T3-S3:

- RAM: 99,552 / 327,680 B = 30.4%;
- application ELF: 1,220,809 / 1,966,080 B = 62.1%;
- real firmware.bin: 1,221,232 B.

## 6.4.0-rc2

- Added Web `SPEGNI` control with controlled ESP32 deep sleep.
- Before deep sleep MQTT, OLED, BME280 and SX1278 are stopped/parked and Wi-Fi is disabled.
- T3-S3: optional default wake from BOOT/User GPIO0 or RESET/EN.
- T3 V1.6.1: default wake through RESET/EN without assuming a user button not guaranteed by the pinout.
- Soft power-off is not an electrical disconnect; a load switch/latch is needed for near-zero current.

## [6.4.0-rc1] - 2026-08-19

### Added

- Configurable device hostname persisted in NVS.
- mDNS discovery through `<hostname>.local`.
- Physical PRG/BOOT short-press fallback for OLED ON/OFF, configurable by GPIO.
- Firmware, Git commit, build timestamp, board and last reset reason in the Hardware tab.
- JSON configuration export/import for network, MQTT/TLS, MQTT field mask, OLED and persistent RF settings.
- Optional inclusion of the MQTT password in configuration backups; Wi-Fi credentials remain excluded.

### Changed

- OLED boot splash reports firmware version from `FIRMWARE_VERSION`.
- PlatformIO builds inject the short Git commit into firmware when built from a Git checkout.
- Physical OLED button default made board-aware: enabled on T3-S3, conservative OFF on T3 V1.6.1 until hardware verification.

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

- RF diagnostics moved away from the main Dashboard to reduce visual clutter.
- RAW/burst diagnostic requests are performed only while Diagnostics is open.
- Hardware monitor moved to its own main tab.
- Restart control moved to the header.
- Dashboard reorganized into responsive weather cards.

### Security

- Removed private local configuration from the distributable repository.
- `src/config_private.h` remains ignored by Git.
