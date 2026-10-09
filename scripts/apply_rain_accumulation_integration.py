"""Final idempotent integration of optional Oregon/Technoline calendar rain accumulation."""
Import('env')
from pathlib import Path
root = Path(env.subst('$PROJECT_DIR'))

def patch(path, old, new, label):
    p = root / path
    src = p.read_text(encoding='utf-8')
    if new in src:
        print('Rain accumulation: already installed', label)
        return
    if old not in src:
        raise RuntimeError('Rain accumulation anchor missing: ' + label)
    p.write_text(src.replace(old, new, 1), encoding='utf-8')
    print('Rain accumulation: installed', label)

patch('src/web_manager.cpp', '#include "sd_logger.h"',
      '#include "sd_logger.h"\n#include "rain_accumulator.h"', 'web include')
patch('src/web_manager.cpp', 'void handleSdConfigGet() {',
      '''void handleRainAccumulation() {
    if (!requireWebAuth()) return;
    sendNoCache();
    server.send(200, "application/json", rainAccumulatorJson());
}

void handleSdConfigGet() {''', 'rain API handler')
patch('src/web_manager.cpp', '    c.logAs3935 = sdBoolArg("as3935", c.logAs3935);',
      '''    c.logAs3935 = sdBoolArg("as3935", c.logAs3935);
    c.rainOregon = sdBoolArg("rain_oregon", c.rainOregon);
    c.rainTechnoline = sdBoolArg("rain_technoline", c.rainTechnoline);
    c.rainPersist = sdBoolArg("rain_sd", c.rainPersist);''', 'SD config post')
patch('src/web_manager.cpp', '    server.on("/api/sd", HTTP_GET, handleSdConfigGet);',
      '''    server.on("/api/rain/accumulation", HTTP_GET, [](){ if (!requireWebAuth()) return; handleRainAccumulation(); });
    server.on("/api/sd", HTTP_GET, handleSdConfigGet);''', 'GET route')
patch('web/dashboard.html',
      '<label class="checkLine"><input id="sdAs3935" type="checkbox"><span>Registra snapshot AS3935</span></label>',
      '''<label class="checkLine"><input id="sdAs3935" type="checkbox"><span>Registra snapshot AS3935</span></label>
<label class="checkLine"><input id="rainAccOregon" type="checkbox"><span>Accumula pioggia Oregon in RAM</span></label>
<label class="checkLine"><input id="rainAccTechnoline" type="checkbox"><span>Accumula pioggia Technoline in RAM</span></label>
<label class="checkLine"><input id="rainAccSd" type="checkbox"><span>Salva accumulatori su microSD (ogni 60 s)</span></label>''', 'SD settings toggles')
patch('web/dashboard.html',
      '<div class="cfgActions"><button class="modeBtn" onclick="saveSd()">Salva microSD</button>',
      '''<div class="cfgNote"><b>Accumulo pioggia (UTC)</b> · indipendente dagli storici mobili 1h/24h. Il totale del sensore non coincide con il cumulato del gateway: il primo telegramma imposta solo la base; reset e duplicati non producono pioggia artificiale. Il salvataggio richiede datalogger SD attivo e scheda montata.</div>
<div class="resourceHeroGrid">
<section class="resourceHero"><div class="heroLabel">Oregon · pioggia cumulata</div><div class="heroValue" id="rainAccOregonToday">--</div><div class="heroState" id="rainAccOregonHistory">--</div></section>
<section class="resourceHero"><div class="heroLabel">Technoline · pioggia cumulata</div><div class="heroValue" id="rainAccTechnolineToday">--</div><div class="heroState" id="rainAccTechnolineHistory">--</div></section>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="loadRainAccumulation()">Aggiorna accumuli</button><span class="muted" id="rainAccStatus">--</span></div>
<div class="cfgActions"><button class="modeBtn" onclick="saveSd()">Salva microSD</button>''', 'SD rain totals view')
patch('web/dashboard.html',
      "E('sdAs3935').checked=!!c.as3935;", 
      "E('sdAs3935').checked=!!c.as3935;E('rainAccOregon').checked=!!c.rain_oregon;E('rainAccTechnoline').checked=!!c.rain_technoline;E('rainAccSd').checked=!!c.rain_sd;", 'SD controls read')
patch('web/dashboard.html',
      "q.set('as3935',E('sdAs3935').checked?'1':'0');",
      "q.set('as3935',E('sdAs3935').checked?'1':'0');q.set('rain_oregon',E('rainAccOregon').checked?'1':'0');q.set('rain_technoline',E('rainAccTechnoline').checked?'1':'0');q.set('rain_sd',E('rainAccSd').checked?'1':'0');", 'SD controls write')
patch('web/dashboard.html',
      "padStart(2,'0');}catch(e){E('sdSummary').textContent='errore lettura microSD'", 
      "padStart(2,'0');loadRainAccumulation();}catch(e){E('sdSummary').textContent='errore lettura microSD'", 'SD refresh rain UI')
patch('web/dashboard.html',
      'async function remountSd(){',
      '''async function loadRainAccumulation(){
 try{
  const r=await fetch('/api/rain/accumulation',{cache:'no-store'});
  if(!r.ok)throw Error('HTTP '+r.status);
  const j=await r.json();
  const mm=n=>Number(n||0).toFixed(2)+' mm';
  for(const [key,id] of [['oregon','Oregon'],['technoline','Technoline']]){
   const v=j[key]||{},has=v.initialized;
   E('rainAcc'+id+'Today').textContent=has?mm(v.today_mm):'--';
   E('rainAcc'+id+'History').textContent=has?('mese '+mm(v.month_mm)+' · anno '+mm(v.year_mm)+' · complessivo '+mm(v.lifetime_mm)):'In attesa del primo telegramma pioggia';
  }
  E('rainAccStatus').textContent=(j.sd_active?'SD persistente':(j.sd_requested?'SD non disponibile':'solo RAM'))+
    (j.sd_restored?' · recuperato da SD':'')+(j.pending_checkpoint?' · salvataggio in attesa':'')+
    (!j.utc_valid?' · NTP non pronto':'')+(j.save_errors?' · errori SD '+j.save_errors:'');
 }catch(e){E('rainAccStatus').textContent='Errore lettura accumuli: '+e;}
}
async function remountSd(){''', 'rain UI renderer')
