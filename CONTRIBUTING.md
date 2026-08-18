# Contributing

Contributions are welcome, especially for additional Oregon Scientific sensor
models, WS23xx compatibility, RF diagnostics, MQTT integrations and hardware
support.

## Development workflow

1. Fork the repository.
2. Create a focused feature/fix branch.
3. Keep RF protocol changes isolated where possible.
4. Build both PlatformIO environments before submitting a PR.
5. Include serial/RF logs for decoder changes.
6. Never attach files containing real Wi-Fi/MQTT credentials.

## Build checks

```bash
pio run -e t3-v161-433
pio run -e t3-s3-433
```

## Decoder changes

For RF decoder work, include:

- sensor model
- frequency
- representative RAW frame(s)
- RSSI if available
- expected decoded values
- checksum/parity result
- whether the change affects Oregon, Technoline, or both

Avoid weakening checksum validation simply to accept a single frame.
