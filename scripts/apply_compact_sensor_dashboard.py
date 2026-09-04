Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
html = path.read_text(encoding="utf-8")


def replace_once(old, new, label):
    global html
    if new in html:
        return
    if old not in html:
        raise RuntimeError(f"Compact sensor dashboard: missing anchor {label}")
    html = html.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Styling: native <details> for optional local sensors and tiny header metrics.
# ---------------------------------------------------------------------------
css_anchor = ".thermoTabs{display:flex;gap:4px;margin-left:auto}"
css_block = r'''
.sensorFold>summary{list-style:none;cursor:pointer;user-select:none}.sensorFold>summary::-webkit-details-marker{display:none}.sensorFold>summary:after{content:'▸';color:var(--muted);font-size:.9rem;margin-left:6px;transition:transform .15s}.sensorFold[open]>summary:after{transform:rotate(90deg)}.sensorFold:not([open])>summary{border-bottom:0}.sensorFold .foldHint{color:var(--muted);font-size:.7rem;font-weight:650;margin-left:auto}.forecastGlyph{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;font-size:1rem;line-height:1}.statusPill.metric{color:#dce8f8}.statusPill.metric.warn{color:#f2cb7c}.statusPill.metric.bad{color:#ff9b9b}.baroPreview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:8px}.baroPreview>div{border:1px solid var(--border);border-radius:9px;background:#0a1525;padding:8px}.baroPreview b{display:block;font-size:.86rem}.baroPreview span{color:var(--muted);font-size:.7rem}
'''
if "sensorFold>summary" not in html:
    if css_anchor not in html:
        raise RuntimeError("Compact sensor dashboard: CSS anchor missing")
    html = html.replace(css_anchor, css_block + css_anchor, 1)


# ---------------------------------------------------------------------------
# Header live summaries: pressure/forecast and lightning session count.
# ---------------------------------------------------------------------------
replace_once(
    '<span id="hdrMqtt" class="statusPill wait">MQTT...</span><button id="displayBtn"',
    '<span id="hdrMqtt" class="statusPill wait">MQTT...</span>'
    '<span id="hdrPressure" class="statusPill metric wait" title="BME280 / previsione WMR-style"><span id="hdrForecastIcon" class="forecastGlyph">◌</span><span id="hdrPressureText">Pressione --</span></span>'
    '<span id="hdrLightning" class="statusPill metric wait" title="Fulmini rilevati dalla partenza"><span class="forecastGlyph">⚡</span><span id="hdrLightningText">--</span></span>'
    '<button id="displayBtn"',
    "header metric pills",
)


# ---------------------------------------------------------------------------
# BME280 and AS3935 are collapsed by default; their full contents are retained.
# ---------------------------------------------------------------------------
replace_once(
    '<div class="panel stationBme compactPanel" id="bmePanel"><div class="panelHead">Sensore locale · BME280 <span id="bmeBadge" class="badge off">rilevamento...</span></div><div class="weatherGrid bmeGrid">',
    '<details class="panel stationBme compactPanel sensorFold" id="bmePanel"><summary class="panelHead"><span>Sensore locale · BME280</span><span class="foldHint">clic per dettagli</span><span id="bmeBadge" class="badge off">rilevamento...</span></summary><div class="weatherGrid bmeGrid">',
    "BME panel opening",
)
replace_once(
    '<div class="foot" id="footP"></div></section>\n</div></div>\n<div class="panel stationLightning compactPanel" id="lightningPanel">',
    '<div class="foot" id="footP"></div></section>\n</div></details>\n<div class="panel stationLightning compactPanel" id="lightningPanel">',
    "BME panel closing",
)
replace_once(
    '<div class="panel stationLightning compactPanel" id="lightningPanel"><div class="panelHead">Rilevatore fulmini · AS3935 <span id="lgBadge" class="badge off">rilevamento...</span></div><div class="weatherGrid lightningGrid">',
    '<details class="panel stationLightning compactPanel sensorFold" id="lightningPanel"><summary class="panelHead"><span>Rilevatore fulmini · AS3935</span><span class="foldHint">clic per dettagli</span><span id="lgBadge" class="badge off">rilevamento...</span></summary><div class="weatherGrid lightningGrid">',
    "AS3935 panel opening",
)
replace_once(
    '<div class="foot">MQTT: <code>…/as3935/state</code> + <code>…/as3935/event</code>.</div></section>\n</div></div>\n</section>\n<section id="mainHardware"',
    '<div class="foot">MQTT: <code>…/as3935/state</code> + <code>…/as3935/event</code>.</div></section>\n</div></details>\n</section>\n<section id="mainHardware"',
    "AS3935 panel closing",
)


