# Configuration backup and restore

The V6.4 development line can export and restore the gateway's persistent runtime configuration from **Configuration → Backup / Restore**.

## Exported settings

Schema `1` currently includes:

- device hostname and IPv4 mode/settings;
- MQTT enable state, broker, port, username, client ID and base topic;
- MQTT TLS mode and CA certificate;
- MQTT field-selection mask;
- OLED ON/OFF state;
- persistent RF mode, Oregon/Technoline gain, Oregon front-end profile and Burst Extra state.

Wi-Fi SSID and password are **never exported** because they remain compile-time/private configuration in `src/config_private.h`.

The MQTT password is **excluded by default**. The Web UI can include it explicitly, in which case the downloaded JSON contains that password in clear text and must be protected accordingly.

## Restore behavior

The firmware accepts backup schema `1`, validates network, MQTT/TLS and RF values, writes only the resulting persistent settings, then restarts the gateway so hostname/network changes take effect cleanly.

If the backup does not contain `mqtt_password`, the MQTT password already stored on the target gateway is preserved.

Automatic RF calibration (`AutoScan`) is intentionally not restored as a running state; it is normalized to the stable profile.

## Security guidance

- Prefer backups without secrets for normal archival/versioning.
- Never commit a secret-bearing backup to Git.
- A CA certificate is public material; a private TLS key is not used by the current HTTP server and is not part of this backup schema.
- Review the JSON before restoring it to a different gateway, especially static IP and hostname values.
