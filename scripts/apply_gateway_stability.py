"""Late, idempotent runtime safeguards for classic LILYGO T3 V1.6.1.

Run after the complete MB/Remote/SD rewrite passes. Do not run ahead of
apply_mb_public_tls_fix and apply_remote_runtime_v2: they canonicalize code.
"""
Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def edit(path, transform):
    f = root / path
    original = f.read_text(encoding="utf-8")
    modified = transform(original)
    if modified != original:
        f.write_text(modified, encoding="utf-8")
        print("LILYGO_STABILITY_V1:", path, "updated")
    else:
        print("LILYGO_STABILITY_V1:", path, "already applied")


def replace_once(s, old, new, label):
    if new in s:
        return s
    if old not in s:
        raise RuntimeError("LILYGO stability: missing " + label)
    return s.replace(old, new, 1)


def remote_stability(s):
    # The two Remote tasks use 12,288 + 7,168 bytes of task-stack reserves.
    # Do not reserve them if the device is not enrolled/configured. Users who
    # subsequently configure the portal from the Web UI still get both tasks.
    old = ('void initRemoteAccess(){if(!mux)mux=xSemaphoreCreateMutex();'
           'if(!requestQueue)requestQueue=xQueueCreate(HTTP_QUEUE_LEN,sizeof(RemoteReq*));'
           'if(!responseQueue)responseQueue=xQueueCreate(HTTP_QUEUE_LEN,sizeof(RemoteReply*));'
           'load();if(take()){st=RemoteAccessStatus{};st.initialized=true;'
           'st.configured=!cfg.portalUrl.isEmpty();st.deviceId=remoteDefaultDeviceId();'
           'st.state=cfg.portalUrl.isEmpty()?"OFF":"WAIT_NETWORK";st.lastWsEvent="INIT";give();}'
           'ws.onEvent(wsEvent);if(!workerHandle&&requestQueue&&responseQueue&&'
           'xTaskCreate(httpWorker,"remote-http",7168,nullptr,1,&workerHandle)!=pdPASS){'
           'workerHandle=nullptr;setState("ERROR","Worker HTTP remoto non avviato");}'
           'if(!taskHandle&&xTaskCreate(task,"adminsensor",12288,nullptr,1,&taskHandle)!=pdPASS){'
           'taskHandle=nullptr;setState("ERROR","Task remoto non avviato");}'
           'Serial.print(F("[REMOTE] Device ID: "));Serial.println(remoteDefaultDeviceId());'
           'Serial.println(F("[REMOTE] Token in NVS (non mostrato)"));}')
    new = '''void initRemoteAccess(){ // LILYGO_STABILITY_REMOTE_LAZY_V1
    if(!mux)mux=xSemaphoreCreateMutex();
    if(!requestQueue)requestQueue=xQueueCreate(HTTP_QUEUE_LEN,sizeof(RemoteReq*));
    if(!responseQueue)responseQueue=xQueueCreate(HTTP_QUEUE_LEN,sizeof(RemoteReply*));
    load();
    if(take()){
        st=RemoteAccessStatus{};st.initialized=true;
        st.configured=!cfg.portalUrl.isEmpty();st.deviceId=remoteDefaultDeviceId();
        st.state=cfg.portalUrl.isEmpty()?"OFF":"WAIT_NETWORK";st.lastWsEvent="INIT";
        give();
    }
    ws.onEvent(wsEvent);
    if(!cfg.portalUrl.isEmpty())startRemoteTasks();
    else Serial.println(F("[REMOTE] no portal: network task stacks not allocated"));
    Serial.print(F("[REMOTE] Device ID: "));Serial.println(remoteDefaultDeviceId());
    Serial.println(F("[REMOTE] Token in NVS (non mostrato)"));
}'''
    s = replace_once(s, old, new, 'Remote init')
    old_save = ('generation++;return true;}\n'
                'bool resetRemoteAccessConfig(){return saveRemoteAccessPortalUrl("");}')
    new_save = ('generation++;\n'
                '    if(!u.isEmpty())startRemoteTasks(); // enable from UI without reboot\n'
                '    return true;}\n'
                'bool resetRemoteAccessConfig(){return saveRemoteAccessPortalUrl("");}')
    s = replace_once(s, old_save, new_save, 'Remote saved URL')
    # Place task factory at the end of the anonymous namespace, where worker
    # and websocket task function definitions are already visible.
    factory = '''// LILYGO_STABILITY_REMOTE_TASK_FACTORY_V1
bool startRemoteTasks(){
    if(!requestQueue || !responseQueue){
        setState("ERROR","Code Remote non disponibili");return false;
    }
    if(!workerHandle &&
       xTaskCreate(httpWorker,"remote-http",7168,nullptr,1,&workerHandle)!=pdPASS){
        workerHandle=nullptr;setState("ERROR","Worker HTTP remoto non avviato");return false;
    }
    if(!taskHandle &&
       xTaskCreate(task,"adminsensor",12288,nullptr,1,&taskHandle)!=pdPASS){
        taskHandle=nullptr;setState("ERROR","Task remoto non avviato");return false;
    }
    return workerHandle!=nullptr && taskHandle!=nullptr;
}
'''
    # Function is defined in the same anonymous namespace, earlier than API use.
    if 'LILYGO_STABILITY_REMOTE_TASK_FACTORY_V1' not in s:
        anchor = '} // namespace\n\nString remoteDefaultDeviceId()'
        if anchor not in s:
            raise RuntimeError('LILYGO stability: Remote namespace end missing')
        s = s.replace(anchor, factory + '} // namespace\n\nString remoteDefaultDeviceId()', 1)
    return s


