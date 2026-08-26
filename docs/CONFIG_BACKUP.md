# Configuration backup and restore

Release candidate `6.4.0-rc3` can export and restore persistent runtime configuration from **Configuration → Backup / Restore**.

## Schema

The current backup schema remains:

```text
1
```

The release extends the contents while preserving schema-1 compatibility.

## Exported settings

Current persistent backup data includes, where supported by the running firmware:

- device hostname;
- IPv4 mode and static network settings;
- MQTT enable state;
- MQTT broker, port, username, client ID and base topic;
- MQTT TLS mode and CA certificate;
- full 32-bit MQTT field-selection mask;
- OLED power state;
- OLED page mask, field selections, page interval and contrast;
- Oregon thermo/hygro enabled-channel mask;
- Oregon primary thermo channel;
- Oregon thermo auto-discovery setting;
- AS3935 configuration;
- persistent RF mode;
- Oregon/Technoline gain settings;
- Oregon front-end profile;
- Burst Extra persistent state.

## Intentionally excluded credentials

Wi-Fi provisioning and Web authentication have their own NVS namespaces and are intentionally kept outside the normal configuration backup.

The backup does **not** export:

- configured Wi-Fi SSID/password pair;
- previous/trial Wi-Fi credentials;
- Web administrator password;
- Web administrator authentication secrets.

This means restoring a backup to another gateway does not overwrite that device's local Wi-Fi provisioning or Web administrator credential.

The primary Wi-Fi password is also never returned by the normal HTTP network API.

## MQTT password

The MQTT password is **excluded by default**.

The Web UI can explicitly include it in an export. In that case the JSON file contains the password in clear text and must be treated as a secret.

When an imported backup does not contain `mqtt_password`, the password already stored on the target gateway is preserved.

## Restore behavior

The firmware validates imported network, MQTT/TLS, Oregon-channel, display, AS3935 and RF values before accepting the configuration.

Persistent settings are written only when the resulting values require a change and are verified/read back where the corresponding manager supports verification.

The gateway restarts after a successful import so hostname/network and other boot-time configuration can be applied cleanly.

Wi-Fi SSID/password and Web administrator credentials are not changed by normal backup restore.

## RF runtime-only items

Automatic RF calibration/AutoScan is not restored as a running operation. Runtime diagnostic/probe states that are intentionally RAM-only are not treated as persistent configuration.

WGR Probe remains a diagnostic runtime feature rather than a normal persistent boot setting.

## AS3935

AS3935 settings included in backup are the same settings exposed by the Web configuration page, including enable/wiring/AFE/filter/tuning choices supported by the firmware.

Live lightning counters/events are telemetry and are not configuration backup data.

## OLED

The backup includes selectable page/field configuration, including the AS3935 page and **Sensori RF / RSSI / batterie** page bit where supported.

## Oregon CH1-CH3

Backup preserves the channel-management policy:

- enabled channels;
- selected primary channel;
- auto-discovery.

Live detected/offline state is telemetry and is not stored as configuration.

## Security guidance

- Prefer exports without secrets for normal archival/versioning.
- Never commit a secret-bearing backup to Git.
- A CA certificate is public material; an MQTT password is not.
- Wi-Fi credentials are intentionally outside the backup schema even though they are configurable from the Web UI.
- Web administrator credentials are intentionally outside the backup schema.
- Review hostname and static IP settings before restoring a backup to another gateway.
- Review AS3935 IRQ/address settings before restoring to a board with different wiring.
