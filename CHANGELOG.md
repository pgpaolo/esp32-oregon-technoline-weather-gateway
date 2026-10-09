# Changelog

All notable project changes are documented here.

## 6.4.0-rc6-stab2 — 2026-10-09 (security/integration review)

- Rotated the legacy `admin/admin` onboarding password to a random 24-character credential, shown on the local OLED and Serial output at first boot or insecure-credential upgrade. Existing custom Web credentials survive schema migration.
- Generated a random 20-character recovery AP passphrase with NVS persistence, rather than deriving it from the public SSID/MAC suffix. Recovery AP provisioning requires local Serial access to the password when STA is unavailable.
- Preserved main-only BME280/I2C hotfix scripts in merge ancestry; the RC6 shared-I2C runtime path remains authoritative and is not double-patched.
- Updated release-facing documentation, citation metadata and security notes; added CI security invariant tests. Hardware endurance/OTA/power-loss recovery still require bench validation.

## 6.4.0-rc6-stab1-rain1 — 2026-10-09 (source candidate)

- Independent Oregon and Technoline rain accumulators: UTC day/month/year/lifetime counters.
- Optional microSD persistence: rotating two-slot checkpoints with integrity checks; write deferred outside RF hot path and limited to approximately 60 seconds.
- Baseline and deduplication guards for repeated RF packets, sensor counter resets and changed RF identity.
- Web UI microSD toggles and authenticated `GET /api/rain/accumulation`; no additional background polling.
- Preceding `stab1` heap/TLS protections and `buildfix1` idempotent pre-build scripts; `buildfix2` fixes Technoline validity to 300 seconds and reports real MB weather measurements.
- Tests: host-side rainfall arithmetic and repeated pre-script generation; [GitHub Actions run 37922875911](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/actions/runs/37922875911) successfully compiled both board targets. Physical board validation remains outstanding.

## 6.4.0-rc4 - refreshed from reviewed develop

This RC4 line has been fully refreshed from validated `develop` commit `68c1adc7df3e4e7a56b24b13bc6bdfc80bd247f3`. `release/6.4.0-rc3` remains frozen. `main` now contains the selective BME280/I2C reliability backport merged through PR #23, while the complete RC4 feature set remains on this release branch.

### BME280 / shared I2C

- Added persistent BME280 station altitude and Web pressure-unit configuration while keeping canonical hPa internally.
- Added WMR200-style forecast categories based on sea-level pressure, 3-hour trend and outdoor temperature where required.
- Added non-blocking BME280 discovery/recovery: boot attempt, then approximately 5 s, 15 s, 60 s and every 5 minutes.
- A previously working BME280 is marked offline after six consecutive invalid pressure reads and rediscovery restarts automatically.
- Physical testing established excessive I2C cable length/capacitance as the cause of the observed missing BME280 ACKs.
- Consolidated the shared OLED/BME280/AS3935 runtime bus at **100 kHz** with an **80 ms** Wire timeout for additional signal margin.
- Removed the experimental boot-time AS3935 address auto-scan; the sensor again uses its configured address deterministically. The valid configurable range remains `0x00..0x03`, with project default `0x03` on T3 V1.6.1.
- Kept BME280 preference for `0x77` with `0x76` fallback.

### I2C / hardware diagnostics

- Moved the manual full-bus scanner out of BAROMETRO into dedicated **CONFIGURAZIONE > I2C / HW**.
- Runtime scan is performed first at 100 kHz; 400 kHz is a manual stress/margin test only.
- Added direct Bosch BME280 chip-ID (`0xD0`) verification at `0x76`/`0x77`; `0x60` confirms BME280.
- The scanner checks initial/final SDA/SCL state and always restores the normal 100 kHz / 80 ms bus configuration.
- Generic scanning does not probe I2C general-call address `0x00`.
- Added authenticated hardware-info and I2C-scan endpoints.
- Added ESP32 internal MCU/die temperature to the Hardware monitor and hardware diagnostics page when a plausible reading is available; this value is explicitly not treated as ambient temperature.
- Consolidated duplicate BME-only scanner documentation into `docs/I2C_HARDWARE_DIAGNOSTICS.md`.

### Web UI / barometer presentation

- BME280 and AS3935 detailed Dashboard sections are collapsible and closed by default.
- Added a larger pressure/forecast tile beside the gateway title.
- BAROMETRO remains focused on altitude, pressure units, BME-specific retry/ACK diagnostics and preview values.
- Dedicated I2C/HW configuration keeps full-bus diagnostics separate from meteorological configuration.

### Project attribution / citation

- Kept the project license unchanged as **GPL-3.0-or-later**; no custom or incompatible attribution clause was introduced.
- Added `AUTHORS.md` with **Gianpaolo P.** (`pgpaolo`) as project author and maintainer and copyright © 2026 Gianpaolo P.
- Added `CITATION.cff` so GitHub and citation-aware tools can expose formal project citation metadata.
- Expanded `NOTICE` to separate original project authorship from upstream protocol/code acknowledgements.
- Added a deliberately low-profile title line showing `© 2026 Gianpaolo P.`, `GPL-3.0-or-later` and the installed firmware version.
- The installed version reuses the existing `/api/state` payload; no extra HTTP request is added.
- Added generated-output CI validation to ensure the attribution/version block is present exactly once.

### COMPATIBLE MB / server normalization

- Added COMPATIBLE MB 192-field publishing through a separate FreeRTOS HTTP/HTTPS worker.
- Added exclusive Oregon/Technoline source selection with no cross-station fallback inside one packet.
- Added generic server-side Weather Realtime API v1 adapter/reference implementation under `server/meteobridge/`.

