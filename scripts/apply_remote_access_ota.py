Import("env")

from pathlib import Path
import gzip
import re

# SCons-safe entry point for the AdminSensor Remote integration.
# The implementation remains a normal Python module-like script and receives
# an explicit __file__ so its existing project-root logic works under both
# PlatformIO/SCons and normal Python inspection.
root = Path(env.subst("$PROJECT_DIR"))

# The classic ESP32 has limited contiguous 8-bit heap once RF, MQTT, SD, Web,
# TLS and the AdminSensor task are all active. The Oregon dashboard is much
# larger than the Davis UI, so buffering the full gzip body before chunking can
# exhaust the largest free block and abort. Keep normal dynamic responses at a
# Davis-sized ceiling and stream the root dashboard directly from flash below.
dashboard_path = root / "web" / "dashboard.html"
dashboard_gz_len = len(gzip.compress(dashboard_path.read_bytes(), compresslevel=9, mtime=0))

max_req = 16384
max_resp = 24576
max_ws = 38000

remote_path = root / "src" / "remote_access.cpp"
remote_text = remote_path.read_text(encoding="utf-8")
limits_re = re.compile(
    r"constexpr size_t MAX_REQ=\d+U, MAX_RESP=\d+U, MAX_WS=\d+U;"
)
new_limits = (
    f"constexpr size_t MAX_REQ={max_req}U, "
    f"MAX_RESP={max_resp}U, MAX_WS={max_ws}U;"
)
remote_text, replacements = limits_re.subn(new_limits, remote_text, count=1)
if replacements != 1:
    raise RuntimeError("Remote memory limits: expected limits anchor missing")
remote_path.write_text(remote_text, encoding="utf-8")
print(
    "AdminSensor Remote limits: "
    f"dashboard gzip {dashboard_gz_len} B, request {max_req // 1024} KiB, "
    f"response {max_resp // 1024} KiB, WebSocket {max_ws // 1024} KiB"
)

impl = root / "scripts" / "apply_remote_access_ota_impl.py"
scope = {"__file__": str(impl), "__name__": "__main__"}
exec(compile(impl.read_text(encoding="utf-8"), str(impl), "exec"), scope, scope)

# Keep the Oregon-specific asynchronous HTTP worker and guarded OTA. The
# reconnect pass retains the Davis-proven retry/reconnect cadence while using
# the Oregon-tested JSON application heartbeat instead of a disconnecting
# protocol-level heartbeat watchdog.
reconnect = root / "scripts" / "apply_remote_reconnect_hardening.py"
reconnect_scope = {
    "__file__": str(reconnect),
    "__name__": "__main__",
    "env": env,
    # The pass is executed inside this already-imported SCons script. It has
    # the env object explicitly, so its standalone Import("env") can be a no-op.
    "Import": lambda *args: None,
}
exec(compile(reconnect.read_text(encoding="utf-8"), str(reconnect), "exec"), reconnect_scope, reconnect_scope)

# ---------------------------------------------------------------------------
# Application-level HTTP response chunking.
#
# Keep legacy http_response for small replies, but split larger dynamic bodies
# into start/chunk/end messages. Use 2 KiB raw chunks so the transient Base64
# String stays below ~3 KiB even when the classic ESP32 heap is fragmented.
# AdminSensor reassembles the fragments by request id and validates sequence and
# declared size before resolving the original HTTP request.
# ---------------------------------------------------------------------------
remote_text = remote_path.read_text(encoding="utf-8")


