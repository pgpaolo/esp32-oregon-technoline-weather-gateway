# Develop notes toward 6.4.0-rc4

This document tracks the changes currently under validation on `develop` that are intended for a future `release/6.4.0-rc4` branch.

The existing `release/6.4.0-rc3` line remains frozen and must not be rewritten. RC4 should be created from a validated `develop` commit after hardware checks.

## Current develop feature set

### COMPATIBLE MB

- dedicated HTTP/HTTPS worker task;
- strict single-station source selection: Oregon **or** Technoline, never mixed in one packet;
- BME280 remains gateway-local and can be included with either selected weather-station source;
- fixed 192-field compatibility payload;
- configurable endpoint, TLS mode and CA;
- server-side Weather Realtime API v1 normalization documented separately.

See [MB_COMPATIBLE.md](MB_COMPATIBLE.md).

### BME280 / barometer

- station altitude configurable at runtime and persisted in NVS;
- default project altitude remains `584 m`;
- sea-level pressure recalculated from BME280 station pressure and configured altitude;
- trend history reset after altitude changes;
- selectable Web display units: hPa, mbar, inHg, mmHg, kPa;
- canonical internal/API compatibility values remain in hPa;
- WMR200-style forecast categories based on sea-level pressure, 3-hour trend and outdoor temperature when needed;
- detailed BME280 panel collapsed by default;
- larger forecast tile beside the gateway title with icon, category, pressure and trend arrow.

See [BAROMETER_BME280.md](BAROMETER_BME280.md).

### AS3935 dashboard compaction

- detailed AS3935 panel collapsed by default;
- click on panel title expands/collapses full diagnostics;
- compact header lightning counter remains visible;
- no additional polling is introduced for the compact status.

## Web UI behavior

The intended Dashboard hierarchy is:

```text
Gateway title                      [large forecast tile]
RF | Wi-Fi | MQTT | lightning | OLED | power/restart

Oregon Scientific                  [expanded]
Technoline / La Crosse             [expanded]
BME280                              [collapsed]
AS3935                              [collapsed]
```

The larger forecast tile deliberately replaces the need to keep the old tiny pressure pill visible. The compatibility pill remains in the generated DOM but is hidden so the historical build-time patch chain remains idempotent on repeated PlatformIO builds.

## Validation gates before RC4

RC4 must not be created only because CI is green. Before branching `release/6.4.0-rc4`, validate:

- T3 V1.6.1 physical BME280 readings and altitude calibration;
- pressure unit switching and persistence;
- forecast tile on desktop and mobile;
- pressure/trend behavior after reboot and altitude changes;
- AS3935 collapsed panel and lightning counter;
- COMPATIBLE MB live receiver integration;
- OTA artifact installation on the intended board;
- second PlatformIO build in the same workspace to preserve patch idempotence.

## Versioning policy

Until RC4 is explicitly created, `develop` remains identified as `6.4.0-dev2` by PlatformIO build flags. `release/6.4.0-rc3` stays unchanged.
