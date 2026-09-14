from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]

remote = (root / "src" / "remote_access.cpp").read_text(encoding="utf-8")
mb = (root / "src" / "mb_compatible_publisher.cpp").read_text(encoding="utf-8")
mqtt = (root / "src" / "mqtt_publisher.cpp").read_text(encoding="utf-8")

# Field names are checked independently from their escaped C++ JSON quoting.
# This keeps the guard strict on the exported telemetry while avoiding a false
# negative caused only by source-string representation (\"key\" vs "key").
required_remote = [
    "RUNTIME_MEMORY_V3_REMOTE",
    "REMOTE_HTTP_STACK_BYTES=7168U",
    "REMOTE_ADMIN_STACK_BYTES=12288U",
    "stack_admin_size_bytes",
    "stack_admin_peak_used_bytes",
    "stack_http_size_bytes",
    "stack_http_peak_used_bytes",
]
for needle in required_remote:
    if needle not in remote:
        raise SystemExit(f"runtime memory V3 remote guard missing: {needle}")

required_mb = [
    "RUNTIME_MEMORY_V3_MB",
    "appendFloatField(",
    "appendFieldValue(",
    "value.length() * 3U + 1U",
    "worker_stack_size_bytes",
    "worker_stack_peak_used_bytes",
]
for needle in required_mb:
    if needle not in mb:
        raise SystemExit(f"runtime memory V3 MB guard missing: {needle}")

if "String floatField(" in mb or "String fieldValue(" in mb:
    raise SystemExit("runtime memory V3: legacy allocating MB field builder remains")
if "payload += fieldValue(" in mb:
    raise SystemExit("runtime memory V3: legacy MB field allocation loop remains")

required_mqtt = [
    "RUNTIME_MEMORY_V3_MQTT",
    "MQTT_TOPIC_BUFFER = 192U",
    "bool makeTopic(",
    "bool publishText(",
]
for needle in required_mqtt:
    if needle not in mqtt:
        raise SystemExit(f"runtime memory V3 MQTT guard missing: {needle}")

if re.search(r"\btopic\(", mqtt):
    raise SystemExit("runtime memory V3: heap-allocating MQTT topic() remains")
if ".publish(topic(" in mqtt:
    raise SystemExit("runtime memory V3: direct MQTT topic String publish remains")

# The single-source invariant is essential because V3 rewrites code around the
# same MB block. Keep this semantic check in the memory guard as well as in the
# generator itself so future refactors cannot accidentally reintroduce mixing.
for marker in [
    "const bool useTechnoline = cfg.sourcePriority == 1U;",
    "Oregon source: no Technoline fallback is allowed.",
    "Technoline source: no Oregon fallback is allowed.",
    "BME280 is local gateway hardware, not a fallback weather station.",
]:
    if marker not in mb:
        raise SystemExit(f"runtime memory V3: MB single-source invariant missing: {marker}")

print(
    "Runtime memory V3 guard: PASS "
    "(stack bytes observable, MB field/url churn reduced, MQTT topics stack-built)"
)
