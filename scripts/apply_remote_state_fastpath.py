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
        raise RuntimeError(f"Remote state fastpath: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Remote state fastpath: opening brace missing: {signature}")
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
    raise RuntimeError(f"Remote state fastpath: unclosed function: {signature}")


# ---------------------------------------------------------------------------
# /api/state segmented transport.
#
# The Oregon state JSON is about 9 KiB. The local WebServer can build it, but a
# second contiguous 9 KiB std::vector in the AdminSensor loopback client is not
# reliable once WSS, MQTT, RF and SD have fragmented the classic ESP32 heap.
# That produced a 502 on the first dashboard refresh; the browser then waited
# for the next 5 s poll, which looked like a slow tunnel.
#
# Keep the public HTTP API unchanged. Only the internal AdminSensor loopback
# path stores /api/state in independent <=2 KiB pieces. The WSS protocol already
# reassembles 2 KiB response chunks, so no AdminSensor server change is needed.
# ---------------------------------------------------------------------------
r_path = "src/remote_access.cpp"
r = read(r_path)
marker = "ADMIN_SENSOR_STATE_SEGMENTED_V1"

if marker not in r:
    local_struct_old = "std::vector<uint8_t> body; };"
    local_struct_new = (
        "std::vector<uint8_t> body; "
        "std::vector<std::vector<uint8_t>> segmentedBody; "
        "size_t segmentedBytes=0; };"
    )
    if local_struct_old not in r:
        raise RuntimeError("Remote state fastpath: LocalResp body anchor missing")
    r = r.replace(local_struct_old, local_struct_new, 1)

    # Insert the segmented read before the normal contiguous-response V4 guard.
    lh_start, lh_end = function_bounds(r, "bool localHttp(")
    lh = r[lh_start:lh_end]
    heap_marker = "// ADMIN_SENSOR_DYNAMIC_HEAP_V4"
    pos = lh.find(heap_marker)
    if pos < 0:
        raise RuntimeError("Remote state fastpath: dynamic heap V4 marker missing")

    segmented_read = r'''// ADMIN_SENSOR_STATE_SEGMENTED_V1
    // /api/state is the only routinely large dashboard reply. Read it into
    // independent 2 KiB blocks instead of requiring one ~9 KiB contiguous
    // allocation. Normal API replies retain the existing V4 heap guard.
    if(method=="GET" && (path=="/api/state" || path.startsWith("/api/state?"))){
        constexpr size_t STATE_SEGMENT_RAW=2048U;
        constexpr size_t STATE_SEGMENT_HEADROOM=12288U;
        r.body.clear();
        r.segmentedBody.clear();
        r.segmentedBytes=0U;
        if(haveLen)r.segmentedBody.reserve((len+STATE_SEGMENT_RAW-1U)/STATE_SEGMENT_RAW);
        start=millis();
        uint8_t buf[512];
        while((c.connected()||c.available())&&millis()-start<6000UL){
            while(c.available()){
                const size_t current=r.segmentedBody.empty()?STATE_SEGMENT_RAW:r.segmentedBody.back().size();
                if(r.segmentedBody.empty() || current>=STATE_SEGMENT_RAW){
                    if(r.segmentedBytes>=MAX_RESP){c.stop();err="Risposta locale oltre limite";return false;}
                    size_t cap=STATE_SEGMENT_RAW;
                    if(haveLen && len>r.segmentedBytes && len-r.segmentedBytes<cap)cap=len-r.segmentedBytes;
                    const size_t largest=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
                    const size_t freeHeap=ESP.getFreeHeap();
                    if(cap>largest || freeHeap<=cap || freeHeap-cap<STATE_SEGMENT_HEADROOM){
                        c.stop();
                        r.segmentedBody.clear();r.segmentedBytes=0U;
                        err="Heap insufficiente per segmento state: need="+String(cap)+" block="+String(largest)+" free="+String(freeHeap);
                        return false;
                    }
                    r.segmentedBody.emplace_back();
                    r.segmentedBody.back().reserve(cap);
                }
                auto &seg=r.segmentedBody.back();
                const size_t room=STATE_SEGMENT_RAW-seg.size();
                size_t ask=static_cast<size_t>(c.available());
                if(ask>sizeof(buf))ask=sizeof(buf);
                if(ask>room)ask=room;
                if(haveLen && r.segmentedBytes+ask>len)ask=len-r.segmentedBytes;
                if(ask==0U)break;
                const int got=c.read(buf,ask);
                if(got<=0)break;
                seg.insert(seg.end(),buf,buf+got);
                r.segmentedBytes+=static_cast<size_t>(got);
                if(r.segmentedBytes>MAX_RESP){c.stop();err="Risposta locale oltre limite";return false;}
                if(haveLen && r.segmentedBytes>=len)break;
            }
            if(haveLen && r.segmentedBytes>=len)break;
            vTaskDelay(pdMS_TO_TICKS(1));
        }
        c.stop();
        if(haveLen && r.segmentedBytes<len){r.segmentedBody.clear();r.segmentedBytes=0U;err="Risposta locale incompleta";return false;}
        if(r.segmentedBytes==0U)r.encoding="";
        return true;
    }

    '''
    lh = lh[:pos] + segmented_read + lh[pos:]
    r = r[:lh_start] + lh + r[lh_end:]

    # Replace the generated chunk sender with a version that can consume either
    # the normal contiguous vector or the segmented /api/state representation.
    send_fn = r'''void sendResp(const String&id,LocalResp&r){ // ADMIN_SENSOR_HTTP_CHUNK_V2 ADMIN_SENSOR_STATE_SEGMENTED_V1
  constexpr size_t HTTP_RESP_LEGACY_MAX=4096U;
  constexpr size_t HTTP_RESP_CHUNK_RAW=2048U;

  JsonDocument hd;
  hd["content-type"]=r.type;
  if(!r.encoding.isEmpty())hd["content-encoding"]=r.encoding;
  if(!r.location.isEmpty())hd["location"]=r.location;
  if(!r.cache.isEmpty())hd["cache-control"]=r.cache;
  if(!r.disposition.isEmpty())hd["content-disposition"]=r.disposition;
  String headersJson;serializeJson(hd,headersJson);
  const String escapedId=esc(id);
  const bool segmented=!r.segmentedBody.empty();
  const size_t bodySize=segmented?r.segmentedBytes:r.body.size();

  // Keep the legacy one-frame response only for genuinely small contiguous
  // bodies. Segmented /api/state always uses the bounded chunk protocol.
  if(!segmented && bodySize<=HTTP_RESP_LEGACY_MAX){
    String o;
    if(!o.reserve(headersJson.length()+escapedId.length()+192U+b64EncodedLength(bodySize))){
      if(take()){st.lastError="Memoria insufficiente per risposta remota";give();}
      return;
    }
    o+=F("{\"type\":\"http_response\",\"id\":\"");o+=escapedId;
    o+=F("\",\"status\":");o+=String(r.code);o+=F(",\"headers\":");o+=headersJson;
    o+=F(",\"body_b64\":\"");
    const size_t encodedLen=b64EncodedLength(bodySize);
    const size_t finalLen=o.length()+encodedLen+2U;
    if(finalLen>MAX_WS||!o.reserve(finalLen+1U)){
      if(take()){st.lastError="Risposta remota oltre limite WebSocket";give();}
      return;
    }
    const size_t bodyStart=o.length();
    if(!appendB64(o,r.body.data(),bodySize)||o.length()!=bodyStart+encodedLen){
      if(take()){st.lastError="Codifica Base64 risposta remota incompleta";give();}
      return;
    }
    o+=F("\"}");
    if(o.length()!=finalLen){
      if(take()){st.lastError="Frame risposta remota incompleto";give();}
      return;
    }
    if(ws.sendTXT(o)&&take()){st.responses++;st.lastActivityMs=millis();st.lastError="";give();}
    return;
  }

  String startFrame;
  startFrame.reserve(headersJson.length()+escapedId.length()+192U);
  startFrame+=F("{\"type\":\"http_response_start\",\"id\":\"");startFrame+=escapedId;
  startFrame+=F("\",\"status\":");startFrame+=String(r.code);startFrame+=F(",\"headers\":");startFrame+=headersJson;
  startFrame+=F(",\"total_bytes\":");startFrame+=String(bodySize);startFrame+='}';
  if(startFrame.length()>MAX_WS||!ws.sendTXT(startFrame)){
    if(take()){st.lastError="Invio inizio risposta HTTP chunked fallito";give();}
    return;
  }

  auto sendChunk=[&](const uint8_t *data,size_t n,uint32_t seq)->bool{
    String frame;
    frame.reserve(escapedId.length()+128U+b64EncodedLength(n));
    frame+=F("{\"type\":\"http_response_chunk\",\"id\":\"");frame+=escapedId;
    frame+=F("\",\"seq\":");frame+=String(seq);frame+=F(",\"body_b64\":\"");
    const size_t encodedLen=b64EncodedLength(n);
    const size_t bodyStart=frame.length();
    const size_t finalLen=bodyStart+encodedLen+2U;
    if(finalLen>MAX_WS||!frame.reserve(finalLen+1U)||
       !appendB64(frame,data,n)||frame.length()!=bodyStart+encodedLen)return false;
    frame+=F("\"}");
    return frame.length()==finalLen&&ws.sendTXT(frame);
  };

  uint32_t seq=0;
  if(segmented){
    for(auto &seg:r.segmentedBody){
      if(seg.empty())continue;
      if(!sendChunk(seg.data(),seg.size(),seq++)){
        if(take()){st.lastError="Invio segmento state fallito";give();}
        return;
      }
      std::vector<uint8_t>().swap(seg);
      vTaskDelay(pdMS_TO_TICKS(1));
    }
    std::vector<std::vector<uint8_t>>().swap(r.segmentedBody);
    r.segmentedBytes=0U;
  }else{
    for(size_t off=0;off<bodySize;off+=HTTP_RESP_CHUNK_RAW){
      const size_t left=bodySize-off;
      const size_t n=left>HTTP_RESP_CHUNK_RAW?HTTP_RESP_CHUNK_RAW:left;
      if(!sendChunk(r.body.data()+off,n,seq++)){
        if(take()){st.lastError="Invio chunk risposta HTTP fallito";give();}
        return;
      }
      vTaskDelay(pdMS_TO_TICKS(1));
    }
    std::vector<uint8_t>().swap(r.body);
  }

  String endFrame;
  endFrame.reserve(escapedId.length()+128U);
  endFrame+=F("{\"type\":\"http_response_end\",\"id\":\"");endFrame+=escapedId;
  endFrame+=F("\",\"chunks\":");endFrame+=String(seq);endFrame+=F(",\"total_bytes\":");
  endFrame+=String(bodySize);endFrame+='}';
  if(endFrame.length()>MAX_WS||!ws.sendTXT(endFrame)){
    if(take()){st.lastError="Invio fine risposta HTTP chunked fallito";give();}
    return;
  }
  if(take()){st.responses++;st.lastActivityMs=millis();st.lastError="";give();}
}'''
    sf_start, sf_end = function_bounds(r, "void sendResp(const String&id,LocalResp&r)")
    r = r[:sf_start] + send_fn + r[sf_end:]
    write(r_path, r)
    print("AdminSensor Remote state: segmented 2 KiB loopback body enabled")
