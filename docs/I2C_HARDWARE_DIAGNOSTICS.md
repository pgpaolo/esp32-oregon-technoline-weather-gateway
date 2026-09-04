# BME280 / I2C hardware diagnostics

This document describes the selective BME280/I2C reliability hotfix prepared for `main`.
It does **not** import the other features under development for v6.4.0-rc4.

## Why this hotfix exists

Hardware testing on the LILYGO T3 V1.6.1 showed that excessive I2C cable length/capacitance can make a BME280 disappear from the bus even while SDA and SCL remain high at idle. Shortening the wiring restored normal BME280 operation.

The firmware therefore keeps the shared OLED/BME280 bus at the more conservative settings already validated on the hardware:

- SDA/SCL from `board_config.h` (GPIO21/GPIO22 on T3 V1.6.1)
- runtime clock: **100 kHz**
- Wire timeout: **80 ms**
- BME280 preferred address: **0x77**
- fallback address: **0x76**

The 400 kHz mode is used only by the manual diagnostic scanner as a stress comparison. The scanner always restores 100 kHz / 80 ms before returning.

## Detection and recovery

BME280 discovery is non-blocking. After a failed discovery the retry schedule is:

1. 5 seconds
2. 15 seconds
3. 60 seconds
4. every 5 minutes thereafter

The normal RF/Web loop is never held by a retry delay.

If a previously working BME280 returns six consecutive invalid pressure reads, it is marked offline and rediscovery starts again. Existing pressure/indoor values are invalidated so stale sensor data is not presented as current.

## CONFIGURAZIONE > I2C / HW

The hotfix adds a dedicated diagnostic page with:

- runtime SDA/SCL pins
- runtime I2C clock and timeout
- BME280 detection/address state
- 0x76/0x77 ACK state and retry counters
- OLED expected address (0x3C)
- ESP32 internal die temperature, when supported by the selected core
- manual I2C scanner

The scanner performs:

- full address scan at 100 kHz
- comparison scan at 400 kHz
- SDA/SCL idle-state capture before and after the test
- direct Bosch chip-ID read from register `0xD0` at 0x76 and 0x77

A genuine BME280 normally reports chip ID **0x60**. A device may ACK at 0x76/0x77 without being a BME280, so the chip-ID check is intentionally separate from the address scan.

## ESP32 temperature

`temperatureRead()` is exposed as `system.hardware_temperature_c` and shown in HARDWARE and I2C / HW. It is the ESP32 **die/internal temperature** and must not be interpreted as ambient temperature.

If the core cannot supply a finite value, the API returns `null` and the UI shows `N/D`.

## Scope of the main hotfix

The branch intentionally does not import unrelated RC4 subsystems such as AS3935 integration or COMPATIBLE MB. The scope is limited to BME280/I2C robustness and the diagnostics needed to verify that hardware path.

Before merging to `main`, both PlatformIO targets must compile twice in the same workspace and the generated integration guard must pass after both builds.
