# Oregon and Technoline rain accumulation (rain1)

This document complements [the Italian implementation guide](RAIN_ACCUMULATION.md).

Two independent accumulators (Oregon PCR800 family and Technoline WS23xx) compute **increments from each sensor's cumulative radio counter**. The first valid telegram establishes a baseline and does **not** count as new rainfall. Duplicate frames count zero. A transmitter ID change, counter reset, or implausible jump greater than 500 mm establishes a new baseline, counted as `rebases`. Accumulations are per **family** rather than per simultaneous transmitter ID.

Counters include UTC **today, month, year and lifetime**. Without synchronized time, lifetime can still increase, but calendar buckets are not populated. Rain already fallen before the first valid sample and exact allocation of rainfall around offline day boundaries cannot be reconstructed.

## Configure

On the authenticated dashboard choose **CONFIGURAZIONE > microSD**:

1. `Accumula pioggia Oregon in RAM` (enabled by default).
2. `Accumula pioggia Technoline in RAM` (enabled by default).
3. `Salva accumulatori su microSD (ogni 60 s)` (disabled by default).

Persistence additionally requires an enabled microSD logger and a mounted card. Configuration is stored in NVS (`sdlog/r_oreg`, `sdlog/r_tech`, `sdlog/r_sd`). Logging raw CSV RF frames is independently configurable.

The authenticated `GET /api/rain/accumulation` endpoint exposes current counters and persistence diagnostics. Dashboard reads occur when opening the SD panel or pressing the refresh control, not on a new polling timer.

## Crash and SD safety

The logger alternates approximately 112-byte binary checkpoint slots `/weather/rain_a.bin` and `/weather/rain_b.bin`, with sequence numbering and FNV-1a integrity verification. It does not write the card in the RF callback. Changed state is saved at most about once every 60 seconds, also flushed before orderly unmount or deep sleep. Abrupt power loss can lose the most recent uncheckpointed state; readings may recover from the radio counter if the transmitter retains its identity and raw counter. Checkpoints do **not** provide event-level history. Manual SD formatting removes the old checkpoints.

The rain accumulation core is sized at about 48 B per sensor bucket (96 B for both on tested host layout, excluding bookkeeping). This is not a substitute for a target board memory measurement.

## Verify

```sh
g++ -std=c++17 -Wall -Wextra -Werror tests/test_rain_accumulator_core.cpp -o /tmp/test_rain && /tmp/test_rain
pio run -e t3-v161-433
pio run -e t3-s3-433
```

Physical verification on LILYGO T3 with SX1278 and a real microSD is still required, including interrupted power writes and concurrent SPI/radio operation. See [release notes](RELEASE_6.4.0_RC6_STAB1_RAIN1.md).