else:
    print("AdminSensor Remote state: segmented loopback body already enabled")


# ---------------------------------------------------------------------------
# Initial browser load serialization.
#
# After the 38 KiB gzip dashboard arrives, the first /api/state must get the
# tunnel to itself. Starting AS3935 and MQTT timers while that first response is
# still crossing the WSS queue adds avoidable contention. Subsequent polling is
# still adaptive/lazy exactly as Runtime V2 configured it.
# ---------------------------------------------------------------------------
d_path = "web/dashboard.html"
d = read(d_path)
boot_marker = "ADMIN_SENSOR_REMOTE_BOOT_SERIAL_V1"
if boot_marker not in d:
    old = '''safeRefresh(true);
if(remoteUi){setTimeout(()=>safeLightning(true),2500);setTimeout(()=>safeMqtt(true),5000);}else{safeLightning(true);safeMqtt(true);}'''
    new = '''/* ADMIN_SENSOR_REMOTE_BOOT_SERIAL_V1 */
if(remoteUi){
 safeRefresh(true).finally(()=>{
  setTimeout(()=>safeLightning(true),1500);
  setTimeout(()=>safeMqtt(true),3500);
 });
}else{safeRefresh(true);safeLightning(true);safeMqtt(true);}'''
    if old not in d:
        raise RuntimeError("Remote state fastpath: Runtime V2 startup polling anchor missing")
    d = d.replace(old, new, 1)
    write(d_path, d)
    print("AdminSensor Remote boot: first state refresh serialized before secondary APIs")
else:
    print("AdminSensor Remote boot: serialized startup already enabled")
