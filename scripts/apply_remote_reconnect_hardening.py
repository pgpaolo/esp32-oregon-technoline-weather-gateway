Import("env")
from pathlib import Path

# Keep the AdminSensor WSS lifecycle identical to the known-good
# esp32-davis-weather-gateway/develop-optimized implementation.
#
# IMPORTANT: an earlier Oregon follow-up made the lifecycle more aggressive
# (5/5/15 s enroll/retry cadence, 15/4/3 WebSocket heartbeat and an additional
# application ping).  Real-device logs showed recurrent code=1005 disconnects
# and duplicate sessions while the gateway was otherwise healthy.  The Davis
# branch does not use those aggressive settings.  The canonical Oregon source
# already contains the Davis-proven values, so this build pass is deliberately
# a verifier, not a mutating patch.

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "remote_access.cpp"
text = path.read_text(encoding="utf-8")

required = {
    "Davis retry cadence":
        "constexpr uint32_t RETRY_PENDING=30000UL, RETRY_ERROR=15000UL, RETRY_APPROVED=60000UL;",
    "Davis reconnect interval":
        "ws.setReconnectInterval(5000);",
    "Davis WebSocket heartbeat":
        "ws.enableHeartbeat(30000,5000,2);",
}

for label, anchor in required.items():
    if anchor not in text:
        raise RuntimeError(f"AdminSensor Davis parity missing: {label}")

forbidden = {
    "aggressive application heartbeat": "APP_HEARTBEAT_MS",
    "extra application ping function": "sendAppHeartbeat",
    "aggressive 15/4/3 heartbeat": "ws.enableHeartbeat(15000,4000,3)",
    "aggressive 3-second reconnect": "ws.setReconnectInterval(3000)",
    "duplicate-session disconnect state": "intentionalDisconnect",
}

for label, anchor in forbidden.items():
    if anchor in text:
        raise RuntimeError(
            f"AdminSensor Davis parity regression: {label} still present"
        )

print(
    "AdminSensor Remote lifecycle: Davis parity OK "
    "(retry 30/15/60 s, reconnect 5 s, WS heartbeat 30/5/2, no extra app ping)"
)
