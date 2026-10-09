Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# The classic ESP32 can have ~60-70 KiB free heap but only a ~20 KiB largest
# contiguous block while the AdminSensor WSS TLS session is active. mbedTLS may
# then fail a second outbound HTTPS handshake with MBEDTLS_ERR_SSL_ALLOC_FAILED.
#
# Arbitrate only the scarce TLS heap: when the MB publisher sees a fragmented
# heap (<32 KiB largest block), temporarily suspend the AdminSensor WSS transport,
# perform the weather HTTPS request, then immediately let Remote reconnect.
# RF, MQTT, SD and the local WebServer continue running throughout.
#
# Remote OTA always wins: a firmware update in progress is never interrupted.
# ---------------------------------------------------------------------------

# Public Remote API used by the MB worker.
h_path = "src/remote_access.h"
h = read(h_path)
if "remoteAccessPauseForExternalTls" not in h:
    anchor = "void retryRemoteAccessNow();\n"
    if anchor not in h:
        raise RuntimeError("MB TLS arbitration: remote header retry anchor missing")
    h = h.replace(
        anchor,
        anchor
        + "bool remoteAccessPauseForExternalTls(uint32_t timeoutMs);\n"
        + "void remoteAccessResumeAfterExternalTls();\n",
        1,
    )
write(h_path, h)

r_path = "src/remote_access.cpp"
r = read(r_path)

# Shared pause handshake between the MB worker and the single Remote/WSS task.
if "externalTlsPauseRequest" not in r:
    anchor = "volatile bool workerBusy=false;\n"
    if anchor not in r:
        raise RuntimeError("MB TLS arbitration: remote state anchor missing")
    r = r.replace(
        anchor,
        anchor
        + "volatile bool externalTlsPauseRequest=false;\n"
        + "volatile bool externalTlsPaused=false;\n",
        1,
    )

pause_marker = "// MB_TLS_REMOTE_PAUSE_V1"
if pause_marker not in r:
    loop_anchor = "    for(;;){\n        RemoteAccessConfig c;if(take()){c=cfg;give();}\n"
    if loop_anchor not in r:
        raise RuntimeError("MB TLS arbitration: Remote task loop anchor missing")
    pause_block = r'''    for(;;){
        // MB_TLS_REMOTE_PAUSE_V1
        if(externalTlsPauseRequest){
            if(!externalTlsPaused){
                // Flush any reply already produced by the loopback HTTP worker
                // before dropping the transport. Do not clear queues here: the
                // WSS pause is intentionally short and must not destroy work.
                if(wsStarted){
                    ws.loop();
                    drainReplies();
                    ws.disconnect();
                    wsStarted=false;
                }
                activeWsUrl="";
                if(take()){
                    st.transportActive=false;
                    if(st.configured)st.state="PAUSED_TLS";
                    st.lastWsEvent="EXTERNAL_TLS_PAUSE";
                    give();
                }
                externalTlsPaused=true;
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if(externalTlsPaused){
            externalTlsPaused=false;
            next=0;
            if(take()){
                if(st.configured)st.state="RECONNECT";
                st.lastWsEvent="EXTERNAL_TLS_RESUME";
                give();
            }
        }
        RemoteAccessConfig c;if(take()){c=cfg;give();}
'''
    r = r.replace(loop_anchor, pause_block, 1)

api_marker = "// MB_TLS_REMOTE_API_V1"
if api_marker not in r:
    anchor = "void retryRemoteAccessNow(){forceRetry=true;}\n"
    if anchor not in r:
        raise RuntimeError("MB TLS arbitration: Remote public API anchor missing")
    api = r'''void retryRemoteAccessNow(){forceRetry=true;}
// MB_TLS_REMOTE_API_V1
bool remoteAccessPauseForExternalTls(uint32_t timeoutMs){
    // Never sacrifice an authenticated firmware update for a weather upload.
    if(firmwareUpdateInProgress())return false;

    bool active=false;
    if(take()){active=st.transportActive;give();}
    if(!active)return false;

    const uint32_t started=millis();
    // If a proxied Web request is completing, allow its response to reach the
    // WSS task first. This is especially useful when "Test invio" is clicked
    // through AdminSensor itself.
    while(workerBusy && (uint32_t)(millis()-started)<timeoutMs){
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    if(workerBusy)return false;

    externalTlsPauseRequest=true;
    while(!externalTlsPaused && (uint32_t)(millis()-started)<timeoutMs){
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    if(!externalTlsPaused){
        externalTlsPauseRequest=false;
        return false;
    }

    // Give WiFiClientSecure/WebSockets a short scheduler window to release
    // their TLS buffers before the next secure client is constructed.
    vTaskDelay(pdMS_TO_TICKS(40));
    return true;
}

void remoteAccessResumeAfterExternalTls(){
    externalTlsPauseRequest=false;
}
'''
    r = r.replace(anchor, api, 1)

