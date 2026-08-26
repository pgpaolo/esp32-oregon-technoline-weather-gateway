# ESP32 Oregon/Technoline Weather Gateway v6.4.0-rc1

Release candidate for the V6.4 firmware line.

V6.4.0-rc1 adds device-management and maintainability features on top of the V6.3 dual-RF baseline. HTTPS is intentionally not included in this release candidate.

## Highlights

- Configurable device hostname persisted in Preferences/NVS
- mDNS access through `http://<hostname>.local/`
- JSON configuration backup and restore from the Web UI
- Optional MQTT password inclusion in exported backups
- Wi-Fi SSID and Wi-Fi password are never exported
- Firmware version, Git commit, build timestamp, board and reset reason in Hardware
- OLED Web ON/OFF power-save retained
- Board-aware physical OLED toggle policy
  - enabled by default on T3-S3
  - disabled by default on T3 V1.6.1 pending board-specific GPIO verification
- Cross-platform Git commit embedding fixed for Windows and GitHub Actions
- Oregon Scientific OSV3 and Technoline / La Crosse WS23xx RF logic retained
- MQTT/TLS, selectable MQTT fields, RF diagnostics and responsive Web UI retained
- SdFat microSD datalogger with explicit FAT format and live header write-status badge
- Expanded OTA application slots through `min_spiffs.csv` while retaining NVS and dual OTA slots

## Supported targets

- `t3-v161-433` — LILYGO T3 / LoRa32 V1.6.1 + SX1278 433 MHz
- `t3-s3-433` — LILYGO T3-S3 + SX1278 433 MHz

Both targets must pass GitHub Actions / PlatformIO before publication.

## Upgrade validation

After flashing, verify:

1. Wi-Fi association and IP configuration
2. hostname persistence after reboot
3. `<hostname>.local` resolution from an mDNS-capable client
4. Oregon and Technoline RF reception
5. MQTT connectivity and field selection
6. OLED Web ON/OFF persistence
7. configuration export/import
8. Hardware tab firmware/build/reset metadata
9. microSD mount, format, CSV write and `SD SCRIVE` header feedback

## Backup security

Wi-Fi SSID and Wi-Fi password are always excluded from exported backups.

The MQTT password is excluded by default. If explicitly included, it is plain text inside the JSON backup and the file must be protected accordingly.

## Known limitations

- This is a **release candidate**, not stable V6.4.0.
- HTTPS Web serving is not included.
- True current/power monitoring requires external hardware such as INA219/INA226.
- Physical OLED toggle is disabled by default on T3 V1.6.1 until the correct GPIO is verified.
- Technoline Gust availability depends on the RF frames actually transmitted by the station.

## GitHub release settings

- Tag: `v6.4.0-rc1`
- Target: `main`
- Title: `ESP32 Oregon/Technoline Weather Gateway v6.4.0-rc1`
- Mark as: **Pre-release**
- Keep V6.3.0 as stable/latest until RC testing is complete.

## License

GNU GPL v3 or later (`GPL-3.0-or-later`).

See `NOTICE` for decoder provenance and upstream acknowledgements.
