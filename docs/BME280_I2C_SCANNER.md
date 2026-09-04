# BME280 manual I2C deep scanner

Status: **develop / 6.4.0-dev2**.

This diagnostic is intended for hardware validation when the local BME280 is not detected at `0x76` or `0x77`.

## Web UI

Open:

```text
CONFIGURAZIONE > BAROMETRO
```

and press:

```text
Scanner I2C
```

The scan is manual and authenticated. It does not add a background poll and is not run continuously, so the normal RF/network loop is not burdened by repeated full-bus scans.

## What the scanner does

On demand it:

1. checks whether SDA or SCL is already electrically low;
2. scans all standard 7-bit I2C addresses `0x01..0x7E` at `400 kHz`;
3. repeats the full scan at `100 kHz`;
4. reads Bosch register `0xD0` at `0x76` and `0x77`;
5. recognizes a BME280 only when the chip ID is `0x60`;
6. restores the normal gateway I2C speed to `400 kHz` before returning.

The OLED, AS3935 and BME280 share the same I2C bus. On the LILYGO T3 V1.6.1 the configured pins are:

```text
SDA = GPIO21
SCL = GPIO22
```

Typical expected devices are:

```text
0x03  AS3935
0x3C  OLED
0x76  BME280 candidate
0x77  BME280 candidate
```

The actual list depends on the hardware connected to the gateway.

## Interpretation

### BME280 confirmed

Example:

```text
400 kHz: 0x03, 0x3C, 0x77
100 kHz: 0x03, 0x3C, 0x77
Chip ID 0x76: -- · 0x77: 0x60
BME280 confirmed
```

This confirms both I2C visibility and the Bosch BME280 chip ID.

### Visible only at 100 kHz

If `0x76` or `0x77` appears at `100 kHz` but not at `400 kHz`, inspect cable length, connector quality and pull-up strength. The diagnostic does not permanently switch the gateway to 100 kHz; it restores 400 kHz after the test.

### Address ACKs but chip ID is not 0x60

The device is electrically present, but it is not being identified as a BME280 by its Bosch chip-ID register. The raw chip ID is shown instead of silently accepting the device.

### No 0x76 / 0x77, while OLED and AS3935 appear

If `0x03` and/or `0x3C` are visible but neither BME280 address is present at either speed, the ESP32 I2C controller and shared bus are operating. Investigation should then focus on the BME280 breakout, power, common ground, SDA/SCL routing, connector continuity and breakout mode/address wiring.

### Bus stuck

If SDA or SCL is already low while the bus should be idle, the firmware avoids the full 126-address iteration. Check for a shorted line, missing/incorrect pull-up, wiring error or a peripheral holding the bus low.

## API

Authenticated endpoint:

```text
POST /api/barometer/i2c-scan
```

The JSON response includes:

```text
sda
scl
sda_initial
scl_initial
sda_final
scl_final
bus_stuck_initial
bus_stuck_final
devices_400khz
count_400khz
devices_100khz
count_100khz
chip_id_0x76
chip_id_0x77
bme280_0x76
bme280_0x77
duration_ms
```

This diagnostic is intended for development/hardware validation before backporting the BME280 hardening to `release/6.4.0-rc4`.
