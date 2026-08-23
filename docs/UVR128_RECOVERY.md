# UVR128 recovery and final development branch

This document describes the consolidated development branch:

```text
feature/uvr128-v21-recovery
```

It supersedes the intermediate AS3935, Oregon multichannel, legacy V2.1 and compact-Web development branches. The pull request for this branch is PR #15 and is targeted directly at `main`.

The firmware version macro remains `6.4.0-rc2`; the branch contains additional development work that has not yet been merged into `main`.

## Scope

The branch combines the following work in one hardware-validation line:

- Oregon Scientific OSV3 reception;
- bounded Oregon Scientific V2.1 support;
- dedicated UVR128 / `EC70` recovery;
- Oregon thermo/hygro CH1-CH3 handling with a configurable primary channel;
- independent multi-transmitter UV display;
- Technoline / La Crosse WS23xx reception;
- optional local BME280;
- optional local AS3935 lightning sensor;
- Web dashboard and diagnostics;
- MQTT with TLS and selectable field groups;
- per-transmitter Oregon MQTT namespaces;
- configurable OLED pages and fields;
- soft controller power-off / deep sleep;
- JSON configuration backup and restore.

## UVR128 recovery

UVR128 (`EC70`, Oregon V2.1) can reach the SX1278 direct-mode slicer with the beginning of the short preamble clipped or with an uncertain initial phase. The recovery path therefore:

- accepts the reduced V2.1 preamble threshold used by the hardware-validation branch;
- scans the stored end-of-burst intervals across possible starts and both physical polarities;
- accepts only sensor code `EC70` in the dedicated fallback;
- requires valid Manchester inverse/original pairs;
- requires the normal V2.1 checksum before a packet can enter the normal RF queue.

The normal OSV3 path, Technoline decoder and normal V2.1 streaming path remain separate.

Hardware reception of a real UVR128 has been confirmed on this branch.

## Oregon thermo/hygro CH1-CH3

The branch keeps separate live state for CH1, CH2 and CH3.

- A configurable primary channel feeds the legacy station temperature/humidity fields and derived values.
- Auto-discovery can make received channels visible automatically.
- Manually enabled channels remain visible even if temporarily offline.
- The parser accepts the legacy one-hot channel representation (`1`, `2`, `4`) and the directly observed representation (`1`, `2`, `3`).
- Legacy MQTT temperature/humidity continue to follow the primary channel.
- Per-channel topics remain available under `oregon/thermo/chN/...`.

## Dashboard sensor status

RSSI presentation is uniform across supported Oregon sensor cards and Technoline:

| RSSI | Class |
|---|---|
| `>= -100 dBm` | green |
| `-115 .. -101 dBm` | yellow |
| `< -115 dBm` | red |
| unavailable | grey |

Battery state is also uniform where the protocol provides it:

- green: `BAT OK`;
- red: `BAT LOW`;
- grey: `BAT N/D`.

Technoline WS23xx does not transmit battery state, therefore its battery status is intentionally `N/D` while its real RF RSSI is still shown.

The Oregon session registry identifies physical transmitters by sensor family/code, channel and rolling code, so different transmitters do not share reception-quality counters.

## Multi-sensor UV

The Dashboard can show UVN800 (`D874`), UVR128 (`EC70`) and other supported UV transmitters independently. The legacy aggregate UV field remains for compatibility.

The normal OLED `ESTERNO` page keeps a compact UV summary, while the detailed per-transmitter RF state is shown on the optional `SENSORI RF` page.

## MQTT

Existing legacy topics remain available for compatibility.

Every accepted Oregon transmitter can also publish under a stable namespace:

```text
<base>/oregon/sensor/<CODE>/ch<CHANNEL>/id<ROLLING>/...
```

Examples:

```text
weatherstation/oregon/sensor/F824/ch1/id165/temperature
weatherstation/oregon/sensor/1D20/ch3/id114/humidity
weatherstation/oregon/sensor/D874/ch1/id245/uv
weatherstation/oregon/sensor/EC70/ch1/id158/uv
weatherstation/oregon/sensor/1984/ch0/id170/wind_average
weatherstation/oregon/sensor/2914/ch0/id189/rain_total
```

