# MQTT reference

The base topic defaults to:

```text
weatherstation
```

All paths below are relative to the configured base topic.

## Gateway

| Topic | Notes |
|---|---|
| `status` | retained `online` / LWT `offline` |
| `ip` | gateway IP address |
| `rf/protocol` | active protocol family metadata |
| `state` | consolidated JSON state, optional |

## Oregon

| Topic | Unit / value |
|---|---|
| `oregon/temperature` | °C |
| `oregon/humidity` | % |
| `oregon/heat_index` | °C |
| `oregon/dew_point` | °C |
| `oregon/wind/average` | km/h |
| `oregon/wind/current` | km/h |
| `oregon/wind/gust` | km/h |
| `oregon/wind/direction_deg` | degrees |
| `oregon/wind/direction` | compass sector |
| `oregon/wind/chill` | °C |
| `oregon/rain/total` | mm |
| `oregon/rain/rate` | mm/h |
| `oregon/rain/last_hour` | mm |
| `oregon/rain/last_24h` | mm |
| `oregon/rain/increment` | mm |
| `oregon/uv` | UV index |
| `oregon/rf/sensor_id` | sensor ID |
| `oregon/rf/sensor_type` | decoded type |
| `oregon/rf/sensor_model` | model string |
| `oregon/rf/sensor_code` | Oregon sensor code |
| `oregon/rf/channel` | channel |
| `oregon/rf/battery` | `OK` / `LOW` |
| `oregon/rf/rssi` | dBm |
| `oregon/rf/raw` | hexadecimal RAW frame |

## Technoline / La Crosse WS23xx

| Topic | Unit / value |
|---|---|
| `technoline/temperature` | °C |
| `technoline/humidity` | % |
| `technoline/rain/total` | mm |
| `technoline/wind/speed` | km/h |
| `technoline/wind/gust` | km/h |
| `technoline/wind/direction_deg` | degrees |
| `technoline/wind/direction` | compass sector |
| `technoline/model` | model string |
| `technoline/sensor_id` | sensor ID |
| `technoline/type` | packet type |
| `technoline/rf/rssi` | dBm |
| `technoline/next_update` | protocol update interval metadata |
| `technoline/rf/raw` | hexadecimal nibbles |
| `technoline/packets` | accepted packet count |
| `technoline/rf/valid` | valid RF frame count |

## Local BME280

| Topic | Unit |
|---|---|
| `local/bme280/temperature` | °C |
| `local/bme280/humidity` | % |
| `local/bme280/pressure_station_hpa` | hPa |
| `local/bme280/altimeter_hpa` | hPa |
| `local/bme280/trend_hpa_3h` | hPa / 3h |

Compatibility aliases under `pressure/*` are retained by the firmware.

## System

| Topic | Value |
|---|---|
| `system/cpu_mhz` | CPU frequency |
| `system/heap_free` | free heap bytes |
| `system/heap_min_free` | minimum observed free heap bytes |
| `system/wifi_rssi` | dBm |
| `system/rf_overflows` | RF ring overflow count |
| `system/uptime_s` | seconds |

## TLS modes

- `OFF`: plain MQTT
- `CA verified`: TLS with configured CA PEM
- `Insecure`: TLS without certificate verification — diagnostics only

The CA can be stored in NVS from the Web UI. The password is not returned by
the configuration API; an empty password field preserves the currently stored
password unless an explicit clear action is requested.
