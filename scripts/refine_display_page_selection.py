from pathlib import Path

p = Path('src/web_manager.cpp')
s = p.read_text(encoding='utf-8')

old = "function displaySelectPages(v){document.querySelectorAll('[data-dpagebit]').forEach(x=>x.checked=!!v)}function displayAutoEnablePages(){const groups=[['data-denvbit',0],['data-dwindbit',1],['data-dtechbit',2],['data-dpressbit',3],['data-dstatusbit',4]];for(const [attr,bit] of groups){if([...document.querySelectorAll('['+attr+']')].some(x=>x.checked)){const p=document.querySelector('[data-dpagebit=\\\"'+bit+'\\\"]');if(p)p.checked=true;}}}"
new = "function displaySelectPages(v){document.querySelectorAll('[data-dpagebit]').forEach(x=>x.checked=!!v)}function bindDisplayFieldAutoPages(){const groups=[['data-denvbit',0],['data-dwindbit',1],['data-dtechbit',2],['data-dpressbit',3],['data-dstatusbit',4]];for(const [attr,bit] of groups){document.querySelectorAll('['+attr+']').forEach(x=>x.addEventListener('change',()=>{if(x.checked){const p=document.querySelector('[data-dpagebit=\\\"'+bit+'\\\"]');if(p)p.checked=true;}}));}}"
if s.count(old) != 1:
    raise SystemExit('DISPLAY helper anchor not found exactly once')
s = s.replace(old, new, 1)

old = "async function saveDisplayConfig(){displayAutoEnablePages();const pageMask=dGet('data-dpagebit');"
new = "async function saveDisplayConfig(){const pageMask=dGet('data-dpagebit');"
if s.count(old) != 1:
    raise SystemExit('DISPLAY save anchor not found exactly once')
s = s.replace(old, new, 1)

old = "loadNetwork();loadMqtt();refresh();setInterval(refresh,2000);"
new = "bindDisplayFieldAutoPages();loadNetwork();loadMqtt();refresh();setInterval(refresh,2000);"
if s.count(old) != 1:
    raise SystemExit('DISPLAY init anchor not found exactly once')
s = s.replace(old, new, 1)

p.write_text(s, encoding='utf-8')
print('DISPLAY page-selection refinement applied')
