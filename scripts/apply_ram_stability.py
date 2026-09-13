Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def function_bounds(text, signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"RAM stability: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"RAM stability: opening brace missing: {signature}")
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
    raise RuntimeError(f"RAM stability: unclosed function: {signature}")


# ---------------------------------------------------------------------------
# COMPATIBLE MB: do not reserve an 8 KiB FreeRTOS stack when the publisher is
# disabled. The worker is created on first real send/test instead. This leaves
# RF behaviour untouched and preserves the existing asynchronous transport.
# ---------------------------------------------------------------------------
mb_path = "src/mb_compatible_publisher.cpp"
mb = read(mb_path)
mb_marker = "RAM_STABILITY_MB_LAZY_V1"

if mb_marker not in mb:
    if "#include <freertos/task.h>" not in mb:
        inc = "#include <time.h>\n"
        if inc not in mb:
            raise RuntimeError("RAM stability MB: include anchor missing")
        mb = mb.replace(inc, inc + "#include <freertos/task.h>\n", 1)

    init_sig = "void initMbCompatiblePublisher(StationState &state)"
    init_start = mb.find(init_sig)
    if init_start < 0:
        raise RuntimeError("RAM stability MB: init function missing")

    helper = r'''bool ensureMbCompatibleWorker() { // RAM_STABILITY_MB_LAZY_V1
    if (gWorkerTask) return true;
    const BaseType_t core = 0;
    if (xTaskCreatePinnedToCore(worker, "mb-compatible", WORKER_STACK, nullptr, 1, &gWorkerTask, core) != pdPASS) {
        gWorkerTask = nullptr;
        setStatusError("worker task creation failed");
        return false;
    }
    return true;
}

'''
    mb = mb[:init_start] + helper + mb[init_start:]

    s, e = function_bounds(mb, init_sig)
    init_new = r'''void initMbCompatiblePublisher(StationState &state) {
    gState = &state;
    gMutex = xSemaphoreCreateMutex();
    loadConfig();
    loadDailyBaselines();
    configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");
    // RAM_STABILITY_MB_LAZY_V1: worker allocation is deferred until a real
    // transmission/test is requested. Disabled-by-default now costs no 8 KiB
    // task stack at boot.
    Serial.println(F("[MB-COMPAT] publisher initialized (lazy worker)"));
}'''
    mb = mb[:s] + init_new + mb[e:]

    old = "    if (!gState || !gWorkerTask || !wifiConnected() || gBusy || gPending) return;"
    new = "    if (!gState || !wifiConnected() || gBusy || gPending) return;"
    if old not in mb:
        raise RuntimeError("RAM stability MB: service guard anchor missing")
    mb = mb.replace(old, new, 1)

    old = "    const bool force = gForceTest;\n    if (!force && !cfg.enabled) return;"
    new = (
        "    const bool force = gForceTest;\n"
        "    if (!force && !cfg.enabled) return;\n"
        "    if (!ensureMbCompatibleWorker()) {\n"
        "        if (force) gForceTest = false;\n"
        "        return;\n"
        "    }"
    )
    if old not in mb:
        raise RuntimeError("RAM stability MB: enable/test anchor missing")
    mb = mb.replace(old, new, 1)

    # Expose measured free stack so a later release can safely right-size the
    # 8 KiB worker instead of guessing.
    status_sig = "String mbCompatibleConfigStatusJson()"
    s, e = function_bounds(mb, status_sig)
    block = mb[s:e]
    if "worker_stack_hwm_bytes" not in block:
        anchor = '    out += ",\\\"pending\\\":"; out += gPending ? "true" : "false";\n'
        if anchor not in block:
            raise RuntimeError("RAM stability MB: status pending anchor missing")
        extra = (
            anchor
            + '    out += ",\\\"worker_stack_hwm_bytes\\\":" + String(gWorkerTask ? static_cast<uint32_t>(uxTaskGetStackHighWaterMark(gWorkerTask)) : 0U);\n'
        )
        block = block.replace(anchor, extra, 1)
        mb = mb[:s] + block + mb[e:]

    write(mb_path, mb)
    print("RAM stability: COMPATIBLE MB worker is lazy; 8 KiB stack avoided while disabled")
else:
    print("RAM stability: COMPATIBLE MB lazy worker already applied")


# ---------------------------------------------------------------------------
# AdminSensor Remote: avoid reserving ~19 KiB of task stacks plus queue storage
# when no portal is configured. Runtime is instantiated on first configuration
# save/retry. Existing chunked WSS/TLS memory safeguards remain untouched.
# ---------------------------------------------------------------------------
remote_path = "src/remote_access.cpp"
remote = read(remote_path)
remote_marker = "RAM_STABILITY_REMOTE_LAZY_V1"

if remote_marker not in remote:
    close_anchor = "} // namespace\n\nString remoteDefaultDeviceId()"
    if close_anchor not in remote:
        raise RuntimeError("RAM stability Remote: namespace close anchor missing")

    helper = r'''bool ensureRemoteRuntime() { // RAM_STABILITY_REMOTE_LAZY_V1
    if (!requestQueue) requestQueue=xQueueCreate(HTTP_QUEUE_LEN,sizeof(RemoteReq*));
    if (!responseQueue) responseQueue=xQueueCreate(HTTP_QUEUE_LEN,sizeof(RemoteReply*));
    if (!requestQueue || !responseQueue) {
        setState("ERROR","Code Remote non allocate");
        return false;
    }
    if (!workerHandle && xTaskCreate(httpWorker,"remote-http",7168,nullptr,1,&workerHandle)!=pdPASS) {
        workerHandle=nullptr;
        setState("ERROR","Worker HTTP remoto non avviato");
        return false;
    }
    if (!taskHandle && xTaskCreate(task,"adminsensor",12288,nullptr,1,&taskHandle)!=pdPASS) {
        taskHandle=nullptr;
        setState("ERROR","Task remoto non avviato");
        return false;
    }
    return true;
}

'''
    remote = remote.replace(close_anchor, helper + close_anchor, 1)

    init_sig = "void initRemoteAccess()"
    s, e = function_bounds(remote, init_sig)
    init_new = r'''void initRemoteAccess(){
    if(!mux)mux=xSemaphoreCreateMutex();
    load();
    if(take()){
        st=RemoteAccessStatus{};
        st.initialized=true;
        st.configured=!cfg.portalUrl.isEmpty();
        st.deviceId=remoteDefaultDeviceId();
        st.state=cfg.portalUrl.isEmpty()?"OFF":"WAIT_NETWORK";
        st.lastWsEvent="INIT";
        give();
    }
    ws.onEvent(wsEvent);
    // RAM_STABILITY_REMOTE_LAZY_V1: an unconfigured device keeps no Remote
    // HTTP/AdminSensor task stacks. Existing configured installations start
    // exactly as before.
    if(!cfg.portalUrl.isEmpty())ensureRemoteRuntime();
    Serial.print(F("[REMOTE] Device ID: "));Serial.println(remoteDefaultDeviceId());
    Serial.println(F("[REMOTE] Token in NVS (non mostrato)"));
}'''
    remote = remote[:s] + init_new + remote[e:]

    save_sig = "bool saveRemoteAccessPortalUrl(const String&in)"
    s, e = function_bounds(remote, save_sig)
    block = remote[s:e]
    if "ensureRemoteRuntime" not in block:
        old = "generation++;return true;"
        new = "generation++;if(!u.isEmpty()&&!ensureRemoteRuntime())return false;return true;"
        if old not in block:
            raise RuntimeError("RAM stability Remote: save generation anchor missing")
        block = block.replace(old, new, 1)
        remote = remote[:s] + block + remote[e:]

    old_retry = "void retryRemoteAccessNow(){forceRetry=true;}"
    if old_retry in remote:
        remote = remote.replace(
            old_retry,
            "void retryRemoteAccessNow(){if(ensureRemoteRuntime())forceRetry=true;}",
            1,
        )

    status_sig = "String remoteAccessStatusJson()"
    s, e = function_bounds(remote, status_sig)
    block = remote[s:e]
    if "task_stack_hwm_bytes" not in block:
        anchor = 'j+=",\\\"last_activity_age_ms\\\":"'
        if anchor not in block:
            raise RuntimeError("RAM stability Remote: status activity anchor missing")
        extra = (
            'j+=",\\\"task_stack_hwm_bytes\\\":"+String(taskHandle?static_cast<uint32_t>(uxTaskGetStackHighWaterMark(taskHandle)):0U);'
            'j+=",\\\"http_stack_hwm_bytes\\\":"+String(workerHandle?static_cast<uint32_t>(uxTaskGetStackHighWaterMark(workerHandle)):0U);'
        )
        block = block.replace(anchor, extra + anchor, 1)
        remote = remote[:s] + block + remote[e:]

    write(remote_path, remote)
    print("RAM stability: AdminSensor Remote task stacks are lazy when unconfigured")
else:
    print("RAM stability: AdminSensor Remote lazy runtime already applied")


# ---------------------------------------------------------------------------
# Web diagnostics: halve raw history RAM and expose contiguous heap health.
# Free heap alone can look healthy while TLS fails because the largest block is
# small; report both current/minimum largest block and fragmentation percentage.
# ---------------------------------------------------------------------------
web_path = "src/web_manager.cpp"
web = read(web_path)
web_marker = "RAM_STABILITY_HEAP_METRICS_V1"

if web_marker not in web:
    if "#include <esp_heap_caps.h>" not in web:
        inc = "#include <Arduino.h>\n"
        if inc not in web:
            raise RuntimeError("RAM stability Web: Arduino include anchor missing")
        web = web.replace(inc, inc + "#include <esp_heap_caps.h>\n", 1)

    old = "constexpr uint8_t RAW_HISTORY_SIZE = 32;"
    if old not in web:
        raise RuntimeError("RAM stability Web: raw history size anchor missing")
    web = web.replace(old, "constexpr uint8_t RAW_HISTORY_SIZE = 16; // RAM_STABILITY_HEAP_METRICS_V1", 1)

    web = web.replace("out.reserve(7000);", "out.reserve(4500);", 1)
    web = web.replace("out.reserve(5500);", "out.reserve(3200);", 1)

    heap_anchor = "    const uint32_t heapMin = ESP.getMinFreeHeap();\n"
    if heap_anchor not in web:
        raise RuntimeError("RAM stability Web: heap metrics anchor missing")
    heap_extra = r'''    const uint32_t heapLargest = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
    static uint32_t heapLargestMin = 0xFFFFFFFFUL;
    if (heapLargest < heapLargestMin) heapLargestMin = heapLargest;
    const uint32_t heapFragmentationPct = (heapFree && heapLargest <= heapFree)
        ? 100U - static_cast<uint32_t>((static_cast<uint64_t>(heapLargest) * 100ULL) / heapFree)
        : 0U;
'''
    web = web.replace(heap_anchor, heap_anchor + heap_extra, 1)

    json_anchor = '    out += ",\\\"heap_min_free\\\":" + String(heapMin);\n'
    if json_anchor not in web:
        raise RuntimeError("RAM stability Web: heap JSON anchor missing")
    json_extra = (
        json_anchor
        + '    out += ",\\\"heap_largest_free\\\":" + String(heapLargest);\n'
        + '    out += ",\\\"heap_largest_min\\\":" + String(heapLargestMin);\n'
        + '    out += ",\\\"heap_fragmentation_pct\\\":" + String(heapFragmentationPct);\n'
    )
    web = web.replace(json_anchor, json_extra, 1)

    write(web_path, web)
    print("RAM stability: raw Web history 32->16; contiguous heap telemetry enabled")
else:
    print("RAM stability: Web heap/history optimization already applied")


# ---------------------------------------------------------------------------
# Dashboard polling: 2 s local state refresh is unnecessarily allocation-heavy
# for a weather gateway. 3 s keeps the UI responsive while cutting state JSON
# construction churn by one third. Remote remains at its existing 5 s cadence.
# ---------------------------------------------------------------------------
dash_path = "web/dashboard.html"
dash = read(dash_path)
poll_old = "setInterval(safeRefresh,remoteUi?5000:2000);"
poll_new = "setInterval(safeRefresh,remoteUi?5000:3000); // RAM_STABILITY_WEB_POLL_V1"
if poll_old in dash:
    dash = dash.replace(poll_old, poll_new, 1)
    write(dash_path, dash)
    print("RAM stability: local dashboard state polling 2 s -> 3 s")
elif "RAM_STABILITY_WEB_POLL_V1" in dash:
    print("RAM stability: dashboard polling already optimized")
else:
    raise RuntimeError("RAM stability: dashboard safeRefresh timer anchor missing")
