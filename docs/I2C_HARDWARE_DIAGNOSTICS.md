# I2C and hardware diagnostics

Status: **release/6.4.0-rc4 / 6.4.0-rc4**. These diagnostics have been promoted from the reviewed `develop` solution into the current RC4 branch.

## Purpose

The OLED, optional BME280 and optional AS3935 share one I2C controller. Hardware testing showed that excessive cable length/capacitance can make a BME280 disappear from the bus even when SDA and SCL are both HIGH at idle. The validated normal gateway bus therefore runs conservatively at:

```text
100 kHz
80 ms Wire timeout
```

The full bus scan is **manual only** and lives in:

```text
CONFIGURAZIONE > I2C / HW
```

It does not run periodically and does not add a background Web poll.

## T3 V1.6.1 bus

```text
SDA = GPIO21
SCL = GPIO22
```

Typical devices are:

```text
0x03  AS3935 with the project default address
0x3C  SSD1306 OLED
0x76  BME280 candidate
0x77  BME280 candidate / common Waveshare default
```

The AS3935 uses its configured address; the generic scanner does not probe the I2C general-call address `0x00`.

## Manual scanner

The dedicated page performs, on demand:

1. initial SDA/SCL level check;
2. complete standard 7-bit scan at **100 kHz**, the real runtime speed;
3. Bosch BME280 chip-ID read from register `0xD0` at `0x76` and `0x77`;
4. complete scan at **400 kHz** as a diagnostic margin/stress test only;
5. final SDA/SCL level check;
6. restoration of the normal **100 kHz / 80 ms** bus settings.

Authenticated endpoint:

```text
POST /api/hardware/i2c-scan
```

The BME280 is positively identified when register `0xD0` returns:

```text
0x60
```

### Example: healthy bus

```text
100 kHz (runtime): 0x03, 0x3C, 0x77
400 kHz (stress):  0x03, 0x3C, 0x77
Chip ID 0x76: -- · 0x77: 0x60
SDA/SCL iniziali: 1/1 · finali: 1/1
BME280 confermato dal chip ID Bosch 0x60.
```

### Example: cable/capacitance margin problem

```text
100 kHz (runtime): 0x03, 0x3C, 0x77
400 kHz (stress):  0x03, 0x3C
Chip ID 0x77: 0x60
```

This means the installation is valid at the configured 100 kHz runtime speed but has insufficient margin at 400 kHz. Shorter wiring and appropriate pull-ups are preferred to raising I2C speed.

### No BME280 at either speed

If OLED/AS3935 are visible but neither `0x76` nor `0x77` appears, check the BME280 branch specifically: cable length, connector/crimp, power, common ground, SDA/SCL continuity and breakout address/mode.

### Bus stuck low

If SDA or SCL is LOW before or after the scan, investigate a short, an incorrect pull-up or a peripheral holding the bus.

## Hardware status and MCU temperature

The same configuration page exposes:

- board name;
- I2C SDA/SCL pins and normal bus speed;
- BME280 detected state/address;
- AS3935 enabled/detected state/address;
- ESP32 internal MCU/die temperature when the Arduino core returns a plausible value.

Authenticated endpoint:

```text
GET /api/hardware/info
```

The MCU temperature is also included in `/api/state` as:

```text
system.hardware_temperature_c
```

and is shown in the main **HARDWARE** monitor.

The MCU temperature is **not an ambient temperature sensor**. It reflects die/internal temperature and is useful only as an indicative hardware-health value. If the platform does not return a valid reading, the API sends `null` and the UI displays `N/D`.

## BME280 automatic recovery

The manual scanner is separate from normal BME280 operation. Normal discovery remains lightweight and probes only `0x76`/`0x77` with the non-blocking sequence:

```text
boot -> 5 s -> 15 s -> 60 s -> every 5 min
```

Six consecutive invalid pressure reads cause the BME280 to be marked offline and rediscovery to restart. RF, Web and MQTT are not deliberately blocked while waiting for rediscovery.

## RC4 validation checklist

Before any promotion of RC4 to `main`:

- verify BME280 `0x76` or `0x77` and chip ID `0x60` on physical hardware;
- verify OLED and AS3935 remain visible on the shared 100 kHz bus;
- verify the scanner page is under **CONFIGURAZIONE > I2C / HW**, not BAROMETRO;
- verify the scanner restores 100 kHz after the 400 kHz stress scan;
- verify disconnect/reconnect recovery without reboot;
- verify the MCU temperature field is plausible or cleanly reports `N/D`;
- verify both PlatformIO targets and the same-workspace idempotence build pass.
