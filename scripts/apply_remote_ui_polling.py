Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
text = path.read_text(encoding="utf-8")

marker = "ADMIN_SENSOR_REMOTE_POLL_V1"
if marker in text:
    print("Remote UI polling: already optimized")
else:
    old = "bindDisplayFieldAutoPages();loadNetwork();loadMqtt();refreshLightning();refresh();setInterval(refresh,2000);setInterval(refreshLightning,2000);setInterval(()=>{const editing=mainTab==='config'&&E('cfgMqtt')&&E('cfgMqtt').classList.contains('active');if(!editing)loadMqtt();},10000);"
    new = """bindDisplayFieldAutoPages();
const remoteUi=location.pathname.includes('/adminsensor/device/')||location.pathname.includes('/proxy/'); // ADMIN_SENSOR_REMOTE_POLL_V1
let refreshBusy=false,lightningBusy=false,mqttBusy=false;
async function safeRefresh(){if(refreshBusy)return;refreshBusy=true;try{await refresh();}finally{refreshBusy=false}}
async function safeLightning(){if(lightningBusy)return;lightningBusy=true;try{await refreshLightning();}finally{lightningBusy=false}}
async function safeMqtt(){if(mqttBusy)return;mqttBusy=true;try{await loadMqtt();}finally{mqttBusy=false}}
// The local Web UI keeps the original 2 s cadence. Through AdminSensor every
// fetch is a complete request/reply over the WSS tunnel, so avoid the previous
// startup burst and never allow polling calls to overlap. Configuration data
// such as /api/network remains lazy-loaded only when CONFIGURAZIONE is opened.
safeRefresh();
setTimeout(safeLightning,remoteUi?1200:0);
setTimeout(safeMqtt,remoteUi?2500:0);
setInterval(safeRefresh,remoteUi?5000:2000);
setInterval(safeLightning,remoteUi?10000:2000);
setInterval(()=>{const editing=mainTab==='config'&&E('cfgMqtt')&&E('cfgMqtt').classList.contains('active');if(!editing)safeMqtt();},remoteUi?30000:10000);"""
    if old not in text:
        raise RuntimeError("Remote UI polling: dashboard timer anchor missing")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("Remote UI polling: AdminSensor mode 5s state / 10s lightning / 30s MQTT, no overlap")
