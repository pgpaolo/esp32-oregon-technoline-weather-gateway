Import("env")

from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
html = path.read_text(encoding="utf-8")

# This pass runs after apply_compact_sensor_dashboard_v2.py.  Keep the tiny
# pressure pill in the DOM (hidden) so the previous pass remains semantically
# idempotent on a second PlatformIO build in the same workspace.  The larger
# title tile mirrors the same BME280/forecast state without extra HTTP polling.

if ".titleForecastTile{" not in html:
    css = r'''
/* Larger always-visible barometer/forecast summary beside the gateway title. */
.brand{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"title forecast" "sub forecast";column-gap:12px;align-items:center}.brand>.title{grid-area:title}.brand>.sub{grid-area:sub}.titleForecastTile{grid-area:forecast;display:flex;align-items:center;gap:10px;min-width:178px;padding:9px 12px;border:1px solid var(--border);border-radius:13px;background:linear-gradient(180deg,#122238,#0d1929);box-shadow:0 4px 14px rgba(0,0,0,.16)}.titleForecastTile .weatherIcon{display:flex;align-items:center;justify-content:center;width:40px;height:40px;font-size:2rem;line-height:1;flex:0 0 40px}.titleForecastTile .weatherCopy{min-width:0}.titleForecastTile .weatherLabel{font-size:.82rem;font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.titleForecastTile .weatherPressure{margin-top:2px;color:var(--muted);font-size:.72rem;white-space:nowrap}.titleForecastTile.ok{border-color:rgba(48,217,154,.35)}.titleForecastTile.wait{opacity:.78}#hdrPressure{display:none!important}
@media(max-width:760px){.brand{grid-template-columns:1fr;grid-template-areas:"title" "forecast" "sub";row-gap:6px}.titleForecastTile{justify-self:start;min-width:170px;padding:7px 10px}.titleForecastTile .weatherIcon{width:34px;height:34px;flex-basis:34px;font-size:1.7rem}}
'''
    if "</style>" not in html:
        raise RuntimeError("Title forecast tile: </style> anchor missing")
    html = html.replace("</style>", css + "</style>", 1)

if 'id="titleForecastTile"' not in html:
    title_pat = r'(<div\s+class="title">Oregon \+ Technoline 433 Gateway</div>)'
    tile = (
        '<div id="titleForecastTile" class="titleForecastTile wait" title="Previsione WMR200-style dal BME280">'
        '<div id="titleForecastIcon" class="weatherIcon">◌</div>'
        '<div class="weatherCopy"><div id="titleForecastLabel" class="weatherLabel">Previsione --</div>'
        '<div id="titleForecastPressure" class="weatherPressure">Pressione --</div></div></div>'
    )
    html, n = re.subn(title_pat, r'\1' + tile, html, count=1)
    if n != 1:
        raise RuntimeError("Title forecast tile: gateway title anchor missing")

# Extend the existing barometer updater.  It continues updating the hidden
# compact pill for backward compatibility and additionally drives the title
# tile.  No new timer/fetch is introduced.
func_pat = re.compile(r"function updateHeaderBarometer\(bme\)\{.*?\}\nasync function loadBarometer", re.S)
m = func_pat.search(html)
if not m:
    raise RuntimeError("Title forecast tile: updateHeaderBarometer function missing")

if "titleForecastLabel" not in m.group(0):
    replacement = r'''function updateHeaderBarometer(bme){
 const pill=E('hdrPressure'),ico=E('hdrForecastIcon'),txt=E('hdrPressureText');
 const tile=E('titleForecastTile'),tIcon=E('titleForecastIcon'),tLabel=E('titleForecastLabel'),tPressure=E('titleForecastPressure');
 const ok=!!bme.detected&&bme.altimeter_hpa!=null,unit=bme.display_unit||'hPa',view=forecastView(bme.forecast_code),trend=Number(bme.trend_hpa_3h);
 let arrow='→';if(Number.isFinite(trend)){if(trend>=.8)arrow='↑';else if(trend<=-.8)arrow='↓'}
 const pressure=ok?pressureText(bme.altimeter_display,unit)+' '+arrow:'Pressione N/D';
 const tip=(ok?view[1]:'BME280 non rilevato')+' · trend '+(Number.isFinite(trend)?((trend>=0?'+':'')+trend.toFixed(1)+' hPa/3h'):'in acquisizione')+' · quota '+(bme.altitude_m==null?'--':Number(bme.altitude_m).toFixed(0))+' m';
 if(pill&&ico&&txt){ico.textContent=view[0];txt.textContent=pressure;pill.className='statusPill metric '+(ok?'ok':'wait');pill.title=tip}
 if(tile&&tIcon&&tLabel&&tPressure){tIcon.textContent=view[0];tLabel.textContent=ok?view[1]:'Previsione N/D';tPressure.textContent=pressure;tile.className='titleForecastTile '+(ok?'ok':'wait');tile.title=tip}
}
async function loadBarometer'''
    html = html[:m.start()] + replacement + html[m.end():]

path.write_text(html, encoding="utf-8")
print("Applied larger title forecast tile (no extra polling)")
