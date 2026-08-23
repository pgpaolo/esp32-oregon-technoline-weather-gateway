# MQTT reference

Default base topic:

```text
weatherstation
```

All paths below are relative to the configured base topic.

## Selection model

The Web UI groups MQTT fields by physical station/sensor family and function:

- Oregon thermo/hygro;
- Oregon wind;
- Oregon rain;
- Oregon UV;
- Technoline;
- local BME280;
- AS3935 lightning;
- gateway/system.

The existing persistent MQTT field mask remains **32 bit**. Selection is per function/family. Individual Oregon transmitters are separated by their topic namespace rather than by an additional persistent enable bit per rolling ID.

## Gateway

| Topic | Notes |
|---|---|
| `status` | retained `online`; LWT `offline` |
| `ip` | gateway IP address |
| `rf/protocol` | active protocol family metadata |
| `state` | consolidated JSON state, optional |

## Oregon legacy topics

Legacy topics remain available for compatibility.

| Topic | Unit / value |
|---|---|
| `oregon/temperature` | °C; follows configured primary thermo channel |
| `oregon/humidity` | %; follows configured primary thermo channel |
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
| `oregon/uv` | compatibility aggregate UV index |
| `oregon/rf/sensor_id` | latest compatibility sensor ID |
| `oregon/rf/sensor_type` | latest decoded type |
| `oregon/rf/sensor_model` | model string |
| `oregon/rf/sensor_code` | Oregon sensor code |
| `oregon/rf/channel` | channel |
| `oregon/rf/battery` | `OK` / `LOW` when provided |
| `oregon/rf/rssi` | dBm |
| `oregon/rf/raw` | hexadecimal RAW frame |

## Oregon thermo CH1-CH3

Thermo/hygro channels keep independent retained values under:

```text
oregon/thermo/ch1/...
oregon/thermo/ch2/...
oregon/thermo/ch3/...
```

Available channel fields include:

- `temperature`;
- `humidity` when supported;
- `battery` when available;
- `rssi`.

The configured primary channel refreshes the legacy `oregon/temperature` and `oregon/humidity` topics. Temperature-only sensors do not expose stale humidity values.

## Oregon per-transmitter namespace

Every accepted Oregon transmitter can also publish under:

```text
oregon/sensor/<CODE>/ch<CHANNEL>/id<ROLLING>/...
```

This key is stable for the current transmitter identity and prevents CH/sensor collisions.

Examples:

```text
oregon/sensor/F824/ch1/id165/temperature
oregon/sensor/F824/ch1/id165/humidity
oregon/sensor/1D20/ch3/id114/temperature
oregon/sensor/D874/ch1/id245/uv
oregon/sensor/EC70/ch1/id158/uv
oregon/sensor/1984/ch0/id170/wind_average
oregon/sensor/2914/ch0/id189/rain_total
```

Possible measurement suffixes, depending on decoded sensor and enabled MQTT fields:

| Suffix | Value |
|---|---|
| `temperature` | °C |
| `humidity` | % |
| `wind_average` | km/h |
| `wind_gust` | km/h |
| `wind_direction_deg` | degrees |
| `wind_direction` | compass sector |
| `rain_total` | mm |
| `rain_rate` | mm/h |
| `uv` | UV index |

When `Metadati RF / RAW / batterie` is enabled, per-transmitter namespaces can also publish:

| Suffix | Value |
|---|---|
| `type` | decoded sensor family |
| `model` | model name |
| `protocol` | `OSV3` or `V2.1` where applicable |
| `rssi` | dBm |
| `battery` | `OK` / `LOW` when provided |

## UV compatibility namespaces

In addition to the generic transmitter namespace, dedicated UV compatibility topics remain available for supported UV sensor codes such as:

```text
oregon/uv/D874/index
oregon/uv/EC70/index
```

With RF metadata enabled, these namespaces can also carry model, RSSI, battery, channel and rolling-code metadata.

## Technoline / La Crosse WS23xx

| Topic | Unit / value |
|---|---|
| `technoline/temperature` | °C |
| `technoline/humidity` | % |
| `technoline/rain/total` | mm |
| `technoline/wind/speed` | km/h |
| `technoline/wind/gust` | km/h when announced/decoded |
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

WS23xx does **not** transmit battery status, therefore no real Technoline battery topic is fabricated.

## Local BME280

| Topic | Unit |
|---|---|
| `local/bme280/temperature` | °C |
| `local/bme280/humidity` | % |
| `local/bme280/pressure_station_hpa` | hPa |
| `local/bme280/altimeter_hpa` | hPa |
| `local/bme280/trend_hpa_3h` | hPa / 3h |

Compatibility aliases under `pressure/*` are retained by the firmware.

## AS3935 lightning

The AS3935 group uses four selectable MQTT functions in the existing 32-bit mask:

- state snapshot;
- IRQ/event stream;
- last strike with distance/energy;
- diagnostics/counters.

Current namespaces:

```text
as3935/state
as3935/event
as3935/last_strike
as3935/diagnostics
```

The state/last-strike/diagnostic outputs are retained where appropriate; the event stream is live/non-retained.

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

- `OFF`: plain MQTT;
- `CA verified`: TLS with configured CA PEM;
- `Insecure`: TLS without certificate verification, diagnostics only.

The CA can be stored in NVS from the Web UI. The password is not returned by the configuration API; an empty password field preserves the stored password unless an explicit clear action is requested.

## Quick verification

To inspect every published topic during hardware testing:

```bash
mosquitto_sub -h <broker> -t 'weatherstation/#' -v
```

Check that:

- legacy thermo values change only with the selected primary channel;
- CH1/CH2/CH3 remain independent;
- UVN800 and UVR128 have different transmitter namespaces;
- wind/rain transmitters do not overwrite one another;
- disabled MQTT function groups stop publishing their measurements;
- RF metadata appears only when the metadata option is enabled.
