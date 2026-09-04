# BME280 deep I2C diagnostics

Status: **develop / 6.4.0-dev2**.

This diagnostic extension is intended to distinguish a firmware/driver problem from a wiring, power, breakout-mode or sensor fault when the BME280 is not detected at `0x76` or `0x77`.

## What it does

The normal BME280 discovery remains lightweight and probes only `0x76` and `0x77` with the existing retry sequence.

When the first boot discovery fails, the gateway performs one cached deep scan of the complete I2C address range at:

- `400 kHz` (normal gateway bus speed);
- `100 kHz` (diagnostic fallback for marginal wiring/breakouts).

The bus clock is restored to `400 kHz` immediately after the scan so OLED and AS3935 operation are unchanged.

The deep diagnostic also reads Bosch register `0xD0` directly at `0x76` and `0x77`. A genuine BME280 returns chip ID:

```text
0x60
```

The scan results are cached in RAM and exposed in **CONFIGURAZIONE > BAROMETRO**.

## Manual scan

The BAROMETRO page includes a button:

```text
Scansione I2C completa
```

Pressing it reruns the complete `400 kHz + 100 kHz` scan and the `0xD0` chip-ID probe through the existing authenticated endpoint:

```text
GET /api/barometer/config?deep_scan=1
```

No new public route and no background HTTP polling are added.

## Expected T3 V1.6.1 result

With the current gateway hardware the scan may show, for example:

```text
Scan 400 kHz: 0x03, 0x3C, 0x77
Scan 100 kHz: 0x03, 0x3C, 0x77
CHIP_ID 0xD0 · 0x77: 0x60 @400k / 0x60 @100k
```

Typical addresses in this project are:

- `0x03` = AS3935 (default project configuration);
- `0x3C` = OLED;
- `0x76` or `0x77` = BME280.

## Diagnostic interpretation

### OLED/AS3935 visible, no 0x76/0x77 at either speed

Example:

```text
400 kHz: 0x03, 0x3C
100 kHz: 0x03, 0x3C
0x76/0x77 CHIP_ID: --
```

The shared ESP32 I2C controller and SDA/SCL pins are functioning. Investigate the BME280 branch specifically: power, common ground, connector/crimp, SDA/SCL continuity, breakout mode or failed sensor.

### BME appears only at 100 kHz

This points to a signal-integrity problem rather than an address/driver problem. Check cable length, pull-ups, breadboard/contact quality and breakout wiring.

### 0x76/0x77 ACKs but chip ID is not 0x60

A device is physically present at the address, but it is not identifying as a BME280. Check the actual sensor fitted to the breakout and its datasheet.

### Chip ID 0x60 is present but Adafruit BME280 detection still fails

This is the important firmware/driver case. Capture the serial log and BAROMETRO diagnostic output before changing hardware; the driver initialization path then needs further investigation.

## Waveshare BME280 breakout note

For the Waveshare `BME280 Environmental Sensor` breakout used during current testing, I2C wiring is:

```text
VCC      -> 3.3 V
GND      -> GND
SDA/MOSI -> SDA (GPIO21 on T3 V1.6.1)
SCL/SCK  -> SCL (GPIO22 on T3 V1.6.1)
CS       -> NC for I2C on this breakout
ADDR/MISO-> NC for the default address (normally 0x77 on this board)
```

When using an external power supply, the external supply ground and ESP32 ground must be common.

## Serial diagnostics

A deep scan also prints concise serial output:

```text
[I2C-DEEP] 400k: 0x03 0x3C 0x77 | 100k: 0x03 0x3C 0x77
[I2C-DEEP] CHIP_ID 0x76 400k=-- 0x77 400k=60 0x76 100k=-- 0x77 100k=60
```

These lines are useful for hardware validation before the BME280 hardening is backported to `release/6.4.0-rc4`.
