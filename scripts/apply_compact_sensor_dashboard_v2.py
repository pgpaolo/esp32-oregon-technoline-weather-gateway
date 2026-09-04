Import("env")

from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
html = path.read_text(encoding="utf-8")


def insert_after_regex(pattern, addition, label):
    global html
    m = re.search(pattern, html, flags=re.S)
    if not m:
        raise RuntimeError(f"Compact sensor dashboard v2: missing anchor {label}")
    html = html[:m.end()] + addition + html[m.end():]


# ---------------------------------------------------------------------------
# CSS: collapse only the local BME280/AS3935 card bodies, leaving one compact
# clickable title row. No DOM restructuring is required, so this remains
# compatible with the historical build-time dashboard patch chain.
# ---------------------------------------------------------------------------
if ".sensorFold:not(.open)>.weatherGrid" not in html:
    css = r'''
.sensorFold>.panelHead{cursor:pointer;user-select:none}.sensorFold>.panelHead:after{content:'▸';color:var(--muted);font-size:.9rem;margin-left:5px;transition:transform .15s}.sensorFold.open>.panelHead:after{transform:rotate(90deg)}.sensorFold:not(.open)>.weatherGrid{display:none}.sensorFold:not(.open)>.panelHead{border-bottom:0}.sensorFold .foldHint{color:var(--muted);font-size:.68rem;font-weight:650;margin-left:auto}.forecastGlyph{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;font-size:1rem;line-height:1}.statusPill.metric{color:#dce8f8}.statusPill.metric.warn{color:#f2cb7c}.statusPill.metric.bad{color:#ff9b9b}.baroPreview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:8px 14px 14px}.baroPreview>div{border:1px solid var(--border);border-radius:9px;background:#0a1525;padding:8px}.baroPreview b{display:block;font-size:.86rem}.baroPreview span{color:var(--muted);font-size:.7rem}
'''
    anchor = ".thermoTabs{display:flex;gap:4px;margin-left:auto}"
    if anchor in html:
        html = html.replace(anchor, css + anchor, 1)
    elif "</style>" in html:
        html = html.replace("</style>", css + "</style>", 1)
    else:
        raise RuntimeError("Compact sensor dashboard v2: CSS anchor missing")


# ---------------------------------------------------------------------------
# Header metrics. Insert directly after MQTT, regardless of any other pills or
# buttons that previous build scripts may have inserted later in headerActions.
# ---------------------------------------------------------------------------
if 'id="hdrPressure"' not in html:
    metrics = (
        '<span id="hdrPressure" class="statusPill metric wait" title="BME280 / previsione WMR-style">'
        '<span id="hdrForecastIcon" class="forecastGlyph">◌</span><span id="hdrPressureText">Pressione --</span></span>'
        '<span id="hdrLightning" class="statusPill metric wait" title="Fulmini rilevati dalla partenza">'
        '<span class="forecastGlyph">⚡</span><span id="hdrLightningText">--</span></span>'
    )
    insert_after_regex(r'<span\s+id="hdrMqtt"[^>]*>.*?</span>', metrics, "MQTT header pill")


# ---------------------------------------------------------------------------
# Local sensor panels: collapsed by default, click the existing title row.
# ---------------------------------------------------------------------------
for panel_id in ("bmePanel", "lightningPanel"):
    # Add class to the existing panel without changing its structure.
    pat = rf'<div\s+class="([^"]*compactPanel[^"]*)"\s+id="{panel_id}">'
    m = re.search(pat, html)
    if not m:
        if f'id="{panel_id}"' not in html:
            raise RuntimeError(f"Compact sensor dashboard v2: panel {panel_id} missing")
    elif "sensorFold" not in m.group(1).split():
        classes = m.group(1) + " sensorFold"
        html = html[:m.start()] + f'<div class="{classes}" id="{panel_id}">' + html[m.end():]

    marker = f'id="{panel_id}"><div class="panelHead"'
    if marker in html:
        html = html.replace(
            marker,
            f'id="{panel_id}"><div class="panelHead" onclick="toggleSensorFold(\'{panel_id}\')" title="Clic per mostrare/nascondere i dettagli"',
            1,
        )
    elif f"toggleSensorFold('{panel_id}')" not in html:
        # Tolerate other attributes on panelHead.
        pat_head = rf'(id="{panel_id}">\s*<div\s+class="panelHead")'
        html, n = re.subn(
            pat_head,
            rf'\1 onclick="toggleSensorFold(\'{panel_id}\')" title="Clic per mostrare/nascondere i dettagli"',
            html,
            count=1,
        )
        if n != 1:
            raise RuntimeError(f"Compact sensor dashboard v2: panel head {panel_id} missing")


