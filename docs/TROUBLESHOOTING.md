# Troubleshooting

## No Wi-Fi connection

- Verify 2.4 GHz SSID/password in `src/config_private.h`.
- Check static IP/gateway/DNS values.
- Use the serial monitor at 115200 baud.

## Web UI not reachable

- Read the assigned IP from serial output.
- Confirm the client and ESP32 are on the same routed LAN/VLAN.
- Check firewall/client-isolation settings on the access point.

## Oregon sensor not received

- Start with RF mode `DUAL` or `OREGON`.
- Use `STABILE`, 125 kHz and AGC first.
- Inspect Diagnostics and RAW frames before changing timing thresholds.
- Check antenna orientation and 433.92 MHz hardware variant.

## Technoline / WS23xx not received

- Confirm the transmitter is a compatible WS23xx family device.
- Inspect the Technoline acquisition badges and RAW diagnostics.
- Keep Burst Extra disabled during normal operation unless diagnosing reception.

## MQTT does not connect

- Verify broker IP/hostname and port.
- Test plain MQTT first on a trusted LAN.
- For CA-verified TLS, ensure the CA PEM is complete and matches the broker chain.
- `TLS insecure` can isolate certificate-validation problems, but should not be a permanent configuration.

## OLED stays off after reboot

OLED state is persisted. Use the Web UI OLED control to switch it back on.

## Build problems

Clean and rebuild:

```bash
pio run -t clean
pio run -e t3-v161-433
```
