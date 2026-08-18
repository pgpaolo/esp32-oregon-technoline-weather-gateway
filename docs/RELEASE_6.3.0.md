# Release notes — V6.3.0

V6.3 consolidates the gateway into a dual-protocol, Web-managed weather receiver.

## Major additions

- Oregon OSV3 + Technoline WS23xx simultaneous receive path.
- Revised responsive dashboard and compact wind compasses.
- Dedicated Hardware and Diagnostics views.
- MQTT TLS and selectable publish fields.
- Technoline Gust state handling.
- RF profile/gain controls and improved diagnostics.
- Persistent OLED power-save control from Web UI.
- ESP32 restart control from the page header.

## Upgrade notes

- Existing NVS network/MQTT settings are preserved unless reset from the UI.
- OLED state is stored in a dedicated `display` Preferences namespace.
- Keep a backup of any private configuration before flashing.
