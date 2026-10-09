# Release notes / Note di rilascio — 6.4.0-rc6-stab1-rain1

**Date / Data:** 2026-10-09  
**Status / Stato:** source release candidate; physical board validation pending / release sorgente, validazione hardware da completare.

## Hardware

Primary target: LILYGO T3 V1.6.1 (ESP32 + SX1278 433.92 MHz), OLED SSD1306, optional microSD, BME280 and AS3935. PlatformIO: `t3-v161-433`. Optional target: T3-S3 (`t3-s3-433`) subject to build and hardware checks.

## Changes / Novità

- **RF / rainfall:** separate Oregon and Technoline UTC day/month/year/lifetime accumulations from raw cumulative values, RF duplicate/reset/identity guards; optional SdFat two-slot checkpoints and NVS controls. No new SD traffic from RF receive callbacks.
- **LILYGO stability:** reduced RF/RAW static buffers (~4,864 B measured in host layout); task creation on demand, TLS/WSS coordination, segmented AdminSensor `/api/state`, reset and contiguous-heap diagnostics.
- **COMPATIBLE MB:** fixed station freshness interpretation (Technoline 300 s); no HTTPS publish with zero valid weather measurements, dashboard and API diagnostics. `192 fields` alone are not proof of 192 valid measurements.
- **Build reproducibility:** prevent unnecessary source rewrites; pre-build scripts patched to remain idempotent over repeated passes.
- **UI/security:** SD format remains explicit; device credentials and OTA require authentication. Note: Basic Auth over HTTP is not encrypted: restrict to trusted LAN/VPN/HTTPS reverse proxy.

## Upgrade / Aggiornamento

1. Export configuration backup and copy SD CSV / `/weather/rain_*.bin` where applicable; ensure adequate power supply.
2. Use PlatformIO and the board-specific target; check output `firmware.bin` size and OTA partition before flashing.
3. Verify Serial 115200 reset reason, `heap largest block`, free stack, Wi-Fi/Web, radio decoders and HTTPS/WSS behaviour.
4. In **CONFIGURAZIONE > microSD** activate Oregon and/or Technoline accumulation; optionally activate SD persistence with SD logging and mounted card.
5. Confirm `GET /api/rain/accumulation`, duplicated RF telegram behaviour, UTC bucket rollover and SD recovery after restart.
6. Validate COMPATIBLE MB status by checking real measurements, not just field count; ensure selected Oregon/Technoline source is correct.

**Important:** A new accumulator starts from the first received baseline; no historical rain is inferred retroactively. Persistence is approximate (up to ~60 seconds of uncheckpointed data). Never format a card without backup.

## Verification status / Stato verifiche

Source-level and host arithmetic/pre-build tests were carried out. [GitHub Actions run 37922875911](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/actions/runs/37922875911) passed builds for both `t3-v161-433` and `t3-s3-433`. OTA on the board, recovery after sudden power loss, SX1278 RF reception, endurance and SD SPI operation **must still be tested on hardware**. No binary is claimed hardware-certified.

## Documents / Documenti

- [English rain guide](RAIN_ACCUMULATION_EN.md) / [Guida italiana accumuli](RAIN_ACCUMULATION.md)
- [LILYGO T3 stability](STABILITY_LILYGO_T3.md)
- [microSD datalogger](SD_DATALOGGER.md)
- [HTTP API](API.md) and [MB compatible publisher](MB_COMPATIBLE.md)
- [Hardware and wiring](HARDWARE.md), [troubleshooting](TROUBLESHOOTING.md)
- [Publishing checklist](../PUBLISHING_RAIN1.md)

Historical documentation, authorship and GPL-3.0-or-later licensing remain in place.