# ---------------------------------------------------------------------------
# Dedicated BAROMETRO tab in configuration.
# ---------------------------------------------------------------------------
if 'id="tabBarometer"' not in html:
    button = '<button id="tabBarometer" class="cfgTab" onclick="showCfgTab(\'barometer\')">BAROMETRO</button>'
    insert_after_regex(
        r'<button\s+id="tabDisplay"[^>]*>DISPLAY</button>',
        button,
        "DISPLAY configuration tab",
    )

if 'id="cfgBarometer"' not in html:
    page = r'''<div id="cfgBarometer" class="cfgPage">
<div class="cfgExplain">
<section class="cfgSection"><div class="cfgSectionHead">Barometro BME280<span class="cfgSectionSub">Quota per la correzione al livello del mare e unità di visualizzazione.</span></div>
<div class="cfgOptionGrid">
<div class="cfgOption"><label>Quota stazione sul livello del mare (m)<input id="baroAltitude" type="number" min="0" max="9000" step="1" value="0"></label><div class="cfgHelp">Taratura altimetrica: la pressione assoluta del BME280 viene riportata al livello del mare usando questa quota. Cambiando quota lo storico del trend viene azzerato per evitare un falso salto di pressione.</div></div>
<div class="cfgOption"><label>Unità pressione<select id="baroUnit"><option value="0">hPa</option><option value="1">mbar</option><option value="2">inHg</option><option value="3">mmHg</option><option value="4">kPa</option></select></label><div class="cfgHelp">La conversione riguarda la Web UI. Acquisizione, calcoli, MQTT, Weather Realtime API e COMPATIBLE MB restano in hPa.</div></div>
</div>
<div class="baroPreview"><div><b id="baroPreviewStation">--</b><span>pressione stazione</span></div><div><b id="baroPreviewSea">--</b><span>livello del mare</span></div><div><b id="baroPreviewForecast">--</b><span>previsione WMR-style</span></div></div>
</section>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveBarometer()">Salva BAROMETRO</button><button class="modeBtn" onclick="resetBarometer()">Default firmware</button><span id="barometerSummary" class="muted"></span></div>
<div class="cfgNote">Le categorie grafiche seguono quelle esposte dalla WMR200. Il protocollo Oregon disponibile trasmette il risultato della console ma non documenta la formula proprietaria: il gateway usa pressione al livello del mare, trend 3 h e temperatura esterna per classificare la neve.</div>
</div>
'''
    anchor = '<div id="cfgLightning" class="cfgPage">'
    if anchor not in html:
        raise RuntimeError("Compact sensor dashboard v2: AS3935 config page anchor missing")
    html = html.replace(anchor, page + anchor, 1)


