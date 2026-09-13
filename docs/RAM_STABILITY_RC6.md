# RC6 RAM stability experiment

Branch: `develop-ram-stability`, based on `release/6.4.0-rc6`.

This branch intentionally leaves the Oregon/Technoline RF decoding path unchanged.

Memory changes are applied as the final PlatformIO generation pass so they affect the actual compiled source after AdminSensor, COMPATIBLE MB, SD and Web generation:

- COMPATIBLE MB worker is created lazily instead of reserving its 8 KiB task stack while disabled.
- AdminSensor Remote HTTP/WSS tasks and queues are created lazily when no portal is configured, avoiding 7,168 + 12,288 bytes of task stack on unconfigured installations.
- Web raw-packet history is reduced from 32 to 16 entries.
- `/api/state` exposes `heap_largest_free`, `heap_largest_min` and `heap_fragmentation_pct` in addition to existing free/min heap values.
- Remote and MB status payloads retain the RC6 Runtime V2 FreeRTOS stack high-water diagnostics so task stacks can later be right-sized from real-device measurements rather than estimates.
- The existing RC6 Runtime V2 dashboard scheduler is deliberately unchanged because its adaptive remote polling and repeat-build repair depend on canonical timer anchors.

Existing RC6 safeguards are preserved, including 2 KiB chunked AdminSensor WSS responses, the two-entry Remote HTTP queue, segmented `/api/state` loopback transfer, post-allocation heap checks and TLS arbitration between AdminSensor and COMPATIBLE MB.

The next decision on reducing the 12,288 / 7,168 / 8,192-byte task stacks should be based on measured high-water values from a real T3 V1.6.1 after sustained operation.