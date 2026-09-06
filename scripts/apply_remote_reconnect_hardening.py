Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "remote_access.cpp"
text = path.read_text(encoding="utf-8")


def replace_once(old, new, label):
    global text
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Remote reconnect hardening anchor missing: {label}")
    text = text.replace(old, new, 1)
    print(f"AdminSensor reconnect: patched {label}")


def function_block(signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Remote reconnect hardening function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Remote reconnect hardening opening brace missing: {signature}")
    depth = 0
    quote = None
    escape = False
    for i in range(brace, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1, text[start:i + 1]
    raise RuntimeError(f"Remote reconnect hardening unclosed function: {signature}")


def replace_function(signature, new_body, marker):
    global text
    if marker in text:
        return
    s, e, _ = function_block(signature)
    text = text[:s] + new_body + text[e:]
    print(f"AdminSensor reconnect: replaced {signature}")


# Proven reconnect timings from esp32-davis-weather-gateway/develop-optimized.
replace_once(
    "constexpr uint32_t RETRY_PENDING=30000UL, RETRY_ERROR=15000UL, RETRY_APPROVED=60000UL;",
    "constexpr uint32_t RETRY_PENDING=5000UL, RETRY_ERROR=5000UL, RETRY_APPROVED=15000UL;\nconstexpr uint32_t APP_HEARTBEAT_MS=15000UL; // ADMIN_SENSOR_RECONNECT_V1",
    "retry/heartbeat timings",
)

replace_once(
    "bool wsStarted=false;\nvolatile uint32_t generation=1;\nvolatile bool forceRetry=false;",
    "bool wsStarted=false;\nbool intentionalDisconnect=false;\nvolatile uint32_t generation=1;\nvolatile bool forceRetry=false;\nuint32_t lastAppHeartbeatMs=0;",
    "reconnect state",
)

ws_event = r'''void wsEvent(WStype_t t,uint8_t*p,size_t n){ // ADMIN_SENSOR_RECONNECT_EVENT_V1
    if(t==WStype_CONNECTED){
        if(take()){
            wsSession++;
            st.transportActive=true;
            st.approved=true;
            st.state="ONLINE";
            st.wsConnects++;
            st.lastActivityMs=millis();
            st.lastWsEvent="CONNECTED";
            st.lastError="";
            give();
        }
        lastAppHeartbeatMs=0;
        Serial.println(F("[REMOTE] AdminSensor ONLINE"));
    }else if(t==WStype_DISCONNECTED){
        firmwareRemoteAbort("Connessione AdminSensor interrotta durante OTA");
        if(intentionalDisconnect){intentionalDisconnect=false;return;}
        if(take()){
            const bool was=st.transportActive;
            wsSession++;
            st.transportActive=false;
            if(st.configured&&st.approved)st.state="RECONNECT";
            if(was)st.wsDisconnects++;
            st.lastWsEvent="DISCONNECTED";
            st.lastError=was ? "WebSocket disconnesso; riconnessione automatica" : "Handshake WebSocket non completato; nuovo tentativo automatico";
            give();
        }
    }else if(t==WStype_ERROR){
        firmwareRemoteAbort("Errore WebSocket AdminSensor durante OTA");
        if(take()){
            st.transportActive=false;
            if(st.configured&&st.approved)st.state="RECONNECT";
            st.lastWsEvent="ERROR";
            st.lastError="Errore WebSocket; riconnessione automatica";
            give();
        }
    }else if(t==WStype_TEXT){
        wsText(p,n);
    }else if(t==WStype_PING||t==WStype_PONG){
        if(take()){
            st.lastActivityMs=millis();
            st.lastWsEvent=t==WStype_PING?"WS_PING":"WS_PONG";
            give();
        }
    }
}'''
replace_function("void wsEvent(WStype_t t,uint8_t*p,size_t n)", ws_event, "ADMIN_SENSOR_RECONNECT_EVENT_V1")

start_ws = r'''bool startWs(const String&url){ // ADMIN_SENSOR_RECONNECT_START_V1
    UrlParts u;
    if(!parseUrl(url,"wss",u))return false;
    if(wsStarted){
        intentionalDisconnect=true;
        ws.disconnect();
    }
    // The Davis optimized branch proved that Wi-Fi modem sleep can make the
    // long-lived TLS/WSS session look dead to the portal even while normal
    // short HTTP traffic still works.
    WiFi.setSleep(false);
    wsAuth="Authorization: Bearer "+token;
    ws.setExtraHeaders(wsAuth.c_str());
    ws.beginSslWithCA(u.host.c_str(),u.port,u.path.c_str(),REMOTE_TRUST_CA,"");
    // Re-apply after begin(): WebSocketsClient rebuilds the connection state.
    ws.setExtraHeaders(wsAuth.c_str());
    ws.setReconnectInterval(3000);
    ws.enableHeartbeat(15000,4000,3);
    activeWsUrl=url;
    wsStarted=true;
    lastAppHeartbeatMs=0;
    if(take()){
        st.wsAttempts++;
        st.lastWsAttemptMs=millis();
        st.wsHost=u.host;
        st.wsPath=u.path;
        st.lastWsEvent="CONNECTING";
        give();
    }
    setState("CONNECTING");
    return true;
}'''
replace_function("bool startWs(const String&url)", start_ws, "ADMIN_SENSOR_RECONNECT_START_V1")

# Application-level ping is kept in addition to WebSocket ping/pong. This is
# the same presence keepalive that made AdminSensor reliably retain the Davis
# device as connected through reverse proxies.
if "ADMIN_SENSOR_APP_HEARTBEAT_V1" not in text:
    signature = "void task(void*)"
    pos = text.find(signature)
    if pos < 0:
        raise RuntimeError("Remote reconnect hardening task anchor missing")
    heartbeat = r'''void sendAppHeartbeat(){ // ADMIN_SENSOR_APP_HEARTBEAT_V1
    String x="{\"type\":\"ping\",\"device_id\":\""+esc(remoteDefaultDeviceId())+"\",\"uptime_ms\":"+String(millis())+"}";
    if(ws.sendTXT(x)&&take()){
        st.lastActivityMs=millis();
        st.lastWsEvent="PING_SENT";
        give();
    }
}

'''
    text = text[:pos] + heartbeat + text[pos:]
    print("AdminSensor reconnect: added application heartbeat")

# Patch only the lifecycle statements in the existing Oregon task so the
# asynchronous HTTP response queue and guarded remote OTA remain untouched.
replace_once(
    'if(g!=seen||fr){firmwareRemoteAbort(fr?"Retry AdminSensor durante OTA":"Configurazione AdminSensor modificata durante OTA");seen=g;if(wsStarted)ws.disconnect();wsStarted=false;activeWsUrl="";next=0;clearQueuedRequests();if(take()){wsSession++;st.transportActive=false;st.approved=false;st.lastWsEvent=fr?"MANUAL_RETRY":"CONFIG_CHANGED";give();}}',
    'if(g!=seen||fr){firmwareRemoteAbort(fr?"Retry AdminSensor durante OTA":"Configurazione AdminSensor modificata durante OTA");seen=g;if(wsStarted){intentionalDisconnect=true;ws.disconnect();}wsStarted=false;activeWsUrl="";next=0;lastAppHeartbeatMs=0;clearQueuedRequests();if(take()){wsSession++;st.transportActive=false;st.approved=false;st.lastWsEvent=fr?"MANUAL_RETRY":"CONFIG_CHANGED";give();}}',
    "configuration-change disconnect",
)
replace_once(
    'if(!wifiConnected()||networkRecoveryApActive()||networkWifiCredentialTrialPending()){firmwareRemoteAbort("Rete non disponibile durante OTA remota");if(wsStarted){ws.disconnect();wsStarted=false;}setState("WAIT_NETWORK");vTaskDelay(pdMS_TO_TICKS(500));continue;}',
    'if(!wifiConnected()||networkRecoveryApActive()||networkWifiCredentialTrialPending()){firmwareRemoteAbort("Rete non disponibile durante OTA remota");if(wsStarted){intentionalDisconnect=true;ws.disconnect();wsStarted=false;}setState("WAIT_NETWORK");vTaskDelay(pdMS_TO_TICKS(500));continue;}',
    "network-loss disconnect",
)
replace_once(
    'if(next==0U||(!online&&(int32_t)(now-next)>=0)){bool pending=false;String u;setState("ENROLLING");const bool ok=enroll(c.portalUrl,u,pending);if(ok&&pending){if(wsStarted){ws.disconnect();wsStarted=false;}next=millis()+RETRY_PENDING;}else if(ok&&!u.isEmpty()){if(!wsStarted||u!=activeWsUrl)startWs(u);next=millis()+RETRY_APPROVED;}else next=millis()+RETRY_ERROR;}',
    'if(next==0U||(!online&&(int32_t)(now-next)>=0)){bool pending=false;String u;setState("ENROLLING");const bool ok=enroll(c.portalUrl,u,pending);if(ok&&pending){if(wsStarted){intentionalDisconnect=true;ws.disconnect();wsStarted=false;}next=millis()+RETRY_PENDING;}else if(ok&&!u.isEmpty()){if(!wsStarted||u!=activeWsUrl)startWs(u);next=millis()+RETRY_APPROVED;}else next=millis()+RETRY_ERROR;}',
    "pending-enrollment disconnect",
)
replace_once(
    'if(wsStarted){ws.loop();drainReplies();}\n        vTaskDelay(pdMS_TO_TICKS(8));',
    'if(wsStarted){ws.loop();drainReplies();}\n        if(online&&(lastAppHeartbeatMs==0U||(uint32_t)(now-lastAppHeartbeatMs)>=APP_HEARTBEAT_MS)){lastAppHeartbeatMs=now;sendAppHeartbeat();}\n        vTaskDelay(pdMS_TO_TICKS(8));',
    "application heartbeat service",
)

path.write_text(text, encoding="utf-8")
print("AdminSensor Remote reconnect hardening applied")
