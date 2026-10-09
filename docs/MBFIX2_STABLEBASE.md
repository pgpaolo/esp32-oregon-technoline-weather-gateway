# MBFIX2 stablebase — Oregon/Technoline daily rain / Pioggia giornaliera

**Source base:** original published rain1 Git tag `v6.4.0-rc6-stab1-rain1` (commit `dd252af91eba4168a1158f9eca422215461a46bc`).

**Target:** `release/6.4.0-rc6-stab1-rain1-mbfix2-stablebase`. **Do not merge into main/develop/RC6 Hardening yet.**

## Provenance from the supplied working ZIP

The uploaded `Nuova cartella(1).zip` was inspected as the known-working reference. Its `platformio.ini`, the MB single-source pre-build generator, the MB measurement-diagnostics generator and the rain accumulator core match the original rain1 Git tag **byte for byte**. Some `src/*.cpp` files in the ZIP are already changed by PlatformIO pre-build generators, unlike committed Git source files. This branch starts from that original immutable Git tag, allowing those same generators to run as intended.

**Security:** the ZIP contained `src/config_private.h`. It has **not been uploaded or committed**. Configure secrets locally and never attach them to logs/issues.

## Only MB-facing functional change

- MB 192-field packet **field 9** now reads the selected source's existing **UTC daily rainfall bucket** from the rain accumulator used by the Web UI; original sensor lifetime total (field 151), instantaneous rate and rolling windows are unchanged.
- A 32-bit rain counter is read directly and divided by 1000. No JSON, String, heap allocations, new FreeRTOS tasks, NVS writes or microSD writes occur inside the new getter.
- Daily value remains valid through brief RF silence. When the source is disabled, uninitialized or the UTC date differs, MB field 9 is `--` rather than an invented zero.
- No new retry intervals, TLS behavior, WSS behavior, radio decoding, display, OTA or SD logic were imported from the failed MBFIX1 or the diagnostic branch.
- PlatformIO identity includes `mbfix2` to distinguish the experimental candidate from the original firmware.

## Explicit reboot-risk validation

Software CI checks both board builds, baseline rainfall arithmetic, MB mapping, existing LILYGO memory/TLS guards and rebuild idempotence. It does **not** prove an ESP32 cannot reset on physical hardware.

On a noncritical device with rollback available:
1. Preserve a local backup and note previous reset reason, uptime, heap minimum and free/largest block.
2. Use the correct board environment. Collect Serial at **115200 baud** and save `[BOOT] last_reset=`, any `Guru Meditation`, `Backtrace`, `Task watchdog` or `Brownout` messages.
3. Test 30–60 minutes with MB disabled; then MB enabled with actual Oregon/Technoline observations and the intended transport; check packet field 9 matches Web rain today on the same UTC day.
4. Test MB + AdminSensor/WSS + MQTT + SD concurrently (if deployed). Observe minimum/contiguous heap and task stack high-water marks.
5. Perform controlled power cycles and allow at least **24 hours** continuous operation without unexplained resets before evaluating further integration.
6. If any reboot occurs, stop promotion; obtain the complete serial panic/reset log. An automated green build is not sufficient.

**Status:** source candidate, physical acceptance PENDING. No GitHub stable release, binary hardware certification or changes to existing rain1 tags.
