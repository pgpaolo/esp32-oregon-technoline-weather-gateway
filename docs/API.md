# HTTP API

The embedded Web UI communicates with the main HTTP server on port 80.

For release candidate `6.4.0-rc3`, HTTP Basic Authentication is enabled by default and normal Dashboard/API routes are protected while authentication is enabled. Factory first-access credentials are `admin / admin` and should be changed immediately from `SISTEMA`.

## Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/state` | live weather, Oregon transmitters, Technoline, RF, Wi-Fi, MQTT and hardware state |
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
| GET | `/api/network` | read network/hostname/Wi-Fi trial/recovery state; primary Wi-Fi password excluded |
| POST | `/api/network` | update SSID/password/open-network + network/hostname configuration |
| POST | `/api/network/reset` | restore firmware network/Wi-Fi defaults |
| POST | `/api/network/scan` | start an authenticated asynchronous Wi-Fi scan |
| GET | `/api/network/scan` | poll asynchronous Wi-Fi scan results |
| GET | `/api/security` | read Web authentication status, username and lock state; password excluded |
| POST | `/api/security` | update Web-auth enabled state, username and/or password |
| GET | `/api/firmware` | read current firmware/board/OTA-space information |
| POST | `/api/firmware` | authenticated multipart firmware OTA upload |
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
| GET | `/api/sd` | read microSD logger configuration and live mount/write/retry diagnostics |
| POST | `/api/sd` | update microSD logger/source/snapshot configuration |
| POST | `/api/sd/reset` | restore microSD logger defaults |
| POST | `/api/sd/remount` | explicitly remount the card |
| POST | `/api/sd/format` | destructively format FAT and remount; requires `confirm=FORMATTA` |
| POST | `/api/poweroff` | controlled MQTT/RF/display/SD shutdown followed by ESP32 deep sleep |
| POST | `/api/restart` | restart ESP32 |

## `/api/network`

`GET /api/network` exposes the current network configuration and operational Wi-Fi state, including fields such as:

- configured Wi-Fi SSID;
- whether a Wi-Fi password is configured, without returning it;
- pending credential-trial state;
- hostname / IP configuration;
- recovery-AP active state;
- recovery-AP SSID/password only while that recovery AP is active.

The primary STA Wi-Fi password is never returned by this endpoint.

When a new SSID/password pair is saved, it is treated as a trial. After reboot, failed association can roll back to the previous credentials.

## `/api/network/scan`

Wi-Fi scanning is manual and asynchronous.

`POST /api/network/scan` starts the scan and normally returns HTTP `202` with a running state.

`GET /api/network/scan` returns JSON in one of these logical states:

```json
{"status":"running","networks":[]}
```

or, once complete:

```json
{
  "status":"done",
  "networks":[
    {"ssid":"Example","rssi":-55,"channel":6,"security":"PROTETTA"}
  ]
}
```

Duplicate SSIDs are collapsed and up to 20 visible SSIDs are returned. Saved passwords are never returned.

## `/api/security`

The security API returns only non-secret state, including whether authentication is enabled, the administrator username, whether a password is set and temporary lockout state.

The actual Web password is never returned.

Factory first-access credentials for this RC are:

```text
admin / admin
```

After 10 failed authentication attempts the Web layer temporarily locks authentication for 30 seconds.

## `/api/firmware`

`GET /api/firmware` provides current firmware/board information and OTA-space data for the Web UI.

`POST /api/firmware` is the multipart OTA upload route. OTA is refused when Web authentication is disabled and requires successful authentication.

The firmware upload path checks:

- free OTA application space;
- ESP application image magic (`0xE9`);
- cumulative upload size;
- `Update.write()` return values;
- final `Update.end(true)` result;
- obvious filename mismatch between the T3 V1.6.1 and T3-S3 families.

The microSD logger is closed before flash. On a failed OTA it is remounted when configured as enabled.

## `/api/state` Oregon session data

The live state includes a transmitter-aware Oregon session registry. Each received transmitter is distinguished by sensor type, sensor code, channel and rolling code. Current fields include reception/quality information, RSSI and the data needed by the Web UI to display independent sensors.

The registry has ten slots shared by all Oregon families. Consequently, multiple UVN800 transmitters remain independent when their rolling codes differ, even on the same RF channel. The API exposes `oregon_sensor_overflow` when additional identities arrive after all slots are occupied.

The `rf` object also includes V2.1/recovery diagnostics for preambles, candidates, accepted frames, checksum failures, invalid Manchester pairs and UVR128 recovery activity.

## Technoline rain state

The Technoline state includes the cumulative sensor total and frame increment plus locally derived fields:

- `rain_rate_5m_mmh` — estimated average rate over a local 5-minute-or-longer baseline;
- `rain_last_hour_mm` — accumulation derived after enough runtime history exists;
- `rain_last_24h_mm` — accumulation derived after enough runtime history exists.

The Technoline sensor does not transmit a native instantaneous rain-rate field. These values are derived from the cumulative counter using a compact RAM-only history and are unavailable until sufficient history has accumulated after boot.

## Oregon thermo-channel API

`/api/thermo/config` controls UI/MQTT routing of CH1-CH3, not RF reception itself. The receiver continues to decode valid supported Oregon frames.

Configuration concepts include enabled channel mask, primary channel, auto-discovery and detected/visible masks. The primary channel feeds legacy temperature/humidity and derived station values.

## Display API

`/api/display/config` includes selectable OLED pages and fields, including the optional **Sensori RF / RSSI / batterie** page.

## AS3935 API

The AS3935 endpoints are served by the same Web server as the rest of the gateway; no standalone port 81 service is used.

The state endpoint is intended for the Dashboard. Configuration/reinit/reset endpoints support guided AS3935 configuration and hardware diagnostics.

## Backup API

Configuration backup schema is currently `1`. Wi-Fi credentials and Web administrator credentials are never exported. The MQTT password is omitted unless explicitly requested with the secrets option.

Backup/restore includes the persistent settings documented in [CONFIG_BACKUP.md](CONFIG_BACKUP.md).

## microSD API

`GET /api/sd` returns `{config,status}`. Status includes mount/support/time state, capacity, current file, queue/write/drop/error counters, negotiated SPI frequency, initialization result and SdFat `sd_error` / `sd_error_data` bytes.

The release candidate also exposes automatic-retry state including:

- `retry_pending`;
- `retry_in_ms`.

Automatic mount retries follow approximately 5 s, 15 s, 60 s and then 300 s repeatedly. No automatic formatting is performed.

The embedded header reads this endpoint periodically. `SD SCRIVE` means the cumulative `written` counter increased since the preceding poll. `SD ATTESA` indicates that a mount retry is scheduled.

`POST /api/sd/format` is intentionally destructive and rejected unless the form body contains `confirm=FORMATTA`. Formatting starts only after SdFat has initialized the card transport; a missing/electrically unavailable card remains a mount error.

## Stability note

This API primarily supports the embedded UI and is not formally versioned. External integrations should pin the firmware release version and expect diagnostic JSON fields to evolve during release-candidate hardware validation.
