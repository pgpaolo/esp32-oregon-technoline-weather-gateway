# Hostname, HTTPS and microSD status

## Hostname / mDNS

The runtime network configuration supports a persistent hostname (1-32 characters, `a-z`, `0-9`, `-`). The hostname is applied before Wi-Fi starts and advertised through mDNS as `hostname.local`. Changing it requires a reboot.

## HTTPS roadmap

The current V6.3 web stack uses Arduino `WebServer` on TCP/80. Direct HTTPS requires a web-server stack with TLS support. The recommended implementation for a future V6.4 branch is:

- HTTP only / HTTPS self-signed / HTTPS custom certificate modes;
- TCP/443 for TLS; optional TCP/80 redirect;
- certificate + private-key validation before activation;
- self-signed certificate generated once and persisted;
- custom PEM certificate and private key upload;
- certificate subject, expiry and SHA-256 fingerprint displayed in Hardware/Configuration;
- small TLS connection limit to protect heap on classic ESP32.

For a browser-trusted LAN certificate, use an internal CA and a DNS name covered by the certificate SAN. A `.local` self-signed certificate will still show a browser trust warning unless its issuing CA is trusted by the client.

## LILYGO T3 V1.6.1 microSD - implemented

The board exposes an onboard microSD interface on a separate SPI pin set from the SX1278:

- SD MOSI: GPIO15
- SD MISO: GPIO2
- SD SCLK: GPIO14
- SD CS: GPIO13

The current `codex/sdfat-write-status` branch implements the microSD datalogger with Greiman SdFat on dedicated HSPI. It writes valid RF/local-sensor records to UTC daily CSV files, supports explicit FAT formatting and exposes mount/write/error state through the Configuration page and top header badge.

The card path is output-only and serviced outside the RF-critical decoder path. Missing or failed storage does not stop Oregon/Technoline reception, MQTT, OLED or the Web server.

Private TLS keys remain better suited to protected internal storage rather than removable media.
