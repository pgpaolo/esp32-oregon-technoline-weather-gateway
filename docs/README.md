# Documentation / Documentazione

> **Current development source / Sorgente di sviluppo corrente:** `6.4.0-rc6-stab2` on `develop` and `release/6.4.0-rc6-stab2-hardening`; `main` remains unchanged. **The integrated candidate has not completed physical testing.** / **La candidata non è ancora stata collaudata integralmente su hardware.**

This is the central documentation map; historical notes are preserved for traceability, not as current deployment instructions. / Questo è l'indice ufficiale: le note storiche non sostituiscono le istruzioni correnti.

## Start here / Per iniziare

| Document / Documento | Purpose / Scopo |
|---|---|
| [Italiano](../README_IT.md) · [English](../README.md) | Features, requirements and source build |
| [RC6-stab2 release notes](RELEASE_6.4.0_RC6_STAB2.md) | Current change summary, migration, limitations and rollback |
| [RC6-stab2 physical acceptance](VALIDATION_RC6_STAB2.md) | **Required** test evidence before promotion / Collaudi obbligatori |
| [Repository policy](../REPOSITORY_INFO.md) | Five current branches, archive tags, published releases |
| [Security](../SECURITY.md) · [Credential migration](SECURITY_MIGRATION_STAB2.md) | Web/AP secrets, NVS and network trust boundaries |
| [Contributing](../CONTRIBUTING.md) | Review, quality and source-change policy |

## Hardware, firmware and user interface

- [Hardware / Pinout](HARDWARE.md), [I2C diagnostics](I2C_HARDWARE_DIAGNOSTICS.md), [BME280 barometer](BAROMETER_BME280.md)
- [Web API](API.md), [configuration backup](CONFIG_BACKUP.md), [Web provisioning / OTA](WEB_PROVISIONING_OTA_AUTH.md)
- [Hostname, HTTP/HTTPS and SD](HOSTNAME_HTTPS_SD.md), [troubleshooting](TROUBLESHOOTING.md)
- [Complete V6.4 subsystem checklist](TEST_CHECKLIST_V6.4.md) — contains some historical test results; the RC6-stab2 acceptance plan above determines release readiness
- [Build on Windows — permissions](BUILD_WINDOWS_PERMISSION_ERROR.md)

## Sensors, storage, transport and architecture

- [Architecture](ARCHITECTURE.md), [memory optimization](MEMORY_OPTIMIZATION.md), [LILYGO stability overlay](STABILITY_LILYGO_T3.md)
- [Oregon OSV2.1](OREGON_V21.md), [UVR128 EC70 recovery](UVR128_RECOVERY.md)
- [Rain accumulation (IT)](RAIN_ACCUMULATION.md) · [Rain accumulation (EN)](RAIN_ACCUMULATION_EN.md)
- [microSD / SdFat datalogger](SD_DATALOGGER.md)
- [COMPATIBLE MB](MB_COMPATIBLE.md), [server adapter and private dependency requirements](../server/meteobridge/README.md), [Weather Realtime v1](WEATHER_REALTIME_V1.md)
- [MQTT](MQTT.md) and [AdminSensor Remote/WSS OTA](REMOTE_ACCESS.md)

## Historical reference / Archivio storico

The following documents retain the evidence and terminology of earlier snapshots. They are **not** a substitute for the RC6-stab2 build and validation instructions. / Le note seguenti descrivono versioni precedenti e non devono essere usate come guida corrente.

- [Published rain1 source candidate](RELEASE_6.4.0_RC6_STAB1_RAIN1.md) · [rain1 publication](../PUBLISHING_RAIN1.md)
- [Historical RC4](RELEASE_6.4.0_RC4.md) · [RC4 development notes](DEVELOP_6.4.0_RC4_NOTES.md)
- [Historical RC1](RELEASE_6.4.0_RC1.md) · [RC1 publication](../PUBLISHING_V6.4.0_RC1.md)
- [V6.3](RELEASE_6.3.0.md), [V6.4 early preview](V6.4_PREVIEW.md)
- [Archive tags and branch chronology](../REPOSITORY_INFO.md), [project changelog](../CHANGELOG.md)

## Evidence and maintenance / Evidenze e manutenzione

Automated builds/validation passed on 2026-10-09 for baseline `b7f4415caa671169f60dd75d37b8947f79cdf6e6` on both PlatformIO environments. This proves compilation and automated guards, **not** OTA success, RF/SD endurance, WSS reliability or credential migration on a live device. [GitHub Actions](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/actions) must be checked against the exact commit being installed.

A documentation-only change should alter `.md` or documentation metadata only. Firmware, PlatformIO, code generation, scripts and Actions workflows must stay unchanged when maintaining these pages.
