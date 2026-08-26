# Publishing checklist — v6.4.0-rc1

Documentation/storage update note: the hardware-validated microSD work is published on `codex/sdfat-write-status`. Before promoting a later V6.4 candidate, carry forward `docs/SD_DATALOGGER.md`, the `/api/sd` reference, `min_spiffs.csv`, both PlatformIO build results and the Edition 3 PDF. Do not claim full/read-only-card or long-duration concurrency validation unless those checklist items have been completed.

1. Create branch `release/v6.4.0-rc1`.
2. Upload/commit the RC1 files and open a Pull Request to `main`.
3. Wait for all checks:
   - `Repository validation`
   - `Build t3-v161-433`
   - `Build t3-s3-433`
4. Merge only when all checks are green.
5. Delete the temporary branch after merge.
6. Verify the push-to-main PlatformIO build is also green.
7. Create GitHub release:
   - tag: `v6.4.0-rc1`
   - target: `main`
   - title: `ESP32 Oregon/Technoline Weather Gateway v6.4.0-rc1`
   - mark as **Pre-release**
   - do not replace V6.3.0 as stable/latest
8. Paste `docs/RELEASE_6.4.0_RC1.md` into the release notes.
9. Download and attach the two successful CI artifacts:
   - `firmware-t3-v161-433`
   - `firmware-t3-s3-433`
10. Promote to stable `v6.4.0` only after real-device validation.
11. Attach or link `output/pdf/Guida_Codifiche_RF_Oregon_Technoline_V6.4.0_Edizione_3.pdf` with the release documentation.
