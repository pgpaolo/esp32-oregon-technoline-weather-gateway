Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
text = path.read_text(encoding="utf-8")

# On a second PlatformIO build the late SD browser pass has already converted
# the original 4 s SD badge poll into a remote-aware cadence.  The earlier
# apply_sdfat_backend.py pass historically recognized only the original
# setInterval(refreshSdHeader,4000) sentinel and therefore tried to patch the
# startup tail again after apply_remote_ui_polling.py had already rewritten it.
# Normalize only this generated sentinel before SdFat runs; the late browser
# pass restores the remote-aware 15 s cadence again before gzip generation.
remote_poll = "setTimeout(refreshSdHeader,remoteUi?3500:0);setInterval(refreshSdHeader,remoteUi?15000:4000);"
legacy_poll = "refreshSdHeader();setInterval(refreshSdHeader,4000);"

if remote_poll in text:
    text = text.replace(remote_poll, legacy_poll, 1)
    path.write_text(text, encoding="utf-8")
    print("SdFat repeat repair: restored base SD header timer sentinel")
elif legacy_poll in text:
    print("SdFat repeat repair: base SD header timer sentinel already present")
else:
    print("SdFat repeat repair: clean/pre-SdFat dashboard, nothing to do")
