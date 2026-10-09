# Publishing checklist — 6.4.0-rc6-stab1-rain1

1. Preserve historic `release/6.4.0-rc6`, RC3, RC4 and current `main`; publish to version-specific branch first.
2. Commit complete source, PlatformIO scripts, both READMEs, updated changelog, API, rain and stability documentation. Do not commit `src/config_private.h`, build artifacts, secrets or logs.
3. Open PR against `main`, account for divergent history, and inspect GitHub Actions output (`validate`, both PlatformIO targets and same-workspace second T3 build). Never merge failing checks.
4. Run host `tests/test_rain_accumulator_core.cpp`; smoke-test radio Oregon/Technoline and SdFat on LILYGO T3 V1.6.1. Record heap/stack and reset reason over extended operation.
5. Verify MB publisher reports real valid measures rather than just 192 placeholders; test timeouts and TLS/WebSocket concurrent operation.
6. Only after successful CI + board review, promote to `main`, create an annotated version tag and GitHub Release notes. GitHub Release may be marked **prerelease** while operational validation remains incomplete. Attach compiled binary only after verified.
7. Back up SD and configuration before upgrade; do not reset accumulated rainfall without explicit operator intent.

No claim is made here that hardware testing, release tag creation, or GitHub Releases publication has already occurred.
