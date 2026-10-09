# RC6-stab2 Hardening — Release notes / Note di rilascio

**Date / Data:** 2026-10-09  
**Firmware identity:** `6.4.0-rc6-stab2`  
**State / Stato:** **source candidate, not a published or physically certified GitHub Release** / **candidata sorgente, non release pubblicata o certificata su hardware**.  
**Branches:** `develop` and independent `release/6.4.0-rc6-stab2-hardening`. `main` is unchanged.  
**Review:** [Draft PR #26](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/pull/26), awaiting physical validation.

## Overview / Panoramica

RC6-stab2 inherits RF and rainfall features from `6.4.0-rc6-stab1-rain1`, improving administrative security and configuration safety without redesigning the radio decoder or claiming new measured RAM savings. / RC6-stab2 mantiene le funzioni radio e pluviometriche di rain1 e migliora sicurezza e configurazione, **senza nuove ottimizzazioni RAM misurate**.

| Domain | rain1 behavior / Stato rain1 | RC6-stab2 change / Variazione |
|---|---|---|
| Oregon OSV2.1/OSV3 + Technoline WS23xx | Radio pipeline integrated | Preserved, not redesigned |
| Rain accumulator + SdFat snapshots | Separate Oregon/Technoline daily/monthly/yearly/total UTC persistence | Preserved; field persistence test pending |
| LILYGO heap/TLS/AdminSensor | rain1 stability and transport work | Preserved; not an additional proven RAM reduction |
| Web bootstrap | Historical factory `admin/admin` possible | Random **24-character** Web password when clean/invalid NVS or insecure default is found |
| NVS migration | Legacy schema | Valid custom username and password preserved on migration |
| Recovery AP | Previously derivable password | Independently random **20-character** passphrase stored in NVS |
| Backup import | Earlier validation order | All sections validated **before** persisting thermo-channel configuration; later write errors are not rolled back |
| Meteobridge PHP adapter | Missing private legacy includes could cause a fatal error | Explicit HTTP 503 and logged dependency error (fails closed) |
| BME280 shared I2C | Separate `main` maintenance lineage | Main-only historical I2C hotfix scripts included in the candidate |

## Automated verification / Verifiche automatiche

The baseline commit `b7f4415caa671169f60dd75d37b8947f79cdf6e6` completed repository validation and both PlatformIO target builds (`t3-v161-433` and `t3-s3-433`) successfully on 2026-10-09. Automated source guards cover security-bootstrap invariants, backup validation ordering, private Meteobridge includes and other previously established host tests.

**CI success is not a hardware test.** Boot stability, first-boot credential presentation, NVS persistence, RF receive in DUAL mode, real UTC rain rollover, microSD fault behavior, TLS/WSS stress, remote OTA and server-side integration must be verified independently.

## Safe preparation / Preparazione

1. Identify the physical board revision and correct build environment: `t3-v161-433` for T3 V1.6.1, `t3-s3-433` for supported T3-S3.
2. Capture the current firmware identity, uptime/reset cause, basic sensor readings and a configuration backup without disclosing secrets.
3. Ensure local physical access to **OLED and/or Serial 115200 baud** before first stab2 boot. A device still using `admin/admin` will rotate its password.
4. Retain a known-working firmware and a board-compatible recovery method. Do not assume a firmware downgrade automatically rolls back NVS or credentials.
5. Review [security migration](SECURITY_MIGRATION_STAB2.md) and the [physical validation gate](VALIDATION_RC6_STAB2.md) before production deployment.

## Build / Compilazione

```bash
git clone https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway.git
cd esp32-oregon-technoline-weather-gateway
git checkout release/6.4.0-rc6-stab2-hardening
cp src/config_private.example.h src/config_private.h
# Set personal local configuration; do not commit secrets.
pio run -e t3-v161-433
# For the correctly connected physical T3 V1.6.1 only, after review:
# pio run -e t3-v161-433 -t upload
# pio device monitor -b 115200
```

For Windows PowerShell, use `Copy-Item src/config_private.example.h src/config_private.h` rather than `cp` if preferred. The T3-S3 requires `-e t3-s3-433` and its corresponding hardware; do not cross-flash a mismatched board. This section describes **how to build**, not an instruction to flash an untested production device.

## Security and NVS / Sicurezza e migrazione

- Clean/invalid auth NVS or the historical factory `admin/admin`: random **24-character** Web password generated from ESP32 RNG and stored in `webauth`; one-time OLED display (about 60 seconds) and local physical Serial output.
- Existing valid custom credentials and administrator username are preserved across auth schema upgrades.
- Recovery AP SSID remains identifiable, but its password is a separate **random 20-character** secret persisted as `netcfg/apsecret`; obtain it when recovery AP starts via physical Serial or authenticated network interface where available.
- Failed NVS writes may leave a temporary credential and require provisioning again after restart. Confirm password survival over cold power cycles.
- HTTP Basic Auth on plain HTTP **does not encrypt credentials or traffic**. Limit access to a trusted LAN/VPN or put the Web service behind a trusted HTTPS reverse proxy. Native device HTTPS WebServer is not claimed.
- Embedded OTA does not imply cryptographic firmware signing; use trusted and correct firmware builds.

## Configuration import / Importazione backup

Stab2 checks the imported sections before committing thermo-channel NVS changes, avoiding an early partial change when later sections fail **validation**. This is **not an atomic transaction** if NVS writes fail during subsequent persistence steps. Test both rejected-invalid and accepted-valid imports, then read settings back after reboot.

## Server-side Meteobridge / Dipendenze server

The PHP adapter requires the deployment's separate private `diga_security.php` and `diga_storage.php`. Those private libraries are **not** part of this public repository. If missing, the adapter deliberately returns HTTP **503** and logs the issue rather than providing insecure mock replacements. Set `DIGA_LEGACY_LIB_DIR` as described in [Meteobridge server README](../server/meteobridge/README.md) and test on the intended host.

## Known limits / Criticità aperte

- Integrated stab2 firmware has **not** completed a full physical endurance or rollback test.
- Backup import is not a fully atomic NVS write transaction.
- Cleartext HTTP Basic, device NVS without guaranteed flash encryption, and lack of OTA signing require network/physical security controls.
- The Meteobridge receiver cannot operate standalone without its private deployment dependencies.
- The published `v6.4.0-rc6-stab1-rain1` is **source-only**. Stab2 is not a published stable release.

## Promotion and rollback / Promozione e ripristino

Follow [RC6-stab2 hardware acceptance](VALIDATION_RC6_STAB2.md), log observable results and compare to known-good rain1. Keep [PR #26](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/pull/26) in Draft and `main` unchanged until evaluated. A regression requires a separate reviewed firmware fix: documentation work does not alter executable behavior.

## Related documents / Documenti correlati

[Documentation index](README.md) · [Security](../SECURITY.md) · [Migration](SECURITY_MIGRATION_STAB2.md) · [Published rain1 history](RELEASE_6.4.0_RC6_STAB1_RAIN1.md) · [Branch archive](../REPOSITORY_INFO.md)
