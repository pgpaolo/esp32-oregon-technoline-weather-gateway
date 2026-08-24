# UVR128 / EC70 V2.1 recovery

This document describes the current UVR128 work carried by `feature/v21-cycle-quality-analyzer`, derived from the SD datalogger and V2.1 quality branches.

## Why UVR128 is special

Oregon Scientific V2.1 transmits every logical bit as an inverted/original pair and repeats the complete message. THGR122NX/THGR228N normally inserts a pause between repetitions; UVR128 does not. Its second V2.1 preamble starts immediately after the first copy.

Reference implementations such as `rtl_433` therefore see a continuous UVR128 V2.1 decoded stream of 148 bits after sync rather than two independently gap-separated messages.

## Firmware strategy

The normal streaming Oregon decoders remain unchanged. The isolated end-of-burst V2.1 recovery accepts only:

- `EC70` / UVR128, checksum position 13 in the internal sync-prefixed buffer;
- `1D20` / THGR122NX-THGR228N, checksum position 16.

Only checksum-valid frames are queued.

The shared raw burst edge buffer is now 672 entries. This preserves the complete no-gap UVR128 double transmission, including the second preamble, when the first copy begins clipped by the SX1278 data slicer. The larger edge buffer costs RAM only, not application Flash.

To compensate its RAM cost, diagnostic history depth is reduced:

- generic burst history: 12 records;
- legacy WGR probe history: 8 records.

## Burst Debug

`BURST DEBUG` is the shared RF diagnostic path for Oregon OSV3, Oregon V2.1 and Technoline. It uses the same bounded raw accumulator required by EC70 recovery; no second EC70-specific raw buffer or second probe decoder is linked.

The former dedicated EC70 passive probe has been removed from the build to recover Flash. For diagnosis use together:

- Decoder RF Oregon counters (`V2.1`, `UVR128 cand/OK`, pair/checksum errors);
- universal Burst Analyzer history (duration, edges, RSSI, timing match and class);
- raw accepted frame table (protocol, decode source, sensor code, RSSI, raw HEX and decoded data).

The WGR-specific probe remains available only as a legacy targeted instrument. Normal all-sensor investigations should start with `BURST DEBUG`.

## Session quality

For `1D20` and `EC70`, valid redundant copies within 1.5 s are counted as copies of the same transmission cycle. They remain visible diagnostically but do not inflate `Rx/Expected`.

## Protocol references used

- Oregon Scientific RF Protocols: V2.1 duplicates each bit and repeats the complete message; UVR128 is the documented example where the second copy follows immediately with no pause.
- `rtl_433` `oregon_scientific.c`: `ID_UVR128 = 0xEC70`, V2.1 UVR128 accepted with a 148-bit decoded message and checksum validation.

## Hardware acceptance

After flashing, verify for at least 30 minutes:

1. `UVR128 cand/OK` begins increasing when the sensor transmits.
2. `1D20` remains cycle-aware and near its observed ~43 s cadence on CH3.
3. WGR800, PCR800, THGN801/THGR810 and UVN800 remain unchanged.
4. RF ring overflow remains zero.
5. parser/checksum drops do not materially increase.
6. With `BURST DEBUG` ON, burst history remains useful for Oregon V2.1/OSV3 and Technoline without changing accepted-frame counts.

Keep the branch/PR in Draft until real UVR128 hardware validates the no-gap double-copy correction.
