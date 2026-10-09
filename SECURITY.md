# Security Policy

## Sensitive configuration

Never commit `src/config_private.h` or any file containing:

- Wi-Fi credentials;
- MQTT passwords;
- private CA/client material;
- private IP addressing that you do not intend to disclose.

The repository contains only `src/config_private.example.h`.

Wi-Fi passwords and Web administrator passwords are stored locally in NVS and are not exported by the normal configuration backup. The primary Wi-Fi password is not returned by the HTTP configuration API.

## Initial credentials and recovery AP (stab2)

New installations and upgrades still using the legacy factory `admin/admin` Web password receive a random 24-character initial password. It is shown on the local OLED for approximately 60 seconds and on the physical Serial console. Existing user-chosen passwords remain unchanged when NVS schema changes. **Have physical access to the device or Serial before applying the upgrade if the current password is `admin`.** A failing NVS write keeps authentication enabled, but may require re-provisioning after a reboot.

The Wi-Fi recovery AP password is now a random 20-character secret, persisted in NVS. Its SSID still identifies the device, but the password cannot be reconstructed from that SSID or MAC suffix. The password is available over the local Serial console when the AP starts and through the authenticated network UI if reachable. Keep this secret private.

## Web interface

The embedded Web UI uses HTTP Basic Authentication and authentication is enabled by default.

**Historical versions through rain1** used these insecure initial credentials (automatically rotated in stab2):

```text
user: admin
password: admin
```

For historical firmware through rain1, change the factory default immediately. For stab2, the initial password is randomly generated; store it securely and optionally replace it from **Configuration > SISTEMA**. Normal user-selected passwords must be at least 8 characters.

After 10 failed authentication attempts the firmware applies a temporary 30-second lockout.

Basic Authentication over plain HTTP provides access control but **does not encrypt credentials or page/API traffic**. The ESP32 Web service should therefore remain on a trusted LAN/VPN or be placed behind a trusted HTTPS reverse proxy/terminator. Do not expose the device's HTTP port directly to the public Internet.

## Firmware OTA

Web OTA is intentionally unavailable when Web authentication is disabled.

An authenticated upload is checked for:

- available OTA application space;
- ESP application image magic/header;
- cumulative image size;
- `Update.write()` errors;
- successful final `Update.end(true)`;
- obvious opposite-board-family names (`t3-v161` versus `t3-s3`).

These checks reduce accidental flashing mistakes but do not constitute cryptographic firmware signing. Install firmware only from a trusted build/source.

The microSD logger is closed before OTA. If an upload fails and the logger is enabled, the firmware attempts to remount the card.

## Wi-Fi provisioning and recovery AP

New Wi-Fi credentials are stored as a trial configuration. If association fails, the previous credentials are restored when available.

After prolonged STA unavailability the firmware starts a local recovery AP so the Web configuration can remain reachable. The recovery AP is shut down automatically once the primary STA reconnects.

Treat access to the recovery AP as local administrative access. Do not publish its credentials unnecessarily.

The Wi-Fi scan endpoint is authenticated when Web authentication is active and returns SSID/RSSI/channel/security information only; it never returns saved Wi-Fi passwords.

## MQTT TLS

Use CA-verified TLS whenever the broker is outside a trusted local network.
The insecure TLS mode disables certificate verification and is intended only for controlled diagnostics.

## Reporting a vulnerability

Please avoid opening a public issue for a vulnerability that includes secrets, credentials or exploit details. Contact the repository maintainer privately through the contact method published on the GitHub profile/repository.
