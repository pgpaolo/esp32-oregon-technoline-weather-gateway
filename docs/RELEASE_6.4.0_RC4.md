# 6.4.0-rc4

Release candidate branch:

```text
release/6.4.0-rc4
```

Firmware identity:

```text
6.4.0-rc4
```

This RC4 branch has been fully refreshed from the reviewed `develop` solution at commit:

```text
68c1adc7df3e4e7a56b24b13bc6bdfc80bd247f3
```

The previous `release/6.4.0-rc3` branch remains frozen and unchanged. `main` is not modified by this refresh.

## Main additions compared with RC3

### COMPATIBLE MB

- configurable HTTP/HTTPS realtime publisher;
- dedicated FreeRTOS worker so transmission does not block RF acquisition;
- fixed 192-field compatibility payload;
- configurable endpoint, timeout, TLS mode and CA certificate;
- strict exclusive source selection: Oregon Scientific **or** Technoline / La Crosse, never mixed in one weather-station packet;
- local BME280 values can remain available with either selected source;
- daily-rain baseline handling and runtime transmission diagnostics.

See [MB_COMPATIBLE.md](MB_COMPATIBLE.md).

### Weather Realtime API v1 server adapter

The repository includes the generic server-side adapter under `server/meteobridge/` for normalizing incoming compatibility packets into the canonical `weather-realtime-v1` JSON model. Public examples remain generic and contain no deployment-specific hostnames or station identifiers.

### BME280 barometer and recovery

- runtime station altitude calibration persisted in NVS;
- project default altitude `584 m`;
- sea-level pressure derived from station pressure and configured altitude;
- trend history reset after altitude changes;
- selectable Web display units: `hPa`, `mbar`, `inHg`, `mmHg`, `kPa`;
- internal meteorological and compatibility values remain canonical hPa;
- boot discovery plus non-blocking retry sequence around 5 s, 15 s, 60 s and then every 5 minutes;
- six consecutive invalid pressure reads mark the BME280 offline and restart rediscovery;
- `0x77` preferred, `0x76` retained as supported fallback.

See [BAROMETER_BME280.md](BAROMETER_BME280.md).

### Shared I2C bus hardening

Physical validation identified excessive cable length/capacitance as the cause of intermittent BME280 ACK loss. The reviewed runtime baseline is therefore:

```text
100 kHz
Wire timeout 80 ms
```

OLED, BME280 and AS3935 continue sharing the same I2C controller. Experimental AS3935 address auto-scanning used during diagnosis has been removed; normal startup again uses the configured AS3935 address deterministically.

### Dedicated I2C / hardware diagnostics

The full manual scanner is no longer located inside BAROMETRO. It is now available under:

```text
CONFIGURAZIONE > I2C / HW
```

The page exposes:

- configured SDA/SCL pins and runtime bus speed;
- BME280 state/address;
- AS3935 state/address;
- ESP32 internal MCU/die temperature when available;
- manual standard 7-bit scan at 100 kHz;
- Bosch BME280 chip-ID check at `0x76` / `0x77`;
- manual 400 kHz stress/margin scan;
- automatic restore to 100 kHz / 80 ms after the diagnostic.

The MCU temperature is diagnostic die temperature only, not ambient temperature.

See [I2C_HARDWARE_DIAGNOSTICS.md](I2C_HARDWARE_DIAGNOSTICS.md).

### WMR200-style forecast presentation

RC4 provides WMR200-style forecast categories from sea-level pressure, 3-hour pressure trend and outdoor temperature where required. The Oregon protocol exposes the forecast result/category but not the proprietary internal forecast formula, so this is intentionally described as a compatible presentation rather than an exact clone.

### Dashboard compaction

- BME280 detailed panel collapsed by default;
- AS3935 detailed panel collapsed by default;
- click panel title to expand/collapse details;
- compact lightning counter remains visible;
- larger forecast tile beside the gateway title;
- responsive layout for narrow screens.

### Existing RC3 baseline retained

RC4 keeps the validated RF/platform baseline, including Oregon OSV2.1/OSV3 + Technoline WS23xx reception, UVR128/EC70 recovery, Oregon CH1-CH3, multi-UV presentation, PCR800 rain-rate correction, Technoline derived rain values, MQTT/TLS, Web auth/provisioning/OTA, SdFat microSD logging, OLED pages and AS3935 integration.

## Validation reference for this RC4 refresh

The exact `develop` source promoted into this RC4 refresh completed successfully:

- Validate #192: **success**;
- PlatformIO Build #268: **success**;
- PCR800 rain-rate regression: **success**;
- Oregon V2.1 vectors: **success**;
- COMPATIBLE MB mapping: **success**;
- `t3-v161-433` build: **success**;
- `t3-s3-433` build: **success**;
- same-workspace rebuild/idempotence check: **success**;
- generated I2C/HW integration guard: **success**;
- physical firmware-size guard: **success**.

The release branch must pass its own RC4 CI after the version/documentation promotion commits before any merge to `main` is considered.

## Branch policy

- `main` remains stable/production;
- `release/6.4.0-rc4` is the current release candidate;
- `release/6.4.0-rc3` remains frozen;
- `develop` remains the next-development line.

PR #22 remains intentionally draft. No automatic merge to `main` is performed by this RC4 refresh.
