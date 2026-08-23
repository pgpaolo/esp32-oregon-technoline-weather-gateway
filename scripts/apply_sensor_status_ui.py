#!/usr/bin/env python3
"""Apply uniform RSSI/battery presentation and MQTT grouping.

Runs after apply_multi_uv_dashboard.py and before web UI compression.
No decoder logic is touched. The Oregon session registry gains one compact
battery-state byte per active transmitter; RSSI already exists.
"""

from pathlib import Path

Import("env")
ROOT = Path(env.subst("$PROJECT_DIR"))
WEB_CPP = ROOT / "src" / "web_manager.cpp"
DASH = ROOT / "web" / "dashboard.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def patch_web_manager() -> None:
    text = WEB_CPP.read_text(encoding="utf-8")
    if "uint8_t batteryState{0}; // compact session battery" not in text:
        text = replace_once(
            text,
            "    int8_t uvIndex{-1}; // compact per-transmitter UV value; also fills existing alignment gap\n    uint32_t firstMs{0};",
            "    int8_t uvIndex{-1}; // compact per-transmitter UV value; also fills existing alignment gap\n    uint8_t batteryState{0}; // compact session battery: 0=N/D, 1=OK, 2=LOW\n    uint32_t firstMs{0};",
            "session battery byte",
        )

        text = replace_once(
            text,
            "    if (reading.type == SensorType::UV && reading.uvValid)\n        sensor->uvIndex = static_cast<int8_t>(reading.uvIndex);\n    sensor->received++;",
            "    if (reading.type == SensorType::UV && reading.uvValid)\n        sensor->uvIndex = static_cast<int8_t>(reading.uvIndex);\n    sensor->batteryState = reading.batteryStatusValid ? (reading.batteryLow ? 2U : 1U) : 0U;\n    sensor->received++;",
            "session battery update",
        )

        text = replace_once(
            text,
            "        out += \",\\\"uv\\\":\" + String(sensor.uvIndex);\n        out += \",\\\"age\\\":\" + String(ageSeconds(sensor.lastMs, now));\n        out += \",\\\"src\\\":\\\"\" + String(nominal ? \"nom\" : (cadence ? \"auto\" : \"cal\")) + \"\\\"}\";",
            "        out += \",\\\"uv\\\":\" + String(sensor.uvIndex);\n        out += \",\\\"age\\\":\" + String(ageSeconds(sensor.lastMs, now));\n        out += \",\\\"bat\\\":\" + String(sensor.batteryState);\n        out += \",\\\"src\\\":\\\"\" + String(nominal ? \"nom\" : (cadence ? \"auto\" : \"cal\")) + \"\\\"}\";",
            "session battery JSON",
        )

    # Technoline has no battery telemetry, but its RF RSSI is real and should
    # be shown with the same signal grade as Oregon.
    if '\\"last_rssi\\\"' not in text:
        text = replace_once(
            text,
            '    out += ",\\\"battery\\\":\\\"N/D\\\"";\n    out += "}";',
            '    out += ",\\\"last_rssi\\\":" + jsonFloat(lc.lastRssi, 1);\n    out += ",\\\"battery\\\":\\\"N/D\\\"";\n    out += "}";',
            "Technoline RSSI JSON",
        )

    WEB_CPP.write_text(text, encoding="utf-8")
    print("Sensor status API: patched web_manager.cpp")


