Import("env")

from pathlib import Path
import gzip
import re

# SCons-safe entry point for the AdminSensor Remote integration.
# The implementation remains a normal Python module-like script and receives
# an explicit __file__ so its existing project-root logic works under both
# PlatformIO/SCons and normal Python inspection.
root = Path(env.subst("$PROJECT_DIR"))

# Size the transient tunnel buffers from the *actual* Web UI that will be
# embedded in this build. This avoids a fixed response ceiling becoming stale
# as dashboard.html grows, while keeping a bounded heap budget on classic ESP32.
#
# The local Web UI is always served gzip-compressed. Keep 8 KiB of response
# headroom above the deterministic gzip payload. MAX_WS remains a safety ceiling
# for all WSS protocol messages; large normal HTTP responses are fragmented
# below into 4 KiB application-level chunks instead of one large JSON frame.
dashboard_path = root / "web" / "dashboard.html"
dashboard_gz_len = len(gzip.compress(dashboard_path.read_bytes(), compresslevel=9, mtime=0))


def round_up(value, block=4096):
    return ((value + block - 1) // block) * block


max_req = 16384
max_resp = max(40960, round_up(dashboard_gz_len + 8192))
base64_resp = ((max_resp + 2) // 3) * 4
max_ws = max(57344, round_up(base64_resp + 4096))

if max_resp > 65536 or max_ws > 98304:
    raise RuntimeError(
        f"Remote tunnel buffers would be unsafe: gzip={dashboard_gz_len}, "
        f"response={max_resp}, websocket={max_ws}"
    )

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

# Keep the Oregon-specific asynchronous HTTP worker and guarded OTA, while the
# separate reconnect pass verifies that the WSS lifecycle stays identical to
# the known-good Davis develop-optimized timing (30/15/60 s retry cadence,
# reconnect 5 s, heartbeat 30/5/2, no extra application ping).
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
# The Oregon dashboard is ~35 KiB gzip and becomes ~48 KiB when Base64-wrapped
# into one JSON WebSocket text message. Real devices showed code=1005 exactly
# while serving that frame. Keep legacy http_response for small replies, but
# split larger bodies into start/chunk/end messages with 4 KiB raw chunks.
# Each chunk frame is only ~5.6 KiB, sharply reducing TLS/WSS contiguous-heap
# pressure and avoiding dependence on a large single-message path in proxies.
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


chunked_send = r'''void sendResp(const String&id,LocalResp&r){ // ADMIN_SENSOR_HTTP_CHUNK_V1
  constexpr size_t HTTP_RESP_LEGACY_MAX=4096U;
  constexpr size_t HTTP_RESP_CHUNK_RAW=4096U;

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

  // The local gzip/vector is no longer needed once every fragment has been
  // written to TLS. Release it before the final control frame.
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

if "ADMIN_SENSOR_HTTP_CHUNK_V1" not in remote_text:
    sig = "void sendResp(const String&id,const LocalResp&r)"
    if sig not in remote_text:
        sig = "void sendResp(const String&id,LocalResp&r)"
    start, end = function_bounds(remote_text, sig)
    remote_text = remote_text[:start] + chunked_send + remote_text[end:]
    remote_path.write_text(remote_text, encoding="utf-8")
    print("AdminSensor Remote HTTP: large responses split into 4 KiB WSS chunks")
else:
    print("AdminSensor Remote HTTP: chunked response protocol already present")

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
