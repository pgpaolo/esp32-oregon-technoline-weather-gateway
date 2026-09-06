#!/usr/bin/env python3
"""Late integration pass for AdminSensor Remote + guarded WSS OTA.

Runs after the existing Web/auth/OTA and RC4 UI passes so it can safely bridge
AdminSensor Remote into the generated WebServer without changing the RF path.
The pass is intentionally idempotent: PlatformIO CI rebuilds the same workspace.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, data: str) -> None:
    (ROOT / path).write_text(data, encoding="utf-8")


def function_block(text: str, signature: str):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Remote integration: function anchor missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Remote integration: opening brace missing: {signature}")
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
    raise RuntimeError(f"Remote integration: unclosed function: {signature}")


# ---------------------------------------------------------------------------
# main.cpp: remote service starts after the local Web server is configured.
# OTA restart servicing stays in the normal low-priority part of loop().
# ---------------------------------------------------------------------------
main = read("src/main.cpp")
if '#include "remote_access.h"' not in main:
    anchor = '#include "web_manager.h"\n'
    if anchor not in main:
        raise RuntimeError("Remote integration: main Web include anchor missing")
    main = main.replace(anchor, anchor + '#include "remote_access.h"\n#include "remote_firmware_update.h"\n', 1)
if "    initRemoteAccess();\n" not in main:
    anchor = "    initWeb(station);\n"
    if anchor not in main:
        raise RuntimeError("Remote integration: initWeb anchor missing")
    main = main.replace(anchor, anchor + "    initRemoteAccess();\n", 1)
if "    serviceRemoteFirmwareUpdate();\n" not in main:
    anchor = "    serviceWeb();\n"
    if anchor not in main:
        raise RuntimeError("Remote integration: serviceWeb anchor missing")
    main = main.replace(anchor, anchor + "    serviceRemoteFirmwareUpdate();\n", 1)
write("src/main.cpp", main)


# ---------------------------------------------------------------------------
# web_manager.h: expose only readiness, never the WebServer itself.
# ---------------------------------------------------------------------------
h = read("src/web_manager.h")
if "bool webStarted();" not in h:
    anchor = "void serviceWeb();\n"
    if anchor not in h:
        raise RuntimeError("Remote integration: web_manager.h service anchor missing")
    h = h.replace(anchor, anchor + "bool webStarted();\n", 1)
write("src/web_manager.h", h)


# ---------------------------------------------------------------------------
# web_manager.cpp: local OTA mutex bridge, AdminSensor config/status routes and
# a readiness accessor for the loopback HTTP worker.
# ---------------------------------------------------------------------------
cpp = read("src/web_manager.cpp")
for inc in ('#include "remote_access.h"\n', '#include "remote_firmware_update.h"\n'):
    if inc not in cpp:
        anchor = '#include "web_ui_generated.h"\n'
        if anchor not in cpp:
            raise RuntimeError("Remote integration: Web include anchor missing")
        cpp = cpp.replace(anchor, anchor + inc, 1)

# Avoid the identifier collision with the exported webStarted() function. The
# earlier Web provisioning pass rewrites serviceWeb() on every build, so this
# normalization must also run on every build.
cpp = cpp.replace("bool webStarted = false;", "bool webStartedFlag = false;")
cpp = cpp.replace("if (!webStarted) {", "if (!webStartedFlag) {")
cpp = cpp.replace("webStarted = true;", "webStartedFlag = true;")

if "bool otaGuardHeld = false;" not in cpp:
    anchor = "String otaError;\n"
    if anchor not in cpp:
        raise RuntimeError("Remote integration: local OTA state anchor missing")
    cpp = cpp.replace(anchor, anchor + "bool otaGuardHeld = false;\n", 1)

# The Web provisioning script regenerates otaFail() on repeated builds, so add
# guard release whenever it is missing from that generated function.
s, e, ota_fail = function_block(cpp, "void otaFail(const String &reason) {")
if "firmwareLocalReleaseGuard" not in ota_fail:
    anchor = "    otaUploadActive = false;\n"
    if anchor not in ota_fail:
        raise RuntimeError("Remote integration: otaFail active anchor missing")
    ota_fail = ota_fail.replace(
        anchor,
        anchor + "    if (otaGuardHeld) { firmwareLocalReleaseGuard(); otaGuardHeld = false; }\n",
        1,
    )
    cpp = cpp[:s] + ota_fail + cpp[e:]

s, e, upload = function_block(cpp, "void handleFirmwareUpload() {")
if "firmwareLocalBeginGuard" not in upload:
    anchor = "        prepareSdLoggerForDeepSleep();\n"
    guard = '''        String otaGuardError;\n        if (!firmwareLocalBeginGuard(otaGuardError)) {\n            otaFail(otaGuardError.length() ? otaGuardError : String("firmware updater busy"));\n            return;\n        }\n        otaGuardHeld = true;\n\n'''
    if anchor not in upload:
        raise RuntimeError("Remote integration: local OTA prepare anchor missing")
    upload = upload.replace(anchor, guard + anchor, 1)
if "firmwareLocalReleaseGuard(); otaGuardHeld = false;" not in upload:
    anchor = "        otaUploadOk = true;\n"
    if anchor not in upload:
        raise RuntimeError("Remote integration: local OTA success anchor missing")
    upload = upload.replace(
        anchor,
        "        if (otaGuardHeld) { firmwareLocalReleaseGuard(); otaGuardHeld = false; }\n" + anchor,
        1,
    )
cpp = cpp[:s] + upload + cpp[e:]

# Authenticated management routes. The device token is never returned; config
# only exposes whether a token exists and the stable device ID.
if 'server.on("/api/remote/config"' not in cpp:
    routes = r'''    // ADMIN_SENSOR_REMOTE_INTEGRATED
    server.on("/api/remote/config", HTTP_GET, [](){
        if (!requireWebAuth()) return;
        sendNoCache();
        server.send(200, "application/json; charset=utf-8", remoteAccessConfigJson());
    });
    server.on("/api/remote/config", HTTP_POST, [](){
        if (!requireWebAuth()) return;
        const String portal = server.hasArg("portal_url") ? server.arg("portal_url") : String("");
        if (!saveRemoteAccessPortalUrl(portal)) {
            server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid HTTPS portal URL or NVS write failed\"}");
            return;
        }
        sendNoCache();
        server.send(200, "application/json", "{\"ok\":true}");
    });
    server.on("/api/remote/status", HTTP_GET, [](){
        if (!requireWebAuth()) return;
        sendNoCache();
        server.send(200, "application/json; charset=utf-8", remoteAccessStatusJson());
    });
    server.on("/api/remote/retry", HTTP_POST, [](){
        if (!requireWebAuth()) return;
        retryRemoteAccessNow();
        sendNoCache();
        server.send(200, "application/json", "{\"ok\":true}");
    });
    server.on("/api/remote/reset", HTTP_POST, [](){
        if (!requireWebAuth()) return;
        if (!resetRemoteAccessConfig()) {
            server.send(500, "application/json", "{\"ok\":false,\"error\":\"NVS reset failed\"}");
            return;
        }
        sendNoCache();
        server.send(200, "application/json", "{\"ok\":true}");
    });
    server.on("/api/firmware/remote-status", HTTP_GET, [](){
        if (!requireWebAuth()) return;
        sendNoCache();
        server.send(200, "application/json; charset=utf-8", firmwareUpdateStatusJson());
    });
'''
    anchor = "    server.onNotFound("
    pos = cpp.find(anchor)
    if pos < 0:
        raise RuntimeError("Remote integration: onNotFound route anchor missing")
    cpp = cpp[:pos] + routes + cpp[pos:]

if "bool webStarted()" not in cpp:
    anchor = "void recordWebPacket("
    pos = cpp.find(anchor)
    if pos < 0:
        raise RuntimeError("Remote integration: recordWebPacket anchor missing")
    cpp = cpp[:pos] + "bool webStarted() { return webStartedFlag; }\n\n" + cpp[pos:]
write("src/web_manager.cpp", cpp)


# ---------------------------------------------------------------------------
# Dashboard: one dedicated REMOTE / OTA page. It is deliberately low-impact:
# no background polling unless the page is selected.
# ---------------------------------------------------------------------------
d = read("web/dashboard.html")
if 'id="tabRemote"' not in d:
    tab_match = re.search(r'(<button id="tabSystem"[^>]*>.*?</button>)', d)
    if not tab_match:
        raise RuntimeError("Remote integration: SISTEMA tab anchor missing")
    tab = '<button id="tabRemote" class="cfgTab" onclick="showCfgTab(\'remote\')">REMOTE / OTA</button>'
    d = d[:tab_match.end()] + tab + d[tab_match.end():]

if 'id="cfgRemote"' not in d:
    page = r'''
<!-- ADMIN_SENSOR_REMOTE_UI -->
<div id="cfgRemote" class="cfgPage">
<div class="cfgGrid">
<label class="cfgWide"><span>Portale AdminSensor HTTPS</span><input id="remotePortal" type="text" maxlength="220" placeholder="https://admin.example.net"></label>
<label><span>Device ID</span><input id="remoteDeviceId" type="text" readonly></label>
<label><span>Stato tunnel</span><input id="remoteState" type="text" readonly></label>
<label><span>Endpoint WSS approvato</span><input id="remoteWs" type="text" readonly></label>
<label><span>Sessioni / richieste</span><input id="remoteCounters" type="text" readonly></label>
<label><span>OTA remota</span><input id="remoteOta" type="text" readonly></label>
<label class="cfgWide"><span>Ultimo evento / errore</span><input id="remoteError" type="text" readonly></label>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveRemoteAccess()">Salva portale</button><button class="modeBtn" onclick="retryRemoteAccess()">Riprova ora</button><button class="modeBtn dangerBtn" onclick="resetRemoteAccess()">Disattiva / reset URL</button><span id="remoteSummary" class="muted"></span></div>
<div class="cfgNote"><b>AdminSensor Remote:</b> il gateway apre esclusivamente connessioni in uscita HTTPS/WSS; non servono port-forwarding sul router. Il token dispositivo casuale resta in NVS e non viene mostrato dalla Web UI. L'OTA remota usa lo stesso tunnel autenticato, richiede dimensione e SHA-256, accetta blocchi numerati in sequenza e scrive soltanto nello slot OTA inattivo. Durante una OTA remota le richieste HTTP tunnel vengono sospese; una perdita WSS annulla l'aggiornamento. L'OTA locale autenticata resta disponibile in <b>SISTEMA</b> ed e' mutuamente esclusiva con quella remota.</div>
</div>
'''
    config_end = '</div>\n</section>\n<section id="mainDiag"'
    if config_end not in d:
        raise RuntimeError("Remote integration: configuration page end anchor missing")
    d = d.replace(config_end, page + '</div>\n</section>\n<section id="mainDiag"', 1)

if "async function loadRemoteAccess()" not in d:
    js = r'''
async function loadRemoteAccess(){try{const [c,s]=await Promise.all([fetch('/api/remote/config',{cache:'no-store'}).then(r=>r.json()),fetch('/api/remote/status',{cache:'no-store'}).then(r=>r.json())]);E('remotePortal').value=c.portal_url||'';E('remoteDeviceId').value=c.device_id||s.device_id||'--';E('remoteState').value=s.state||'--';E('remoteWs').value=(s.ws_host?('wss://'+s.ws_host+(s.ws_path||'')):'--');E('remoteCounters').value='WS '+Number(s.ws_connects||0)+' · req '+Number(s.requests||0)+' · resp '+Number(s.responses||0);const o=s.firmware_update||{};E('remoteOta').value=o.in_progress?((o.source||'remote')+' · '+Number(o.percent||0).toFixed(1)+'%'):((o.restart_pending?'riavvio programmato':(o.last_result||'pronta')));E('remoteError').value=s.last_error||o.last_error||s.last_ws_event||'--';E('remoteSummary').textContent=(s.transport_active?'Tunnel ONLINE':(c.portal_url?'Tunnel '+(s.state||'in attesa'):'Remote disattivato'))+' · token '+(c.has_token?'presente':'non disponibile');}catch(e){if(E('remoteSummary'))E('remoteSummary').textContent='errore lettura AdminSensor Remote'}}
async function saveRemoteAccess(){const q=new URLSearchParams();q.set('portal_url',E('remotePortal').value.trim());const r=await fetch('/api/remote/config?'+q.toString(),{method:'POST',cache:'no-store'});const body=await r.text();if(!r.ok){alert('AdminSensor Remote: '+body);return}E('remoteSummary').textContent='Configurazione salvata · nuova registrazione in corso';setTimeout(loadRemoteAccess,500)}
async function retryRemoteAccess(){const r=await fetch('/api/remote/retry',{method:'POST',cache:'no-store'});if(!r.ok){alert('Retry Remote fallito: '+await r.text());return}E('remoteSummary').textContent='Nuovo tentativo richiesto';setTimeout(loadRemoteAccess,500)}
async function resetRemoteAccess(){if(!confirm('Disattivare AdminSensor Remote e cancellare l URL del portale? Il token dispositivo resta locale per mantenere l identita in caso di riattivazione.'))return;const r=await fetch('/api/remote/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset Remote fallito: '+await r.text());return}E('remotePortal').value='';E('remoteSummary').textContent='Remote disattivato';setTimeout(loadRemoteAccess,300)}
setInterval(()=>{const p=E('cfgRemote');if(p&&p.classList.contains('active'))loadRemoteAccess()},5000);
'''
    if "</script>" not in d:
        raise RuntimeError("Remote integration: dashboard script end missing")
    d = d.replace("</script>", js + "</script>", 1)

s, e, show_cfg = function_block(d, "function showCfgTab(t){")
if "'remote'" not in show_cfg:
    m = re.search(r"for\(const x of \[([^\]]+)\]\)", show_cfg)
    if not m:
        raise RuntimeError("Remote integration: showCfgTab list missing")
    values = m.group(1).rstrip()
    show_cfg = show_cfg[:m.start(1)] + values + ",'remote'" + show_cfg[m.end(1):]
if "t==='remote'" not in show_cfg:
    show_cfg = show_cfg[:-1] + "else if(t==='remote'){loadRemoteAccess();}" + show_cfg[-1:]
d = d[:s] + show_cfg + d[e:]
write("web/dashboard.html", d)

print("AdminSensor Remote + guarded WSS OTA integration applied")
