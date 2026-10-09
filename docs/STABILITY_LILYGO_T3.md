# LILYGO T3 V1.6.1 stability changes — 6.4.0-rc6-stab1

**Target:** LilyGO LoRa32 T3 V1.6.1 (ESP32 + SX1278 433 MHz). The supplied firmware also declares a T3-S3 build target, but this change is primarily targeted at the **classic ESP32**, whose available contiguous RAM is constrained by Wi-Fi + mbedTLS.

**Status:** source-level hardening; not yet hardware-validated. A firmware reset can also result from an inadequate USB cable or 3.3 V supply, a brownout, a stack overflow, a memory-corruption bug, or a watchdog timeout. We **cannot** claim to know the actual reset cause without the on-board logs.

## What changed

1. Previous `mem1` optimization preserved: bit-packed RF level FIFO and deduplicated RAW Web history, reducing static allocation by 4,864 bytes, with RF test coverage.
2. Enabled `apply_remote_runtime_v2.py` after V1 TLS arbitration to reconnect WSS directly to the previously approved endpoint instead of repeating an HTTPS enrollment before every scheduled MB upload. It also reduces AdminSensor-only Web polling and adds heap/stack metrics to its status.
3. The existing `apply_remote_state_fastpath.py` now runs after Runtime V2: `/api/state` over AdminSensor is held in individual 2 KiB segments, rather than a single approximately 9 KiB heap block. The initial remote-dashboard refresh is serialized before less critical requests.
4. `apply_gateway_stability.py` is the last source overlay. The AdminSensor HTTP and WSS FreeRTOS tasks now start only when AdminSensor has a configured portal. MB publisher task starts only when enabled or when “test upload” is requested. The tasks start on demand without a firmware restart.
5. When the largest free contiguous 8-bit heap block is **below 32 KiB** and AdminSensor WSS cannot be paused, the MB HTTPS upload is **deferred** rather than starting another mbedTLS handshake with insufficient headroom. This may skip a reporting interval, which is preferable to resetting and losing all reception. The existing TLS session arbitration is retained. An OTA session is never deliberately interrupted for an MB upload.
6. Boot UART reports `last_reset`, current and historic minimum free heap. `/api/state` adds `system.heap_largest_block`, `system.loop_stack_min_free_bytes`, alongside existing `system.heap_free`, `system.heap_min_free`, `system.reset_reason`, and `system.uptime_s`.

## Diagnostics to confirm actual reboot cause

Connect via stable USB power and serial monitor (115200 baud), and capture the **last 50 lines before** and **first 30 lines after** a reboot. ESP32 startup will report a reset reason.

```bash
pio device monitor -e t3-v161-433 --baud 115200
```

Inspect these authenticated endpoints and record metrics before, during and after scheduled MB uploads:

- `GET /api/state`: `system.reset_reason`, `system.heap_free`, `system.heap_min_free`, `system.heap_largest_block`, `system.loop_stack_min_free_bytes`, `system.uptime_s`.
- `GET /api/remote/status`: `heap_largest`, `stack_admin_hwm`, `stack_http_hwm`, `tls_pause_count`, `tls_direct_reconnects`, `ws_disconnects`, `last_error`.
- `GET /api/mbcompatible`: `worker_stack_hwm`, `heap_largest`, `last_error`, `last_http_code`.

The high-water marks are reported by the ESP-IDF FreeRTOS API on Espressif boards. Values near zero indicate stack exhaustion and must be investigated. Note: `heap_free` and `heap_largest_block` are not equivalent; free aggregate memory may still be heavily fragmented.

### Reset reason quick map

| Reason | Interpretation | First action |
|---|---|---|
| `BROWNOUT` | Undervoltage detected | Stable 5 V supply, USB cable, connectors, local voltage under Wi-Fi/TLS load |
| `TASK_WDT`, `INT_WDT`, `OTHER_WDT` | Scheduler/task/interrupt watchdog | Serial trace, long blocking operations, tight loops; do not disable WDT |
| `PANIC` | Exception (e.g., illegal access, stack corruption) | Preserve decoded exception/backtrace and firmware ELF |
| `SOFTWARE` | Software-requested restart | Look for deliberate OTA, Web `/api/restart`, network configuration |
| `POWERON`, `EXTERNAL` | Reset/power cycle | Check external reset circuit, power and wiring |

### Validation and rollback

```bash
python scripts/test_memory_optimizations.py
python scripts/test_oregon_v21.py
python scripts/test_mb_compatible_mapping.py
python scripts/test_gateway_stability.py
pio run -e t3-v161-433
pio run -e t3-v161-433   # idempotence: pre-build scripts modify code
```

In a production soak test (24–72 hours), keep both Oregon/Technoline reception and configured services running, including remote WSS and HTTPS reporting if used. Check uptime monotonicity, no new reset, stable RF overflow count, worker stack minima, and absence of TLS allocation failures. If the reboot continues, use the original 6.4.0-rc6 binary for rollback and provide UART log plus reset cause. Do **not** disable brownout protection or watchdog.

**Important:** This is a stability-oriented source package, not a tested `.bin`. Builds may require PlatformIO dependencies and hardware-specific settings not available in the review environment.
