Import("env")

from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
text = path.read_text(encoding="utf-8")

marker = "ADMIN_SENSOR_REMOTE_POLL_V2"
if marker in text:
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
    path.write_text(text, encoding="utf-8")
    print(
        "Remote UI polling: AdminSensor mode 5s state / 10s lightning / "
        "30s MQTT, no overlap"
    )
