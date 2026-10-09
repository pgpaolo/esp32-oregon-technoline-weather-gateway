# Publishing checklist — 6.4.0-rc6-stab1-rain1

1. Preserve historic `release/6.4.0-rc6`, RC3, RC4 and current `main`; publish to version-specific branch first.
2. Commit complete source, PlatformIO scripts, both READMEs, updated changelog, API, rain and stability documentation. Do not commit `src/config_private.h`, build artifacts, secrets or logs.
3. Open PR against `main`, account for divergent history, and inspect GitHub Actions output (`validate`, both PlatformIO targets and same-workspace second T3 build). Never merge failing checks.
4. Run host `tests/test_rain_accumulator_core.cpp`; smoke-test radio Oregon/Technoline and SdFat on LILYGO T3 V1.6.1. Record heap/stack and reset reason over extended operation.
5. Verify MB publisher reports real valid measures rather than just 192 placeholders; test timeouts and TLS/WebSocket concurrent operation.
6. The branch workflow `.github/workflows/release-rain1-source.yml` runs host checks and builds both PlatformIO targets, then can create a **source-only prerelease** (no unverified firmware binary). CI and hardware validation are different gates; the prerelease does not certify the LILYGO board.
7. Only after successful CI + board review, reconcile the divergent `main` history and promote with a reviewed merge. Attach compiled binaries to a production GitHub Release only after device verification.
8. Back up SD and configuration before upgrade; do not reset accumulated rainfall without explicit operator intent.

Do not mark the prerelease as production ready without physical testing. GitHub Actions status and the Releases page determine whether the automated source-only publication actually completed.

## Follow-up publication / Pubblicazione MBFIX1

- Source-only follow-up tag: `v6.4.0-rc6-stab1-rain1-mbfix1`. Its immutable historical predecessor `v6.4.0-rc6-stab1-rain1` must not be moved, overwritten or deleted.
- The branch-only workflow runs the rainfall arithmetic host test, COMPATIBLE MB mapping guard and PlatformIO builds for **both** board environments **before** it creates the new GitHub prerelease from its exact successful checkout commit.
- The release notes are [docs/RELEASE_6.4.0_RC6_STAB1_RAIN1_MBFIX1.md](docs/RELEASE_6.4.0_RC6_STAB1_RAIN1_MBFIX1.md). No firmware `.bin` is attached; physical device verification is still required.
- This correction is restricted to the rain1 line. Leave `main`, `develop`, RC6 original and the separate RC6-stab2 Hardening branch unchanged; decide on integration only after rain1 field checks.
- After publication check the tag/ref actually points at the release commit, both PlatformIO jobs, release asset list and the unchanged original release.