def function_bounds(text, signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Remote HTTP chunking: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Remote HTTP chunking: opening brace missing: {signature}")
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
    raise RuntimeError(f"Remote HTTP chunking: unclosed function: {signature}")


chunked_send = r'''void sendResp(const String&id,LocalResp&r){ // ADMIN_SENSOR_HTTP_CHUNK_V2
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
  const size_t bodySize=r.body.size();

  // Backward compatibility for normal small API replies. These stay as the
  // original single http_response message understood by every AdminSensor.
  if(bodySize<=HTTP_RESP_LEGACY_MAX){
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

  String start;
  start.reserve(headersJson.length()+escapedId.length()+192U);
  start+=F("{\"type\":\"http_response_start\",\"id\":\"");start+=escapedId;
  start+=F("\",\"status\":");start+=String(r.code);start+=F(",\"headers\":");start+=headersJson;
  start+=F(",\"total_bytes\":");start+=String(bodySize);start+='}';
  if(start.length()>MAX_WS||!ws.sendTXT(start)){
    if(take()){st.lastError="Invio inizio risposta HTTP chunked fallito";give();}
    return;
  }

  uint32_t seq=0;
  for(size_t off=0;off<bodySize;off+=HTTP_RESP_CHUNK_RAW){
    const size_t left=bodySize-off;
    const size_t n=left>HTTP_RESP_CHUNK_RAW?HTTP_RESP_CHUNK_RAW:left;
    String frame;
    frame.reserve(escapedId.length()+128U+b64EncodedLength(n));
    frame+=F("{\"type\":\"http_response_chunk\",\"id\":\"");frame+=escapedId;
    frame+=F("\",\"seq\":");frame+=String(seq);frame+=F(",\"body_b64\":\"");
    const size_t encodedLen=b64EncodedLength(n);
    const size_t bodyStart=frame.length();
    const size_t finalLen=bodyStart+encodedLen+2U;
    if(finalLen>MAX_WS||!frame.reserve(finalLen+1U)||
       !appendB64(frame,r.body.data()+off,n)||frame.length()!=bodyStart+encodedLen){
      if(take()){st.lastError="Preparazione chunk risposta HTTP fallita";give();}
      return;
    }
    frame+=F("\"}");
    if(frame.length()!=finalLen||!ws.sendTXT(frame)){
      if(take()){st.lastError="Invio chunk risposta HTTP fallito";give();}
      return;
    }
    seq++;
    vTaskDelay(pdMS_TO_TICKS(1));
  }

  // The dynamic response vector is no longer needed once every fragment has
  // been written to TLS. Release it before the final control frame.
  std::vector<uint8_t>().swap(r.body);

  String end;
  end.reserve(escapedId.length()+128U);
  end+=F("{\"type\":\"http_response_end\",\"id\":\"");end+=escapedId;
  end+=F("\",\"chunks\":");end+=String(seq);end+=F(",\"total_bytes\":");
  end+=String(bodySize);end+='}';
  if(end.length()>MAX_WS||!ws.sendTXT(end)){
    if(take()){st.lastError="Invio fine risposta HTTP chunked fallito";give();}
    return;
  }
  if(take()){st.responses++;st.lastActivityMs=millis();st.lastError="";give();}
}'''

if "ADMIN_SENSOR_HTTP_CHUNK_V2" not in remote_text:
    sig = "void sendResp(const String&id,const LocalResp&r)"
    if sig not in remote_text:
        sig = "void sendResp(const String&id,LocalResp&r)"
    start, end = function_bounds(remote_text, sig)
    remote_text = remote_text[:start] + chunked_send + remote_text[end:]
    remote_path.write_text(remote_text, encoding="utf-8")
    print("AdminSensor Remote HTTP: dynamic responses split into 2 KiB WSS chunks")
else:
    print("AdminSensor Remote HTTP: 2 KiB chunked response protocol already present")

# ---------------------------------------------------------------------------
# Zero-copy root Web UI streaming for classic ESP32.
#
# The local WebServer already serves WEB_UI_GZ directly from PROGMEM. Doing a
# loopback GET and then reserving another ~36 KiB std::vector defeats that
# advantage and, on a feature-rich Oregon build, can exhaust the largest
# contiguous heap block. Root GET therefore bypasses loopback HTTP and streams
# the same embedded gzip image straight to AdminSensor in 2 KiB chunks.
# ---------------------------------------------------------------------------
remote_text = remote_path.read_text(encoding="utf-8")

remote_text = remote_text.replace(
    "constexpr UBaseType_t HTTP_QUEUE_LEN=4;",
    "constexpr UBaseType_t HTTP_QUEUE_LEN=2;",
)
if "constexpr UBaseType_t HTTP_QUEUE_LEN=2;" not in remote_text:
    raise RuntimeError("Remote flash UI: queue-length anchor missing")

if "heap_caps_get_largest_free_block" not in remote_text:
    inc = "#include <esp_random.h>\n"
    if inc not in remote_text:
        raise RuntimeError("Remote flash UI: esp_random include anchor missing")
    remote_text = remote_text.replace(inc, inc + "#include <esp_heap_caps.h>\n", 1)

reserve_old = "r.body.clear();r.body.reserve(haveLen?len:2048U);start=millis();"
reserve_new = "r.body.clear();\n    const size_t reserveLen=haveLen?len:2048U;\n    const size_t largestBlock=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);\n    if(reserveLen>largestBlock||largestBlock-reserveLen<8192U){\n        c.stop();err=\"Heap contiguo insufficiente per risposta locale\";return false;\n    }\n    r.body.reserve(reserveLen);start=millis();"
if reserve_old in remote_text:
    remote_text = remote_text.replace(reserve_old, reserve_new, 1)
elif "Heap contiguo insufficiente per risposta locale" not in remote_text:
    raise RuntimeError("Remote flash UI: local response reserve anchor missing")

reply_old = "struct RemoteReply { uint32_t session=0; String id; LocalResp response; };"
reply_new = "struct RemoteReply { uint32_t session=0; String id; LocalResp response; bool webUi=false; };"
if reply_old in remote_text:
    remote_text = remote_text.replace(reply_old, reply_new, 1)
elif reply_new not in remote_text:
    raise RuntimeError("Remote flash UI: RemoteReply anchor missing")

webh_path = root / "src" / "web_manager.h"
webh_text = webh_path.read_text(encoding="utf-8")
if "webUiGzipData" not in webh_text:
    h_anchor = "bool webStarted();\n"
    if h_anchor not in webh_text:
        raise RuntimeError("Remote flash UI: webStarted declaration missing")
    webh_text = webh_text.replace(
        h_anchor,
        h_anchor + "const uint8_t *webUiGzipData();\nsize_t webUiGzipSize();\n",
        1,
    )
    webh_path.write_text(webh_text, encoding="utf-8")

webcpp_path = root / "src" / "web_manager.cpp"
webcpp_text = webcpp_path.read_text(encoding="utf-8")
if "webUiGzipData()" not in webcpp_text:
    c_anchor = "bool webStarted() { return webStartedFlag; }\n"
    if c_anchor not in webcpp_text:
        raise RuntimeError("Remote flash UI: webStarted implementation missing")
    accessors = "const uint8_t *webUiGzipData() { return WEB_UI_GZ; }\nsize_t webUiGzipSize() { return WEB_UI_GZ_LEN; }\n"
    webcpp_text = webcpp_text.replace(c_anchor, c_anchor + accessors, 1)
    webcpp_path.write_text(webcpp_text, encoding="utf-8")

flash_send = r'''void sendEmbeddedWebUi(const String&id){ // ADMIN_SENSOR_FLASH_UI_V2
  constexpr size_t FLASH_CHUNK_RAW=2048U;
  const uint8_t *data=webUiGzipData();
  const size_t bodySize=webUiGzipSize();
  if(!data||bodySize==0U){
    LocalResp e;e.code=503;const char*m="Web UI non disponibile";e.body.assign(m,m+strlen(m));
    sendResp(id,e);return;
  }
  const String escapedId=esc(id);
  String start;
  start.reserve(escapedId.length()+240U);
  start+=F("{\"type\":\"http_response_start\",\"id\":\"");start+=escapedId;
  start+=F("\",\"status\":200,\"headers\":{\"content-type\":\"text/html; charset=utf-8\",\"content-encoding\":\"gzip\",\"cache-control\":\"no-store\"},\"total_bytes\":");
  start+=String(bodySize);start+='}';
  if(start.length()>MAX_WS||!ws.sendTXT(start)){
    if(take()){st.lastError="Invio inizio Web UI flash fallito";give();}
    return;
  }
  uint32_t seq=0;
  for(size_t off=0;off<bodySize;off+=FLASH_CHUNK_RAW){
    const size_t left=bodySize-off;
    const size_t n=left>FLASH_CHUNK_RAW?FLASH_CHUNK_RAW:left;
    String frame;
    const size_t encodedLen=b64EncodedLength(n);
    if(!frame.reserve(escapedId.length()+128U+encodedLen)){
      if(take()){st.lastError="Heap insufficiente per chunk Web UI";give();}
      return;
    }
    frame+=F("{\"type\":\"http_response_chunk\",\"id\":\"");frame+=escapedId;
    frame+=F("\",\"seq\":");frame+=String(seq);frame+=F(",\"body_b64\":\"");
    const size_t bodyStart=frame.length();
    const size_t finalLen=bodyStart+encodedLen+2U;
    if(finalLen>MAX_WS||!frame.reserve(finalLen+1U)||
       !appendB64(frame,data+off,n)||frame.length()!=bodyStart+encodedLen){
      if(take()){st.lastError="Preparazione chunk Web UI flash fallita";give();}
      return;
    }
    frame+=F("\"}");
    if(frame.length()!=finalLen||!ws.sendTXT(frame)){
      if(take()){st.lastError="Invio chunk Web UI flash fallito";give();}
      return;
    }
    seq++;
    vTaskDelay(pdMS_TO_TICKS(1));
  }
  String end;
  end.reserve(escapedId.length()+128U);
  end+=F("{\"type\":\"http_response_end\",\"id\":\"");end+=escapedId;
  end+=F("\",\"chunks\":");end+=String(seq);end+=F(",\"total_bytes\":");
  end+=String(bodySize);end+='}';
  if(end.length()>MAX_WS||!ws.sendTXT(end)){
    if(take()){st.lastError="Invio fine Web UI flash fallito";give();}
    return;
  }
  if(take()){st.responses++;st.lastActivityMs=millis();st.lastError="";give();}
}'''

if "ADMIN_SENSOR_FLASH_UI_V2" not in remote_text:
    senderr_pos = remote_text.find("void sendErr(")
    if senderr_pos < 0:
        raise RuntimeError("Remote flash UI: sendErr anchor missing")
    remote_text = remote_text[:senderr_pos] + flash_send + "\n" + remote_text[senderr_pos:]

worker_v2 = r'''void httpWorker(void*){ // ADMIN_SENSOR_FLASH_UI_WORKER_V2
  for(;;){
    RemoteReq*q=nullptr;
    if(!requestQueue||xQueueReceive(requestQueue,&q,portMAX_DELAY)!=pdTRUE||!q)continue;
    workerBusy=true;
    RemoteReply*out=new(std::nothrow)RemoteReply();
    if(out){
      out->session=q->session;out->id=q->id;
      const bool rootUi=q->method.equalsIgnoreCase("GET")&&(q->path=="/"||q->path.startsWith("/?"));
      if(rootUi){
        out->webUi=true;
        out->response.code=200;
        out->response.type="text/html; charset=utf-8";
        out->response.encoding="gzip";
        out->response.cache="no-store";
      }else{
        String e;
        if(!localHttp(q->method,q->path,q->contentType,q->accept,q->body,out->response,e)){
          out->response.code=502;out->response.type="text/plain; charset=utf-8";out->response.encoding="";
          out->response.body.assign(e.c_str(),e.c_str()+e.length());
        }
      }
      if(!responseQueue||xQueueSend(responseQueue,&out,pdMS_TO_TICKS(250))!=pdTRUE){
        delete out;if(take()){queueDrops++;give();}
      }
    }else if(take()){queueDrops++;give();}
    delete q;workerBusy=false;
  }
}'''
if "ADMIN_SENSOR_FLASH_UI_WORKER_V2" not in remote_text:
    w_start,w_end=function_bounds(remote_text,"void httpWorker(void*)")
    remote_text=remote_text[:w_start]+worker_v2+remote_text[w_end:]

drain_v2 = r'''void drainReplies(){ // ADMIN_SENSOR_FLASH_UI_DRAIN_V2
  if(!responseQueue)return;
  for(uint8_t i=0;i<2;i++){
    RemoteReply*r=nullptr;if(xQueueReceive(responseQueue,&r,0)!=pdTRUE||!r)break;
    uint32_t current=0;bool online=false;if(take()){current=wsSession;online=st.transportActive;give();}
    if(online&&r->session==current){
      if(r->webUi)sendEmbeddedWebUi(r->id);
      else sendResp(r->id,r->response);
    }
    delete r;
  }
}'''
if "ADMIN_SENSOR_FLASH_UI_DRAIN_V2" not in remote_text:
    d_start,d_end=function_bounds(remote_text,"void drainReplies()")
    remote_text=remote_text[:d_start]+drain_v2+remote_text[d_end:]

limits_re = re.compile(r"constexpr size_t MAX_REQ=\d+U, MAX_RESP=\d+U, MAX_WS=\d+U;")
remote_text,n_limits=limits_re.subn(
    "constexpr size_t MAX_REQ=16384U, MAX_RESP=24576U, MAX_WS=38000U;",
    remote_text,
    count=1,
)
if n_limits!=1:
    raise RuntimeError("Remote flash UI: final limit anchor missing")

required_flash = (
    "ADMIN_SENSOR_HTTP_CHUNK_V2",
    "ADMIN_SENSOR_FLASH_UI_V2",
    "ADMIN_SENSOR_FLASH_UI_WORKER_V2",
    "ADMIN_SENSOR_FLASH_UI_DRAIN_V2",
    "heap_caps_get_largest_free_block",
    "constexpr UBaseType_t HTTP_QUEUE_LEN=2;",
)
for marker in required_flash:
    if marker not in remote_text:
        raise RuntimeError(f"Remote flash UI result missing: {marker}")

remote_path.write_text(remote_text, encoding="utf-8")
print(
    "AdminSensor Remote Web UI: zero-copy flash stream in 2 KiB chunks; "
    "dynamic response cap 24 KiB; HTTP queue 2"
)

# ---------------------------------------------------------------------------
# Remote OTA image-type guard.
#
# Checking only byte 0 == 0xE9 is insufficient: ESP32 bootloader images also
# start with the ESP image magic and a merged/full-flash image can therefore be
# written into an OTA app slot. An application image carries the ESP app
# descriptor magic 0xABCD5432 at fixed offset 32 (24-byte image header + 8-byte
# first segment header). Reject anything else before the first flash write.
# This protects NVS/network configuration indirectly by preventing a bad OTA
# slot from being selected and making a healthy device appear to have lost IP.
# ---------------------------------------------------------------------------
ota_path = root / "src" / "remote_firmware_update.cpp"
ota_text = ota_path.read_text(encoding="utf-8")
helper_name = "looksLikeOtaApplication"
if helper_name not in ota_text:
    helper = '''constexpr size_t OTA_APP_DESC_OFFSET = 32U;\nconstexpr uint32_t OTA_APP_DESC_MAGIC = 0xABCD5432UL;\n\nbool looksLikeOtaApplication(const uint8_t *data, size_t len) {\n    if (!data || len < OTA_APP_DESC_OFFSET + sizeof(uint32_t)) return false;\n    if (data[0]!=0xE9U) return false;\n    const uint32_t magic =\n        static_cast<uint32_t>(data[OTA_APP_DESC_OFFSET]) |\n        (static_cast<uint32_t>(data[OTA_APP_DESC_OFFSET + 1U]) << 8) |\n        (static_cast<uint32_t>(data[OTA_APP_DESC_OFFSET + 2U]) << 16) |\n        (static_cast<uint32_t>(data[OTA_APP_DESC_OFFSET + 3U]) << 24);\n    return magic == OTA_APP_DESC_MAGIC;\n}\n\n'''
    anchor = "String shaHex(const unsigned char digest[32]) {"
    if anchor not in ota_text:
        raise RuntimeError("Remote OTA image guard: shaHex anchor missing")
    ota_text = ota_text.replace(anchor, helper + anchor, 1)

old_first_chunk = '''    if (firstChunk) {\n        firstChunk=false;\n        if (data[0]!=0xE9U) {\n            const bool r=failRemoteLocked("File non riconosciuto come immagine firmware ESP32",error);unlock();return r;\n        }\n    }'''
new_first_chunk = '''    if (firstChunk) {\n        firstChunk=false;\n        if (!looksLikeOtaApplication(data,len)) {\n            const bool r=failRemoteLocked("File OTA non valido: usare firmware.bin applicativo, non bootloader/partitions/merged",error);unlock();return r;\n        }\n    }'''
if old_first_chunk in ota_text:
    ota_text = ota_text.replace(old_first_chunk, new_first_chunk, 1)
elif new_first_chunk not in ota_text:
    raise RuntimeError("Remote OTA image guard: first-chunk anchor missing")

ota_path.write_text(ota_text, encoding="utf-8")
print("Remote OTA safety: application-image descriptor validation enabled")
