# HTTP API

The embedded Web UI communicates with the following endpoints on the main HTTP server (port 80).

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/state` | live weather, per-transmitter Oregon session state, Technoline, RF, Wi-Fi, MQTT and hardware state |
| GET | `/api/raw` | recent decoded/RAW RF records |
| GET | `/api/raw.txt` | text representation of recent RF records |
| GET | `/api/bursts` | burst diagnostics |
| POST | `/api/rfmode` | select Oregon / Technoline / Dual |
| POST | `/api/rfgain` | set RF gain |
| POST | `/api/rfprofile` | set RF front-end profile |
| POST | `/api/burstextra` | toggle extra burst diagnostics |
| POST | `/api/wgrprobe` | toggle WGR probe |
| GET | `/api/wgrprobe/history` | WGR probe history |
| GET | `/api/mqtt` | read MQTT/TLS configuration; password excluded |
| POST | `/api/mqtt` | update MQTT/TLS configuration and field mask |
| POST | `/api/mqtt/reset` | restore MQTT defaults |
| GET | `/api/network` | read network/hostname configuration |
| POST | `/api/network` | update network/hostname configuration |
| POST | `/api/network/reset` | restore network defaults |
| GET | `/api/config/export` | export persistent configuration as JSON; `?secrets=1` can include MQTT password |
| POST | `/api/config/import` | validate/import a JSON backup and restart |
| GET | `/api/thermo/config` | read Oregon CH1-CH3 configuration and detected/visible mask |
| POST | `/api/thermo/config` | set enabled channels, primary channel and auto-discovery |
| POST | `/api/thermo/reset` | restore thermo-channel defaults |
| POST | `/api/display` | OLED ON/OFF power-save control |
| GET | `/api/display/config` | read OLED page/field/interval/contrast configuration |
| POST | `/api/display/config` | update OLED configuration |
| POST | `/api/display/reset` | restore display defaults |
| GET | `/api/as3935/state` | AS3935 live state, last event and diagnostics |
| GET | `/api/as3935/config` | read AS3935 configuration |
| POST | `/api/as3935/config` | update AS3935 configuration |
| POST | `/api/as3935/reset` | restore AS3935 defaults |
| POST | `/api/as3935/reinit` | reinitialize/re-detect AS3935 using current configuration |
| POST | `/api/poweroff` | controlled MQTT/RF/display shutdown followed by ESP32 deep sleep |
| POST | `/api/restart` | restart ESP32 |

## `/api/state` Oregon session data

The live state includes a transmitter-aware Oregon session registry. Each received transmitter is distinguished by sensor type, sensor code, channel and rolling code. Current fields include reception/quality information, RSSI and the data needed by the Web UI to display independent sensors.

This prevents traffic from different OSV2.1/OSV3 transmitters from sharing a single reception-quality counter.

The `rf` object also includes V2.1/recovery diagnostics for preambles, candidates, accepted frames, checksum failures, invalid Manchester pairs and UVR128 recovery activity.

## Oregon thermo-channel API

`/api/thermo/config` controls the UI/MQTT routing of CH1-CH3, not RF reception itself. The receiver continues to decode valid supported Oregon frames.

Configuration concepts:

- enabled channel mask;
- primary channel;
- auto-discovery;
- detected/visible channel masks returned to the UI.

The primary channel feeds legacy temperature/humidity and derived station values.

## Display API

`/api/display/config` includes the selectable OLED pages and fields. On the consolidated UVR128 branch the page mask includes the optional **Sensori RF / RSSI / batterie** page in addition to the existing weather, Technoline, barometer, RF/status and AS3935 pages.

## AS3935 API

The AS3935 endpoints are served by the same Web server as the rest of the gateway; no standalone port 81 service is used.

The state endpoint is intended for the Dashboard. Configuration/reinit/reset endpoints support the guided AS3935 configuration page and hardware diagnostics.

## Backup API

Configuration backup schema is currently `1`. Wi-Fi credentials are never exported. The MQTT password is omitted unless explicitly requested with the secrets option.

Backup/restore includes the persistent settings documented in [CONFIG_BACKUP.md](CONFIG_BACKUP.md).

## Stability note

This API primarily supports the embedded UI and is not formally versioned. External integrations should pin the firmware/branch version and expect diagnostic JSON fields to evolve during hardware-validation work.