The Web MQTT configuration is grouped by station/sensor family and function:

- Oregon thermo/hygro;
- Oregon wind;
- Oregon rain;
- Oregon UV;
- Technoline;
- local BME280;
- AS3935 lightning;
- gateway/system.

The existing 32-bit MQTT mask is preserved. No new persistent bit is added for an individual rolling ID. A selected Oregon function applies to all accepted transmitters of that function, while the per-transmitter namespace prevents value collisions.

With RF metadata enabled, Oregon transmitter namespaces can also expose model, type, protocol, RSSI and battery state.

## AS3935

AS3935 is integrated as an optional local I2C/IRQ sensor. On the classic T3 V1.6.1 defaults are:

- I2C address `0x03`;
- IRQ `GPIO34`;
- shared I2C bus with OLED/BME280.

The Web UI provides state, configuration, reinitialization and reset functions. MQTT selection uses the existing upper four bits of the 32-bit mask for state, events, last strike and diagnostics. AS3935 also has a selectable OLED page.

## OLED

Display pages remain configurable from the Web UI. The consolidated branch adds the selectable page:

```text
Sensori RF / RSSI / batterie
```

It keeps a compact live registry of up to ten recent Oregon transmitters, displays five rows at a time and rotates automatically when more than five are active.

Examples:

```text
T1 F824 -116R B+
T3 1D20  -94G B+
U1 D874  -88G B+
U1 EC70 -122R B+
W0 1984  -92G B+
```

Legend:

- `G`, `Y`, `R`: RSSI class;
- `B+`: battery OK;
- `B!`: battery low;
- `B-`: battery unavailable.

The Technoline page uses the same signal convention, for example:

```text
ID79 -113dBm Y B-
```

`B-` is expected because WS23xx does not transmit battery status.

## Build and CI reference

Functional code was validated by PlatformIO Build #92 before the documentation cleanup commits:

- Validate: PASS;
- AS3935 Integration Guard: PASS;
- `t3-v161-433`: PASS;
- `t3-s3-433`: PASS;
- Oregon V2.1 host vectors: 6 valid accepted, 6 corrupt rejected, UVR128 clipped-preamble/phase-scan recovery PASS.

T3 V1.6.1 measurements from Build #92:

- RAM: `92,560 / 327,680 B` = 28.2%;
- application ELF: `1,226,765 / 1,310,720 B` = 93.6%;
- real `firmware.bin`: `1,233,472 B`;
- real app-partition margin: `77,248 B`.

Build #92 T3 V1.6.1 artifact ID: `9498796327`.

Documentation-only commits after Build #92 change the embedded Git commit identifier when rebuilt, but do not intentionally change RF, Web, MQTT or OLED application logic.

## Hardware validation checklist

Before merging PR #15 into `main`, verify on the real T3 V1.6.1:

1. UVR128 continues to decode together with UVN800 and the existing Oregon/Technoline sensors.
2. Dashboard RSSI/battery badges match the received sensor metadata.
3. CH1/CH2/CH3 tabs remain independent and the selected primary channel alone drives legacy temperature/humidity.
4. `mosquitto_sub -t 'weatherstation/#' -v` shows independent per-transmitter Oregon namespaces without collisions.
5. MQTT field selection still suppresses disabled function groups.
6. OLED `SENSORI RF` remains readable and rotates correctly with more than five recent transmitters.
7. Technoline OLED RSSI uses the same G/Y/R convention and shows battery as unavailable.
8. AS3935 state/configuration, OLED page and selected MQTT outputs still work.
9. Restart, soft power-off, backup/restore and NVS persistence remain functional.

## Branch policy

The intended repository layout after cleanup is deliberately simple:

- `main` - stable/integrated line;
- `feature/uvr128-v21-recovery` - current hardware-validation/development line.

Historical pull requests remain available as development history even after their intermediate branches are removed.
