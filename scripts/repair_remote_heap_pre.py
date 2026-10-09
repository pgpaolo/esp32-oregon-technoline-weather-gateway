Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "remote_access.cpp"
text = path.read_text(encoding="utf-8")

historical = "Heap contiguo insufficiente per risposta locale"
markers = (
    "ADMIN_SENSOR_DYNAMIC_HEAP_V3",
    "ADMIN_SENSOR_DYNAMIC_HEAP_V4",
)

if historical in text:
    print("Remote heap repair: compatibility sentinel already present")
elif any(marker in text for marker in markers):
    # apply_remote_access_ota.py runs before the Oregon-specific dynamic heap
    # pass and historically recognizes an already-mutated localHttp() by this
    # exact message. Old source archives may contain V3/V4 code that replaced
    # the message, so repeat builds can fail before the later idempotent pass
    # has a chance to run. Restore only a harmless comment sentinel.
    inserted = False
    for marker in markers:
        needle = "// " + marker
        if needle in text:
            text = text.replace(
                needle,
                needle + "\n    // " + historical + " (repeat-build sentinel)",
                1,
            )
            inserted = True
            break
    if not inserted:
        raise RuntimeError("Remote heap repair: dynamic heap marker found but insertion point missing")
    path.write_text(text, encoding="utf-8")
    print("Remote heap repair: restored repeat-build compatibility sentinel")
else:
    print("Remote heap repair: clean source, no repair required")
