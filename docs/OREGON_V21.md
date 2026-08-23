# Oregon Scientific protocol V2.1

This branch adds a bounded V2.1 decoder alongside the existing OSV3 decoders.
It does not replace or relax OSV3 validation.

## Supported sensors

| Sensor code | Known models | Values |
|---|---|---|
| `EC40` | THN132N, THR228N | temperature, channel, battery |
| `1D20` | THGR122NX, THGR228N | temperature, humidity, channel, battery |

Legacy channel values `1`, `2`, `4` are normalized to CH1, CH2, CH3. The
already-supported direct values `1`, `2`, `3` remain accepted.

## Decoder boundaries

- recognizes the alternating 32-bit physical preamble;
- reconstructs and validates every Manchester inverse/original pair;
- accepts only the documented `EC40` and `1D20` lengths;
- verifies the nibble-sum checksum before placing a frame in the RF queue;
- exposes V2.1 preamble, candidate, valid-frame, checksum and pair-error counters
  in `/api/state` under `rf`.

The decoder is intentionally restricted to these two documented sensor families.
Other V2/V2.1 IDs can be added later with a known packet layout, checksum position
and real RF captures.

## Reference vectors

- `AEC4015F07300D30`: EC40, CH1, 3.7 °C, checksum `3D`;
- `A1D20485C480882835`: 1D20, CH3, battery low, -8.4 °C, 28%, checksum `53`.

Run `python scripts/test_oregon_v21.py` to validate framing, checksum and field
positions. These host-side tests do not substitute for reception tests with real
433.92 MHz hardware.

## Sources

- Oregon Scientific RF Protocols IV: <https://www.osengr.org/Articles/OS-RF-Protocols-IV.pdf>
- rtl_433 Oregon decoder: <https://github.com/merbanan/rtl_433/blob/master/src/devices/oregon_scientific.c>
