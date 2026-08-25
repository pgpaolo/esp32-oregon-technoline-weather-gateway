# microSD datalogger

Development branch:

```text
codex/sdfat-write-status
```

This branch is derived from `feature/v21-cycle-quality-analyzer` and keeps the RF decoders unchanged. The microSD path is an output layer only. Mount and format have been confirmed on the physical T3 V1.6.1 setup.

## Hardware pinout

Official LILYGO mappings used by the branch:

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

The branch uses Greiman **SdFat 2.3.1**, not the Arduino-ESP32 `SD` wrapper. Hardware diagnostics showed that the card entered SPI idle state (`CMD0 = 0x01`) while the previous `SD.begin()` path still failed later in initialization. Reformatting could not solve that state because the old formatter never obtained a usable block device.

The current sequence is deliberately bounded:

1. CS is driven high while the official LILYGO SCK/MISO/MOSI pins are configured.
2. SdFat tries shared HSPI at 4 MHz.
3. After a complete bus cleanup, one 400 kHz fallback is attempted for slow or marginal cards.
4. `sdErrorCode` and `sdErrorData` are retained for Web diagnostics.
5. When the card transport is ready but FAT is absent/invalid, the explicit format action calls the SdFat formatter and performs a clean remount.

Formatting is never attempted when the card transport itself has not initialized.

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

Initial branch support:

- Oregon: every checksum-valid decoded frame;
- Technoline / La Crosse WS23xx: every accepted frame;
- BME280: periodic snapshot;
- AS3935: periodic snapshot.

Each source can be enabled or disabled from the Web configuration independently.

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

Endpoints on this branch:

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
- explicit remount action.
- explicit destructive FAT format action with two Web confirmations;
- negotiated SPI frequency and SdFat error code/data.

The top header contains a compact status badge refreshed every four seconds:

| Badge | Meaning |
|---|---|
| `SD OFF` | datalogger disabled; the optional card is not mounted |
| `SD PRONTA` | card mounted, datalogger disabled |
| `SD ON` | card mounted and datalogger enabled |
| `SD SCRIVE` | cumulative written-record counter increased since the previous poll |
| `SD KO` | datalogger enabled but mount failed |
| `SD ERR` | Web status request failed |

The badge tooltip reports written records, queue depth, errors and current file. The polling reads existing counters only and does not write NVS or touch the RF decoder.

Configuration is stored in the dedicated NVS namespace `sdlog` and is only rewritten when values actually change.

## Queue and write policy

Current defaults:

- 16 fixed-size RAM slots;
- no dynamic telemetry history;
- SD service period: 750 ms;
- maximum six records per write batch;
- capacity refresh every 30 s.

If the queue becomes full, new records are dropped and the counter is exposed to the UI rather than blocking the RF path.

## Power management

Before deep sleep the logger attempts to drain the pending queue, closes the filesystem and ends the dedicated SPI bus.

## Hardware test checklist

1. Boot with no card: gateway must remain fully functional.
2. Insert a FAT/FAT32 card and press `Rimonta scheda`.
3. Verify mount status and reported capacity.
4. Confirm `/weather/...csv` creation.
5. Check Oregon and Technoline rows while all RF decoders remain stable.
6. Verify `dropped=0`, `write_errors=0` and RF ring overflow remains unchanged.
7. Disconnect Wi-Fi/NTP after sync and confirm logging continues.
8. Test deep-sleep shutdown with pending records.
9. Test a full/read-only/bad card and confirm fail-safe behavior.
10. With an invalid/blank card press `FORMATTA SD`, confirm both prompts and verify automatic remount.
11. Verify the top badge changes from `SD ON` to `SD SCRIVE` after a CSV append.
12. Hover the badge and verify write count, queue, errors and current file.

## Current status

Mount and format are hardware-confirmed on T3 V1.6.1. Both PlatformIO targets build successfully and the Oregon V2.1 host vectors remain green. Long-duration RF + microSD concurrency, full/read-only-card handling and deep-sleep draining remain checklist items rather than claimed hardware proof.

Current build reference with `min_spiffs.csv`:

| Target | RAM | Application | Slot use |
|---|---:|---:|---:|
| T3 V1.6.1 | 100,592 / 327,680 B | 1,276,881 / 1,966,080 B | 64.9% |
| T3-S3 | 99,552 / 327,680 B | 1,220,809 / 1,966,080 B | 62.1% |

`min_spiffs.csv` is appropriate because the Web UI is embedded and the project does not use SPIFFS. NVS and two OTA application slots remain available.
