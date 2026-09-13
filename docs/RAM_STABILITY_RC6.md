# RC6 RAM stability experiment

Branch: `develop-ram-stability`, based on frozen `release/6.4.0-rc6`.

This branch intentionally leaves the Oregon/Technoline RF decoding path and the RC6 boot/service ordering unchanged.

## Current SAFE V2 state

The first RAM experiment tried lazy COMPATIBLE MB and AdminSensor Remote task allocation. Although CI passed, the real T3 V1.6.1 did not reach normal Wi-Fi provisioning. Those lifecycle changes were therefore fully reverted. The current branch keeps the RC6 task lifecycle and service order.

Current runtime changes are deliberately low risk:

- Web raw-packet history is reduced from 32 to 16 entries, saving about 3.5 KiB of static RAM.
- `/api/state` exposes `heap_largest_free`, `heap_largest_min` and `heap_fragmentation_pct` in addition to existing heap diagnostics.
- Espressif32 is pinned to the known-good `7.1.2` toolchain used by the stable RC6 build.
- All external Arduino libraries are pinned to the exact versions resolved by the known-good `d5aabb35` CI build; AS3935MI remains pinned to its exact Git commit.
- RTC-only boot diagnostics record the current and previous boot checkpoint, Wi-Fi milestone and reset reason without adding NVS/flash writes.
- Boot diagnostics are exposed under the `boot` object in `/api/state` and printed once on Serial after startup begins.

Existing RC6 safeguards are preserved, including 2 KiB chunked AdminSensor WSS responses, the two-entry Remote HTTP queue, segmented `/api/state` loopback transfer, post-allocation heap checks and TLS arbitration between AdminSensor and COMPATIBLE MB.

## Boot checkpoint interpretation

A checkpoint is written immediately before entering each initialization stage. If a reset occurs before the firmware reaches `READY`, the next boot reports the retained `previous_checkpoint`. Network progress is tracked independently as `STA_PENDING`, `STA_CONNECTED`, `RECOVERY_AP` or `LOST`.

Typical reset reasons are `POWERON`, `SOFTWARE`, `PANIC`, `INT_WDT`, `TASK_WDT`, `WDT`, `DEEPSLEEP` and `BROWNOUT`.

The 12,288 / 7,168 / 8,192-byte AdminSensor, remote HTTP and COMPATIBLE MB task stacks remain unchanged. Any future reduction must be based on real-device high-water measurements after sustained RF, Web, TLS, MQTT, SD and OTA testing.