### Validation reference

- Validated source commit on `develop`: `68c1adc7df3e4e7a56b24b13bc6bdfc80bd247f3`.
- Validate #192: success.
- PlatformIO Build #268: success.
- Both `t3-v161-433` and `t3-s3-433` compiled successfully.
- Same-workspace T3 V1.6.1 rebuild/idempotence check passed.
- PCR800, Oregon V2.1 and COMPATIBLE MB host-side checks passed.
- Generated I2C/HW integration guard passed.
- Physical `firmware.bin` size guard passed.
- RC4 release-branch CI must remain green after attribution/documentation updates before any merge to `main`.

## 6.4.0-rc3 / RC4 baseline work

### microSD / Web status

- Replaced Arduino-ESP32 `SD` transport with Greiman SdFat 2.3.1.
- Added explicit FAT formatting, SdFat error diagnostics and non-blocking mount retries.
- Added live SD status/write badge.
- Switched both targets to `min_spiffs.csv`, preserving NVS and two OTA slots while giving each application slot 1,966,080 bytes.

### Oregon RF / UVR128

- Added bounded Oregon Scientific V2.1 support for supported thermo, wind, rain and UV sensors.
- Added dedicated UVR128/EC70 recovery for clipped preamble / uncertain initial phase captures.
- Preserved separate OSV3, Technoline and normal V2.1 decoder paths.
- Added host-side Oregon V2.1 protocol vectors and runtime diagnostics.

### Oregon CH1-CH3 / multi-sensor Dashboard

- Added independent CH1-CH3 thermo/hygro state, configurable primary channel and auto-discovery.
- Added per-transmitter Oregon MQTT namespaces keyed by sensor code, channel and rolling ID.
- Fixed D874/UVN800 UV parsing when battery/flag bits are non-zero.
- Added simultaneous UVN800/UVR128 presentation and transmitter-aware session quality.
- Unified RSSI and battery presentation across supported sensor families.

### MQTT / AS3935 / OLED

- Preserved legacy MQTT topics and 32-bit persistent field mask while adding grouped sensor publishing.
- Added optional AS3935 local lightning detector with Web, MQTT, OLED, backup/restore and deep-sleep integration.
- Added configurable OLED pages including compact RF/RSSI/battery status.

### Web provisioning / security / OTA

- Added configurable hostname/mDNS, Wi-Fi provisioning, SSID scan, credential trial/rollback and recovery AP.
- Added Basic Authentication, temporary lockout, security configuration and authenticated OTA.
- Added JSON configuration backup/restore with secret-handling safeguards.

## 6.4.0-rc2

- Added Web `SPEGNI` control with controlled ESP32 deep sleep.
- Before deep sleep MQTT, OLED, BME280 and SX1278 are stopped/parked and Wi-Fi is disabled.
- T3-S3 supports optional BOOT/User GPIO0 or RESET/EN wake; T3 V1.6.1 uses conservative RESET/EN wake.

## 6.4.0-rc1 - 2026-08-19

- Added persistent hostname/mDNS and richer Hardware firmware/build/reset information.
- Added JSON configuration export/import.
- Added physical OLED-button support with board-aware defaults.
- Added Git commit injection into firmware builds.
- Hardened backup secret handling.

## 6.3.0 - 2026-08-18

- Added simultaneous Oregon OSV3 + Technoline/La Crosse WS23xx reception.
- Added responsive Web Dashboard, Hardware, Configuration and Diagnostics tabs.
- Added MQTT TLS and selectable publishing mask.
- Added runtime RF mode/gain/profile controls, wind compasses, data freshness and OLED Web control.
- Added initial hardware resource monitor and REST-style control endpoints.
- Removed private local configuration from the distributable repository; `src/config_private.h` remains ignored by Git.

## 6.4.0-rc6-mem1 — conservative SRAM optimization (source overlay)

- Packed SX1278 edge logic levels into 1-bit-per-entry storage while preserving the 4096-entry FIFO and full 16-bit pulse duration.
- Reconstructed the Oregon/Technoline RAW history protocol/source/type labels on demand instead of storing 44 bytes of duplicated text in each history entry.
- Host regression shows 4,864 fewer bytes in these static buffers. New source-backed test and detailed rationale: `docs/MEMORY_OPTIMIZATION.md`.
- Requires PlatformIO and hardware validation before installation; the original RC6 release is otherwise unchanged.

## 6.4.0-rc6-stab1 — LILYGO T3 reboot containment

- Includes all 6.4.0-rc6-mem1 savings (4,864 B static SRAM).
- Activates the pre-existing remote runtime V2: direct WSS reconnect after scheduled HTTPS MB transmission, reduced remote-only Web UI polling, and task stack diagnostics.
- Activates the existing segmented `/api/state` AdminSensor fastpath: 2 KiB independent buffers avoid another ~9 KiB contiguous allocation; serializes the first remote-dashboard refresh.
- Delays creation of the AdminSensor (12 KiB + 7 KiB) and MB-compatible (8 KiB) FreeRTOS task stacks until the feature is actually enabled, while preserving enablement through the authenticated Web UI. These are stack reservation values, **not** claimed measured heap gains.
- Defers MB HTTPS attempts when the largest 8-bit heap block is under 32 KiB and WSS cannot be safely paused. No watchdog/brownout bypass.
- Exposes heap largest free block and loop task's stack high-water mark in `/api/state`; logs the ESP reset reason at boot.
- Full PlatformIO build and LILYGO soak test remain required. See `docs/STABILITY_LILYGO_T3.md`.
