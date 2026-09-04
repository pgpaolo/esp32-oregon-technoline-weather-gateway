# Develop review notes applied to 6.4.0-rc4

The reviewed `develop` delta has now been fully applied to `release/6.4.0-rc4` from commit:

```text
68c1adc7df3e4e7a56b24b13bc6bdfc80bd247f3
```

`release/6.4.0-rc3` remains frozen. `develop` continues as the next-development line with its own `6.4.0-dev2` identity, while RC4 uses firmware identity `6.4.0-rc4`.

## Baseline represented by RC4

### COMPATIBLE MB

- dedicated HTTP/HTTPS worker task;
- strict single-station source selection: Oregon **or** Technoline, never mixed inside one packet;
- BME280 remains gateway-local and can be included with either selected weather source;
- fixed 192-field compatibility payload;
- configurable endpoint, TLS mode and CA;
- server-side Weather Realtime API v1 normalization reference implementation.

See [MB_COMPATIBLE.md](MB_COMPATIBLE.md).

### Barometer / presentation

- runtime station altitude persisted in NVS;
- default project altitude 584 m;
- selectable Web pressure units;
- canonical internal/compatibility values remain hPa;
- WMR200-style forecast categories;
- BME280 and AS3935 detailed panels collapsed by default;
- larger title forecast tile with category, pressure and trend.

See [BAROMETER_BME280.md](BAROMETER_BME280.md).

## Reviewed hardening now included in RC4

### BME280 detection/recovery

- discovery at boot plus non-blocking retries after approximately 5 s, 15 s, 60 s and then every 5 minutes;
- latest ACK state retained separately for `0x76` and `0x77`;
- six consecutive invalid pressure readings mark the sensor offline and restart discovery;
- BME280 `0x77` is preferred while `0x76` remains supported.

### Shared I2C bus

Physical testing identified **excessive I2C cable length/capacitance** as the real cause of the lost BME280 ACKs. It was not a BME280 driver failure.

The RC4 runtime baseline is:

```text
100 kHz
Wire timeout 80 ms
```

OLED, BME280 and AS3935 continue sharing the same controller. Experimental AS3935 address auto-scanning used during diagnosis has been removed; normal boot again uses the configured AS3935 address deterministically.

### Dedicated I2C / hardware page

The full manual scanner is no longer part of BAROMETRO. It is placed under:

```text
CONFIGURAZIONE > I2C / HW
```

The page provides:

- normal SDA/SCL pin and runtime-speed information;
- BME280 detected state/address;
- AS3935 enabled/detected state/address;
- ESP32 internal MCU/die temperature when available;
- manual standard 7-bit scan at 100 kHz;
- Bosch BME280 chip-ID check at `0x76/0x77`;
- manual 400 kHz stress/margin scan;
- guaranteed restore to 100 kHz / 80 ms after the diagnostic.

The MCU temperature is hardware/die temperature only and is not presented as ambient temperature.

See [I2C_HARDWARE_DIAGNOSTICS.md](I2C_HARDWARE_DIAGNOSTICS.md).

## Web UI hierarchy

```text
Gateway title                      [large forecast tile]
RF | Wi-Fi | MQTT | lightning | SD | OLED | power/restart

Oregon Scientific                  [expanded]
Technoline / La Crosse             [expanded]
BME280                              [collapsed]
AS3935                              [collapsed]

CONFIGURAZIONE:
RETE / WI-FI | OREGON | MQTT / TLS | DISPLAY | BAROMETRO | I2C / HW | ...
```

BAROMETRO remains focused on meteorological configuration and BME-specific retry/ACK state. Full bus diagnostics belong to I2C/HW.

## Validation reference

The promoted `develop` commit passed:

- repository validation;
- PCR800 rain-rate regression;
- Oregon V2.1 host vectors;
- COMPATIBLE MB mapping test;
- T3 V1.6.1 build;
- T3-S3 build;
- second T3 V1.6.1 build in the same workspace;
- generated I2C/HW integration guard;
- physical `firmware.bin` size check.

The current RC4 branch must pass the same release-branch CI after the RC4 identity/documentation commits.

## Physical validation before main

- BME280 detected with final short wiring and chip ID `0x60`;
- OLED and AS3935 stable on the shared 100 kHz bus;
- BME280 disconnect/reconnect recovery without reboot;
- altitude and pressure-unit persistence;
- forecast tile desktop/mobile behavior;
- I2C/HW page and manual scanner behavior;
- scanner restores 100 kHz after the stress test;
- MCU temperature plausible or cleanly shown as `N/D`;
- RF reception, MQTT, Web authentication/OTA, microSD and display behavior unaffected.

RC4 remains unmerged into `main` until an explicit final release decision.
