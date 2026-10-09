# Repository information / Informazioni sul repository

## Project and governance

- **Repository:** [esp32-oregon-technoline-weather-gateway](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway).
- **Hardware:** ESP32 LILYGO T3 V1.6.1 / T3-S3, SX1278 433.92 MHz, Oregon OSV2.1/OSV3, Technoline WS23xx, optional microSD, BME280, AS3935, OLED.
- **Features:** Web UI, MQTT/TLS, COMPATIBLE MB publishing, SdFat datalogging, rainfall accumulation and optional AdminSensor Remote/WSS.
- **Maintainer:** Gianpaolo P. (`pgpaolo`); copyright © 2026 Gianpaolo P.
- **License:** [GPL-3.0-or-later](LICENSE). See [AUTHORS](AUTHORS.md), [NOTICE](NOTICE), [CITATION.cff](CITATION.cff).
- **Documentation:** [docs/README.md](docs/README.md).

## Active branches (verified 2026-10-09)

| Branch | Role / Ruolo |
|---|---|
| `main` | Protected previous stable/production branch; **no stab2 promotion** |
| `develop` | Current development source, aligned with the stab2 Hardening candidate |
| `release/6.4.0-rc6` | Preserved historical RC6 baseline |
| `release/6.4.0-rc6-stab1-rain1` | Preserved historical rain accumulation/stability candidate |
| `release/6.4.0-rc6-stab2-hardening` | Independent RC6-stab2 source candidate, [Draft PR #26](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/pull/26) |

The baseline code commit for `develop` and stab2 was `b7f4415caa671169f60dd75d37b8947f79cdf6e6`. Documentation-only commits can advance both branch pointers **without changing the firmware**. No claim of real-board validation follows from the existence of these branches.

## Historical archival tags / Tag di archivio

These old branch tips were preserved as Git tags before the branches were removed:

| Archive tag | Former branch | Original commit |
|---|---|---|
| `archive/2026-10-09/rc3` | `release/6.4.0-rc3` | `e812809ed95861bf73efa7ce6aaea0101b2f9597` |
| `archive/2026-10-09/rc4` | `release/6.4.0-rc4` | `f31a1147bac53a4abffb831b30dba562e6f6eee6` |
| `archive/2026-10-09/rc5` | `release/6.4.0-rc5` | `77031040c8b7ce8cc42c1173da7e87c41ac78a15` |
| `archive/2026-10-09/ram-stability` | `develop-ram-stability` | `54d7c0c42ba5921a617f48145cdca554188cb629` |
| `archive/2026-10-09/bme280-hotfix` | `hotfix/bme280-i2c-main` | `9654752cd62932eecfd2619e8b64b87225f775a8` |

A historical tag preserves an old commit, but does **not** indicate its entire experimental delta is merged into stab2.

## GitHub releases / Release pubblicate

- `v6.3.0`: published stable release.
- `v6.4.0-rc1`: published prerelease.
- `v6.4.0-rc6-stab1-rain1`: published **source-only** prerelease.
- `6.4.0-rc6-stab2`: **not** currently a published/certified release; source candidate undergoing physical validation.

## Documentation and promotion

- [Central documentation index](docs/README.md)
- [Current RC6-stab2 release notes](docs/RELEASE_6.4.0_RC6_STAB2.md)
- [Physical acceptance and rollback plan](docs/VALIDATION_RC6_STAB2.md)
- [Security migration](docs/SECURITY_MIGRATION_STAB2.md)

The [PR #26](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/pull/26) remains Draft until physical T3 validation and review. Passing GitHub Actions shows compilation and automated guards; it does not certify RF endurance, SD/rain recovery, OTA or secure access on a real device. Neither historical branches nor `main` are rewritten during document maintenance.