write(r_path, r)

# MB publisher: request the Remote pause only when fragmentation is actually
# below the observed safe envelope, and always restore Remote afterwards.
m_path = "src/mb_compatible_publisher.cpp"
m = read(m_path)
if '#include "remote_access.h"' not in m:
    anchor = '#include "network_manager.h"\n'
    if anchor not in m:
        raise RuntimeError("MB TLS arbitration: MB include anchor missing")
    m = m.replace(anchor, anchor + '#include "remote_access.h"\n', 1)

mb_marker = "// MB_TLS_MEMORY_ARBITRATION_V1"
if mb_marker not in m:
    old = '''    if (requestUrl.startsWith("https://")) {
        const uint32_t heapBefore = ESP.getFreeHeap();
        const uint32_t blockBefore = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
        WiFiClientSecure client;'''
    new = '''    if (requestUrl.startsWith("https://")) {
        // MB_TLS_MEMORY_ARBITRATION_V1
        constexpr uint32_t MB_TLS_HEAP_PAUSE_THRESHOLD = 32768U;
        const uint32_t blockInitial = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
        const bool remotePaused = blockInitial < MB_TLS_HEAP_PAUSE_THRESHOLD &&
                                  remoteAccessPauseForExternalTls(2000U);
        const uint32_t heapBefore = ESP.getFreeHeap();
        const uint32_t blockBefore = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
        WiFiClientSecure client;'''
    if old not in m:
        raise RuntimeError("MB TLS arbitration: HTTPS preflight anchor missing")
    m = m.replace(old, new, 1)

    old_diag = '''                    char diag[320];
                    snprintf(diag, sizeof(diag),
                             "HTTPS fail http=%d ssl=%d %s dns=%s tcp=%s ip=%s heap=%lu block=%lu",
                             httpCode, sslCode, sslText[0] ? sslText : "n/a",
                             dnsOk ? "ok" : "fail", tcpOk ? "ok" : "fail",
                             dnsOk ? resolved.toString().c_str() : "--",
                             static_cast<unsigned long>(heapBefore),
                             static_cast<unsigned long>(blockBefore));'''
    new_diag = '''                    char diag[384];
                    snprintf(diag, sizeof(diag),
                             "HTTPS fail http=%d ssl=%d %s dns=%s tcp=%s ip=%s heap=%lu block=%lu preblock=%lu remote_pause=%s",
                             httpCode, sslCode, sslText[0] ? sslText : "n/a",
                             dnsOk ? "ok" : "fail", tcpOk ? "ok" : "fail",
                             dnsOk ? resolved.toString().c_str() : "--",
                             static_cast<unsigned long>(heapBefore),
                             static_cast<unsigned long>(blockBefore),
                             static_cast<unsigned long>(blockInitial),
                             remotePaused ? "yes" : "no");'''
    if old_diag not in m:
        raise RuntimeError("MB TLS arbitration: HTTPS diagnostic anchor missing")
    m = m.replace(old_diag, new_diag, 1)

    # First client.stop() after the HTTPS block belongs to WiFiClientSecure.
    start = m.find(mb_marker)
    stop_anchor = "            client.stop();\n        }\n    } else {"
    pos = m.find(stop_anchor, start)
    if pos < 0:
        raise RuntimeError("MB TLS arbitration: HTTPS resume anchor missing")
    replacement = (
        "            client.stop();\n"
        "        }\n"
        "        if (remotePaused) remoteAccessResumeAfterExternalTls();\n"
        "    } else {"
    )
    m = m[:pos] + replacement + m[pos + len(stop_anchor):]

write(m_path, m)

print("MB HTTPS memory arbitration: temporary AdminSensor WSS pause enabled below 32 KiB contiguous heap")