def patch_dashboard() -> None:
    text = DASH.read_text(encoding="utf-8")
    if "batterySignal" in text and "Sensori RF / RSSI / batterie" in text:
        print("Sensor status UI: dashboard.html already patched")
        return

    # Battery indicator uses the same visual language as RSSI: green OK,
    # red LOW, grey N/D. Keep it tiny enough for card footers and UV tiles.
    css_marker = ".technolineGrid{grid-template-columns:repeat(3,minmax(0,1fr))}\n"
    css_extra = css_marker + ".batterySignal{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}.batteryDot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#65758a;box-shadow:0 0 0 2px #65758a22}.batteryDot.good{background:var(--ok);box-shadow:0 0 0 2px #30d99a22}.batteryDot.bad{background:var(--bad);box-shadow:0 0 0 2px #ff707022}.sensorHealth{display:inline-flex;align-items:center;gap:7px;flex-wrap:wrap}\n"
    text = replace_once(text, css_marker, css_extra, "battery status CSS")

    helper_marker = "const rssiClass=v=>v==null?'na':(Number(v)>=-100?'good':(Number(v)>=-115?'warn':'bad'));const rssiBadge=v=>'<span class=\\\"rssiSignal\\\"><i class=\\\"rssiDot '+rssiClass(v)+'\\\"></i>'+(v==null?'RSSI N/D':Number(v).toFixed(1)+' dBm')+'</span>';const showOrWait="
    helper_new = "const rssiClass=v=>v==null?'na':(Number(v)>=-100?'good':(Number(v)>=-115?'warn':'bad'));const rssiBadge=v=>'<span class=\\\"rssiSignal\\\"><i class=\\\"rssiDot '+rssiClass(v)+'\\\"></i>'+(v==null?'RSSI N/D':Number(v).toFixed(1)+' dBm')+'</span>';const batteryState=v=>{if(typeof v==='string'){v=v.toUpperCase();return v==='OK'?1:(v==='LOW'?2:0)}return Number(v||0)};const batteryBadge=v=>{const b=batteryState(v),c=b===1?'good':(b===2?'bad':'na'),t=b===1?'BAT OK':(b===2?'BAT LOW':'BAT N/D');return '<span class=\\\"batterySignal\\\"><i class=\\\"batteryDot '+c+'\\\"></i>'+t+'</span>'};const showOrWait="
    text = replace_once(text, helper_marker, helper_new, "battery JS helper")

    # Helpers over the already existing per-transmitter session registry.
    sensor_helpers = "const sensorRows=s=>Array.isArray(s&&s.oregon_sensors)?s.oregon_sensors:[];const sensorFor=(s,t,ch=null,code=null)=>sensorRows(s).find(x=>x.t===t&&(ch==null||Number(x.ch)===Number(ch))&&(code==null||String(x.c)===String(code)))||null;const sensorHealth=x=>'<span class=\\\"sensorHealth\\\">'+rssiBadge(x?x.rssi:null)+' '+batteryBadge(x?x.bat:0)+'</span>';\n"
    text = replace_once(text, "const hist={", sensor_helpers + "const hist={", "sensor health helpers")

    # Quality table and UV tile: include battery state next to RSSI.
    text = replace_once(text, "+rssi+' · '+(x.cad?", "+rssi+' · '+batteryBadge(x.bat)+' · '+(x.cad?", "quality battery badge")
    text = replace_once(text, "+rssiBadge(x.rssi)+' · '+age(x.age)", "+rssiBadge(x.rssi)+' · '+batteryBadge(x.bat)+' · '+age(x.age)", "UV battery badge")

    # Oregon card footers. Temperature uses the selected channel state directly;
    # wind/rain use the matching session transmitter to obtain RSSI+battery.
    old_t = "footT.innerHTML='CH'+thermoViewChannel+(primaryView?' principale':'')+' · '+(tv[4]||'----')+' · BAT '+(tv[5]||'N/D')+' · '+f(tv[3],1,' dBm');"
    new_t = "footT.innerHTML='CH'+thermoViewChannel+(primaryView?' principale':'')+' · '+(tv[4]||'----')+' · '+rssiBadge(tv[3])+' · '+batteryBadge(tv[5]);"
    text = replace_once(text, old_t, new_t, "thermo health footer")

    old_w = "footW.innerHTML='A1: '+p.A1+' · sessione '+sess.wind_received+' · '+ss.wind.model+' '+ss.wind.code+' · '+batt(ss.wind)+' · WGR scan '+r.wind_recovery_success+'/'+r.wind_recovery_starts+' · csKO '+r.wind_scan_checksum_fail;"
    new_w = "footW.innerHTML='A1: '+p.A1+' · sessione '+sess.wind_received+' · '+ss.wind.model+' '+ss.wind.code+' · '+sensorHealth(sensorFor(sess,'wind'))+' · WGR scan '+r.wind_recovery_success+'/'+r.wind_recovery_starts+' · csKO '+r.wind_scan_checksum_fail;"
    text = replace_once(text, old_w, new_w, "wind health footer")

    old_r = "footR.innerHTML='A2: '+p.A2+' · sessione '+sess.rain_received+' · '+ss.rain.model+' '+ss.rain.code+' · '+batt(ss.rain)+' · storico 1h/24h locale';"
    new_r = "footR.innerHTML='A2: '+p.A2+' · sessione '+sess.rain_received+' · '+ss.rain.model+' '+ss.rain.code+' · '+sensorHealth(sensorFor(sess,'rain'))+' · storico 1h/24h locale';"
    text = replace_once(text, old_r, new_r, "rain health footer")

    # Technoline is one station: same last RF RSSI is repeated on its three
    # functional cards; battery stays grey because WS23xx does not transmit it.
    old_lct = "E('lcFootTH').textContent='T '+lc.temperature_packets+' · H '+lc.humidity_packets+' · sessione '+sess.lc_temperature_received+'/'+sess.lc_humidity_received+' · BAT N/D';"
    new_lct = "E('lcFootTH').innerHTML='T '+lc.temperature_packets+' · H '+lc.humidity_packets+' · sessione '+sess.lc_temperature_received+'/'+sess.lc_humidity_received+' · '+rssiBadge(lc.last_rssi)+' · '+batteryBadge('N/D');"
    text = replace_once(text, old_lct, new_lct, "Technoline TH health")

    old_lcw = "E('lcFootW').textContent='W '+lc.wind_packets+' · G '+lc.gust_packets+' · sessione '+sess.lc_wind_received+'/'+sess.lc_gust_received+' · GUST '+(lcGustExpected?'annunciata':'non annunciata')+' · next '+lc.next_update;"
    new_lcw = "E('lcFootW').innerHTML='W '+lc.wind_packets+' · G '+lc.gust_packets+' · sessione '+sess.lc_wind_received+'/'+sess.lc_gust_received+' · '+rssiBadge(lc.last_rssi)+' · '+batteryBadge('N/D')+' · next '+lc.next_update;"
    text = replace_once(text, old_lcw, new_lcw, "Technoline wind health")

    old_lcr = "E('lcFootR').textContent='Rain '+lc.rain_packets+' · sessione '+sess.lc_rain_received+' · incremento locale';"
    new_lcr = "E('lcFootR').innerHTML='Rain '+lc.rain_packets+' · sessione '+sess.lc_rain_received+' · '+rssiBadge(lc.last_rssi)+' · '+batteryBadge('N/D')+' · incremento locale';"
    text = replace_once(text, old_lcr, new_lcr, "Technoline rain health")

    # Reorganize MQTT functions by physical sensor/station while retaining the
    # exact same data-mqbit values and therefore the same NVS schema.
    old_oregon = '''<div class="fieldGroup"><b>Oregon</b>
<label class="fieldCheck"><input data-mqbit="0" type="checkbox">Temperatura</label><label class="fieldCheck"><input data-mqbit="1" type="checkbox">Umidita</label><label class="fieldCheck"><input data-mqbit="2" type="checkbox">Heat index</label><label class="fieldCheck"><input data-mqbit="3" type="checkbox">Punto di rugiada</label><label class="fieldCheck"><input data-mqbit="4" type="checkbox">Vento medio</label><label class="fieldCheck"><input data-mqbit="5" type="checkbox">Raffica/current</label><label class="fieldCheck"><input data-mqbit="6" type="checkbox">Direzione vento</label><label class="fieldCheck"><input data-mqbit="7" type="checkbox">Wind chill</label><label class="fieldCheck"><input data-mqbit="8" type="checkbox">Pioggia totale</label><label class="fieldCheck"><input data-mqbit="9" type="checkbox">Intensita pioggia</label><label class="fieldCheck"><input data-mqbit="10" type="checkbox">Pioggia 1 h</label><label class="fieldCheck"><input data-mqbit="11" type="checkbox">Pioggia 24 h</label><label class="fieldCheck"><input data-mqbit="12" type="checkbox">Incremento pioggia</label><label class="fieldCheck"><input data-mqbit="13" type="checkbox">UV</label>
</div>'''
    new_oregon = '''<div class="fieldGroup"><b>Oregon · Termo/igro</b>
<label class="fieldCheck"><input data-mqbit="0" type="checkbox">Temperatura · tutti CH</label><label class="fieldCheck"><input data-mqbit="1" type="checkbox">Umidita · tutti CH</label><label class="fieldCheck"><input data-mqbit="2" type="checkbox">Heat index principale</label><label class="fieldCheck"><input data-mqbit="3" type="checkbox">Punto di rugiada principale</label><label class="fieldCheck"><input data-mqbit="7" type="checkbox">Wind chill principale</label><small class="cfgHelp">F824/F8B4/1D20/EC40: ogni canale/rolling ID ricevuto mantiene il proprio topic.</small>
</div>
<div class="fieldGroup"><b>Oregon · Vento</b>
<label class="fieldCheck"><input data-mqbit="4" type="checkbox">Velocita media</label><label class="fieldCheck"><input data-mqbit="5" type="checkbox">Raffica / current</label><label class="fieldCheck"><input data-mqbit="6" type="checkbox">Direzione vento</label><small class="cfgHelp">WGR800 e sensori vento legacy supportati.</small>
</div>
<div class="fieldGroup"><b>Oregon · Pioggia</b>
<label class="fieldCheck"><input data-mqbit="8" type="checkbox">Totale sensore</label><label class="fieldCheck"><input data-mqbit="9" type="checkbox">Intensita / rate</label><label class="fieldCheck"><input data-mqbit="10" type="checkbox">Pioggia 1 h</label><label class="fieldCheck"><input data-mqbit="11" type="checkbox">Pioggia 24 h</label><label class="fieldCheck"><input data-mqbit="12" type="checkbox">Incremento frame</label><small class="cfgHelp">PCR800/RGR e futuri pluviometri riconosciuti.</small>
</div>
<div class="fieldGroup"><b>Oregon · UV</b>
<label class="fieldCheck"><input data-mqbit="13" type="checkbox">Indice UV · tutti i sensori</label><small class="cfgHelp">UVN800 D874, UVR128 EC70 e futuri UV supportati restano separati.</small>
</div>'''
    text = replace_once(text, old_oregon, new_oregon, "MQTT Oregon sensor groups")

    old_note = '<div class="cfgNote">TLS verificato usa la CA PEM. CH1-CH3 seguono OREGON. NVS solo su modifica.</div>'
    new_note = '<div class="cfgNote">TLS verificato usa la CA PEM. Le caselle selezionano le funzioni per sensore/stazione. Per Oregon ogni trasmettitore ricevuto viene pubblicato anche sotto <code>oregon/sensor/CODE/chN/idN/...</code>: CH1-CH3 e rolling ID non si sovrascrivono. I topic legacy restano compatibili. NVS solo su modifica.</div>'
    text = replace_once(text, old_note, new_note, "MQTT sensor namespace note")

    # New OLED page is a normal selectable page-mask bit; no extra NVS object.
    old_pages = '<label class="fieldCheck"><input data-dpagebit="0" type="checkbox">Esterno</label><label class="fieldCheck"><input data-dpagebit="1" type="checkbox">Vento / Pioggia</label><label class="fieldCheck"><input data-dpagebit="2" type="checkbox">Technoline</label><label class="fieldCheck"><input data-dpagebit="3" type="checkbox">Barometro</label><label class="fieldCheck"><input data-dpagebit="4" type="checkbox">RF / Status</label><label class="fieldCheck"><input data-dpagebit="5" type="checkbox">AS3935 fulmini</label>'
    new_pages = old_pages + '<label class="fieldCheck"><input data-dpagebit="6" type="checkbox">Sensori RF / RSSI / batterie</label>'
    text = replace_once(text, old_pages, new_pages, "OLED sensor page checkbox")

    old_display_note = "<div class=\"cfgNote\">Le pagine disabilitate vengono saltate automaticamente. Intervallo e campi sono persistenti in NVS e vengono scritti solo quando cambiano. Se il Gust Technoline non e' stato ricevuto il display mostra <code>G --</code>, mai uno zero artificiale.</div>"
    new_display_note = "<div class=\"cfgNote\">Le pagine disabilitate vengono saltate automaticamente. <b>Sensori RF</b> mostra fino a 10 trasmettitori Oregon, 5 righe alla volta: G = RSSI ≥ -100 dBm, Y = -115…-101 dBm, R = &lt; -115 dBm; B+ = batteria OK, B! = LOW, B- = N/D. La pagina ruota automaticamente se i sensori sono piu di cinque. Intervallo e campi restano persistenti in NVS. Se il Gust Technoline non e' stato ricevuto il display mostra <code>G --</code>, mai uno zero artificiale.</div>"
    text = replace_once(text, old_display_note, new_display_note, "OLED sensor page note")

    DASH.write_text(text, encoding="utf-8")
    print("Sensor status UI: patched dashboard.html")


patch_web_manager()
patch_dashboard()