# ---------------------------------------------------------------------------
# JavaScript helpers and runtime API.
# ---------------------------------------------------------------------------
if "function toggleSensorFold(" not in html:
    helpers = r'''
function toggleSensorFold(id){const p=E(id);if(p)p.classList.toggle('open')}
function pressureDecimals(unit){return unit==='inHg'?2:(unit==='kPa'?2:(unit==='mmHg'?1:1))}
function pressureText(v,unit){return v==null||!Number.isFinite(Number(v))?'--':Number(v).toFixed(pressureDecimals(unit))+' '+unit}
function forecastView(code){let c=Number(code);const h=(new Date()).getHours(),night=h<7||h>=20;if(night&&c===3)c=4;else if(night&&c===0)c=6;const map={0:['◐','Parzialmente nuvoloso'],1:['☂','Pioggia'],2:['☁','Nuvoloso'],3:['☀','Sereno'],4:['☾','Sereno notte'],5:['❄','Neve'],6:['☾☁','Poco nuvoloso notte'],7:['◌','N/D']};return map[c]||map[7]}
function updateHeaderBarometer(bme){const pill=E('hdrPressure'),ico=E('hdrForecastIcon'),txt=E('hdrPressureText');if(!pill||!ico||!txt)return;const ok=!!bme.detected&&bme.altimeter_hpa!=null,unit=bme.display_unit||'hPa',view=forecastView(bme.forecast_code),trend=Number(bme.trend_hpa_3h);let arrow='→';if(Number.isFinite(trend)){if(trend>=.8)arrow='↑';else if(trend<=-.8)arrow='↓'}ico.textContent=view[0];txt.textContent=ok?pressureText(bme.altimeter_display,unit)+' '+arrow:'Pressione N/D';pill.className='statusPill metric '+(ok?'ok':'wait');pill.title=(ok?view[1]:'BME280 non rilevato')+' · trend '+(Number.isFinite(trend)?((trend>=0?'+':'')+trend.toFixed(1)+' hPa/3h'):'in acquisizione')+' · quota '+(bme.altitude_m==null?'--':Number(bme.altitude_m).toFixed(0))+' m'}
async function loadBarometer(){try{const r=await fetch('/api/barometer/config',{cache:'no-store'});if(!r.ok)throw new Error(await r.text());const c=await r.json();E('baroAltitude').value=Number(c.altitude_m||0).toFixed(0);E('baroUnit').value=String(c.pressure_unit??0);E('barometerSummary').textContent=(c.detected?'BME280 rilevato':'BME280 non rilevato')+' · quota '+Number(c.altitude_m||0).toFixed(0)+' m · '+(c.pressure_unit_name||'hPa');const sr=await fetch('/api/state',{cache:'no-store'}),s=await sr.json(),b=s.bme280||{},u=b.display_unit||c.pressure_unit_name||'hPa';E('baroPreviewStation').textContent=pressureText(b.pressure_station_display,u);E('baroPreviewSea').textContent=pressureText(b.altimeter_display,u);const fv=forecastView(b.forecast_code);E('baroPreviewForecast').textContent=fv[0]+' '+fv[1];}catch(e){if(E('barometerSummary'))E('barometerSummary').textContent='errore lettura barometro'}}
async function saveBarometer(){const q=new URLSearchParams();q.set('altitude_m',E('baroAltitude').value);q.set('pressure_unit',E('baroUnit').value);const r=await fetch('/api/barometer/config',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:q.toString(),cache:'no-store'});if(!r.ok){alert('BAROMETRO: '+await r.text());return}await loadBarometer();await refresh()}
async function resetBarometer(){if(!confirm('Ripristinare quota e unità pressione ai default firmware?'))return;const r=await fetch('/api/barometer/reset',{method:'POST',cache:'no-store'});if(!r.ok){alert('Reset BAROMETRO fallito: '+await r.text());return}await loadBarometer();await refresh()}

'''
    anchor = "async function powerOffDevice()"
    if anchor not in html:
        # Fall back to the first known async UI control function.
        m = re.search(r'async function [A-Za-z0-9_]+\(', html)
        if not m:
            raise RuntimeError("Compact sensor dashboard v2: JS insertion anchor missing")
        html = html[:m.start()] + helpers + html[m.start():]
    else:
        html = html.replace(anchor, helpers + anchor, 1)


