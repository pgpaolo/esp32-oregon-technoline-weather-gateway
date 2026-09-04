# HTTP API

The embedded Web UI communicates with the main HTTP server on port 80.

On the current development line, HTTP Basic Authentication is enabled by default and normal Dashboard/API routes are protected while authentication is enabled. Factory first-access credentials are `admin / admin` and should be changed immediately from `SISTEMA`. The current release-candidate line is `release/6.4.0-rc4`.

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
| GET | `/api/barometer/config` | read BME280 altitude/unit and lightweight discovery diagnostics |
| POST | `/api/barometer/config` | update station altitude and Web pressure unit |
| POST | `/api/barometer/reset` | restore barometer defaults |
| GET | `/api/hardware/info` | read I2C pins/runtime speed, local-sensor state and MCU die temperature |
| POST | `/api/hardware/i2c-scan` | manual authenticated 100/400 kHz I2C scan + BME280 chip-ID probe |
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

`GET /api/network` exposes the current network configuration and operational Wi-Fi state, including configured Wi-Fi SSID, password-configured state without the password, pending credential-trial state, hostname/IP configuration and recovery-AP state.

The primary STA Wi-Fi password is never returned. When a new SSID/password pair is saved it is treated as a trial; failed association after reboot can roll back to the previous credentials.

## `/api/network/scan`

Wi-Fi scanning is manual and asynchronous. `POST /api/network/scan` starts the scan and normally returns HTTP `202`; `GET /api/network/scan` returns running/completed state and up to 20 de-duplicated networks with RSSI/channel/security. Saved passwords are never returned.

## `/api/security`

The security API returns only non-secret state, including whether authentication is enabled, administrator username, whether a password is set and temporary lockout state. The actual password is never returned.

Factory first-access credentials are:

```text
admin / admin
```

After 10 failed authentication attempts the Web layer temporarily locks authentication for 30 seconds.

## `/api/firmware`

`GET /api/firmware` provides current firmware/board information and OTA-space data. `POST /api/firmware` is the multipart OTA route and is refused when Web authentication is disabled.

The upload path checks free OTA space, ESP application magic (`0xE9`), cumulative size, `Update.write()` results, final `Update.end(true)` and obvious T3 V1.6.1/T3-S3 filename mismatch. The microSD logger is closed before flash and remounted after a failed OTA when enabled.

## `/api/state`

The live state contains weather/sensor objects plus RF/session/system data. Oregon transmitters are separated by sensor type, sensor code, channel and rolling code; the live registry has ten shared slots.

The `system` object includes ESP32 CPU/heap/flash/uptime/build information. The reviewed develop line also exposes:

```text
system.hardware_temperature_c
```

This is the ESP32 internal MCU/die temperature when the Arduino core returns a plausible value. It is **not ambient temperature**. Unavailable/invalid readings are represented as JSON `null`.

The `rf` object includes V2.1/recovery diagnostics for preambles, candidates, accepted frames, checksum failures, invalid Manchester pairs and UVR128 recovery activity.

## BME280 / barometer API

`GET /api/barometer/config` returns persistent barometer configuration and lightweight discovery state. Configuration includes station altitude and pressure display unit; diagnostics include SDA/SCL, latest ACK state at `0x76`/`0x77`, retry counters and invalid-read counters.

Normal BME280 discovery probes only `0x76`/`0x77` and retries non-blockingly after approximately 5 s, 15 s, 60 s and then every 5 minutes.

The complete bus scanner is deliberately **not** part of the BAROMETRO page/API. It is separated under the hardware diagnostics API below.

## I2C / hardware diagnostics API

`GET /api/hardware/info` supports **CONFIGURAZIONE > I2C / HW** and returns:

- board name;
- SDA/SCL pins;
- normal I2C runtime speed;
- BME280 detected state/address;
- AS3935 enabled/detected state/address;
- MCU/die temperature or `null`.

`POST /api/hardware/i2c-scan` is manual and authenticated. It scans the standard 7-bit bus first at the validated **100 kHz runtime speed**, reads BME280 chip ID register `0xD0` at `0x76`/`0x77`, then runs a **400 kHz diagnostic margin test**. It always restores 100 kHz / 80 ms timeout before returning.

The generic scan intentionally starts at `0x01`; it does not probe I2C general-call address `0x00`.

Reference: [I2C_HARDWARE_DIAGNOSTICS.md](I2C_HARDWARE_DIAGNOSTICS.md).

## Technoline rain state

The Technoline state includes cumulative sensor total and frame increment plus locally derived values:

- `rain_rate_5m_mmh` — estimated average rate over a local 5-minute-or-longer baseline;
- `rain_last_hour_mm` — accumulation after enough runtime history exists;
- `rain_last_24h_mm` — accumulation after enough runtime history exists.

The WS23xx protocol does not transmit a native instantaneous rain-rate field. These values are derived from the cumulative counter using compact RAM-only history and are unavailable until enough history exists after boot.

## Oregon thermo-channel API

`/api/thermo/config` controls UI/MQTT routing of CH1-CH3, not RF reception itself. The receiver continues decoding valid supported Oregon frames. The primary channel feeds legacy temperature/humidity and derived station values.

## Display API

`/api/display/config` includes selectable OLED pages and fields, including the optional **Sensori RF / RSSI / batterie** page.

## AS3935 API

The AS3935 endpoints use the same Web server; no standalone port 81 service is used. State is intended for the Dashboard, while configuration/reinit/reset support guided setup and diagnostics.

## Backup API

Configuration backup schema is currently `1`. Wi-Fi credentials and Web administrator credentials are never exported. The MQTT password is omitted unless explicitly requested with the secrets option.

Reference: [CONFIG_BACKUP.md](CONFIG_BACKUP.md).

## microSD API

`GET /api/sd` returns `{config,status}` with mount/support/time state, capacity, current file, queue/write/drop/error counters, negotiated SPI frequency, initialization result, SdFat error bytes and automatic-retry state.

Automatic mount retries follow approximately 5 s, 15 s, 60 s and then 300 s repeatedly. No automatic formatting is performed.

`POST /api/sd/format` is destructive and rejected unless the body contains `confirm=FORMATTA`. Formatting starts only after SdFat initializes the card transport.

## Stability note

This API primarily supports the embedded UI and is not formally versioned. External integrations should pin the firmware release version and expect diagnostic JSON fields to evolve during release-candidate hardware validation.
