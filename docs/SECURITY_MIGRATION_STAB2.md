# Security migration — 6.4.0-rc6-stab2

## Changes

- On clean NVS / invalid Web password or an existing legacy `admin/admin` password, create a random **24-character** Web password using ESP32 hardware RNG; store it in `webauth` NVS; display on local OLED for 60 seconds and write to physical Serial console (115200 baud). Do not embed a public default credential in a production deployment.
- Preserve already valid custom Web passwords and administrator usernames during NVS schema upgrades. Upgrades no longer overwrite personal credentials merely because the schema changed.
- Recovery AP `OregonGateway-Setup-XXXXXX` keeps the discoverable SSID but uses an independently generated random **20-character** password, persisted as `netcfg/apsecret`. It is created only when AP recovery actually starts with Wi-Fi hardware enabled; do not derive from MAC/SSID.
- NVS failure: authentication remains enabled with a temporary local initial password; repeat provisioning after a reboot if persistence fails. The AP password may also be ephemeral if NVS cannot save it.

## Operator migration checklist

1. Back up your NVS/ESP32 settings where feasible and keep USB/Serial access available.
2. If the former password is `admin`, upgrade **only when physically present**; read the new initial password from OLED/Serial and update it in SISTEMA.
3. If a custom password is already set, it should continue to work after a schema upgrade. Verify login and administrator API permissions.
4. Simulate STA loss to check the recovery AP. Obtain its password from the local Serial console, then verify NVS persistence after restart.
5. Protect the physical Serial and OLED display from unauthorized access; never log credentials to a public telemetry service.
6. Keep Web Basic Authentication confined to LAN/VPN or an HTTPS reverse proxy: Basic Auth does not encrypt HTTP sessions.

## Remaining security considerations

The existing firmware stores configuration secrets in ESP32 NVS, and Web administration is based on HTTP Basic Auth. This patch does **not** implement device-bound encrypted NVS, Web TLS, cryptographic firmware signing or secure boot. A full security review should treat these as separate requirements. Do not expose the device's Web management port to the public Internet.
