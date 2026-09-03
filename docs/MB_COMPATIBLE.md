# COMPATIBLE MB realtime publisher

Status: **development / hardware test** (`develop`, firmware `6.4.0-dev1`).

This feature is disabled by default and does not change the Oregon/Technoline RF decoder path. It adds an optional HTTP/HTTPS realtime publisher compatible with the whitespace-separated Meteobridge/Aurora data layout used by `mb.php`-style receivers.

## Web configuration

Open **CONFIGURAZIONE > COMPATIBLE MB**.

Available settings:

- **Abilita invio realtime**: enables periodic transmission.
- **URL endpoint**: fully editable URL, maximum 384 characters.
- **Intervallo invio**: 10 to 3600 seconds; default 60 seconds.
- **Timeout HTTP**: 500 to 10000 ms; default 2500 ms.
- **Sorgente primaria**:
  - Oregon, with Technoline fallback;
  - Technoline, with Oregon fallback.
- **HTTPS / TLS**:
  - verified CA mode;
  - insecure diagnostic mode.
- **CA certificate PEM**: optional replacement CA for verified HTTPS. Leaving the field blank keeps the saved CA.
- **Cancella CA salvata**: removes the stored CA.
- **Test invio**: queues one transmission without requiring periodic mode to be enabled.

The page reports the last HTTP status, endpoint response, error, last attempt/success age, NTP synchronization state, and generated payload size.

## Endpoint URL

The endpoint is never hard-coded. Examples:

```text
https://weather.example.net/path/mb.php
```

The gateway automatically sends:

```text
https://weather.example.net/path/mb.php?d=<URL-ENCODED-PACKET>
```

If the configured URL already has query parameters, `&d=` is appended.

A `{data}` placeholder can also be used:

```text
https://weather.example.net/path/mb.php?station=05013&d={data}
```

The placeholder is replaced by the URL-encoded realtime packet.

A successful receiver is expected to return an HTTP 2xx response whose body is `success`.

## Packet layout

The publisher generates exactly **192 whitespace-separated positions**. Unsupported or unavailable values are represented by `--`; positions are never removed, preserving index compatibility.

Currently populated core positions:

| Index | Value |
|---:|---|
| 0 | UTC date `dd/mm/yyyy` |
| 1 | UTC time `HH:mm:ss` |
| 2 | outdoor temperature °C |
| 3 | outdoor humidity % |
| 4 | dew point °C |
| 5 | average wind m/s |
| 6 | gust m/s |
| 7 | wind direction degrees |
| 8 | rain rate mm/h |
| 9 | rain today mm |
| 10 | sea-level pressure hPa |
| 11 | best available wind direction fallback |
| 12 | Beaufort |
| 15 | pressure unit `hPa` |
| 16 | rain unit `mm` |
| 18 | pressure approximately 3 hours ago |
| 22 | indoor/BME temperature °C |
| 23 | indoor/BME humidity % |
| 24 | wind chill °C |
| 25 | station type `ESP32-Oregon-Technoline` |
| 38 | firmware version |
| 42 | heat index °C |
| 43 | UV index |
| 44 | rain last 24 hours mm |
| 46 | best available wind direction |
| 47 | rain last hour mm |
| 81 | controller uptime seconds |
| 151 | cumulative rain sensor total mm |

No monthly/yearly rainfall, solar radiation, or other unsupported measurements are fabricated.

## Source selection

Selection is performed independently for thermo/hygro, wind, and rain using fresh gateway data.

With **Oregon first**, a fresh Oregon value is used and Technoline becomes fallback. With **Technoline first**, the order is reversed. BME280 pressure/indoor values and Oregon UV are independent of this priority.

For Technoline thermo/hygro, dew point can be derived locally. For Technoline rain, the 5-minute estimated rate and local 1-hour/24-hour histories are used when available.

## Rain today

The sensor total is cumulative and must not be presented as daily rainfall. The publisher therefore keeps an independent daily baseline for Oregon and Technoline. The baseline is persisted in NVS once per UTC day, and also refreshed if the sensor cumulative counter genuinely resets.

The cumulative sensor total remains available separately at index 151.

## Network and RF isolation

The HTTP/HTTPS transaction runs in a dedicated low-priority FreeRTOS worker task. A slow endpoint therefore does not make the main RF loop wait for the remote HTTP request. Network requests use a bounded configurable timeout.

Transmission requires normal STA Wi-Fi connectivity. The recovery access point alone is not treated as Internet connectivity.

## TLS

For `https://` URLs:

- **Verifica CA** requires a PEM CA certificate stored in NVS;
- **Senza verifica** accepts any server certificate and is intended only for diagnostics/testing.

For production use, prefer verified HTTPS.

## Web API

All endpoints are protected by the same Web Basic Authentication used by the rest of the configuration interface.

```text
GET  /api/mbcompatible
POST /api/mbcompatible
POST /api/mbcompatible/test
POST /api/mbcompatible/reset
```

The GET response reports only whether a CA is configured (`ca_set`); it does not return the stored CA text.

## Backup / restore

The JSON configuration backup includes:

- enabled state;
- endpoint URL;
- interval;
- HTTP timeout;
- TLS mode;
- CA certificate;
- source priority.

No new username/password credential is introduced by this publisher.

## Test sequence

1. Flash a `develop` / `6.4.0-dev1` firmware build.
2. Open **CONFIGURAZIONE > COMPATIBLE MB**.
3. Enter the complete `mb.php`-compatible URL.
4. For a first LAN test, use HTTP or the diagnostic HTTPS mode only if necessary.
5. Select the preferred Oregon/Technoline priority.
6. Press **Salva COMPATIBLE MB**.
7. Press **Test invio**.
8. Confirm the Web status becomes HTTP 2xx with response `success`.
9. Verify the receiver sees exactly 192 fields and that available values correspond to the gateway dashboard.
10. Enable periodic transmission only after the manual test succeeds.

## CI regression guards

GitHub Actions verifies:

- the packet remains 192 fields;
- the main Aurora/Meteobridge field indexes do not move;
- URL `d=` and `{data}` modes remain present;
- HTTP remains on a worker task;
- both ESP32 targets compile;
- the T3 V1.6.1 firmware compiles twice in the same workspace to catch pre-build patch duplication.
