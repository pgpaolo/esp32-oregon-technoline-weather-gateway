# 6.4.0-rc5

Release candidate branch:

```text
release/6.4.0-rc5
```

Firmware identity:

```text
6.4.0-rc5
```

Project author and maintainer:

```text
Gianpaolo P. (pgpaolo)
Copyright © 2026 Gianpaolo P.
```

RC5 is promoted from the validated `develop` source at commit:

```text
4310a5097c0097df4b32ae08f548ceef57957c7b
```

The previous `release/6.4.0-rc4` and `release/6.4.0-rc3` branches remain frozen. `main` is not modified by this RC5 promotion.

## Main additions compared with RC4

### AdminSensor Remote

RC5 adds an outbound remote-management path designed for the same T3 hardware already used by the gateway:

- HTTPS enrollment from the ESP32 to AdminSensor;
- authenticated WSS management tunnel;
- no router port-forward required;
- bounded retry/reconnect cadence;
- JSON application heartbeat every 20 seconds;
- Links2004 control-frame heartbeat watchdog disabled for this tunnel after physical testing showed false disconnects with the server stack;
- authenticated HTTP proxy to the ESP32 Web UI and REST endpoints.

See [REMOTE_ACCESS.md](REMOTE_ACCESS.md).

### Heap-safe remote Web UI

The Oregon dashboard is materially larger than the Davis-oriented reference UI, so RC5 includes an Oregon-specific memory strategy for the classic ESP32:

- `/` is served remotely from the already embedded gzip image in flash;
- no full-dashboard heap copy is created;
- root Web UI uses 2 KiB raw chunks over WSS;
- normal dynamic responses retain a 24 KiB ceiling and 2 KiB raw WSS chunks;
- `/api/state` reserves its real response buffer first and then measures the actual post-allocation heap layout;
- at least 4 KiB contiguous heap is kept for one Base64/WSS fragment;
- at least 16 KiB total free heap is kept for TLS/RF/MQTT/SD runtime state;
- a rejected reserve is released before returning an error.

This replaces the earlier inferred contiguous-headroom test that could reject a valid ~9 KiB state response even when more than 50 KiB total heap remained available.

### Remote Web polling and JSON handling

When the same dashboard is opened through AdminSensor, RC5 automatically uses a lower request cadence and prevents overlapping fetches:

- state: 5 s remote / 2 s local;
- AS3935: 10 s remote / 2 s local;
- MQTT: 30 s remote / 10 s local;
- configuration/network calls remain lazy where possible.

JSON fetches validate HTTP status and content type before parsing, so a tunnel-side HTTP error is shown as a useful HTTP diagnostic instead of a JavaScript `Unexpected token` exception.

### Guarded WSS OTA

RC5 adds remote OTA over the authenticated AdminSensor tunnel:

- exact image-size validation;
- SHA-256 verification;
- strict chunk sequence;
- ESP32 application-descriptor validation;
- bootloader, partition-table and merged images rejected before flashing;
- local authenticated OTA and remote OTA are mutually exclusive;
- SD logging is prepared for shutdown before the remote reboot path.

CI publishes one unambiguous `*-OTA.bin` application image plus its SHA-256 for each board. Manual-flash/debug binaries remain in a separately labelled artifact.

### Repeat-build / source-archive hardening

PlatformIO pre-scripts intentionally transform generated source. RC5 hardens this workflow so a local source archive can be compiled repeatedly without manually restoring the original source tree:

- SD datalogger anchors are semantic/idempotent;
- SD format and route repair tolerate already-auth-wrapped/generated handlers;
- remote heap compatibility is repaired before the main Remote pass;
- a second T3 V1.6.1 build in the same CI workspace is mandatory.

## RC4 baseline retained

RC5 retains the complete RC4 functionality, including:

- Oregon OSV2.1/OSV3 + Technoline WS23xx RF reception;
- UVR128/EC70 recovery;
- Oregon CH1-CH3 and multi-UV support;
- PCR800 rain-rate correction;
- MQTT/TLS and COMPATIBLE MB;
- SdFat microSD logging and FAT tools;
- authenticated Web UI, Wi-Fi provisioning and local OTA;
- BME280 altitude/pressure/forecast support;
- shared I2C runtime at 100 kHz / 80 ms;
- dedicated I2C/HW diagnostics;
- optional AS3935 integration;
- OLED pages and hardware monitor.

## Validation reference

The exact `develop` source promoted into RC5 completed successfully before branching:

- Validate #272: **success**;
- PlatformIO Build #348: **success**;
- `t3-v161-433`: **success**;
- `t3-s3-433`: **success**;
- same-workspace T3 V1.6.1 rebuild: **success**;
- AdminSensor Remote integration guard: **success**;
- remote OTA validation guard: **success**;
- firmware-size guard: **success**.

The RC5 branch has its own Validate and PlatformIO Build triggers and must remain green after the RC5 identity/documentation commits.

## Branch policy

- `main` remains stable/production;
- `release/6.4.0-rc5` is the current complete release candidate;
- `release/6.4.0-rc4` remains frozen;
- `release/6.4.0-rc3` remains frozen;
- `develop` remains the next-development line.

No automatic merge to `main` is performed by this RC5 promotion.
