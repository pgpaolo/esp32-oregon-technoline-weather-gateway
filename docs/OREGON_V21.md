# Oregon Scientific protocol V2.1

This branch adds a bounded V2.1 decoder alongside the existing OSV3 decoders.
It does not replace or relax OSV3 validation.

## Supported sensors

| Sensor code | Known models | Values |
|---|---|---|
| `EC40` | THN132N, THR228N | temperature, channel, battery |
| `1D20` | THGR122NX, THGR228N | temperature, humidity, channel, battery |
| `1D30` | THGR968, THGN500 | temperature, humidity, channel, battery |
| `3D00` | WGR968 | average/gust wind speed, direction, battery |
| `2D10` | RGR968 | rainfall rate, total rainfall, battery |
| `EC70` | UVR128 | UV index, battery |

Legacy channel values `1`, `2`, `4` are normalized to CH1, CH2, CH3. The
already-supported direct values `1`, `2`, `3` remain accepted.

## Decoder boundaries

- recognizes the alternating 32-bit physical preamble;
- reconstructs and validates every Manchester inverse/original pair;
- accepts only the listed sensor IDs and their bounded payload through checksum;
- verifies the nibble-sum checksum before placing a frame in the RF queue;
- exposes V2.1 preamble, candidate, valid-frame, checksum and pair-error counters
  in `/api/state` under `rf`.

The UVR128 transmission is longer than its useful measurement payload. The decoder
stops after the validated checksum, so supporting it does not enlarge the 12-byte
RF packet buffer. Barometric V2.1 families are deliberately not decoded yet: they
need a pressure data path and real RF captures before being exposed by the UI/API.

## Reference vectors

- `AEC4015F07300D30`: EC40, CH1, 3.7 °C, checksum `3D`;
- `A1D20485C480882835`: 1D20, CH3, battery low, -8.4 °C, 28%, checksum `53`.

The test script also builds deterministic checksum-valid vectors for `1D30`,
`3D00`, `2D10` and `EC70`, then corrupts each one to exercise rejection.

Run `python scripts/test_oregon_v21.py` to validate framing, checksum and field
positions. These host-side tests do not substitute for reception tests with real
433.92 MHz hardware.

## Sources

- Oregon Scientific RF Protocols IV: <https://www.osengr.org/Articles/OS-RF-Protocols-IV.pdf>
- rtl_433 Oregon decoder: <https://github.com/merbanan/rtl_433/blob/master/src/devices/oregon_scientific.c>
