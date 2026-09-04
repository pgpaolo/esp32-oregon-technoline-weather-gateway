# BME280 deep I2C diagnostics

Status: **develop / 6.4.0-dev2**.

This diagnostic extension is intended to distinguish a firmware/driver problem from a wiring, power, breakout-mode or sensor fault when the BME280 is not detected at `0x76` or `0x77`.

## What it does

The normal BME280 discovery remains lightweight and probes only `0x76` and `0x77` with the existing non-blocking retry sequence.

A separate **manual** deep scanner is available from **CONFIGURAZIONE > BAROMETRO**. It scans the complete I2C address range at:

- `400 kHz` (normal gateway bus speed);
- `100 kHz` (diagnostic fallback for marginal wiring/breakouts).

The scan is deliberately user-triggered so RF/network operation is not periodically burdened by a full `1..126` address sweep. The I2C clock is restored to `400 kHz` before the request returns.

The scanner also checks whether SDA or SCL is stuck low before/after the scan and reads Bosch register `0xD0` directly at `0x76` and `0x77`. A genuine BME280 returns chip ID:

```text
0x60
```

## Manual scan

The BAROMETRO page includes the button:

```text
Scanner I2C
```

Pressing it calls the existing authenticated Web layer through:

```text
POST /api/barometer/i2c-scan
```

No background polling is added.

The result shows:

- devices visible at 400 kHz;
- devices visible at 100 kHz;
- chip ID read at `0x76` and `0x77`;
- initial/final SDA and SCL levels;
- scan duration;
- a short diagnostic verdict.

## Expected T3 V1.6.1 result

With the current gateway hardware the scanner may show, for example:

```text
400 kHz: 0x03, 0x3C, 0x77
100 kHz: 0x03, 0x3C, 0x77
Chip ID 0x76: -- · 0x77: 0x60
SDA/SCL iniziali: 1/1 · finali: 1/1
BME280 confermato dal chip ID Bosch 0x60.
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
Chip ID 0x76: -- · 0x77: --
```

The shared ESP32 I2C controller and SDA/SCL pins are functioning. Investigate the BME280 branch specifically: power, common ground, connector/crimp, SDA/SCL continuity, breakout mode or failed sensor.

### BME appears only at 100 kHz

This points to a signal-integrity problem rather than an address/driver problem. Check cable length, pull-ups, breadboard/contact quality and breakout wiring.

### 0x76/0x77 ACKs but chip ID is not 0x60

A device is physically present at the address, but it is not identifying as a BME280. Check the actual sensor fitted to the breakout and its datasheet.

### Chip ID 0x60 is present but Adafruit BME280 detection still fails

This is the important firmware/driver case. Capture the BAROMETRO scanner result and serial log before changing hardware; the driver initialization path then needs further investigation.

### SDA or SCL is low

The scanner reports a blocked bus when either line is low before or after the diagnostic. Check shorts, connector orientation, pull-ups and any device holding the bus low.

## Waveshare BME280 breakout note

For the Waveshare `BME280 Environmental Sensor` breakout used during current testing, I2C wiring is:

```text
VCC       -> 3.3 V
GND       -> GND
SDA/MOSI  -> SDA (GPIO21 on T3 V1.6.1)
SCL/SCK   -> SCL (GPIO22 on T3 V1.6.1)
CS        -> NC for I2C on this breakout
ADDR/MISO -> NC for the default address (normally 0x77 on this board)
```

When using an external power supply, the external supply ground and ESP32 ground must be common.

## RC4 validation use

Before backporting this BME280 hardening to `release/6.4.0-rc4`, run the scanner on the physical T3 V1.6.1 and record the exact 400/100 kHz address lists and chip ID. This gives a definitive hardware/firmware boundary for the BME280 test.
