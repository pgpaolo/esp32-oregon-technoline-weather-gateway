# Windows: PermissionError during PlatformIO pre-build

## Symptom

```
PermissionError: [Errno 13] Permission denied: '...\src\web_manager.cpp'
scripts/apply_remote_access_ota_impl.py, write(...)
```

This occurs in the **PlatformIO Python pre-script**, before the C++ compiler,
so it is unrelated to ESP32 RAM, heap, RF or watchdog resets.

## Fix in this package

The AdminSensor integration (`apply_remote_access_ota_impl.py` and
`apply_remote_access_ota.py`) now compares the proposed content with the
existing file first. **Unchanged files are never opened for writing.**
If the file genuinely needs updating and Windows denies access, the script
still stops with a clear diagnostic message: it does **not** bypass permissions.

## Diagnose on Windows PowerShell

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\diagnose_build_access.ps1
# Only if it reports read-only:
powershell -ExecutionPolicy Bypass -File .\scripts\diagnose_build_access.ps1 -RepairReadOnly
pio run -e t3-v161-433
```

If still denied:

1. Check NTFS access with `icacls .\src\web_manager.cpp`.
2. Close editors, serial monitors, simultaneous PlatformIO builds and file-sync utilities.
3. Check Windows Security > Virus & threat protection > Ransomware protection / Protection history.
   The **Desktop** folder can be protected by Controlled Folder Access; permit the
   legitimate `python.exe`/`platformio.exe` executable if Defender identifies it
   as blocked. Prefer moving your project outside a protected/synced folder,
   e.g. `C:\Dev\esp32-oregon-gateway`, with appropriate user permissions.
4. Re-extract the ZIP into a fresh, user-owned directory if extraction left
   files read-only. Do **not** run PlatformIO elevated as a general workaround.

When the file must change, its write permission is still required. No script
can reliably repair a Windows access denial that comes from ACLs or file locks.

## Architectural limitation

The release uses several dozen PlatformIO pre-build scripts that **modify files
under `src/` and `web/`**. The conditional-write fix removes redundant writes in
AdminSensor, but other passes still need write permission. The long-term design
should generate patched sources under `.pio/` instead of mutating the working tree.

The firmware logic, radio decoder, SD storage and TLS safeguards are unchanged
by this build-only update. Hardware reboot cause diagnosis is separate.
