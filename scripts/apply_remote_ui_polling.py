Import("env")

from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
text = path.read_text(encoding="utf-8")

poll_marker = "ADMIN_SENSOR_REMOTE_POLL_V2"
poll_marker_v3 = "ADMIN_SENSOR_REMOTE_POLL_V3"
if poll_marker in text or poll_marker_v3 in text:
    # A later runtime pass upgrades V2 to V3 in-place. Repeated PlatformIO
    # builds and source archives captured after a previous build must therefore
    # treat either marker as already optimized; otherwise this V2 pass looks
    # for the original refresh()/refreshLightning()/loadMqtt() timers that V3
    # has intentionally replaced and aborts with state=0/lightning=0/mqtt=0.
    print("Remote UI polling: already optimized")
else:
    # Work only on the startup/timer tail that follows the existing display
    # binding. Earlier pre-scripts legitimately extend the dashboard, so do not
    # depend on one giant exact string for the whole footer.
    anchor = "bindDisplayFieldAutoPages();"
    pos = text.find(anchor)
    if pos < 0:
        raise RuntimeError("Remote UI polling: display binding anchor missing")

    head = text[: pos + len(anchor)]
    tail = text[pos + len(anchor):]

    # The original startup burst is local-friendly but expensive over the WSS
    # tunnel. Remove only the immediate startup calls before the first timer;
    # configuration loaders elsewhere in the page remain untouched/lazy.
    first_timer = tail.find("setInterval(")
    if first_timer < 0:
        raise RuntimeError("Remote UI polling: timer section missing")
    startup = tail[:first_timer]
    timers = tail[first_timer:]
    for call in ("loadNetwork();", "loadMqtt();", "refreshLightning();", "refresh();"):
        startup = startup.replace(call, "", 1)

    state_re = re.compile(r"setInterval\(\s*refresh\s*,\s*\d+\s*\);")
    lightning_re = re.compile(r"setInterval\(\s*refreshLightning\s*,\s*\d+\s*\);")
    mqtt_re = re.compile(
        r"setInterval\(\(\)=>\{const editing=mainTab==='config'&&E\('cfgMqtt'\)&&"
        r"E\('cfgMqtt'\)\.classList\.contains\('active'\);if\(!editing\)loadMqtt\(\);\},\s*\d+\s*\);"
    )

    timers, n_state = state_re.subn(
        "setInterval(safeRefresh,remoteUi?5000:2000);", timers, count=1
    )
    timers, n_lightning = lightning_re.subn(
        "setInterval(safeLightning,remoteUi?10000:2000);", timers, count=1
    )
    timers, n_mqtt = mqtt_re.subn(
        "setInterval(()=>{const editing=mainTab==='config'&&E('cfgMqtt')&&E('cfgMqtt').classList.contains('active');if(!editing)safeMqtt();},remoteUi?30000:10000);",
        timers,
        count=1,
    )
    if n_state != 1 or n_lightning != 1 or n_mqtt != 1:
        raise RuntimeError(
            "Remote UI polling: timer anchors missing "
            f"state={n_state} lightning={n_lightning} mqtt={n_mqtt}"
        )

    helper = """
const remoteUi=location.pathname.includes('/adminsensor/device/')||location.pathname.includes('/proxy/'); // ADMIN_SENSOR_REMOTE_POLL_V2
let refreshBusy=false,lightningBusy=false,mqttBusy=false;
async function safeRefresh(){if(refreshBusy)return;refreshBusy=true;try{await refresh();}finally{refreshBusy=false}}
async function safeLightning(){if(lightningBusy)return;lightningBusy=true;try{await refreshLightning();}finally{lightningBusy=false}}
async function safeMqtt(){if(mqttBusy)return;mqttBusy=true;try{await loadMqtt();}finally{mqttBusy=false}}
// Locale: mantieni la reattivita originale. AdminSensor: ogni fetch attraversa
// il WSS, quindi niente startup burst, niente richieste sovrapposte e polling
// piu lento per gli endpoint secondari.
safeRefresh();
setTimeout(safeLightning,remoteUi?1200:0);
setTimeout(safeMqtt,remoteUi?2500:0);
"""

    text = head + helper + startup + timers
    print(
        "Remote UI polling: AdminSensor mode 5s state / 10s lightning / "
        "30s MQTT, no overlap"
    )

# ---------------------------------------------------------------------------
# Robust JSON transport handling.
#
# A reverse proxy must preserve an ESP HTTP error as an HTTP error. The old UI
# immediately called Response.json(), so a legitimate 502 text/plain body such
# as "Heap insufficiente ..." surfaced as the misleading browser error
# "Unexpected token H". Check status/content type first and preserve a compact
# device error in the visible Web status pill.
# ---------------------------------------------------------------------------
json_marker = "ADMIN_SENSOR_FETCH_JSON_V3"
if json_marker in text:
    print("Remote UI JSON transport: already hardened")
else:
    fetch_helper = r'''
async function fetchJsonChecked(url,options){ // ADMIN_SENSOR_FETCH_JSON_V3
 const opt=Object.assign({cache:'no-store'},options||{});
 const r=await fetch(url,opt);
 const body=await r.text();
 const compact=(body||'').replace(/\s+/g,' ').trim();
 if(!r.ok)throw new Error('HTTP '+r.status+(compact?' · '+compact.slice(0,140):''));
 const ct=(r.headers.get('content-type')||'').toLowerCase();
 if(ct&&ct.indexOf('json')<0)throw new Error('HTTP '+r.status+' · risposta non JSON'+(compact?' · '+compact.slice(0,100):''));
 try{return JSON.parse(body)}catch(e){throw new Error('JSON non valido'+(compact?' · '+compact.slice(0,100):''))}
}
'''
    anchor = "async function refresh(){"
    pos = text.find(anchor)
    if pos < 0:
        raise RuntimeError("Remote UI JSON transport: refresh anchor missing")
    text = text[:pos] + fetch_helper + text[pos:]

    replacements = (
        (
            "const s=await (await fetch('/api/state',{cache:'no-store'})).json()",
            "const s=await fetchJsonChecked('/api/state')",
            "state",
        ),
        (
            "const l=await (await fetch('/api/as3935/state',{cache:'no-store'})).json()",
            "const l=await fetchJsonChecked('/api/as3935/state')",
            "lightning state",
        ),
        (
            "const m=await (await fetch('/api/mqtt',{cache:'no-store'})).json()",
            "const m=await fetchJsonChecked('/api/mqtt')",
            "MQTT",
        ),
        (
            "const rr=await (await fetch('/api/raw',{cache:'no-store'})).json()",
            "const rr=await fetchJsonChecked('/api/raw')",
            "raw diagnostics",
        ),
        (
            "const bb=await (await fetch('/api/bursts',{cache:'no-store'})).json()",
            "const bb=await fetchJsonChecked('/api/bursts')",
            "burst diagnostics",
        ),
    )

    for old, new, label in replacements:
        if old in text:
            text = text.replace(old, new)
            print(f"Remote UI JSON transport: hardened {label}")
        elif new not in text:
            raise RuntimeError(f"Remote UI JSON transport: {label} fetch anchor missing")

path.write_text(text, encoding="utf-8")