# ---------------------------------------------------------------------------
# Dedicated BAROMETRO configuration tab.
# ---------------------------------------------------------------------------
replace_once(
    '<button id="tabDisplay" class="cfgTab" onclick="showCfgTab(\'display\')">DISPLAY</button><button id="tabLightning"',
    '<button id="tabDisplay" class="cfgTab" onclick="showCfgTab(\'display\')">DISPLAY</button><button id="tabBarometer" class="cfgTab" onclick="showCfgTab(\'barometer\')">BAROMETRO</button><button id="tabLightning"',
    "barometer tab",
)

barometer_page = r'''<div id="cfgBarometer" class="cfgPage">
<div class="cfgExplain">
<section class="cfgSection"><div class="cfgSectionHead">Barometro BME280<span class="cfgSectionSub">Quota per la correzione al livello del mare e unità usata soltanto nella Web UI.</span></div>
<div class="cfgOptionGrid">
<div class="cfgOption"><label>Quota stazione sul livello del mare (m)<input id="baroAltitude" type="number" min="0" max="9000" step="1" value="0"></label><div class="cfgHelp">La pressione assoluta del BME280 viene riportata al livello del mare usando questa quota. Cambiando quota lo storico del trend viene azzerato per evitare un falso salto di pressione.</div></div>
<div class="cfgOption"><label>Unità pressione<select id="baroUnit"><option value="0">hPa</option><option value="1">mbar</option><option value="2">inHg</option><option value="3">mmHg</option><option value="4">kPa</option></select></label><div class="cfgHelp">Solo visualizzazione Web. Calcoli interni, API canoniche, MQTT e COMPATIBLE MB restano in hPa.</div></div>
</div>
<div class="baroPreview"><div><b id="baroPreviewStation">--</b><span>pressione stazione</span></div><div><b id="baroPreviewSea">--</b><span>livello del mare</span></div><div><b id="baroPreviewForecast">--</b><span>previsione WMR-style</span></div></div>
</section>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveBarometer()">Salva BAROMETRO</button><button class="modeBtn" onclick="resetBarometer()">Default firmware</button><span id="barometerSummary" class="muted"></span></div>
<div class="cfgNote">Le categorie della previsione seguono la presentazione WMR200 (sereno, parzialmente nuvoloso, nuvoloso, pioggia, neve e varianti notte). Il codice Oregon disponibile trasmette il risultato della console ma non documenta la formula proprietaria: il gateway usa pressione al livello del mare + trend 3 h e temperatura esterna per la neve.</div>
</div>
'''
if 'id="cfgBarometer"' not in html:
    anchor = '<div id="cfgLightning" class="cfgPage">'
    if anchor not in html:
        raise RuntimeError("Compact sensor dashboard: barometer page anchor missing")
    html = html.replace(anchor, barometer_page + anchor, 1)


# ---------------------------------------------------------------------------
# Config tab navigation.
# ---------------------------------------------------------------------------
replace_once(
    "for(const x of ['net','thermo','mqtt','display','lightning','backup'])",
    "for(const x of ['net','thermo','mqtt','display','barometer','lightning','backup'])",
    "config tab list",
)
replace_once(
    "else if(t==='display')loadDisplay();else if(t==='lightning')loadLightning();",
    "else if(t==='display')loadDisplay();else if(t==='barometer')loadBarometer();else if(t==='lightning')loadLightning();",
    "config tab loader",
)


