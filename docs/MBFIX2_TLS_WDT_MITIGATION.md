# MBFIX2 — TLS memory arbitration / TASK_WDT mitigation

**Working branch:** `release/6.4.0-rc6-stab1-rain1-mbfix2-stablebase`. This is an incremental fix on the same branch, not a new release line. Original rain1 tag, main, develop and Hardening remain untouched.

## Observed facts from hardware (2026-10-09)

ESP32-PICO-D4 T3 V1.6.1, MBFIX2, a **TASK_WDT** reset was displayed following a recent ~11-minute uptime, while MB HTTPS was in use. At another capture: heap free 68,068 bytes, largest block 27,636 bytes, 32,768-byte contiguous preflight threshold and an HTTP 200 with a newer `HTTPS deferred` error. This proves neither that TLS caused the watchdog nor which task timed out: a serial watchdog task listing/backtrace is needed.

## Narrow change; risk reduction, not proven fix

- **No WSS worker:** `remoteAccessPauseForExternalTls()` now returns true when there is no Remote task (previously false because not active).
- **Active or connecting WSS:** always request pause/acknowledgment before a second MB HTTPS handshake, including when the initially contiguous heap is above 32 KiB. If OTA is in progress, or remote does not acknowledge, **defer** the weather send.
- **After pausing:** measure heap again; require >=32 KiB contiguous and >=48 KiB total free before the handshake. These are conservative software preflight floors, **not proofs of runtime sufficiency**. Do not bypass when fragmented; an ESP32 showing ~27 KiB contiguous can continue to defer.
- Always release the pause on preflight failure or at the original HTTP completion path.
- Prevent invalid MB URL and unsynchronized NTP/UTC from causing buildPayload/config retry in every `loop()` iteration; retry at configured interval instead.
- Explicitly reset stale `last_http_code: 200` and last response when latest send is deferred, preserving last successful send timestamp.
- Preserve existing HTTP/HTTPS code, verified/public/custom/insecure TLS modes, RF and Technoline/Oregon exclusive selector, 192-field mapping, UTC rain accumulation, SD, Web, OTA and GPL-3.0-or-later attribution.
- Register a final idempotent PlatformIO pre-script *after* all source normalizers; CI repeats a build on the same checkout.

## Field acceptance test — mandatory

1. Save a known-good firmware image and serial logs before flashing the unvalidated candidate. Ensure power supply and USB cable are stable.
2. Check `/api/mbcompatible`: `source_priority=1`, `source_station=TECHNOLINE`, and correct station destination `station=technoline-ws23xx` (URL stored in device NVS, not hard-coded by this fix).
3. Test with MB disabled; then MB HTTPS with AdminSensor disabled; then MB + AdminSensor enabled. Log `last_http_code`, `last_error`, `heap_largest`, `worker_stack_hwm` and `/api/state` `heap_largest_block`.
4. **Expected when memory is insufficient:** `HTTPS deferred: insufficient heap after TLS arbitration`. No forced handshake into 27 KiB fragmentation. Stop and investigate memory rather than lowering thresholds.
5. Collect serial `Task watchdog got triggered`, `Tasks currently running`, `Backtrace`, `[BOOT] last_reset`, full logs at 115200 baud. No WDT timeout increase or WDT disable.
6. Evaluate a >=24h physical stability session and successful MB transport before calling the issue fixed.

**Scope:** only mitigates plausible TLS contention and avoidable CPU retry loops. The origin of the **TASK_WDT** is still unproven.
