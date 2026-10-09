# SRAM optimization — 6.4.0-rc6-mem1

This is a conservative RAM-only overlay of `release/6.4.0-rc6` for the LILYGO
T3 V1.6.1 (ESP32/SX1278) and T3-S3 targets. It intentionally **does not**
change decoder thresholds, protocols, sampling capacity, telemetry schema,
network services, partition layout, OTA logic, or rainfall-history precision.

## Baseline and source-backed results

Measured with `python scripts/test_memory_optimizations.py` using the same
32-bit field alignments for the source structures on the host test. This is a
**static buffer allocation reduction**, not a measured on-device free-heap or
firmware Flash reduction.

| Object (statically allocated) | RC6 before | mem1 after | Saved |
|---|---:|---:|---:|
| RF duration + level FIFO, 4096 entries | 12,288 B | 8,704 B | 3,584 B |
| Web RAW history, 32 entries | 7,168 B | 5,888 B | 1,280 B |
| **Total** | **19,456 B** | **14,592 B** | **4,864 B** |

### RF FIFO (`src/oregon_receiver.cpp`)

* Before: `volatile uint16_t duration[4096]` + `volatile uint8_t level[4096]`.
* Now: same **4096 full 16-bit durations** and 128 x `uint32_t` bitset words
  for the associated levels (one bit per edge).
* ISR writes the bit before advancing the visible head; the foreground
  consumer extracts the corresponding bit before advancing the tail.
* There is no reduction in FIFO depth, duration range (0..65535 us),
  synchronization behavior, or overflow handling. The ISR adds a small amount
  of bit-manipulation work, so real RF timing should still be validated.

### Web RAW history (`src/web_manager.cpp`)

* Before: each of 32 records stored separate `protocol[12]`, `sourceName[16]`
  and `type[16]` text fields in RAM.
* Now: `technoline`, `source` and `typeCode` retain the metadata; their names
  are generated only when serving `/api/raw` or `/api/raw.txt`.
* The JSON field names, original Oregon/Technoline labels, stored decoded
  strings, hex data, and 32-entry history depth are unchanged.

## Protected memory allocations (not modified)

* **Rainfall history:** 2048 x 8 B (16,384 B) in `station_state.cpp`, retaining
  the original full-width millisecond timestamps and floating-point cumulative
  rainfall needed to derive one-hour and 24-hour totals accurately. Aggressive
  sampling/quantization would alter reporting semantics.
* **Remote AdminSensor:** large WebSockets/TLS allocations, JSON requests,
  limited chunk sizes, heap headroom and zero-copy compressed Web UI. Preserved.
* **MicroSD:** queue depth and per-line length, to avoid extra SD write drops.
* **Oregon V2.1 double-copy:** recovery burst capacity preserved; reducing it
  would break the EC70/UVR128 repeated-frame recovery path.

## Verification

Host tests (run before building):

```bash
python scripts/test_memory_optimizations.py
python scripts/test_oregon_v21.py
python scripts/test_mb_compatible_mapping.py
```

The memory test compiles the **actual ISR and FIFO pop functions from the source**
with host GPIO/micros stubs and checks 200,000 randomized producer/consumer
operations, overflow, and 32-bit timer wraparound against the previous data
representation. It also checks the Web RAW metadata conversion routines and
records the exact static allocation sizes. It is integrated in the build CI.

PlatformIO build (requires installed PlatformIO packages and board toolchain):

```bash
pio run -e t3-v161-433
pio run -e t3-s3-433
```

**Important:** the supplied source has passed the host tests, but the full
PlatformIO build and on-device measurements have not been executed in the
analysis environment, which does not have PlatformIO installed. Do not treat
this as a hardware-validated production binary.

After flashing, compare before/after values in `/api/state`:

* `system.heap_free` — currently free heap;
* `system.heap_min_free` — lowest remaining heap since boot;
* `system.rf_overflows` — must remain stable under the same RF load;
* monitor `/api/raw`, `/api/raw.txt`, and remote/dashboard refresh behavior.

Repeat the measurements at similar uptime and with the same MQTT, microSD,
HTTPS and AdminSensor connections. A reduction in static SRAM should increase
headroom, but runtime free-heap gains may differ due to allocator and link
layout. Use the original RC6 firmware image as a rollback reference. The
firmware version is separately identified as `6.4.0-rc6-mem1`.

---

## Nota in italiano

L'ottimizzazione recupera **4.864 byte di SRAM allocata staticamente** rispetto
al sorgente RC6: 3.584 byte dal buffer degli impulsi RF e 1.280 byte dallo
storico dei pacchetti RAW. Sono preservati i 4.096 fronti radio, la durata
originale a 16 bit, i 32 pacchetti dello storico, i decoder Oregon/Technoline,
lo storico delle precipitazioni e le API. Questo dato non equivale a una misura
su ESP32 del nuovo heap disponibile: serve compilare, caricare e misurare la
stessa configurazione hardware e di servizi prima/dopo. **Non pubblicare o
installare direttamente in produzione senza test di ricezione RF e OTA.**
