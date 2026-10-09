"""Idempotent Web presentation of actual MB weather value count and RF source."""
Import('env')
from pathlib import Path
root = Path(env.subst('$PROJECT_DIR'))
p = root / 'web/dashboard.html'
s = p.read_text(encoding='utf-8')
old = "if(Number(m.payload_fields))s+=' · '+m.payload_fields+' campi / '+m.payload_bytes+' B';e.textContent=s;"
new = "if(Number(m.payload_fields))s+=' · '+m.payload_fields+' campi / '+m.payload_bytes+' B';if(m.source_station)s+=' · sorgente '+m.source_station;if(m.weather_measurements!=null)s+=' · misure meteo reali '+m.weather_measurements;e.textContent=s;"
if new not in s:
    if old not in s:
        raise RuntimeError('MB diagnostics UI anchor missing')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')
    print('MB diagnostics Web UI: source and actual meteorological count displayed')
else:
    print('MB diagnostics Web UI: already applied')
