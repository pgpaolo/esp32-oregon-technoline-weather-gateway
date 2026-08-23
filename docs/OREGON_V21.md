# Oregon Scientific protocol V2.1

The consolidated development branch `feature/uvr128-v21-recovery` runs a bounded Oregon V2.1 decoder alongside the existing OSV3 path. It does not replace or relax OSV3 validation.

## Supported V2.1 sensors

| Sensor code | Known models | Values |
|---|---|---|
| `EC40` | THN132N, THR228N | temperature, channel, battery |
| `1D20` | THGR122NX, THGR228N | temperature, humidity, channel, battery |
| `1D30` | THGR968, THGN500 | temperature, humidity, channel, battery |
| `3D00` | WGR968 | average/gust wind speed, direction, battery |
| `2D10` | RGR968 | rainfall rate, total rainfall, battery |
| `EC70` | UVR128 | UV index, battery |

The rest of the firmware also continues to support the existing OSV3 families, including the sensors used by the main Oregon weather station.

## Channel normalization

Both representations observed in compatible thermo/hygro sensors are accepted:

- one-hot legacy: raw `1` -> CH1, `2` -> CH2, `4` -> CH3;
- direct numeric representation observed on hardware: raw `1` -> CH1, `2` -> CH2, `3` -> CH3.

The resulting normalized channel is used by the CH1-CH3 manager, Dashboard and MQTT routing.

## Decoder boundaries

The bounded V2.1 path:

- recognizes the alternating physical preamble;
- accepts the configured shortened stable tail while retaining downstream validation;
- reconstructs and validates Manchester inverse/original pairs;
- accepts only supported/bounded sensor IDs and payload formats;
- verifies the nibble-sum checksum before a frame can enter the normal RF queue;
- exposes V2.1 candidate/valid/checksum/pair diagnostics in `/api/state`.

## Per-transmitter session quality

Oregon session quality is transmitter-aware. A physical transmitter is identified by:

- sensor family/type;
- sensor code;
- channel;
- rolling code.

Each row has separate received/expected/lost/quality information and latest RSSI. OSV3 and V2.1 traffic from different transmitters therefore does not share a single counter.

Nominal cadence is used only for known sensor families; guarded observed cadence is used for unknown-but-supported cases only after sufficient samples. The UI does not invent a percentage when cadence is unavailable.

## UVR128 / EC70 behavior

UVR128 sends a longer transmission containing two copies without the usual inter-message pause. The useful measurement and checksum are already complete in the first valid copy.

Real SX1278 direct-mode captures can lose the exact beginning of the short V2.1 preamble or start at an uncertain physical phase even when other V2.1 sensors decode normally. The dedicated recovery path therefore scans stored end-of-burst intervals across candidate start positions and both physical polarities.

The fallback is intentionally narrow:

- sensor code must resolve to `EC70`;
- valid inverse/original Manchester pairs are still required;
- the normal V2.1 checksum must pass;
- only then can the recovered frame enter the normal RF queue.

OSV3, Technoline and the normal V2.1 streaming decoder remain separate from this fallback.

## Hardware validation status

A real UVR128 has been successfully received on the consolidated branch together with the existing Oregon and Technoline sensors. The EC70 recovery is therefore no longer only a host-side hypothesis; it has field evidence on the target T3/SX1278 setup.

The branch still remains a hardware-validation line until the full combined Web/MQTT/OLED behavior is accepted before merge to `main`.

## Build-time recovery patch

The current branch applies the UVR128 recovery as an idempotent PlatformIO pre-build step. Minimum raw interval collection required by the EC70 fallback remains available when Oregon reception is active even with optional `BURST EXTRA` diagnostics disabled.

This is intentional: `BURST EXTRA` controls additional diagnostics, while the small EC70 recovery input is part of the functional receiver path on this branch.

## Reference vectors

Examples used by the host-side validation include:

```text
AEC4015F07300D30
```

EC40, CH1, 3.7 °C, checksum `3D`.

```text
A1D20485C480882835
```

1D20, CH3, battery low, -8.4 °C, 28%, checksum `53`.

The host-side suite also exercises UVR128 with clipped preamble and artificial phase offset/junk prefix. The recovery must reconstruct the original checksum-valid EC70 frame and reject corrupted vectors.

Run:

```bash
python scripts/test_oregon_v21.py
```

Build #92 reported:

```text
6 valid, 6 corrupt rejected, UVR128 clipped-preamble + phase-scan recovery OK
```

Host vectors complement but do not replace RF hardware tests.

## Dashboard / MQTT consequences

V2.1 transmitters use the same uniform RSSI/battery presentation as supported OSV3 transmitters.

When MQTT fields are enabled, a V2.1 transmitter can publish through the generic per-transmitter namespace:

```text
oregon/sensor/<CODE>/ch<CHANNEL>/id<ROLLING>/...
```

UVR128 also retains the dedicated compatibility namespace under `oregon/uv/EC70/...`.

## Sources

- Oregon Scientific RF Protocols IV: <https://www.osengr.org/Articles/OS-RF-Protocols-IV.pdf>
- Oregon Scientific RF Protocols II: <https://www.osengr.org/WxShield/Downloads/OregonScientific-RF-Protocols-II.pdf>
- rtl_433 Oregon decoder: <https://github.com/merbanan/rtl_433/blob/master/src/devices/oregon_scientific.c>
- HEYU Oregon sensor interval notes: <https://www.gsp.com/cgi-bin/man.cgi?section=5&topic=X10OREGON>
- Oregon UVR128 user manual: <https://usermanual.wiki/Oregon-Scientific/OregonScientificUvr128UsersManual374420.769016158.pdf>
