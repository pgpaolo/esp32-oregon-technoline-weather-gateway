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
- accepts a shortened stable tail of that preamble while retaining downstream validation;
- reconstructs and validates every Manchester inverse/original pair;
- accepts only the listed sensor IDs and their bounded payload through checksum;
- verifies the nibble-sum checksum before placing a frame in the RF queue;
- exposes V2.1 preamble, candidate, valid-frame, checksum and pair-error counters
  in `/api/state` under `rf`.

Session quality excludes sensors not observed after the latest RF mode/gain
reset. Every physical transmitter has its own row, identified by family, sensor
code, channel and rolling code, so OSV3 and V2.1 traffic never shares a received
or expected counter. The same row also exposes the RSSI of its latest valid
frame.

The UVR128 transmission is longer than its useful measurement payload and sends
two copies without an inter-message pause. Measurement and checksum are already
complete in the first useful copy. Real SX1278 direct-mode captures can lose the
exact initial phase/sync even when other V2.1 sensors decode normally, so the
UVR128 recovery branch also scans the stored end-of-burst intervals across
possible start positions and both physical polarities. This fallback is bounded
to sensor code `EC70` and still requires valid inverse/original pairs and the
V2.1 checksum before a packet can enter the normal RF queue. OSV3, Technoline
and the normal V2.1 streaming decoder are not changed by this recovery path.

Hardware validation with a real UVR128 remains required before this recovery is
merged into the legacy V2.1 branch. The isolated CI runner is used only to apply
and compile the recovery without changing the legacy branch itself.

## Reference vectors

- `AEC4015F07300D30`: EC40, CH1, 3.7 °C, checksum `3D`;
- `A1D20485C480882835`: 1D20, CH3, battery low, -8.4 °C, 28%, checksum `53`.

The host-side test also exercises UVR128 with a clipped preamble and with an
artificial phase offset/junk prefix, requiring the phase-scan recovery to
reconstruct the original checksum-valid `EC70` frame.

Run `python scripts/test_oregon_v21.py` to validate framing, checksum and field
positions. These host-side tests do not substitute for reception tests with real
433.92 MHz hardware.

## Sources

- Oregon Scientific RF Protocols IV: <https://www.osengr.org/Articles/OS-RF-Protocols-IV.pdf>
- Oregon Scientific RF Protocols II: <https://www.osengr.org/WxShield/Downloads/OregonScientific-RF-Protocols-II.pdf>
- rtl_433 Oregon decoder: <https://github.com/merbanan/rtl_433/blob/master/src/devices/oregon_scientific.c>
- HEYU Oregon sensor interval notes: <https://www.gsp.com/cgi-bin/man.cgi?section=5&topic=X10OREGON>
- Oregon UVR128 user manual: <https://usermanual.wiki/Oregon-Scientific/OregonScientificUvr128UsersManual374420.769016158.pdf>
