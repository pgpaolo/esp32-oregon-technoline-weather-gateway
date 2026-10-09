Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "remote_access.cpp"
text = path.read_text(encoding="utf-8")

old = "constexpr size_t MAX_REQ=12288U, MAX_RESP=24576U, MAX_WS=38000U;"
new = "constexpr size_t MAX_REQ=16384U, MAX_RESP=28672U, MAX_WS=42000U;"

if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise RuntimeError("Remote memory limits: expected limits anchor missing")

path.write_text(text, encoding="utf-8")
print("AdminSensor Remote limits: request 16 KiB, response 28 KiB, WebSocket 42 kB")
