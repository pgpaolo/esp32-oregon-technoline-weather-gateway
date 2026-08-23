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
- accepts a 16-bit stable tail of that preamble, matching rtl_433 tolerance for
  data-slicer startup clipping, while retaining all downstream validation;
- reconstructs and validates every Manchester inverse/original pair;
- accepts only the listed sensor IDs and their bounded payload through checksum;
- verifies the nibble-sum checksum before placing a frame in the RF queue;
- exposes V2.1 preamble, candidate, valid-frame, checksum and pair-error counters
  in `/api/state` under `rf`.

Session quality excludes sensors not observed after the latest RF mode/gain
reset. Every physical transmitter has its own row, identified by family, sensor
code, channel and rolling code, so OSV3 and V2.1 traffic never shares a received
or expected counter. The same row also exposes the RSSI of its latest valid
frame. Known nominal intervals are used for THN/THGR channels,
WGR, RGR and UV families. A legacy model without a reliable nominal interval is
shown as `CAL`/`LINK` until four valid frames have provided three intervals; the
shortest observed interval then becomes its adaptive session cadence. This keeps
packet-loss percentages explicit without inventing a cadence before evidence is
available.

The UVR128 transmission is longer than its useful measurement payload and sends
two copies without an inter-message pause: 152 bits from the first sync (148
after sync in the rtl_433 convention). Measurement and checksum are already
complete in the first copy, so the live decoder validates and queues its first
8 useful bytes without making reception of the redundant copy mandatory. This
restores the behavior of the initial EC70 implementation and does not enlarge
the 12-byte RF packet buffer. Dedicated candidate and valid-frame counters make
UVR128 reception visible in `/api/state` and Diagnostics. Barometric V2.1
families are deliberately not decoded yet: they
need a pressure data path and real RF captures before being exposed by the UI/API.

## Reference vectors

- `AEC4015F07300D30`: EC40, CH1, 3.7 °C, checksum `3D`;
- `A1D20485C480882835`: 1D20, CH3, battery low, -8.4 °C, 28%, checksum `53`.

The test script also builds deterministic checksum-valid vectors for `1D30`,
`3D00` and `2D10`. Its `EC70` vector includes the complete no-pause UVR128
double message while verifying first-copy acceptance; every vector is also
corrupted to exercise checksum rejection.

Run `python scripts/test_oregon_v21.py` to validate framing, checksum and field
positions. These host-side tests do not substitute for reception tests with real
433.92 MHz hardware.

## Sources

- Oregon Scientific RF Protocols IV: <https://www.osengr.org/Articles/OS-RF-Protocols-IV.pdf>
- Oregon Scientific RF Protocols II: <https://www.osengr.org/WxShield/Downloads/OregonScientific-RF-Protocols-II.pdf>
- rtl_433 Oregon decoder: <https://github.com/merbanan/rtl_433/blob/master/src/devices/oregon_scientific.c>
- HEYU Oregon sensor interval notes: <https://www.gsp.com/cgi-bin/man.cgi?section=5&topic=X10OREGON>
- Oregon UVR128 user manual: <https://usermanual.wiki/Oregon-Scientific/OregonScientificUvr128UsersManual374420.769016158.pdf>