def mb_stability(s):
    # Existing TLS arbitration can fail when a WSS request is busy or OTA
    # forbids suspension. Never launch *another* mbedTLS handshake in that case.
    s = replace_once(s,
        '''        const bool remotePaused = blockInitial < MB_TLS_HEAP_PAUSE_THRESHOLD &&
                                  remoteAccessPauseForExternalTls(2000U);
        const uint32_t heapBefore''',
        '''        const bool remotePaused = blockInitial < MB_TLS_HEAP_PAUSE_THRESHOLD &&
                                  remoteAccessPauseForExternalTls(2000U);
        // LILYGO_STABILITY_TLS_GUARD_V1: prefer an omitted report to MCU reset.
        if(blockInitial < MB_TLS_HEAP_PAUSE_THRESHOLD && !remotePaused){
            setStatusError("HTTPS deferred: insufficient contiguous heap for a second TLS session");
            gBusy=false;
            return;
        }
        const uint32_t heapBefore''', 'MB TLS second handshake guard')
    old_init = '''#if CONFIG_FREERTOS_UNICORE
    const BaseType_t core = 0;
#else
    const BaseType_t core = 0;
#endif
    if (xTaskCreatePinnedToCore(worker, "mb-compatible", WORKER_STACK, nullptr, 1, &gWorkerTask, core) != pdPASS) {
        gWorkerTask = nullptr;
        setStatusError("worker task creation failed");
    }
    Serial.println(F("[MB-COMPAT] publisher initialized (disabled by default)"));'''
    new_init = '''// LILYGO_STABILITY_MB_LAZY_V1: reserve stack only if publisher enabled.
    if(gConfig.enabled)ensureMbWorker();
    Serial.println(F("[MB-COMPAT] publisher initialized"));'''
    s = replace_once(s, old_init, new_init, 'MB init worker')
    old_service = '''    if (!gState || !gWorkerTask || !wifiConnected() || gBusy || gPending) return;
    const MbCompatibleConfig cfg = getMbCompatibleConfig();'''
    new_service = '''    if (!gState || !wifiConnected() || gBusy || gPending) return;
    const MbCompatibleConfig cfg = getMbCompatibleConfig();
    if(!gWorkerTask && (cfg.enabled || gForceTest)){
        // Throttle allocation retries if memory is extremely low.
        static uint32_t nextWorkerRetryMs=0;
        const uint32_t current=millis();
        if(!nextWorkerRetryMs || (int32_t)(current-nextWorkerRetryMs)>=0){
            nextWorkerRetryMs=current+30000UL;
            ensureMbWorker();
        }
    }
    if(!gWorkerTask)return;'''
    s = replace_once(s, old_service, new_service, 'MB service worker')
    factory = '''// LILYGO_STABILITY_MB_TASK_FACTORY_V1
bool ensureMbWorker(){
    if(gWorkerTask)return true;
    // The original worker uses core 0 on the T3 ESP32 and T3-S3 targets.
    const BaseType_t core=0;
    if(xTaskCreatePinnedToCore(worker,"mb-compatible",WORKER_STACK,nullptr,1,
                               &gWorkerTask,core)!=pdPASS){
        gWorkerTask=nullptr;
        setStatusError("worker task creation failed - insufficient heap");
        return false;
    }
    return true;
}
'''
    if 'LILYGO_STABILITY_MB_TASK_FACTORY_V1' not in s:
        anchor='} // namespace\n\nconst char *mbCompatibleTlsModeName('
        if anchor not in s:
            raise RuntimeError('LILYGO stability: MB namespace end missing')
        s=s.replace(anchor,factory+'} // namespace\n\nconst char *mbCompatibleTlsModeName(',1)
    return s


