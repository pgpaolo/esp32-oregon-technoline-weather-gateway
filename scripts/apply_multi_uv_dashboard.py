#!/usr/bin/env python3
"""Apply the compact multi-UV dashboard changes before PlatformIO build.

The hardware-validation branch keeps the large dashboard source stable while
this feature is tested on real sensors. The patch is deliberately tolerant of
both a clean checkout and a workspace already modified by previous PlatformIO
pre-script runs. It touches only the Web/API presentation layer; RF decoders
are not changed.
"""

from pathlib import Path

Import("env")
ROOT = Path(env.subst("$PROJECT_DIR"))
WEB_CPP = ROOT / "src" / "web_manager.cpp"
DASH = ROOT / "web" / "dashboard.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Best-effort idempotent textual replacement.

    Pre-scripts modify the checkout in-place. Therefore a later build can see
    the replacement already present, a partially transformed source, or more
    than one copy of an old marker. None of those states should abort a
    firmware build.
    """
    if new in text:
        print(f"Multi-UV: {label} already patched")
        return text

    count = text.count(old)
    if count == 0:
        print(f"Multi-UV: {label} marker unavailable; keeping compatible existing source")
        return text

    if count > 1:
        print(f"Multi-UV: {label} found {count} times; patching first occurrence only")

    return text.replace(old, new, 1)


def patch_web_manager() -> None:
    text = WEB_CPP.read_text(encoding="utf-8")
    if "int8_t uvIndex{-1}; // compact per-transmitter UV value" in text:
        print("Multi-UV API: web_manager.cpp already patched")
        return

    text = replace_once(
        text,
        "    uint8_t protocolVersion{0};\n    uint8_t cadenceSamples{0};\n    uint32_t firstMs{0};",
        "    uint8_t protocolVersion{0};\n    uint8_t cadenceSamples{0};\n    int8_t uvIndex{-1}; // compact per-transmitter UV value; also fills existing alignment gap\n    uint32_t firstMs{0};",
        "session UV slot",
    )

    text = replace_once(
        text,
        "    sensor->lastMs = reading.receivedAtMs;\n    sensor->lastRssi = reading.rssi;\n    sensor->received++;",
        "    sensor->lastMs = reading.receivedAtMs;\n    sensor->lastRssi = reading.rssi;\n    if (reading.type == SensorType::UV && reading.uvValid)\n        sensor->uvIndex = static_cast<int8_t>(reading.uvIndex);\n    sensor->received++;",
        "session UV update",
    )

    text = replace_once(
        text,
        "        out += \",\\\"rssi\\\":\" + jsonFloat(sensor.lastRssi, 1);\n        out += \",\\\"src\\\":\\\"\" + String(nominal ? \"nom\" : (cadence ? \"auto\" : \"cal\")) + \"\\\"}\";",
        "        out += \",\\\"rssi\\\":\" + jsonFloat(sensor.lastRssi, 1);\n        out += \",\\\"uv\\\":\" + String(sensor.uvIndex);\n        out += \",\\\"age\\\":\" + String(ageSeconds(sensor.lastMs, now));\n        out += \",\\\"src\\\":\\\"\" + String(nominal ? \"nom\" : (cadence ? \"auto\" : \"cal\")) + \"\\\"}\";",
        "session UV JSON",
    )

    WEB_CPP.write_text(text, encoding="utf-8")
    print("Multi-UV API: web_manager.cpp normalized")


def patch_dashboard() -> None:
    text = DASH.read_text(encoding="utf-8")
    if "uvSensorGrid" in text and "rssiBadge" in text and "technolineGrid" in text:
        print("Multi-UV UI: dashboard.html already patched")
        return

    css_marker = ".qhdr{color:var(--muted);font-size:.72rem}.qgood{color:#70e2ad}.qwarn{color:#f0c56c}.qbad{color:#ff9b9b}\n"
    css_extra = css_marker + ".rssiSignal{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}.rssiDot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#65758a;box-shadow:0 0 0 2px #65758a22}.rssiDot.good{background:var(--ok);box-shadow:0 0 0 2px #30d99a22}.rssiDot.warn{background:var(--warn);box-shadow:0 0 0 2px #f0b24a22}.rssiDot.bad{background:var(--bad);box-shadow:0 0 0 2px #ff707022}.uvSensorGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px;padding:8px 0}.uvSensorItem{border:1px solid #213249;border-radius:9px;background:#0a1525;padding:9px}.uvSensorHead{display:flex;align-items:center;justify-content:space-between;gap:8px}.uvSensorValue{font-size:1.35rem;font-weight:850;color:#f4f8ff}.technolineGrid{grid-template-columns:repeat(3,minmax(0,1fr))}\n"
    text = replace_once(text, css_marker, css_extra, "RSSI/UV CSS")

    old_uv_card = '<section class="card good uvCard"><div class="cardTitle">Radiazione UV<svg class="spark" id="spUv"></svg></div><div class="body"><div class="row"><div class="name">Indice UV</div><div><div class="value" id="uv">--</div><div class="age" id="ageU"></div></div></div></div><div class="foot" id="footU"></div></section>'
    new_uv_card = '<section class="card good uvCard"><div class="cardTitle">Radiazione UV <span class="muted" id="uvCount"></span></div><div class="body"><div id="uvSensors" class="uvSensorGrid"><div class="muted">In attesa dei sensori UV...</div></div><div id="uv" hidden></div><div id="ageU" hidden></div></div><div class="foot" id="footU"></div></section>'
    text = replace_once(text, old_uv_card, new_uv_card, "Oregon multi-UV card")

    tech_head = '<div class="panel stationTechnoline" id="lacrossePanel"><div class="panelHead">Dati meteo live · Technoline WS230x <span id="technolineModeBadge" class="badge off">RF non in ascolto</span></div><div class="acqBar"><b>Acquisizione Technoline</b><span id="lcSessionAge" class="badge off">--</span><span id="lcAcqT" class="badge wait">TEMP attesa</span><span id="lcAcqH" class="badge wait">HUM attesa</span><span id="lcAcqW" class="badge wait">WIND attesa</span><span id="lcAcqG" class="badge wait">GUST attesa</span><span id="lcAcqR" class="badge wait">RAIN attesa</span></div><div class="weatherGrid">'
    text = replace_once(text, tech_head, tech_head[:-2] + ' technolineGrid">', "Technoline 3-column grid")

    tech_uv = '''<section class="card good uvCard nodata"><div class="cardTitle">Radiazione UV</div><div class="body">
<div class="row"><div class="name">Indice UV</div><div class="value">N/D</div></div>
<div class="row"><div class="name">WS-2305</div><div class="value">non trasmesso</div></div>
</div><div class="foot">Il protocollo WS-23xx non contiene un dato UV.</div></section>
'''
    text = replace_once(text, tech_uv, "", "remove Technoline UV card")

    helper_marker = "const E=id=>document.getElementById(id);const f=(v,d=1,u='')=>v==null?'--':Number(v).toFixed(d)+u;const age=v=>(v==null||v>4290000)?'mai':(v<60?v+' s fa':Math.floor(v/60)+' min fa');const batt=x=>!x||!x.battery_known?'<span class=\\\"battNA\\\">BAT N/D</span>':(x.battery_low?'<span class=\\\"battLOW\\\">BAT LOW</span>':'<span class=\\\"battOK\\\">BAT OK</span>');const setBadge=(id,ok,label)=>{const e=E(id);e.className='badge '+(ok?'ok':'wait');e.textContent=label};const qClass=q=>q<0?'':(q>=85?'qgood':(q>=60?'qwarn':'qbad'));const qText=q=>q<0?'--':q+'%';const showOrWait="
    helper_replacement = "const E=id=>document.getElementById(id);const f=(v,d=1,u='')=>v==null?'--':Number(v).toFixed(d)+u;const age=v=>(v==null||v>4290000)?'mai':(v<60?v+' s fa':Math.floor(v/60)+' min fa');const batt=x=>!x||!x.battery_known?'<span class=\\\"battNA\\\">BAT N/D</span>':(x.battery_low?'<span class=\\\"battLOW\\\">BAT LOW</span>':'<span class=\\\"battOK\\\">BAT OK</span>');const setBadge=(id,ok,label)=>{const e=E(id);e.className='badge '+(ok?'ok':'wait');e.textContent=label};const qClass=q=>q<0?'':(q>=85?'qgood':(q>=60?'qwarn':'qbad'));const qText=q=>q<0?'--':q+'%';const rssiClass=v=>v==null?'na':(Number(v)>=-100?'good':(Number(v)>=-115?'warn':'bad'));const rssiBadge=v=>'<span class=\\\"rssiSignal\\\"><i class=\\\"rssiDot '+rssiClass(v)+'\\\"></i>'+(v==null?'RSSI N/D':Number(v).toFixed(1)+' dBm')+'</span>';const showOrWait="
    text = replace_once(text, helper_marker, helper_replacement, "RSSI JS helper")

    old_rssi = "rssi=x.rssi==null?'RSSI N/D':'RSSI '+Number(x.rssi).toFixed(1)+' dBm';return"
    text = replace_once(text, old_rssi, "rssi=rssiBadge(x.rssi);return", "quality RSSI dot")

    uv_helper = "const getUvRows=s=>(Array.isArray(s.oregon_sensors)?s.oregon_sensors:[]).filter(x=>x.t==='uv'&&Number(x.uv)>=0);const renderUvSensors=s=>{const rows=getUvRows(s);if(!rows.length)return '<div class=\\\"muted\\\">Nessun sensore UV ricevuto nella sessione.</div>';return rows.map(x=>'<div class=\\\"uvSensorItem\\\"><div class=\\\"uvSensorHead\\\"><b>'+x.m+'</b><span class=\\\"uvSensorValue\\\">'+Number(x.uv).toFixed(1)+'</span></div><small class=\\\"qmeta\\\">'+(Number(x.v)===2?'V2.1':'OSV3')+' · 0x'+x.c+' · CH'+x.ch+' · '+rssiBadge(x.rssi)+' · '+age(x.age)+'</small></div>').join('')};\n"
    text = replace_once(text, "const hist={", uv_helper + "const hist={", "multi-UV renderer")

    old_uv_refresh = "if(isO&&!sess.uv_acquired){showOrWait(uv,false,'');ageU.textContent='ultimo dato '+age(a.uv_age_s)}else{showOrWait(uv,true,w.uv<0?'--':Number(w.uv).toFixed(1));ageU.textContent=age(a.uv_age_s)}footU.innerHTML='AD: '+p.AD+' · sessione '+sess.uv_received+' · '+ss.uv.model+' '+ss.uv.code+' · '+batt(ss.uv);setFresh('ageU',a.uv_age_s,isO&&sess.uv_acquired);"
    new_uv_refresh = "const uvRows=getUvRows(sess),uvNewest=uvRows.length?Math.min(...uvRows.map(x=>Number(x.age??4294967295))):4294967295;E('uvSensors').innerHTML=renderUvSensors(sess);E('uvCount').textContent=uvRows.length?(uvRows.length+' sensore'+(uvRows.length>1?'i':'')):'nessun sensore';footU.innerHTML='AD: '+p.AD+' · '+uvRows.length+' trasmettitori · RSSI: verde ≥ -100 · giallo -115…-101 · rosso < -115 dBm';setFresh('ageU',uvNewest,isO&&uvRows.length>0);"
    text = replace_once(text, old_uv_refresh, new_uv_refresh, "multi-UV refresh")

    DASH.write_text(text, encoding="utf-8")
    print("Multi-UV UI: dashboard.html normalized")


patch_web_manager()
patch_dashboard()

# CI marker: tolerant repeated-build version for hardware-validation branch.
