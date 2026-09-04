# BME280 barometer, altitude calibration and WMR200-style forecast

Status: **develop / 6.4.0-dev2**, candidate for the future `6.4.0-rc4` validation line.

## Scope

The optional local BME280 provides:

- indoor/local temperature and humidity;
- absolute station pressure;
- sea-level pressure derived from the configured station altitude;
- 3-hour pressure trend;
- a WMR200-style forecast category;
- a compact Web summary that remains visible even when the detailed BME280 panel is collapsed.

The BME280 and AS3935 detailed panels are collapsed by default on the Dashboard. Clicking their title row expands or hides the full details.

## I2C wiring

The BME280 is detected automatically at I2C address `0x76` or `0x77`.

### LILYGO T3 / LoRa32 V1.6.1

| BME280 | ESP32 |
|---|---:|
| VCC | 3.3 V |
| GND | GND |
| SDA | GPIO21 |
| SCL | GPIO22 |

### LILYGO T3-S3

| BME280 | ESP32-S3 |
|---|---:|
| VCC | 3.3 V |
| GND | GND |
| SDA | GPIO18 |
| SCL | GPIO17 |

Use 3.3 V unless the specific breakout board explicitly documents a safe onboard regulator/level shifter arrangement.

## Altitude calibration

The firmware default is defined by:

```cpp
#define BAROMETER_ALTITUDE_M 584.0f
```

The runtime value can be changed from **CONFIGURAZIONE > BAROMETRO** and is stored in ESP32 NVS namespace `barocfg`.

The accepted runtime range is `0..9000 m`.

The BME280 measures station pressure. The gateway converts that pressure to sea-level pressure using the configured altitude. Therefore the station altitude should represent the actual installation elevation, not an arbitrary pressure correction.

When the altitude is changed, the pressure-trend history is cleared. This avoids treating the calibration jump as a real meteorological pressure change.

## Pressure units

The Web UI can display pressure using:

- `hPa`;
- `mbar`;
- `inHg`;
- `mmHg`;
- `kPa`.

Only presentation is converted. Internal meteorological calculations and compatibility interfaces remain canonical in **hPa**. In particular, MQTT, COMPATIBLE MB and Weather Realtime API values are not silently converted by the Web display preference.

## Dashboard presentation

The Dashboard keeps the detailed BME280 panel collapsed by default and exposes the important barometer state in a dedicated forecast tile beside the gateway title.

Example:

```text
Oregon + Technoline 433 Gateway        ┌──────────────────────┐
                                       │  ☀  Sereno           │
                                       │  1018.4 hPa  ↑       │
                                       └──────────────────────┘
```

The tile shows:

- a larger weather icon;
- the current WMR200-style forecast label;
- sea-level pressure in the selected Web unit;
- a trend arrow (`↑`, `→`, `↓`).

The legacy compact pressure pill is retained internally for build-script compatibility but hidden in the rendered UI. The title tile reuses the normal `/api/state` refresh; it does **not** add another HTTP poll or timer.

The AS3935 lightning count remains a compact header status item (`⚡ N`).

## Forecast categories

The gateway exposes the same category set used by the WMR200 presentation:

| Code | Category |
|---:|---|
| 0 | Partly cloudy |
| 1 | Rainy |
| 2 | Cloudy |
| 3 | Sunny |
| 4 | Clear night |
| 5 | Snowy |
| 6 | Partly cloudy night |
| 7 | Unknown / N/A |

Important: the available Oregon protocol information exposes the forecast result/category produced by the console, but not Oregon Scientific's proprietary forecasting formula. The gateway therefore implements a **WMR200-style classification**, not a claim of an exact proprietary algorithm clone.

The classification uses sea-level pressure, the 3-hour pressure trend, and outdoor temperature when available. Snow additionally requires a sufficiently low outdoor temperature.

The Web UI maps daytime categories to night variants according to local browser time for visual presentation.

## Trend acquisition

The BME280 is sampled every 5 seconds by default. Pressure trend history uses 10-minute samples and estimates the pressure roughly three hours earlier when enough runtime history exists.

Immediately after boot, after an altitude change, or before sufficient history exists, the trend can legitimately show `in acquisizione` / unavailable.

## Web configuration API

Authenticated endpoints:

```text
GET  /api/barometer/config
POST /api/barometer/config
POST /api/barometer/reset
```

`POST /api/barometer/config` accepts:

```text
altitude_m=<0..9000>
pressure_unit=<0..4>
```

Pressure-unit IDs:

```text
0 = hPa
1 = mbar
2 = inHg
3 = mmHg
4 = kPa
```

The `/api/state` BME280 object keeps canonical hPa fields and adds display-oriented fields such as:

```text
altitude_m
forecast
forecast_code
display_unit
display_unit_id
pressure_station_display
altimeter_display
trend_display
```

## RC4 hardware validation checklist

Before promoting develop to `release/6.4.0-rc4`, verify on the physical T3 V1.6.1:

1. BME280 detection at `0x76` or `0x77`.
2. Altitude change is persisted across reboot.
3. Sea-level pressure changes coherently when altitude changes.
4. Trend history resets after altitude calibration.
5. Each Web pressure unit renders correctly.
6. MQTT/COMPATIBLE MB remain in canonical hPa.
7. The title forecast tile updates without an extra network request.
8. BME280 and AS3935 panels start collapsed and open/close on title click.
9. Mobile layout keeps the forecast tile readable without overlapping the header controls.

