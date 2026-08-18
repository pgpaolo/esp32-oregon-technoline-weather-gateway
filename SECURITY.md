# Security Policy

## Sensitive configuration

Never commit `src/config_private.h` or any file containing:

- Wi-Fi credentials
- MQTT passwords
- private CA/client material
- private IP addressing that you do not intend to disclose

The repository contains only `src/config_private.example.h`.

## Web interface

The embedded HTTP UI is designed for a trusted LAN. Unless additional access
controls are added, do not expose the ESP32 directly to the public Internet.
Prefer VPN access, network segmentation, firewall rules or an authenticated
reverse proxy.

## MQTT TLS

Use CA-verified TLS whenever the broker is outside a trusted local network.
The insecure TLS mode disables certificate verification and is intended only
for controlled diagnostics.

## Reporting a vulnerability

Please avoid opening a public issue for a vulnerability that includes secrets,
credentials or exploit details. Contact the repository maintainer privately
through the contact method published on the GitHub profile/repository.
