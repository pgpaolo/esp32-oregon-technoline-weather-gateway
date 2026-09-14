Import("env")

from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
MARKER = "RUNTIME_MEMORY_V3"


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def function_bounds(text, signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Runtime memory V3: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Runtime memory V3: opening brace missing: {signature}")
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
    raise RuntimeError(f"Runtime memory V3: unclosed function: {signature}")


# ---------------------------------------------------------------------------
# 1) Task-stack measurement made explicit in bytes.
#
# ESP-IDF's uxTaskGetStackHighWaterMark() reports bytes on ESP32. Keep the
# proven stack allocations unchanged in V3; expose allocated bytes and peak
# used bytes so a later reduction is based on a real soak test, not a guess.
# ---------------------------------------------------------------------------
remote_path = "src/remote_access.cpp"
remote = read(remote_path)

if f"// {MARKER}_REMOTE" not in remote:
    anchor = "constexpr UBaseType_t HTTP_QUEUE_LEN=2;\n"
    if anchor not in remote:
        raise RuntimeError("Runtime memory V3: final Remote queue anchor missing")
    remote = remote.replace(
        anchor,
        anchor
        + f"// {MARKER}_REMOTE\n"
        + "constexpr uint32_t REMOTE_HTTP_STACK_BYTES=7168U;\n"
        + "constexpr uint32_t REMOTE_ADMIN_STACK_BYTES=12288U;\n",
        1,
    )

    old_http = 'xTaskCreate(httpWorker,"remote-http",7168,nullptr,1,&workerHandle)'
    old_admin = 'xTaskCreate(task,"adminsensor",12288,nullptr,1,&taskHandle)'
    if old_http not in remote or old_admin not in remote:
        raise RuntimeError("Runtime memory V3: Remote task-create anchors missing")
    remote = remote.replace(
        old_http,
        'xTaskCreate(httpWorker,"remote-http",REMOTE_HTTP_STACK_BYTES,nullptr,1,&workerHandle)',
        1,
    )
    remote = remote.replace(
        old_admin,
        'xTaskCreate(task,"adminsensor",REMOTE_ADMIN_STACK_BYTES,nullptr,1,&taskHandle)',
        1,
    )

    sig = "String remoteAccessStatusJson()"
    s, e = function_bounds(remote, sig)
    seg = remote[s:e]

    local_anchor = "    RemoteAccessStatus s=getRemoteAccessStatus();\n"
    if local_anchor not in seg:
        raise RuntimeError("Runtime memory V3: Remote status local anchor missing")
    seg = seg.replace(
        local_anchor,
        local_anchor
        + "    const uint32_t adminHwm=taskHandle?uxTaskGetStackHighWaterMark(taskHandle):0U;\n"
        + "    const uint32_t httpHwm=workerHandle?uxTaskGetStackHighWaterMark(workerHandle):0U;\n"
        + "    const uint32_t adminPeak=(adminHwm<=REMOTE_ADMIN_STACK_BYTES)?REMOTE_ADMIN_STACK_BYTES-adminHwm:0U;\n"
        + "    const uint32_t httpPeak=(httpHwm<=REMOTE_HTTP_STACK_BYTES)?REMOTE_HTTP_STACK_BYTES-httpHwm:0U;\n",
        1,
    )

    old_stack = (
        '    j+=",\\\"stack_admin_hwm\\\":"+String(taskHandle?uxTaskGetStackHighWaterMark(taskHandle):0U);\n'
        '    j+=",\\\"stack_http_hwm\\\":"+String(workerHandle?uxTaskGetStackHighWaterMark(workerHandle):0U);\n'
    )
    new_stack = (
        '    j+=",\\\"stack_admin_hwm\\\":"+String(adminHwm);\n'
        '    j+=",\\\"stack_admin_size_bytes\\\":"+String(REMOTE_ADMIN_STACK_BYTES);\n'
        '    j+=",\\\"stack_admin_peak_used_bytes\\\":"+String(adminPeak);\n'
        '    j+=",\\\"stack_http_hwm\\\":"+String(httpHwm);\n'
        '    j+=",\\\"stack_http_size_bytes\\\":"+String(REMOTE_HTTP_STACK_BYTES);\n'
        '    j+=",\\\"stack_http_peak_used_bytes\\\":"+String(httpPeak);\n'
    )
    if old_stack not in seg:
        raise RuntimeError("Runtime memory V3: Remote HWM JSON anchor missing")
    seg = seg.replace(old_stack, new_stack, 1)
    remote = remote[:s] + seg + remote[e:]

write(remote_path, remote)


# ---------------------------------------------------------------------------
# 2) MB-compatible payload: remove hundreds of short-lived String(float)
# allocations. Keep byte-for-byte field formatting by using dtostrf with the
# same width Arduino String(float, decimals) uses, but append from a stack
# buffer directly into the already-reserved payload.
# ---------------------------------------------------------------------------
mb_path = "src/mb_compatible_publisher.cpp"
mb = read(mb_path)

if f"// {MARKER}_MB" not in mb:
    stack_anchor = "constexpr uint32_t WORKER_STACK = 8192;\n"
    if stack_anchor not in mb:
        raise RuntimeError("Runtime memory V3: MB stack constant missing")
    mb = mb.replace(stack_anchor, stack_anchor + f"// {MARKER}_MB\n", 1)

    start = mb.find("String floatField(float value, uint8_t decimals)")
    end = mb.find("bool buildPayload(", start)
    if start < 0 or end < 0:
        raise RuntimeError("Runtime memory V3: MB field builder bounds missing")
    append_builder = r'''bool appendFloatField(String &out, float value, uint8_t decimals) {
    if (!finiteValue(value)) return out.concat("--");
    char buf[48]{};
    dtostrf(value, static_cast<signed char>(decimals + 2U), decimals, buf);
    return out.concat(buf);
}

bool appendFieldValue(String &out, size_t index, const LiveSelection &v, const tm &utc, uint32_t uptimeSec) {
    char buf[32]{};
    switch (index) {
        case 0:
            snprintf(buf, sizeof(buf), "%02d/%02d/%04d", utc.tm_mday, utc.tm_mon + 1, utc.tm_year + 1900);
            return out.concat(buf);
        case 1:
            snprintf(buf, sizeof(buf), "%02d:%02d:%02d", utc.tm_hour, utc.tm_min, utc.tm_sec);
            return out.concat(buf);
        case 2: return appendFloatField(out, v.tempC, 1);
        case 3: return appendFloatField(out, v.humPct, 0);
        case 4: return appendFloatField(out, v.dewC, 1);
        case 5: return appendFloatField(out, finiteValue(v.windKmh) ? v.windKmh / 3.6f : NAN, 2);
        case 6: return appendFloatField(out, finiteValue(v.gustKmh) ? v.gustKmh / 3.6f : NAN, 2);
        case 7: return appendFloatField(out, v.dirDeg, 0);
        case 8: return appendFloatField(out, v.rainRateMmH, 2);
        case 9: return appendFloatField(out, v.rainTodayMm, 2);
        case 10: return appendFloatField(out, v.pressureHpa, 1);
        case 11: return appendFloatField(out, v.dirDeg, 0);
        case 12:
            if (!finiteValue(v.windKmh)) return out.concat("--");
            snprintf(buf, sizeof(buf), "%u", static_cast<unsigned>(beaufortFromKmh(v.windKmh)));
            return out.concat(buf);
        case 15: return out.concat("hPa");
        case 16: return out.concat("mm");
        case 18: return appendFloatField(out, v.pressure3hAgoHpa, 1);
        case 22: return appendFloatField(out, v.indoorTempC, 1);
        case 23: return appendFloatField(out, v.indoorHumPct, 0);
        case 24: return appendFloatField(out, v.windChillC, 1);
        case 25: return out.concat("ESP32-Oregon-Technoline");
        case 38: return out.concat(FIRMWARE_VERSION);
        case 42: return appendFloatField(out, v.heatIndexC, 1);
        case 43: return appendFloatField(out, v.uv, 1);
        case 44: return appendFloatField(out, v.rain24hMm, 2);
        case 46: return appendFloatField(out, v.dirDeg, 0);
        case 47: return appendFloatField(out, v.rain1hMm, 2);
        case 81:
            snprintf(buf, sizeof(buf), "%lu", static_cast<unsigned long>(uptimeSec));
            return out.concat(buf);
        case 151: return appendFloatField(out, v.rainTotalMm, 2);
        default: return out.concat("--");
    }
}

'''
    mb = mb[:start] + append_builder + mb[end:]

    old_payload = '''    payload = "";
    payload.reserve(1050);
    for (size_t i = 0; i < MB_FIELD_COUNT; ++i) {
        if (i) payload += ' ';
        payload += fieldValue(i, live, utc, millis() / 1000UL);
    }
    return true;
'''
    new_payload = '''    payload.clear();
    if (!payload.reserve(1050)) {
        error = "payload reserve failed";
        return false;
    }
    const uint32_t uptimeSec = millis() / 1000UL;
    for (size_t i = 0; i < MB_FIELD_COUNT; ++i) {
        if (i && !payload.concat(' ')) {
            error = "payload separator allocation failed";
            return false;
        }
        if (!appendFieldValue(payload, i, live, utc, uptimeSec)) {
            error = "payload field allocation failed";
            return false;
        }
    }
    return true;
'''
    if old_payload not in mb:
        raise RuntimeError("Runtime memory V3: MB payload loop anchor missing")
    mb = mb.replace(old_payload, new_payload, 1)

    s, e = function_bounds(mb, "String urlEncode(")
    url_encode = r'''String urlEncode(const String &value) {
    static const char HEX[] = "0123456789ABCDEF";
    String out;
    // Worst case every byte becomes %XX. Reserving the final upper bound once
    // avoids realloc/copy cycles on the 192-field MB payload.
    if (!out.reserve(value.length() * 3U + 1U)) return String();
    for (size_t i = 0; i < value.length(); ++i) {
        const uint8_t c = static_cast<uint8_t>(value[i]);
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~') {
            out += static_cast<char>(c);
        } else {
            out += '%';
            out += HEX[(c >> 4) & 0x0FU];
            out += HEX[c & 0x0FU];
        }
    }
    return out;
}'''
    mb = mb[:s] + url_encode + mb[e:]

    s, e = function_bounds(mb, "String buildRequestUrl(")
    request_url = r'''String buildRequestUrl(const String &base, const String &encodedPayload) {
    const int marker = base.indexOf("{data}");
    String url;
    if (marker >= 0) {
        const size_t prefixLen = static_cast<size_t>(marker);
        const size_t tailPos = prefixLen + 6U;
        const size_t tailLen = base.length() > tailPos ? base.length() - tailPos : 0U;
        if (!url.reserve(prefixLen + encodedPayload.length() + tailLen + 1U)) return String();
        if (prefixLen) url.concat(base.c_str(), prefixLen);
        url += encodedPayload;
        if (tailLen) url.concat(base.c_str() + tailPos, tailLen);
        return url;
    }
    const bool direct = base.endsWith("?d=") || base.endsWith("&d=");
    const bool hasQuery = base.indexOf('?') >= 0;
    if (!url.reserve(base.length() + encodedPayload.length() + (direct ? 1U : 4U))) return String();
    url = base;
    if (!direct) {
        url += hasQuery ? '&' : '?';
        url += "d=";
    }
    url += encodedPayload;
    return url;
}'''
    mb = mb[:s] + request_url + mb[e:]

    status_anchor = (
        '    out += ",\\\"worker_stack_hwm\\\":" + String(gWorkerTask ? '
        'uxTaskGetStackHighWaterMark(gWorkerTask) : 0U);\n'
    )
    if status_anchor not in mb:
        raise RuntimeError("Runtime memory V3: MB HWM status anchor missing")
    status_repl = (
        '    const uint32_t workerHwm = gWorkerTask ? uxTaskGetStackHighWaterMark(gWorkerTask) : 0U;\n'
        + '    const uint32_t workerPeak = workerHwm <= WORKER_STACK ? WORKER_STACK - workerHwm : 0U;\n'
        + '    out += ",\\\"worker_stack_hwm\\\":" + String(workerHwm);\n'
        + '    out += ",\\\"worker_stack_size_bytes\\\":" + String(WORKER_STACK);\n'
        + '    out += ",\\\"worker_stack_peak_used_bytes\\\":" + String(workerPeak);\n'
    )
    mb = mb.replace(status_anchor, status_repl, 1)

write(mb_path, mb)


# ---------------------------------------------------------------------------
# 3) MQTT: eliminate one heap String allocation for every published topic.
#
# baseTopic is capped at 96 chars and all dynamic suffix buffers are <=47 chars.
# A 192-byte stack buffer therefore has ample deterministic headroom and avoids
# repeated heap allocate/free cycles in the high-frequency publish path.
# ---------------------------------------------------------------------------
mqtt_path = "src/mqtt_publisher.cpp"
mqtt = read(mqtt_path)

if f"// {MARKER}_MQTT" not in mqtt:
    s, e = function_bounds(mqtt, "String topic(")
    helper = f'''// {MARKER}_MQTT
constexpr size_t MQTT_TOPIC_BUFFER = 192U;

bool makeTopic(const char *suffix, char *out, size_t capacity) {{
    if (!out || capacity == 0U) return false;
    const size_t baseLen = mqttCfg.baseTopic.length();
    const size_t suffixLen = (suffix && *suffix) ? strlen(suffix) : 0U;
    const size_t needed = baseLen + (suffixLen ? 1U + suffixLen : 0U) + 1U;
    if (needed > capacity) return false;
    memcpy(out, mqttCfg.baseTopic.c_str(), baseLen);
    size_t pos = baseLen;
    if (suffixLen) {{
        out[pos++] = '/';
        memcpy(out + pos, suffix, suffixLen);
        pos += suffixLen;
    }}
    out[pos] = '\\0';
    return true;
}}

bool publishText(PubSubClient &client, const char *suffix, const char *payload, bool retained) {{
    char topicBuf[MQTT_TOPIC_BUFFER];
    if (!makeTopic(suffix, topicBuf, sizeof(topicBuf))) return false;
    return client.publish(topicBuf, payload ? payload : "", retained);
}}'''
    mqtt = mqtt[:s] + helper + mqtt[e:]

publish_re = re.compile(r'client\.publish\(topic\(([^()]*)\)\.c_str\(\),')
mqtt, _ = publish_re.subn(r'publishText(client, \1,', mqtt)

status_decl = 'const String statusTopic = topic("status");'
status_buf = (
    'char statusTopic[MQTT_TOPIC_BUFFER];\n'
    '    if (!makeTopic("status", statusTopic, sizeof(statusTopic))) return;'
)
mqtt = mqtt.replace(status_decl, status_buf)
mqtt = mqtt.replace("statusTopic.c_str()", "statusTopic")

if re.search(r"\btopic\(", mqtt):
    raise RuntimeError("Runtime memory V3: unoptimized MQTT topic() call remains")

static_suffixes = re.findall(r'publishText\(client,\s*"([^"]+)"', mqtt)
max_static = max((len(s) for s in static_suffixes), default=0)
max_suffix = max(max_static, 47)
if 96 + 1 + max_suffix + 1 > 192:
    raise RuntimeError("Runtime memory V3: MQTT topic buffer bound is too small")

write(mqtt_path, mqtt)

print(
    "Runtime memory V3: stack sizing telemetry + MB allocation cleanup + "
    "heap-free MQTT topic builder enabled"
)
