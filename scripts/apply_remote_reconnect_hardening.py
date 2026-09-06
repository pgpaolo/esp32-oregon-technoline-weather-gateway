Import("env")
from pathlib import Path

# AdminSensor WSS lifecycle guard.
#
# Real-device logs on the Oregon gateway showed a very repeatable disconnect
# about 44 seconds after connection.  That timing matches the Links2004
# heartbeat watchdog configured as 30 s ping / 5 s pong timeout / 2 misses.
# Through the current Apache/Uvicorn/AdminSensor path, relying on protocol-level
# PONG delivery is therefore too brittle: the library can tear down a healthy
# tunnel even though application traffic is still valid.
#
# Keep the Davis-proven retry and reconnect cadence, but disable the client
# library's disconnecting control-frame heartbeat and use a small JSON
# application ping every 20 seconds instead.  AdminSensor already handles
# {"type":"ping"} and answers with {"type":"pong"}, so this heartbeat crosses
# the complete WSS/application path and cannot trigger the library's HB timeout.

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "remote_access.cpp"
text = path.read_text(encoding="utf-8")

required_base = {
    "retry cadence":
        "constexpr uint32_t RETRY_PENDING=30000UL, RETRY_ERROR=15000UL, RETRY_APPROVED=60000UL;",
    "reconnect interval":
        "ws.setReconnectInterval(5000);",
}
for label, anchor in required_base.items():
    if anchor not in text:
        raise RuntimeError(f"AdminSensor lifecycle anchor missing: {label}")

# Disable the Links2004 control-frame heartbeat watchdog.  Keep this
# idempotent because PlatformIO deliberately rebuilds the same workspace in CI.
old_hb = "ws.enableHeartbeat(30000,5000,2);"
new_hb = "ws.disableHeartbeat();"
if old_hb in text:
    text = text.replace(old_hb, new_hb, 1)
elif new_hb not in text:
    raise RuntimeError("AdminSensor lifecycle anchor missing: WebSocket heartbeat")

# Application heartbeat cadence.
app_ping_const = "constexpr uint32_t APP_PING_MS=20000UL;"
if app_ping_const not in text:
    retry_anchor = (
        "constexpr uint32_t RETRY_PENDING=30000UL, RETRY_ERROR=15000UL, "
        "RETRY_APPROVED=60000UL;"
    )
    text = text.replace(retry_anchor, retry_anchor + "\n" + app_ping_const, 1)

app_ping_state = "uint32_t lastAppPingMs=0;"
if app_ping_state not in text:
    state_anchor = "bool timeRequested=false;"
    if state_anchor not in text:
        raise RuntimeError("AdminSensor lifecycle anchor missing: timeRequested")
    text = text.replace(state_anchor, state_anchor + "\n" + app_ping_state, 1)

# Send the application ping from the AdminSensor task itself.  All normal WSS
# response writes are drained from this same task, avoiding concurrent sendTXT
# calls from different FreeRTOS tasks.
app_ping_marker = "APP_PING_MS"
loop_old = "if(wsStarted){ws.loop();drainReplies();}"
loop_new = '''if(wsStarted){
            ws.loop();drainReplies();
            bool transport=false;if(take()){transport=st.transportActive;give();}
            const uint32_t pingNow=millis();
            if(transport&&(uint32_t)(pingNow-lastAppPingMs)>=APP_PING_MS){
                lastAppPingMs=pingNow;
                ws.sendTXT("{\\\"type\\\":\\\"ping\\\"}");
            }
        }'''

# The constant itself contains APP_PING_MS, so detect the actual task body by
# the distinctive pingNow variable rather than the generic marker.
if "const uint32_t pingNow=millis();" not in text:
    if loop_old not in text:
        raise RuntimeError("AdminSensor lifecycle anchor missing: ws loop")
    text = text.replace(loop_old, loop_new, 1)

# Reset the app heartbeat clock on every successful connection so the first
# application ping is sent after a full interval, not immediately after WSS
# establishment.
connect_old = 'st.lastActivityMs=millis();st.lastWsEvent="CONNECTED";'
connect_new = 'st.lastActivityMs=millis();lastAppPingMs=millis();st.lastWsEvent="CONNECTED";'
if connect_new not in text:
    if connect_old not in text:
        raise RuntimeError("AdminSensor lifecycle anchor missing: connected event")
    text = text.replace(connect_old, connect_new, 1)

# Regression checks after mutation.
forbidden = {
    "disconnecting WS heartbeat": "ws.enableHeartbeat(",
    "aggressive 3-second reconnect": "ws.setReconnectInterval(3000)",
    "old aggressive app heartbeat": "APP_HEARTBEAT_MS",
    "duplicate-session disconnect state": "intentionalDisconnect",
}
for label, anchor in forbidden.items():
    if anchor in text:
        raise RuntimeError(f"AdminSensor lifecycle regression: {label} still present")

required_final = {
    "disabled control heartbeat": "ws.disableHeartbeat();",
    "application ping cadence": app_ping_const,
    "application ping task": 'ws.sendTXT("{\\\"type\\\":\\\"ping\\\"}");',
    "5-second reconnect": "ws.setReconnectInterval(5000);",
}
for label, anchor in required_final.items():
    if anchor not in text:
        raise RuntimeError(f"AdminSensor lifecycle result missing: {label}")

path.write_text(text, encoding="utf-8")
print(
    "AdminSensor Remote lifecycle: retry 30/15/60 s, reconnect 5 s, "
    "WS control heartbeat disabled, JSON app ping 20 s"
)
