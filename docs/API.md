# HTTP API

The embedded Web UI communicates with these endpoints.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/state` | live weather, RF, Wi-Fi, MQTT and hardware state |
| GET | `/api/raw` | recent decoded/RAW RF records |
| GET | `/api/raw.txt` | text representation of recent RF records |
| GET | `/api/bursts` | burst diagnostics |
| POST | `/api/rfmode` | select Oregon / Technoline / Dual |
| POST | `/api/rfgain` | set RF gain |
| POST | `/api/rfprofile` | set RF front-end profile |
| POST | `/api/burstextra` | toggle extra burst diagnostics |
| POST | `/api/wgrprobe` | toggle WGR probe |
| GET | `/api/wgrprobe/history` | WGR probe history |
| GET | `/api/mqtt` | read MQTT configuration (password excluded) |
| POST | `/api/mqtt` | update MQTT/TLS configuration |
| POST | `/api/mqtt/reset` | restore MQTT defaults |
| GET | `/api/network` | read network configuration |
| POST | `/api/network` | update network configuration |
| POST | `/api/network/reset` | restore network defaults |
| GET | `/api/config/export` | export persistent configuration as JSON (`?secrets=1` optionally includes MQTT password) |
| POST | `/api/config/import` | validate/import a JSON backup and restart |
| POST | `/api/display` | OLED ON/OFF |
| POST | `/api/restart` | restart ESP32 |

## Notes

This API is designed to support the embedded UI and is not currently versioned.
If you build external integrations against it, pin the firmware release and
expect diagnostic fields to evolve. Configuration backups use schema `1`; Wi-Fi credentials are never exported by the current firmware and the MQTT password is omitted unless explicitly requested.
