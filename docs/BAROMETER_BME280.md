# BME280 barometer, altitude calibration and WMR200-style forecast

Status: **develop / 6.4.0-dev2**. The `release/6.4.0-rc4` branch already exists; the BME280 detection/recovery hardening described below is validated on `develop` before being backported to RC4.

## Scope

The optional local BME280 provides:

- indoor/local temperature and humidity;
- absolute station pressure;
- sea-level pressure derived from the configured station altitude;
- 3-hour pressure trend;
- a WMR200-style forecast category;
- a compact Web summary that remains visible even when the detailed BME280 panel is collapsed;
- non-blocking rediscovery if the sensor is unavailable at boot or temporarily disappears from the I2C bus;
- authenticated I2C/retry diagnostics in **CONFIGURAZIONE > BAROMETRO**.

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

The OLED, BME280 and AS3935 share the board I2C bus. BME280 discovery only probes `0x76` and `0x77`; it does not scan arbitrary addresses and does not change the AS3935 configuration.

## Detection and automatic recovery

BME280 detection is no longer a boot-only operation. The firmware performs one discovery attempt during startup and, if no valid BME280 is found, retries without blocking the RF/network loop.

Retry sequence after consecutive discovery failures:

```text
boot attempt
   -> 5 s
   -> 15 s
   -> 60 s
   -> every 5 min
```

Each discovery attempt records whether an I2C device ACKed at `0x76` and/or `0x77`, then asks the Adafruit BME280 driver to validate the device as a BME280.

This distinction is useful diagnostically:

- no ACK at `0x76`/`0x77`: wiring, power, bus or sensor absence is the likely area to inspect;
- ACK present but BME280 validation fails: a device exists at the address but is not being recognized as a BME280. One common hardware possibility is a breakout sold as BME280 that actually contains a BMP280; the firmware does not assume this automatically.

While running, pressure is sampled at the normal interval. If **six consecutive pressure reads** are invalid, the firmware:

1. marks the BME280 offline;
2. invalidates the local pressure/indoor values;
3. restarts rediscovery from the 5-second stage.

This allows recovery after a temporary connector/bus/power problem without rebooting the ESP32.

The retry logic uses `millis()` scheduling and contains no `delay()` loop, so RF reception is not intentionally blocked while waiting for the BME280.

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

## BAROMETRO diagnostics

The BAROMETRO configuration page reuses its normal authenticated `GET /api/barometer/config` call to display a compact diagnostic line. No extra background poll is added.

The diagnostic line includes:

- configured SDA/SCL pins;
- ACK state for `0x76` and `0x77` from the latest discovery attempt;
- total discovery attempts;
- current retry countdown when the sensor is offline;
- total invalid pressure-read count;
- detected BME280 address when online.

If an address ACKs but the BME280 driver does not validate it, the UI reports that an I2C device is present but not recognized as a BME280, instead of presenting the same message as a completely absent bus device.

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

Immediately after boot, after an altitude change, after BME280 rediscovery, or before sufficient history exists, the trend can legitimately show `in acquisizione` / unavailable.

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

`GET /api/barometer/config` additionally exposes detection diagnostics such as:

```text
detection_attempts
last_attempt_ms
retry_in_ms
retry_delay_ms
i2c_sda
i2c_scl
i2c_ack_0x76
i2c_ack_0x77
read_failures_total
consecutive_read_failures
last_good_read_ms
```

The `/api/state` BME280 object keeps canonical hPa fields and display-oriented fields such as:

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

## Hardware validation checklist before RC4 backport

Verify on the physical T3 V1.6.1 before copying this hardening into `release/6.4.0-rc4`:

1. BME280 detection at `0x76` and, where available, a module at `0x77`.
2. Boot with the BME280 disconnected: RF/Web continue working and retry progresses 5 s -> 15 s -> 60 s -> 5 min.
3. Connect/power the BME280 after boot: it is acquired on a later retry without ESP32 reboot.
4. With the sensor online, temporarily disconnect it long enough to produce six invalid reads; the firmware marks it offline and starts rediscovery.
5. Reconnect it and confirm automatic recovery.
6. BAROMETRO diagnostics report SDA/SCL, ACK state, attempt count and retry countdown coherently.
7. Altitude change is persisted across reboot and sea-level pressure changes coherently.
8. Trend history resets after altitude calibration.
9. Each Web pressure unit renders correctly while MQTT/COMPATIBLE MB remain in canonical hPa.
10. The title forecast tile updates without an extra network request.
11. BME280 and AS3935 panels start collapsed and open/close on title click.
12. Mobile layout keeps the forecast tile readable without overlapping the header controls.
