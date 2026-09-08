Import("env")
from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def function_bounds(text, signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Remote runtime V2: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Remote runtime V2: opening brace missing: {signature}")
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
                return start, i + 1
    raise RuntimeError(f"Remote runtime V2: unclosed function: {signature}")


# ---------------------------------------------------------------------------
# AdminSensor / Meteobridge TLS arbitration V2.
#
# V1 proved the root cause on real T3 V1.6.1 hardware: while AdminSensor WSS is
# active the second mbedTLS client can fail with MBEDTLS_ERR_SSL_ALLOC_FAILED.
# V1 solved that by dropping WSS for the short MB upload, but also cleared the
# approved websocket URL. The Remote task then repeated HTTPS enrollment before
# reconnecting WSS, making the GUI visibly slow every MB cycle.
#
# V2 keeps the already-approved websocket URL across the intentional TLS pause
# and reconnects directly to it after the MB transaction. No new enrollment is
# needed. OTA remains authoritative: the V1 API already refuses to pause WSS
# while a firmware update is active.
# ---------------------------------------------------------------------------
r_path = "src/remote_access.cpp"
r = read(r_path)

if "MB_TLS_REMOTE_PAUSE_V1" not in r or "MB_TLS_REMOTE_API_V1" not in r:
    raise RuntimeError("Remote runtime V2: V1 TLS arbitration must run first")

if "externalTlsPauseCount" not in r:
    anchor = "volatile bool externalTlsPaused=false;\n"
    if anchor not in r:
        raise RuntimeError("Remote runtime V2: external TLS state anchor missing")
    r = r.replace(
        anchor,
        anchor
        + "volatile uint32_t externalTlsPauseCount=0;\n"
        + "volatile uint32_t externalTlsDirectReconnectCount=0;\n",
        1,
    )

# Work only inside the task prelude so legitimate activeWsUrl clears on manual
# retry/configuration changes remain untouched.
pause_start = r.find("// MB_TLS_REMOTE_PAUSE_V1")
pause_end = r.find("RemoteAccessConfig c;if(take()){c=cfg;give();}", pause_start)
if pause_start < 0 or pause_end < 0:
    raise RuntimeError("Remote runtime V2: pause block bounds missing")
seg = r[pause_start:pause_end]
if 'activeWsUrl="";' in seg:
    seg = seg.replace('                activeWsUrl="";\n', "", 1)

if "externalTlsPauseCount++;" not in seg:
    anchor = "                externalTlsPaused=true;\n"
    if anchor not in seg:
        raise RuntimeError("Remote runtime V2: pause acknowledge anchor missing")
    seg = seg.replace(anchor, "                externalTlsPauseCount++;\n" + anchor, 1)

old_resume = '''        if(externalTlsPaused){
            externalTlsPaused=false;
            next=0;
            if(take()){
                if(st.configured)st.state="RECONNECT";
                st.lastWsEvent="EXTERNAL_TLS_RESUME";
                give();
            }
        }
'''
new_resume = '''        if(externalTlsPaused){
            // ADMIN_SENSOR_RUNTIME_V2
            // Keep the approved WSS URL obtained by the last successful enroll.
            // A weather upload therefore costs one short TLS reconnect, not an
            // HTTPS enroll followed by another TLS handshake.
            externalTlsPaused=false;
            const String resumeUrl=activeWsUrl;
            bool directReconnect=false;
            if(!resumeUrl.isEmpty()&&!firmwareUpdateInProgress()){
                directReconnect=startWs(resumeUrl);
                if(directReconnect)externalTlsDirectReconnectCount++;
            }
            next=directReconnect?millis()+RETRY_APPROVED:0U;
            if(take()){
                if(st.configured&&!directReconnect)st.state="RECONNECT";
                st.lastWsEvent=directReconnect?"EXTERNAL_TLS_DIRECT_RECONNECT":"EXTERNAL_TLS_RESUME";
                give();
            }
        }
'''
if old_resume in seg:
    seg = seg.replace(old_resume, new_resume, 1)
elif "ADMIN_SENSOR_RUNTIME_V2" not in seg:
    raise RuntimeError("Remote runtime V2: V1 resume block missing")

r = r[:pause_start] + seg + r[pause_end:]

# Replace the status JSON function so runtime measurements are observable during
# the soak test. High-water marks are deliberately measured before changing any
# task stack sizes; stack sizes are not reduced blindly.
status_fn = r'''String remoteAccessStatusJson(){
    RemoteAccessStatus s=getRemoteAccessStatus();
    String j="{\"initialized\":";j+=s.initialized?"true":"false";
    j+=",\"configured\":";j+=s.configured?"true":"false";
    j+=",\"approved\":";j+=s.approved?"true":"false";
    j+=",\"transport_active\":";j+=s.transportActive?"true":"false";
    j+=",\"state\":\""+esc(s.state)+"\",\"device_id\":\""+esc(s.deviceId)+"\",\"enroll_attempts\":"+String(s.enrollAttempts)+",\"last_enroll_http_code\":"+String(s.lastEnrollHttpCode);
    j+=",\"ws_attempts\":"+String(s.wsAttempts)+",\"ws_connects\":"+String(s.wsConnects)+",\"ws_disconnects\":"+String(s.wsDisconnects);
    j+=",\"ws_host\":\""+esc(s.wsHost)+"\",\"ws_path\":\""+esc(s.wsPath)+"\",\"last_ws_event\":\""+esc(s.lastWsEvent)+"\"";
    j+=",\"requests\":"+String(s.requests)+",\"responses\":"+String(s.responses)+",\"http_queue\":"+String(requestQueue?uxQueueMessagesWaiting(requestQueue):0)+",\"http_worker_busy\":"+(workerBusy?String("true"):String("false"))+",\"queue_drops\":"+String(queueDrops);
    j+=",\"last_activity_age_ms\":"+(s.lastActivityMs?String((uint32_t)(millis()-s.lastActivityMs)):String("null"))+",\"last_error\":\""+esc(s.lastError)+"\"";
    j+=",\"heap_free\":"+String(ESP.getFreeHeap());
    j+=",\"heap_largest\":"+String(heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
    j+=",\"stack_admin_hwm\":"+String(taskHandle?uxTaskGetStackHighWaterMark(taskHandle):0U);
    j+=",\"stack_http_hwm\":"+String(workerHandle?uxTaskGetStackHighWaterMark(workerHandle):0U);
    j+=",\"tls_pause_count\":"+String(externalTlsPauseCount);
    j+=",\"tls_direct_reconnects\":"+String(externalTlsDirectReconnectCount);
    j+=",\"firmware_update\":"+firmwareUpdateStatusJson()+"}";
    return j;
}'''
start, end = function_bounds(r, "String remoteAccessStatusJson()")
r = r[:start] + status_fn + r[end:]
write(r_path, r)
print("Remote runtime V2: WSS direct reconnect + heap/stack diagnostics enabled")


# ---------------------------------------------------------------------------
# MB worker runtime measurements. Keep the proven 8 KiB stack until the real
# high-water mark is known; expose the measurement instead of guessing.
# ---------------------------------------------------------------------------
m_path = "src/mb_compatible_publisher.cpp"
m = read(m_path)
if "#include <freertos/task.h>" not in m:
    inc = "#include <time.h>\n"
    if inc not in m:
        raise RuntimeError("Remote runtime V2: MB task include anchor missing")
    m = m.replace(inc, inc + "#include <freertos/task.h>\n", 1)
if "#include <esp_heap_caps.h>" not in m:
    inc = "#include <freertos/task.h>\n"
    m = m.replace(inc, inc + "#include <esp_heap_caps.h>\n", 1)

mb_start, mb_end = function_bounds(m, "String mbCompatibleConfigStatusJson()")
mb_seg = m[mb_start:mb_end]
if '"worker_stack_hwm"' not in mb_seg:
    anchor = '    out += ",\\\"payload_fields\\\":" + String(fieldCount);\n'
    if anchor not in mb_seg:
        raise RuntimeError("Remote runtime V2: MB status payload anchor missing")
    mb_seg = mb_seg.replace(
        anchor,
        anchor
        + '    out += ",\\\"worker_stack_hwm\\\":" + String(gWorkerTask ? uxTaskGetStackHighWaterMark(gWorkerTask) : 0U);\n'
        + '    out += ",\\\"heap_largest\\\":" + String(heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));\n',
        1,
    )
    m = m[:mb_start] + mb_seg + m[mb_end:]
write(m_path, m)
print("Remote runtime V2: MB worker high-water mark exposed")


# ---------------------------------------------------------------------------
# Adaptive remote Web UI polling.
#
# The local browser keeps its fast behaviour. Through AdminSensor every fetch is
# a loopback HTTP transaction plus WSS framing, so only the visible page gets the
# higher cadence. CONFIGURAZIONE is deliberately slower and secondary endpoints
# are lazy/gated. This reduces transient allocations without hiding data.
# ---------------------------------------------------------------------------
d_path = "web/dashboard.html"
d = read(d_path)

if "ADMIN_SENSOR_REMOTE_POLL_V2" not in d and "ADMIN_SENSOR_REMOTE_POLL_V3" not in d:
    raise RuntimeError("Remote runtime V2: Remote polling V2 must run first")
d = d.replace("ADMIN_SENSOR_REMOTE_POLL_V2", "ADMIN_SENSOR_REMOTE_POLL_V3", 1)

old_helpers = '''let refreshBusy=false,lightningBusy=false,mqttBusy=false;
async function safeRefresh(){if(refreshBusy)return;refreshBusy=true;try{await refresh();}finally{refreshBusy=false}}
async function safeLightning(){if(lightningBusy)return;lightningBusy=true;try{await refreshLightning();}finally{lightningBusy=false}}
async function safeMqtt(){if(mqttBusy)return;mqttBusy=true;try{await loadMqtt();}finally{mqttBusy=false}}
'''
new_helpers = '''let refreshBusy=false,lightningBusy=false,mqttBusy=false,lastStateFetchMs=0,lastLightningFetchMs=0,lastMqttFetchMs=0;
function cfgActive(id){const e=E(id);return !!(e&&e.classList.contains('active'))}
function remoteStatePeriod(){if(!remoteUi)return 2000;if(mainTab==='config')return 15000;if(mainTab==='diag')return 8000;if(mainTab==='hardware')return 8000;return 5000}
async function safeRefresh(force=false){const now=Date.now(),period=remoteStatePeriod();if(refreshBusy||(!force&&now-lastStateFetchMs<period))return;refreshBusy=true;try{await refresh();lastStateFetchMs=Date.now()}finally{refreshBusy=false}}
async function safeLightning(force=false){const visible=mainTab==='dashboard'||(mainTab==='config'&&cfgActive('cfgLightning'));if(lightningBusy||(remoteUi&&!force&&!visible)||(remoteUi&&!force&&Date.now()-lastLightningFetchMs<10000))return;lightningBusy=true;try{await refreshLightning();lastLightningFetchMs=Date.now()}finally{lightningBusy=false}}
async function safeMqtt(force=false){const editing=mainTab==='config'&&cfgActive('cfgMqtt');if(mqttBusy||(!force&&editing)||(remoteUi&&!force&&mainTab!=='dashboard')||(remoteUi&&!force&&Date.now()-lastMqttFetchMs<30000))return;mqttBusy=true;try{await loadMqtt();lastMqttFetchMs=Date.now()}finally{mqttBusy=false}}
'''
if old_helpers in d:
    d = d.replace(old_helpers, new_helpers, 1)
elif new_helpers not in d:
    raise RuntimeError("Remote runtime V2: polling helper anchor missing")

old_startup = '''safeRefresh();
setTimeout(safeLightning,remoteUi?1200:0);
setTimeout(safeMqtt,remoteUi?2500:0);
'''
new_startup = '''safeRefresh(true);
if(remoteUi){setTimeout(()=>safeLightning(true),2500);setTimeout(()=>safeMqtt(true),5000);}else{safeLightning(true);safeMqtt(true);}
'''
if old_startup in d:
    d = d.replace(old_startup, new_startup, 1)
elif new_startup not in d:
    raise RuntimeError("Remote runtime V2: startup polling anchor missing")

repls = {
    "setInterval(safeRefresh,remoteUi?5000:2000);": "setInterval(()=>safeRefresh(false),2000);",
    "setInterval(safeLightning,remoteUi?10000:2000);": "setInterval(()=>safeLightning(false),remoteUi?2500:2000);",
    "setInterval(()=>{const editing=mainTab==='config'&&E('cfgMqtt')&&E('cfgMqtt').classList.contains('active');if(!editing)safeMqtt();},remoteUi?30000:10000);": "setInterval(()=>safeMqtt(false),remoteUi?5000:10000);",
}
for old, new in repls.items():
    if old in d:
        d = d.replace(old, new, 1)
    elif new not in d:
        raise RuntimeError(f"Remote runtime V2: polling timer anchor missing: {old[:32]}")

# Entering CONFIGURAZIONE used to issue Network and MQTT together. The default
# config page is RETE/WI-FI; MQTT is loaded by showCfgTab() only when selected.
d = d.replace("if(t==='config')loadNetwork();if(t==='config')loadMqtt();", "if(t==='config')loadNetwork();", 1)

# The final SD browser inserts a separate remote /api/sd badge poll. /api/state
# already carries SD status, while the MICROSD tab itself loads /api/sd on demand.
# Keep the dedicated 4 s badge refresh only for the local UI.
sd_old = "setTimeout(refreshSdHeader,remoteUi?3500:0);setInterval(refreshSdHeader,remoteUi?15000:4000);"
sd_new = "if(!remoteUi){refreshSdHeader();setInterval(refreshSdHeader,4000);}"
if sd_old in d:
    d = d.replace(sd_old, sd_new, 1)
elif sd_new not in d:
    raise RuntimeError("Remote runtime V2: final SD polling anchor missing")

write(d_path, d)
print("Remote runtime V2: adaptive/lazy AdminSensor Web polling enabled; remote SD badge poll removed")