# Add BAROMETRO page toggling/loading without modifying the historical stable
# configuration-tab array that other idempotence scripts intentionally retain.
if "cfgBarometer').classList.toggle" not in html:
    sig = "function showCfgTab(t){"
    if sig not in html:
        raise RuntimeError("Compact sensor dashboard v2: showCfgTab missing")
    injected = (
        sig
        + "E('cfgBarometer').classList.toggle('active',t==='barometer');"
        + "E('tabBarometer').classList.toggle('active',t==='barometer');"
        + "if(t==='barometer')loadBarometer();"
    )
    html = html.replace(sig, injected, 1)


# BME pressure display. Canonical hPa values remain available in /api/state;
# these three UI lines use the additional display-unit fields only.
replacements = {
    "psta.textContent=f(bme.pressure_station_hpa,1,' hPa');": "psta.textContent=pressureText(bme.pressure_station_display,bme.display_unit||'hPa');",
    "psea.textContent=f(bme.altimeter_hpa,1,' hPa');": "psea.textContent=pressureText(bme.altimeter_display,bme.display_unit||'hPa');",
    "ptrend.textContent=bme.trend_hpa_3h==null?'in acquisizione':((bme.trend_hpa_3h>=0?'+':'')+f(bme.trend_hpa_3h,1,' hPa/3h'));": "ptrend.textContent=bme.trend_display==null?'in acquisizione':((bme.trend_display>=0?'+':'')+pressureText(bme.trend_display,bme.display_unit||'hPa')+'/3h');",
}
for old, new in replacements.items():
    if old in html:
        html = html.replace(old, new, 1)
    elif new not in html:
        raise RuntimeError("Compact sensor dashboard v2: BME display anchor missing")

old_forecast = "forecast.textContent=bme.forecast||'In acquisizione';"
new_forecast = "const fv=forecastView(bme.forecast_code);forecast.textContent=fv[0]+' '+fv[1];updateHeaderBarometer(bme);"
if old_forecast in html:
    html = html.replace(old_forecast, new_forecast, 1)
elif new_forecast not in html:
    raise RuntimeError("Compact sensor dashboard v2: forecast display anchor missing")


# AS3935 header status reuses the existing refresh payload; no extra HTTP poll.
old_lg = "function updateLightningUi(l){if(!l)return;"
if "hdrLightningText" in html and "Fulmini rilevati dalla partenza: '+String(l.lightning_total" not in html:
    if old_lg not in html:
        raise RuntimeError("Compact sensor dashboard v2: updateLightningUi anchor missing")
    new_lg = old_lg + "const hp=E('hdrLightning'),ht=E('hdrLightningText');if(hp&&ht){const ok=!!l.enabled&&!!l.detected&&!!l.irq_ok&&!!l.calibration_ok;hp.className='statusPill metric '+(!l.enabled?'wait':(ok?'ok':'bad'));ht.textContent=String(l.lightning_total||0);hp.title=!l.enabled?'AS3935 disabilitato':(!l.detected?'AS3935 non rilevato':('Fulmini rilevati dalla partenza: '+String(l.lightning_total||0)+(l.last_lightning_ms?' · ultimo '+(l.distance_out_of_range?'>40 km':String(l.last_distance_km)+' km'):'')));}"
    html = html.replace(old_lg, new_lg, 1)


# Initial configuration load. Live pressure is then updated by the normal state
# refresh and lightning by the existing AS3935 state refresh.
startup = "bindDisplayFieldAutoPages();loadNetwork();loadMqtt();refreshLightning();refresh();"
if startup in html and "loadMqtt();loadBarometer();refreshLightning()" not in html:
    html = html.replace(startup, "bindDisplayFieldAutoPages();loadNetwork();loadMqtt();loadBarometer();refreshLightning();refresh();", 1)

path.write_text(html, encoding="utf-8")
print("Applied compact sensor dashboard v2, BAROMETRO settings and header metrics")