def web_diagnostics(s):
    if '#include <esp_heap_caps.h>' not in s:
        s=s.replace('#include <Arduino.h>\n','#include <Arduino.h>\n#include <esp_heap_caps.h>\n#include <freertos/task.h>\n',1)
    return replace_once(s,
        '''    out += ",\\"heap_min_free\\":" + String(heapMin);''',
        '''    out += ",\\"heap_min_free\\":" + String(heapMin);
    // LILYGO_STABILITY_WEB_DIAG_V1: fragmentation + loop-task stack headroom.
    out += ",\\"heap_largest_block\\":" + String(heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
    out += ",\\"loop_stack_min_free_bytes\\":" + String(uxTaskGetStackHighWaterMark(nullptr));''',
        'Web API heap/stack diagnostics')


def boot_diagnostics(s):
    if '#include "firmware_info.h"' not in s:
        s=s.replace('#include "config.h"\n','#include "config.h"\n#include "firmware_info.h"\n',1)
    return replace_once(s,
        '''    Serial.println(F(" RF: SX1278 OOK direct RAW EDGE"));''',
        '''    // LILYGO_STABILITY_BOOT_DIAG_V1
    Serial.print(F("[BOOT] last_reset="));Serial.println(firmwareResetReason());
    Serial.print(F("[BOOT] heap_free="));Serial.print(ESP.getFreeHeap());
    Serial.print(F(" heap_min="));Serial.println(ESP.getMinFreeHeap());
    Serial.println(F(" RF: SX1278 OOK direct RAW EDGE"));''',
        'Serial boot diagnostics')

edit('src/remote_access.cpp', remote_stability)
edit('src/mb_compatible_publisher.cpp', mb_stability)
edit('src/web_manager.cpp', web_diagnostics)
edit('src/main.cpp', boot_diagnostics)

# Normalize SD auth routes after the last Web regeneration pass.
# Generate strict-auth handlers on both first and subsequent builds.
edit('src/web_manager.cpp', lambda s: s.replace(
    'server.on("/api/sd/files", HTTP_GET, handleSdFiles);',
    'server.on("/api/sd/files", HTTP_GET, [](){ if (!requireWebAuth()) return; handleSdFiles(); });'
).replace(
    'server.on("/api/sd/read", HTTP_GET, handleSdRead);',
    'server.on("/api/sd/read", HTTP_GET, [](){ if (!requireWebAuth()) return; handleSdRead(); });'
))

# A cosmetic empty line can be removed by a late SD compatibility pass.
# Canonicalize it for repeat-build byte-for-byte reproducibility.
edit('src/sd_logger.cpp', lambda s: s.replace(
    '    return ok;\n#endif\n}\n\n\n// ADMIN_SENSOR_SD_BROWSER_V1',
    '    return ok;\n#endif\n}\n\n// ADMIN_SENSOR_SD_BROWSER_V1',
    1
))
