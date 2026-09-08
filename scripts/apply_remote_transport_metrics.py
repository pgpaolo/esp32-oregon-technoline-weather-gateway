Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "remote_access.cpp"
r = path.read_text(encoding="utf-8")
MARKER = "ADMIN_SENSOR_TRANSPORT_METRICS_V1"


def function_bounds(text, signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Remote transport metrics: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Remote transport metrics: opening brace missing: {signature}")
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
        if ch in ('\"', "'"):
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
    raise RuntimeError(f"Remote transport metrics: unclosed function: {signature}")


if MARKER not in r:
    # These are deliberately tiny fixed counters: no dynamic allocation and no
    # extra network traffic. They measure exactly the two transfers that make
    # the remote dashboard feel slow: the compressed root UI and /api/state.
    anchor = "uint32_t queueDrops=0;\n"
    if anchor not in r:
        raise RuntimeError("Remote transport metrics: global counter anchor missing")
    r = r.replace(
        anchor,
        anchor
        + "// ADMIN_SENSOR_TRANSPORT_METRICS_V1\n"
        + "volatile uint32_t transportRootSendMs=0,transportRootBytes=0,transportRootChunks=0;\n"
        + "volatile uint32_t transportStateLocalMs=0,transportStateSendMs=0,transportStateBytes=0,transportStateChunks=0;\n",
        1,
    )

    # Measure the loopback WebServer time for the segmented /api/state response.
    s, e = function_bounds(r, "bool localHttp(")
    seg = r[s:e]
    if "ADMIN_SENSOR_STATE_SEGMENTED_V1" not in seg:
        raise RuntimeError("Remote transport metrics: segmented state fastpath missing")
    start_anchor = "        constexpr size_t STATE_SEGMENT_HEADROOM=12288U;\n        r.body.clear();"
    if start_anchor not in seg:
        raise RuntimeError("Remote transport metrics: state local start anchor missing")
    seg = seg.replace(
        start_anchor,
        "        constexpr size_t STATE_SEGMENT_HEADROOM=12288U;\n"
        "        const uint32_t transportStateLocalStarted=millis();\n"
        "        r.body.clear();",
        1,
    )
    end_anchor = "        if(r.segmentedBytes==0U)r.encoding=\"\";\n        return true;"
    if end_anchor not in seg:
        raise RuntimeError("Remote transport metrics: state local completion anchor missing")
    seg = seg.replace(
        end_anchor,
        "        if(r.segmentedBytes==0U)r.encoding=\"\";\n"
        "        transportStateLocalMs=(uint32_t)(millis()-transportStateLocalStarted);\n"
        "        return true;",
        1,
    )
    r = r[:s] + seg + r[e:]

    # Measure only segmented /api/state WSS transmission. Reading the status
    # endpoint later does not overwrite these values.
    s, e = function_bounds(r, "void sendResp(const String&id,LocalResp&r)")
    seg = r[s:e]
    send_anchor = "  const bool segmented=!r.segmentedBody.empty();\n  const size_t bodySize=segmented?r.segmentedBytes:r.body.size();"
    if send_anchor not in seg:
        raise RuntimeError("Remote transport metrics: state send start anchor missing")
    seg = seg.replace(
        send_anchor,
        send_anchor + "\n  const uint32_t transportStateSendStarted=segmented?millis():0U;",
        1,
    )
    done_anchor = "  if(take()){st.responses++;st.lastActivityMs=millis();st.lastError=\"\";give();}\n}"
    if done_anchor not in seg:
        raise RuntimeError("Remote transport metrics: state send completion anchor missing")
    seg = seg.replace(
        done_anchor,
        "  if(segmented){transportStateSendMs=(uint32_t)(millis()-transportStateSendStarted);transportStateBytes=(uint32_t)bodySize;transportStateChunks=seq;}\n"
        + done_anchor,
        1,
    )
    r = r[:s] + seg + r[e:]

    # Measure the zero-copy compressed root Web UI transfer separately.
    s, e = function_bounds(r, "void sendEmbeddedWebUi(const String&id)")
    seg = r[s:e]
    root_anchor = "  const size_t bodySize=webUiGzipSize();"
    if root_anchor not in seg:
        raise RuntimeError("Remote transport metrics: root UI start anchor missing")
    seg = seg.replace(root_anchor, root_anchor + "\n  const uint32_t transportRootStarted=millis();", 1)
    if done_anchor not in seg:
        raise RuntimeError("Remote transport metrics: root UI completion anchor missing")
    seg = seg.replace(
        done_anchor,
        "  transportRootSendMs=(uint32_t)(millis()-transportRootStarted);transportRootBytes=(uint32_t)bodySize;transportRootChunks=seq;\n"
        + done_anchor,
        1,
    )
    r = r[:s] + seg + r[e:]

    # Expose raw timings through the existing authenticated /api/remote/status.
    # No extra polling is added to the dashboard.
    s, e = function_bounds(r, "String remoteAccessStatusJson()")
    seg = r[s:e]
    status_anchor = '    j+=",\\\"firmware_update\\\":"+firmwareUpdateStatusJson()+"}";'
    if status_anchor not in seg:
        raise RuntimeError("Remote transport metrics: status JSON anchor missing")
    transport_json = (
        '    j+=",\\\"transport_diag\\\":{\\\"root_send_ms\\\":"+String(transportRootSendMs)'
        '+",\\\"root_bytes\\\":"+String(transportRootBytes)'
        '+",\\\"root_chunks\\\":"+String(transportRootChunks)'
        '+",\\\"state_local_ms\\\":"+String(transportStateLocalMs)'
        '+",\\\"state_send_ms\\\":"+String(transportStateSendMs)'
        '+",\\\"state_bytes\\\":"+String(transportStateBytes)'
        '+",\\\"state_chunks\\\":"+String(transportStateChunks)+"}";\n'
    )
    seg = seg.replace(status_anchor, transport_json + status_anchor, 1)
    r = r[:s] + seg + r[e:]

    path.write_text(r, encoding="utf-8")
    print("AdminSensor Remote transport metrics: root/state local+WSS timings exposed")
else:
    print("AdminSensor Remote transport metrics: already enabled")
