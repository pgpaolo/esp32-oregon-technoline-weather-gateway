Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
d = path.read_text(encoding="utf-8")

MARKER = "SD_HEADER_STABLE_V2"


def replace_js_function(text, signature, replacement):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"SD header indicator: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"SD header indicator: opening brace missing: {signature}")
    depth = 0
    quote = None
    escape = False
    for i in range(brace, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[:start] + replacement + text[i + 1:]
    raise RuntimeError(f"SD header indicator: closing brace missing: {signature}")


# Keep the header footprint invariant. The previous implementation changed the
# visible text between SD SCRIVE / SD ON / SD PRONTA / SD KO / SD OFF, which
# changed the pill width and made the whole header reflow at every SD write.
# The detailed state remains available in the tooltip; only the existing status
# dot/border changes colour.
if 'id="hdrSd"' not in d:
    raise RuntimeError("SD header indicator: hdrSd badge missing")

badge_start = d.find('<span id="hdrSd"')
badge_end = d.find('</span>', badge_start)
if badge_start < 0 or badge_end < 0:
    raise RuntimeError("SD header indicator: hdrSd markup malformed")
badge_end += len('</span>')
new_badge = '<span id="hdrSd" class="statusPill sdPill wait" title="microSD · stato in attesa" aria-label="microSD">SD</span>'
d = d[:badge_start] + new_badge + d[badge_end:]

if MARKER not in d:
    css = r'''/* SD_HEADER_STABLE_V2 */
.statusPill.sdPill{width:72px;min-width:72px;flex:0 0 72px;justify-content:center;white-space:nowrap;transition:color .16s,border-color .16s,background-color .16s}
.statusPill.sdPill.write{background:#0b2230}
.statusPill.sdPill.off{color:var(--muted);border-color:var(--border);background:#0d1829}
.statusPill.sdPill.off:before{background:#65758a;box-shadow:0 0 0 3px #65758a18}
'''
    style_end = d.find("</style>")
    if style_end < 0:
        raise RuntimeError("SD header indicator: </style> anchor missing")
    d = d[:style_end] + css + d[style_end:]

if "let sdHeaderWritten=null;" not in d:
    raise RuntimeError("SD header indicator: sdHeaderWritten state missing")

update_fn = r'''function updateSdHeader(c,s){ // SD_HEADER_STABLE_V2
 const e=E('hdrSd');if(!e)return;
 const n=Number(s.written||0),wrote=sdHeaderWritten!==null&&n>sdHeaderWritten;
 sdHeaderWritten=n;
 let cls='off',state='assente o disattivata';
 if(s.mounted){
  if(wrote){cls='write';state='scrittura in corso'}
  else if(c.enabled){cls='ok';state='logger attivo'}
  else{cls='ok';state='scheda montata'}
 }else if(c.enabled){cls='bad';state='errore mount'}
 e.className='statusPill sdPill '+cls;
 e.textContent='SD';
 e.title='microSD · '+state+' · scritture '+n+' · coda '+Number(s.queue_depth||0)+' · errori '+Number(s.write_errors||0)+(s.file?' · '+s.file:'');
 e.setAttribute('aria-label','microSD '+state);
}'''

d = replace_js_function(d, "function updateSdHeader(c,s)", update_fn)

refresh_fn = r'''async function refreshSdHeader(){
 try{
  const j=await (await fetch('/api/sd',{cache:'no-store'})).json();
  updateSdHeader(j.config||{},j.status||{});
 }catch(e){
  const h=E('hdrSd');
  if(h){h.className='statusPill sdPill bad';h.textContent='SD';h.title='microSD · errore lettura stato';h.setAttribute('aria-label','microSD errore')}
 }
}'''

d = replace_js_function(d, "async function refreshSdHeader()", refresh_fn)

# Guard against the old variable-width labels surviving in a mutated source
# archive. These strings are no longer needed because state is shown by colour
# and tooltip while the visible label remains exactly "SD".
for legacy in ("SD SCRIVE", "SD ON", "SD PRONTA", "SD KO", "SD OFF", "SD ERR"):
    if legacy in d:
        raise RuntimeError(f"SD header indicator: legacy variable label survived: {legacy}")

path.write_text(d, encoding="utf-8")
print("SD header indicator: fixed-width SD pill, colour-only state, no header reflow")
