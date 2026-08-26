# microSD datalogger

Release candidate:

```text
release/6.4.0-rc3
```

The microSD path is an output layer only and does not change the RF decoder architecture. Mount and explicit FAT format have been confirmed on the physical T3 V1.6.1 setup.

## Hardware pinout

Official LILYGO mappings used by the firmware:

### T3 / LoRa32 V1.6.1

| Signal | GPIO |
|---|---:|
| SD MOSI | 15 |
| SD MISO | 2 |
| SD SCLK | 14 |
| SD CS | 13 |

### T3-S3 V1.2/V1.3

| Signal | GPIO |
|---|---:|
| SD MOSI | 11 |
| SD MISO | 2 |
| SD SCLK | 14 |
| SD CS | 13 |

The SD card uses a dedicated `SPIClass(HSPI)` path. SX1278 keeps its existing radio SPI pins.

## SdFat backend and initialization

The release uses Greiman **SdFat 2.3.1**, not the Arduino-ESP32 `SD` wrapper. Hardware diagnostics showed that the card entered SPI idle state (`CMD0 = 0x01`) while the previous `SD.begin()` path could still fail later in initialization.

The current mount sequence is deliberately bounded:

1. CS is driven high while the official LILYGO SCK/MISO/MOSI pins are configured.
2. SdFat tries shared HSPI at 4 MHz.
3. After a complete bus cleanup, one 400 kHz fallback is attempted for slow or marginal cards.
4. `sdErrorCode` and `sdErrorData` are retained for Web diagnostics.
5. When card transport is ready but FAT is absent/invalid, only the explicit format action invokes the SdFat formatter and then performs a clean remount.

Formatting is never attempted automatically and is never attempted when the card transport itself has not initialized.

## Automatic mount and retry

If the datalogger is enabled in NVS, boot automatically attempts to mount the card. RF acquisition does not wait for a successful mount.

When mount fails, the firmware schedules non-blocking retries approximately as follows:

```text
1st retry:  5 s
2nd retry: 15 s
3rd retry: 60 s
then:      every 300 s
```

A successful remount clears the retry sequence. An explicit Web remount failure also schedules the retry mechanism instead of leaving the logger permanently stopped.

No automatic FAT format is ever performed by this retry logic.

## Safety rule

The RF decoder never writes to the filesystem.

```text
valid RF frame
     |
     v
small RAM queue
     |
     +----> RF loop continues immediately
     |
     v
SD service outside critical RF path
     |
     v
CSV append batch
```

After SD service the main loop performs another `serviceOregonReceiver()` pass so edges captured while the filesystem was busy are drained promptly.

If the card is missing, full, damaged or cannot be mounted, Oregon/Technoline reception, Web, MQTT and OLED continue to operate.

## Data sources

Supported logger sources:

- Oregon: every checksum-valid decoded frame;
- Technoline / La Crosse WS23xx: every accepted frame;
- BME280: periodic snapshot;
- AS3935: periodic snapshot.

Each source can be enabled or disabled independently from Web configuration.

## CSV layout

One universal CSV schema is used so different sensor families can coexist in the same daily file.

Main fields include:

- UTC timestamp;
- uptime / received timestamp;
- source and protocol;
- decoded type and model;
- Oregon sensor code, channel and rolling ID;
- RSSI and battery status;
- temperature / humidity;
- wind average / gust / direction;
- rain total / rate;
- UV index;
- BME280 pressure fields;
- AS3935 distance / energy / count;
- Technoline sensor ID / next-update;
- compact RAW payload.

Unused columns remain empty rather than inventing values.

## File organization

Once NTP is synchronized the logger writes UTC daily files:

```text
/weather/YYYY/MM/YYYY-MM-DD.csv
```

Before valid UTC time is available it uses:

```text
/weather/unsynced.csv
```

This avoids assigning a false date to frames received immediately after boot.

## Web/API

Endpoints:

```text
GET  /api/sd
POST /api/sd
POST /api/sd/reset
POST /api/sd/remount
POST /api/sd/format
```

The Web configuration exposes:

- datalogger enable;
- Oregon logging;
- Technoline logging;
- BME280 snapshots;
- AS3935 snapshots;
- snapshot interval 30..3600 s;
- mount state;
- card size / used bytes;
- current file;
- queue depth, dropped records and write errors;
- UTC/NTP synchronization state;
- explicit remount action;
- explicit destructive FAT format action with Web confirmation;
- negotiated SPI frequency and SdFat error code/data;
- automatic retry pending state and time to next retry.

`GET /api/sd` exposes retry information including:

```text
retry_pending
retry_in_ms
```

## Header badge

The top header contains a compact status badge refreshed periodically:

| Badge | Meaning |
|---|---|
| `SD OFF` | datalogger disabled; optional card not active |
| `SD PRONTA` | card mounted, datalogger disabled |
| `SD ATTESA` | logger enabled, card not mounted, automatic retry scheduled |
| `SD ON` | card mounted and datalogger enabled |
| `SD SCRIVE` | cumulative written-record counter increased since previous poll |
| `SD KO` | mount/write failure without a normal ready state |
| `SD ERR` | Web status request failed |

The badge tooltip reports written records, queue depth, errors, current file and retry information. Polling reads existing counters only and does not write NVS or touch the RF decoder.

Configuration is stored in the dedicated NVS namespace `sdlog` and is only rewritten when values actually change.

## Queue and write policy

Current defaults:

- 16 fixed-size RAM slots;
- no dynamic telemetry history;
- SD service period: 750 ms;
- maximum six records per write batch;
- capacity refresh every 30 s.

If the queue becomes full, new records are dropped and the counter is exposed to the UI rather than blocking the RF path.

## OTA interaction

Before Web OTA starts, the logger flushes/closes the filesystem and ends the SD bus cleanly.

If the OTA upload fails and the logger is configured as enabled, the firmware attempts to remount the card. A successful OTA reboots normally into the new firmware.

## Power management

Before deep sleep the logger attempts to drain the pending queue, closes the filesystem and ends the dedicated SPI bus.

## Hardware test checklist

1. Boot with no card: gateway must remain fully functional.
2. With datalogger enabled and no card, verify `SD ATTESA` and automatic retry scheduling.
3. Insert a FAT/FAT32 card and allow retry or press `Rimonta scheda`.
4. Verify mount status and reported capacity.
5. Confirm `/weather/...csv` creation.
6. Check Oregon and Technoline rows while all RF decoders remain stable.
7. Verify `dropped=0`, `write_errors=0` and RF ring overflow remains unchanged.
8. Disconnect Wi-Fi/NTP after sync and confirm logging continues.
9. Test deep-sleep shutdown with pending records.
10. Test a full/read-only/bad card and confirm fail-safe behavior.
11. With an invalid/blank card press `FORMATTA SD`, confirm the prompt and verify remount.
12. Verify the top badge changes from `SD ON` to `SD SCRIVE` after a CSV append.
13. Simulate a failed mount and verify retry progression 5 s / 15 s / 60 s / 300 s.
14. Test an OTA failure path and confirm the enabled SD logger can be remounted.

## Current status

Mount and explicit format are hardware-confirmed on T3 V1.6.1. Both PlatformIO targets build in CI and Oregon V2.1/PCR800 host vectors are checked automatically. Long-duration RF + microSD concurrency, full/read-only-card handling and deep-sleep/OTA edge cases remain appropriate hardware-validation items rather than claimed proof.

The project uses `min_spiffs.csv`, keeping NVS and two OTA application slots of `0x1E0000` bytes (`1,966,080` bytes) each. The Web UI is embedded and the project does not depend on SPIFFS.
