# BME280 barometer, altitude calibration and WMR200-style forecast

Status: **develop / 6.4.0-dev2**. The `release/6.4.0-rc4` branch already exists; the BME280 recovery and shared-bus hardening are validated on `develop` before the RC4 refresh.

## Scope

The optional local BME280 provides:

- indoor/local temperature and humidity;
- absolute station pressure;
- sea-level pressure derived from the configured station altitude;
- 3-hour pressure trend;
- a WMR200-style forecast category;
- a compact Web summary that remains visible when the detailed BME280 panel is collapsed;
- non-blocking rediscovery if the sensor is unavailable at boot or temporarily disappears from I2C;
- lightweight ACK/retry diagnostics in **CONFIGURAZIONE > BAROMETRO**.

The complete manual bus scanner is intentionally separate from the barometer settings and lives in **CONFIGURAZIONE > I2C / HW**. See [I2C_HARDWARE_DIAGNOSTICS.md](I2C_HARDWARE_DIAGNOSTICS.md).

## I2C wiring and validated bus speed

The BME280 is detected automatically at `0x76` or `0x77`.

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

The OLED, BME280 and AS3935 share the board I2C bus. Physical testing established that the earlier BME280 detection failure was caused by **excessive I2C cable length/capacitance**, not by the Adafruit BME280 driver. The normal shared bus is therefore kept conservatively at:

```text
100 kHz
Wire timeout 80 ms
```

Use short SDA/SCL wiring whenever possible. SDA/SCL can both read HIGH at idle while edges are still too degraded for a peripheral to ACK reliably.

## Detection and automatic recovery

BME280 detection is not boot-only. The firmware performs one discovery attempt during startup and retries without blocking the RF/network loop.

```text
boot attempt
   -> 5 s
   -> 15 s
   -> 60 s
   -> every 5 min
```

Each discovery records ACK state at `0x76` and `0x77`, then asks the BME280 driver to validate the sensor. The current Waveshare/common default `0x77` is tried first, with `0x76` retained as fallback.

While running, if **six consecutive pressure reads** are invalid, the firmware marks the BME280 offline, invalidates local pressure/indoor values and restarts rediscovery from the 5-second stage.

The retry logic uses `millis()` scheduling and does not add a blocking delay loop.

## Altitude calibration

The firmware default is defined by:

```cpp
#define BAROMETER_ALTITUDE_M 584.0f
```

The runtime value can be changed from **CONFIGURAZIONE > BAROMETRO** and is stored in NVS namespace `barocfg`. Accepted range: `0..9000 m`.

The BME280 measures station pressure. The gateway converts it to sea-level pressure using the configured installation altitude. When altitude changes, the pressure-trend history is cleared so the calibration change is not mistaken for a meteorological pressure jump.

## Pressure units

The Web UI can display:

- `hPa`;
- `mbar`;
- `inHg`;
- `mmHg`;
- `kPa`.

Only presentation is converted. Internal calculations and compatibility interfaces remain canonical in **hPa**, including MQTT, COMPATIBLE MB and Weather Realtime API values.

## Dashboard presentation

The detailed BME280 panel starts collapsed. A larger forecast tile beside the gateway title shows:

- WMR200-style weather icon/category;
- sea-level pressure in the selected Web unit;
- trend arrow (`↑`, `→`, `↓`).

The tile reuses the normal `/api/state` refresh and does not add another polling timer.

The AS3935 panel is likewise collapsible and its compact lightning counter remains available in the header.

## BAROMETRO diagnostics

The BAROMETRO configuration page reuses its authenticated `GET /api/barometer/config` request to show:

- configured SDA/SCL pins;
- ACK state for `0x76` and `0x77` from the latest discovery attempt;
- discovery attempt count;
- retry countdown when offline;
- invalid pressure-read count;
- detected BME280 address when online.

This is intentionally the **BME280-specific** diagnostic view. Full bus enumeration, 100/400 kHz comparison, chip-ID probing and MCU hardware temperature are in **CONFIGURAZIONE > I2C / HW**.

## Forecast categories

The gateway uses the same category set exposed by WMR200 presentation:

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

The available Oregon protocol information exposes the forecast result/category produced by the console, but not Oregon Scientific's proprietary formula. The gateway therefore implements a **WMR200-style classification**, not an exact proprietary algorithm clone. Classification uses sea-level pressure, 3-hour trend and outdoor temperature when available.

## Trend acquisition

The BME280 is sampled every 5 seconds by default. Pressure trend history uses 10-minute samples and estimates the pressure roughly three hours earlier once enough runtime history exists.

After boot, altitude change or BME280 rediscovery, the trend can legitimately show `in acquisizione` until sufficient history accumulates.

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

`GET /api/barometer/config` additionally exposes:

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

The `/api/state` BME280 object keeps canonical hPa fields plus display-oriented fields such as:

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

## Validation before RC4 refresh

Verify on physical T3 V1.6.1 before copying the reviewed develop line into `release/6.4.0-rc4`:

1. BME280 is detected at `0x76` or `0x77` with short, final wiring.
2. Boot without BME280 keeps RF/Web alive and retry progresses 5 s -> 15 s -> 60 s -> 5 min.
3. Reconnect/power BME280 after boot and confirm acquisition on a later retry.
4. Disconnect an online BME280 long enough for six invalid reads, then verify rediscovery/recovery.
5. BAROMETRO diagnostics remain coherent and the full scanner is no longer in that page.
6. **I2C / HW** scanner confirms runtime 100 kHz, BME chip ID `0x60`, and restores 100 kHz after its 400 kHz stress pass.
7. Altitude/unit settings persist and MQTT/COMPATIBLE MB remain canonical hPa.
8. Forecast tile and collapsible BME280/AS3935 panels remain functional on desktop/mobile.
9. Both PlatformIO targets and the same-workspace idempotence build pass.