# ---------------------------------------------------------------------------
# Pressure formatting, forecast icon and configuration API helpers.
# ---------------------------------------------------------------------------
helper_anchor = "async function powerOffDevice()"
if "function pressureDecimals(" not in html:
    helpers = r'''
function pressureDecimals(unit){return unit==='inHg'?2:(unit==='kPa'?2:(unit==='mmHg'?1:1))}
function pressureText(v,unit){return v==null?'--':Number(v).toFixed(pressureDecimals(unit))+' '+unit}
function forecastView(code){let c=Number(code);const h=(new Date()).getHours(),night=h<7||h>=20;if(night&&c===3)c=4;else if(night&&c===0)c=6;const map={0:['◐','Parzialmente nuvoloso'],1:['☂','Pioggia'],2:['☁','Nuvoloso'],3:['☀','Sereno'],4:['☾','Sereno notte'],5:['❄','Neve'],6:['☾☁','Poco nuvoloso notte'],7:['◌','N/D']};return map[c]||map[7]}
function updateHeaderBarometer(bme){const pill=E('hdrPressure'),ico=E('hdrForecastIcon'),txt=E('hdrPressureText');if(!pill||!ico||!txt)return;const ok=!!bme.detected&&bme.altimeter_hpa!=null,unit=bme.display_unit||'hPa',view=forecastView(bme.forecast_code),trend=Number(bme.trend_hpa_3h);let arrow='→';if(Number.isFinite(trend)){if(trend>=.8)arrow='↑';else if(trend<=-.8)arrow='↓'}ico.textContent=view[0];txt.textContent=ok?pressureText(bme.altimeter_display,unit)+' '+arrow:'Pressione N/D';pill.className='statusPill metric '+(ok?'ok':'wait');pill.title=(ok?view[1]:'BME280 non rilevato')+' · trend '+(Number.isFinite(trend)?((trend>=0?'+':'')+trend.toFixed(1)+' hPa/3h'):'in acquisizione')+' · quota '+(bme.altitude_m==null?'--':Number(bme.altitude_m).toFixed(0))+' m'}
async function loadBarometer(){try{const c=await (await fetch('/api/barometer/config',{cache:'no-store'})).json();E('baroAltitude').value=Number(c.altitude_m||0).toFixed(0);E('baroUnit').value=String(c.pressure_unit??0);E('barometerSummary').textContent=(c.detected?'BME280 rilevato':'BME280 non rilevato')+' · quota '+Number(c.altitude_m||0).toFixed(0)+' m · '+(c.pressure_unit_name||'hPa');const s=await (await fetch('/api/state',{cache:'no-store'})).json(),b=s.bme280||{},u=b.display_unit||c.pressure_unit_name||'hPa';E('baroPreviewStation').textContent=pressureText(b.pressure_station_display,u);E('baroPreviewSea').textContent=pressureText(b.altimeter_display,u);E('baroPreviewForecast').textContent=(forecastView(b.forecast_code)[0]+' '+(b.forecast||'N/D'));}catch(e){E('barometerSummary').textContent='errore lettura barometro'}}
async function saveBarometer(){const q=new URLSearchParams();q.set('altitude_m',E('baroAltitude').value);q.set('pressure_unit',E('baroUnit').value);const r=await fetch('/api/barometer/config',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});if(!r.ok){alert('BAROMETRO: '+await r.text());return}await loadBarometer();await refresh();}
async function resetBarometer(){if(!confirm('Ripristinare quota e unità pressione ai default firmware?'))return;const r=await fetch('/api/barometer/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset BAROMETRO fallito: '+await r.text());return}await loadBarometer();await refresh();}

'''
    if helper_anchor not in html:
        raise RuntimeError("Compact sensor dashboard: JS helper anchor missing")
    html = html.replace(helper_anchor, helpers + helper_anchor, 1)


# ---------------------------------------------------------------------------
# Replace hard-coded hPa Web rendering with the selected UI unit, while trend
# classification continues to use canonical hPa in firmware.
# ---------------------------------------------------------------------------
old_bme = "psta.textContent=f(bme.pressure_station_hpa,1,' hPa');psea.textContent=f(bme.altimeter_hpa,1,' hPa');ptrend.textContent=bme.trend_hpa_3h==null?'in acquisizione':((bme.trend_hpa_3h>=0?'+':'')+f(bme.trend_hpa_3h,1,' hPa/3h'));forecast.textContent=bme.forecast||'In acquisizione';ageP.textContent=age(bme.age_s);"
new_bme = "const baroUnit=bme.display_unit||'hPa';psta.textContent=pressureText(bme.pressure_station_display,baroUnit);psea.textContent=pressureText(bme.altimeter_display,baroUnit);ptrend.textContent=bme.trend_display==null?'in acquisizione':((bme.trend_display>=0?'+':'')+pressureText(bme.trend_display,baroUnit)+'/3h');const fv=forecastView(bme.forecast_code);forecast.textContent=fv[0]+' '+(bme.forecast||fv[1]);updateHeaderBarometer(bme);ageP.textContent=age(bme.age_s);"
replace_once(old_bme, new_bme, "BME rendering")


# ---------------------------------------------------------------------------
# AS3935 top pill mirrors the session lightning counter without adding polling.
# ---------------------------------------------------------------------------
old_lg = "function updateLightningUi(l){if(!l)return;const badge=E('lgBadge');"
new_lg = "function updateLightningUi(l){if(!l)return;const hp=E('hdrLightning'),ht=E('hdrLightningText');if(hp&&ht){const ok=!!l.enabled&&!!l.detected&&!!l.irq_ok&&!!l.calibration_ok;hp.className='statusPill metric '+(!l.enabled?'wait':(ok?'ok':'bad'));ht.textContent=String(l.lightning_total||0);hp.title=!l.enabled?'AS3935 disabilitato':(!l.detected?'AS3935 non rilevato':('Fulmini rilevati dalla partenza: '+String(l.lightning_total||0)+(l.last_lightning_ms?' · ultimo '+(l.distance_out_of_range?'>40 km':String(l.last_distance_km)+' km'):'')));}const badge=E('lgBadge');"
replace_once(old_lg, new_lg, "AS3935 header pill")


# Load barometer once at startup; regular /api/state refresh handles live data.
replace_once(
    "bindDisplayFieldAutoPages();loadNetwork();loadMqtt();refreshLightning();refresh();",
    "bindDisplayFieldAutoPages();loadNetwork();loadMqtt();loadBarometer();refreshLightning();refresh();",
    "startup barometer load",
)

path.write_text(html, encoding="utf-8")
print("Applied compact BME280/AS3935 panels, header metrics and BAROMETRO Web tab")
