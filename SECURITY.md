# Security Policy

## Sensitive configuration

Never commit `src/config_private.h` or any file containing:

- Wi-Fi credentials;
- MQTT passwords;
- private CA/client material;
- private IP addressing that you do not intend to disclose.

The repository contains only `src/config_private.example.h`.

Wi-Fi passwords and Web administrator passwords are stored locally in NVS and are not exported by the normal configuration backup. The primary Wi-Fi password is not returned by the HTTP configuration API.

## Web interface

The embedded Web UI uses HTTP Basic Authentication and authentication is enabled by default.

Factory credentials for release candidate `6.4.0-rc3` are:

```text
user: admin
password: admin
```

Change the password immediately after first access from **Configuration > SISTEMA**. Normal replacement passwords must be at least 8 characters.

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
