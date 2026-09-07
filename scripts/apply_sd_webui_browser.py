Import("env")
from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Public SD browsing API. This pass intentionally runs late, after SdFat and
# Web authentication have already been generated, but before Web gzip output.
# It therefore fixes the final dashboard rather than an intermediate template.
# ---------------------------------------------------------------------------
h_path = "src/sd_logger.h"
h = read(h_path)
if "ADMIN_SENSOR_SD_BROWSER_V1" not in h:
    anchor = "String sdLoggerStatusJson();\n"
    if anchor not in h:
        raise RuntimeError("SD browser: sdLoggerStatusJson declaration missing")
    h = h.replace(
        anchor,
        anchor
        + "\n// ADMIN_SENSOR_SD_BROWSER_V1\n"
        + "String sdLoggerFilesJson();\n"
        + "bool sdLoggerReadFileChunk(const String &path, uint32_t offset, size_t maxBytes, String &data, uint32_t &totalBytes);\n",
        1,
    )
    write(h_path, h)
    print("SD browser: public file API declared")
else:
    print("SD browser: public file API already declared")


cpp_path = "src/sd_logger.cpp"
cpp = read(cpp_path)
if "ADMIN_SENSOR_SD_BROWSER_V1" not in cpp:
    if "SdFat32 sd;" not in cpp or "File32" not in cpp:
        raise RuntimeError("SD browser: SdFat backend must run first")

    block = r'''
// ADMIN_SENSOR_SD_BROWSER_V1
namespace {
constexpr uint16_t SD_BROWSER_FILE_LIMIT = 48U;
constexpr size_t SD_BROWSER_CHUNK_MAX = 6144U;

bool validSdBrowserPath(const String &path) {
    return path.length() > 13U && path.length() < 96U &&
           path.startsWith("/weather/") && path.endsWith(".csv") &&
           path.indexOf("..") < 0 && path.indexOf('\\') < 0;
}

void appendSdJsonString(String &out, const char *value) {
    out += '"';
    if (value) {
        for (const char *p = value; *p; ++p) {
            const unsigned char c = static_cast<unsigned char>(*p);
            if (c == '"' || c == '\\') {
                out += '\\';
                out += static_cast<char>(c);
            } else if (c >= 0x20U) {
                out += static_cast<char>(c);
            }
        }
    }
    out += '"';
}

void appendSdDirectoryFiles(const String &dirPath, uint8_t depth, String &out,
                            uint16_t &count, bool &first) {
    if (!status.mounted || depth > 3U || count >= SD_BROWSER_FILE_LIMIT) return;

    File32 dir = sd.open(dirPath.c_str(), O_RDONLY);
    if (!dir || !dir.isDir()) {
        dir.close();
        return;
    }

    File32 entry;
    while (count < SD_BROWSER_FILE_LIMIT && entry.openNext(&dir, O_RDONLY)) {
        char name[64]{};
        entry.getName(name, sizeof(name));
        if (!name[0] || name[0] == '.') {
            entry.close();
            continue;
        }

        String full = dirPath;
        if (!full.endsWith("/")) full += '/';
        full += name;

        if (entry.isDir()) {
            entry.close();
            appendSdDirectoryFiles(full, static_cast<uint8_t>(depth + 1U), out, count, first);
            continue;
        }

        if (full.endsWith(".csv")) {
            const uint32_t fileSize = static_cast<uint32_t>(entry.fileSize());
            if (!first) out += ',';
            first = false;
            out += "{\"path\":";
            appendSdJsonString(out, full.c_str());
            out += ",\"size\":" + String(fileSize) + "}";
            count++;
        }
        entry.close();
    }
    dir.close();
}
} // namespace

String sdLoggerFilesJson() {
    String out;
    out.reserve(4096U);
    out = "{\"status\":" + sdLoggerStatusJson() + ",\"files\":[";
    uint16_t count = 0;
    bool first = true;
    appendSdDirectoryFiles("/weather", 0U, out, count, first);
    out += "],\"count\":" + String(count);
    out += ",\"truncated\":";
    out += count >= SD_BROWSER_FILE_LIMIT ? "true" : "false";
    out += "}";
    return out;
}

bool sdLoggerReadFileChunk(const String &path, uint32_t offset, size_t maxBytes,
                           String &data, uint32_t &totalBytes) {
    data = "";
    totalBytes = 0;
    if (!status.mounted || !validSdBrowserPath(path)) return false;
    if (maxBytes == 0U || maxBytes > SD_BROWSER_CHUNK_MAX) maxBytes = SD_BROWSER_CHUNK_MAX;

    File32 file = sd.open(path.c_str(), O_RDONLY);
    if (!file || file.isDir()) {
        file.close();
        return false;
    }

    totalBytes = static_cast<uint32_t>(file.fileSize());
    if (offset > totalBytes) {
        file.close();
        return false;
    }
    if (offset == totalBytes) {
        file.close();
        return true;
    }
    if (!file.seekSet(offset)) {
        file.close();
        return false;
    }

    const size_t remaining = static_cast<size_t>(totalBytes - offset);
    const size_t wanted = remaining < maxBytes ? remaining : maxBytes;
    if (!data.reserve(wanted + 1U)) {
        file.close();
        return false;
    }

    uint8_t buf[512];
    size_t done = 0;
    while (done < wanted) {
        const size_t ask = (wanted - done) < sizeof(buf) ? (wanted - done) : sizeof(buf);
        const int got = file.read(buf, ask);
        if (got <= 0) break;
        data.concat(reinterpret_cast<const char *>(buf), static_cast<unsigned int>(got));
        done += static_cast<size_t>(got);
    }
    file.close();
    return done == wanted;
}

'''
    anchor = "void enqueueSdOregon("
    pos = cpp.find(anchor)
    if pos < 0:
        raise RuntimeError("SD browser: enqueueSdOregon anchor missing")
    cpp = cpp[:pos] + block + cpp[pos:]
    write(cpp_path, cpp)
    print("SD browser: SdFat file listing/chunk reader added")
else:
    print("SD browser: SdFat file API already present")


# ---------------------------------------------------------------------------
# Authenticated Web endpoints. Keep each payload below the 24 KiB AdminSensor
# dynamic-response ceiling. CSV downloads are assembled in the browser from
# 6 KiB HTTP chunks, so the same feature works locally and through WSS.
# ---------------------------------------------------------------------------
wm_path = "src/web_manager.cpp"
wm = read(wm_path)
if "ADMIN_SENSOR_SD_BROWSER_V1" not in wm:
    handlers = r'''
// ADMIN_SENSOR_SD_BROWSER_V1
void handleSdFiles() {
    if (!requireWebAuth()) return;
    sendNoCache();
    server.send(200, "application/json", sdLoggerFilesJson());
}

void handleSdRead() {
    if (!requireWebAuth()) return;
    if (!server.hasArg("path")) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"path required\"}");
        return;
    }
    const String path = server.arg("path");
    const uint32_t offset = server.hasArg("offset")
        ? static_cast<uint32_t>(strtoul(server.arg("offset").c_str(), nullptr, 10)) : 0U;
    size_t limit = server.hasArg("limit")
        ? static_cast<size_t>(strtoul(server.arg("limit").c_str(), nullptr, 10)) : 6144U;
    if (limit == 0U || limit > 6144U) limit = 6144U;

    String data;
    uint32_t totalBytes = 0;
    if (!sdLoggerReadFileChunk(path, offset, limit, data, totalBytes)) {
        server.send(404, "application/json", "{\"ok\":false,\"error\":\"SD file unavailable\"}");
        return;
    }
    sendNoCache();
    server.sendHeader("X-SD-File-Size", String(totalBytes));
    server.send(200, "text/csv; charset=utf-8", data);
}

'''
    anchor = "void handleThermoConfigGet() {"
    pos = wm.find(anchor)
    if pos < 0:
        raise RuntimeError("SD browser: Web handler anchor missing")
    wm = wm[:pos] + handlers + wm[pos:]

    nf = re.search(r'(?m)^([ \t]*)server\.onNotFound\s*\(', wm)
    if not nf:
        raise RuntimeError("SD browser: server.onNotFound route anchor missing")
    indent = nf.group(1)
    routes = (
        f'{indent}server.on("/api/sd/files", HTTP_GET, handleSdFiles);\n'
        f'{indent}server.on("/api/sd/read", HTTP_GET, handleSdRead);\n'
    )
    wm = wm[:nf.start()] + routes + wm[nf.start():]
    write(wm_path, wm)
    print("SD browser: authenticated file routes added")
else:
    print("SD browser: authenticated file routes already present")


# ---------------------------------------------------------------------------
# Final dashboard repair/enrichment.
# The original SD generator used an overly broad idempotence test for the
# showCfgTab() loop. On some generated/source-archive builds the MICROSD button
# existed but 'sd' was absent from the loop, so clicking it hid every page.
# Repair the *final* dashboard here, after all other configuration-tab passes.
# ---------------------------------------------------------------------------
d_path = "web/dashboard.html"
d = read(d_path)

if 'id="tabSd"' not in d:
    anchor = '<button id="tabLightning"'
    pos = d.find(anchor)
    if pos < 0:
        raise RuntimeError("SD browser: Lightning tab anchor missing")
    d = d[:pos] + '<button id="tabSd" class="cfgTab" onclick="showCfgTab(\'sd\')">MICROSD</button>' + d[pos:]

if 'id="cfgSd"' not in d:
    page = '''<div id="cfgSd" class="cfgPage">
<div class="resourceHeroGrid">
<section class="resourceHero"><div class="heroLabel">microSD</div><div class="heroValue" id="sdMountState">--</div><div class="heroState" id="sdCardSize">--</div></section>
<section class="resourceHero"><div class="heroLabel">Archivio corrente</div><div class="heroValue" style="font-size:1rem" id="sdFile">--</div><div class="heroState" id="sdTimeState">--</div></section>
<section class="resourceHero"><div class="heroLabel">Scritture</div><div class="heroValue" id="sdWritten">--</div><div class="heroState" id="sdQueue">--</div></section>
</div>
<div class="cfgGrid">
<label class="checkLine"><input id="sdEnabled" type="checkbox"><span>Abilita datalogger microSD</span></label>
<label><span>Snapshot BME280 / AS3935 (secondi)</span><input id="sdSnapshot" type="number" min="30" max="3600" value="300"></label>
<label class="checkLine"><input id="sdOregon" type="checkbox"><span>Registra ogni frame Oregon valido</span></label>
<label class="checkLine"><input id="sdTechnoline" type="checkbox"><span>Registra ogni frame Technoline valido</span></label>
<label class="checkLine"><input id="sdBme" type="checkbox"><span>Registra snapshot BME280</span></label>
<label class="checkLine"><input id="sdAs3935" type="checkbox"><span>Registra snapshot AS3935</span></label>
</div>
<div class="cfgActions"><button class="modeBtn" onclick="saveSd()">Salva microSD</button><button class="modeBtn" onclick="remountSd()">Rimonta scheda</button><button class="modeBtn" style="border-color:#a44;color:#ff8f8f" onclick="formatSd()">FORMATTA SD</button><button class="modeBtn" onclick="resetSd()">Default firmware</button><span id="sdSummary" class="muted"></span></div>
<div class="cfgNote">CSV giornalieri UTC in <code>/weather/YYYY/MM/YYYY-MM-DD.csv</code>. La scrittura e differita e non blocca il decoder RF.</div>
</div>
'''
    anchor = '<div id="cfgLightning" class="cfgPage">'
    pos = d.find(anchor)
    if pos < 0:
        raise RuntimeError("SD browser: Lightning config page anchor missing")
    d = d[:pos] + page + d[pos:]

# Ensure showCfgTab knows about SD even in a partially generated source archive.
show_re = re.compile(r"function showCfgTab\(t\)\{for\(const x of \[([^\]]*)\]\)")
m = show_re.search(d)
if not m:
    raise RuntimeError("SD browser: showCfgTab loop missing")
items = m.group(1)
if "'sd'" not in items:
    if "'display'" in items:
        fixed = items.replace("'display'", "'display','sd'", 1)
    else:
        fixed = items + ",'sd'"
    d = d[:m.start(1)] + fixed + d[m.end(1):]
    print("SD browser: repaired blank MICROSD tab loop")

# Replace any old SD loader with a panel loader that probes once and fetches files.
d = re.sub(r"else if\(t==='sd'\)(?:\{[^{}]*\}|loadSd\(\);)", "else if(t==='sd')loadSdPanel();", d, count=1)
if "t==='sd')loadSdPanel()" not in d:
    display_loader = "else if(t==='display')loadDisplay();"
    if display_loader not in d:
        raise RuntimeError("SD browser: config loader anchor missing")
    d = d.replace(display_loader, display_loader + "else if(t==='sd')loadSdPanel();", 1)

browser_html = '''
<div id="sdBrowserPanel" class="diagSection">
<div class="panelHead"><span>microSD · stato e archivio CSV</span><div class="cfgActions" style="padding:0"><button class="modeBtn" onclick="loadSdFiles()">Aggiorna elenco</button><button class="modeBtn" onclick="downloadSdCurrent()">Scarica corrente</button></div></div>
<div class="diagGrid">
<div class="diag"><b>Capacita</b><div id="sdFsInfo" class="muted" style="margin-top:7px">--</div></div>
<div class="diag"><b>Bus / mount</b><div id="sdBusInfo" class="muted" style="margin-top:7px">--</div></div>
<div class="diag"><b>I/O logger</b><div id="sdIoInfo" class="muted" style="margin-top:7px">--</div></div>
</div>
<div class="rawWrap"><table><thead><tr><th>File CSV</th><th>Dimensione</th><th></th></tr></thead><tbody id="sdFilesRows"><tr><td colspan="3" class="muted">Apri MICROSD per leggere l archivio.</td></tr></tbody></table></div>
<div id="sdDownloadProgress" class="cfgNote"></div>
</div>
'''
if 'id="sdBrowserPanel"' not in d:
    transition = '\n</div>\n<div id="cfgLightning" class="cfgPage">'
    if transition not in d:
        raise RuntimeError("SD browser: cfgSd -> cfgLightning transition missing")
    d = d.replace(transition, browser_html + '\n</div>\n<div id="cfgLightning" class="cfgPage">', 1)

browser_js = r'''
// ADMIN_SENSOR_SD_BROWSER_V1
let sdPanelProbeDone=false,sdFilesCache=[];
function sdEsc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function sdInitName(v){return ({0:'--',1:'OK',2:'CARD INIT',3:'FAT INVALID',4:'FORMAT FAIL'}[Number(v)]||String(v??'--'))}
function sdRenderExtended(s){
 const card=Number(s.card_size||0),total=Number(s.total_bytes||0),used=Number(s.used_bytes||0),free=Math.max(0,total-used),pct=total>0?(used*100/total):0;
 const spi=Number(s.spi_hz||0),spiTxt=spi>=1000000?(spi/1000000).toFixed(spi%1000000?1:0)+' MHz':(spi?Math.round(spi/1000)+' kHz':'--');
 if(E('sdFsInfo'))E('sdFsInfo').innerHTML='Scheda <b>'+sdBytes(card)+'</b><br>FAT utilizzabile '+sdBytes(total)+'<br>Usati '+sdBytes(used)+' ('+pct.toFixed(1)+'%)<br>Liberi '+sdBytes(free);
 if(E('sdBusInfo'))E('sdBusInfo').innerHTML='Stato <b>'+(s.mounted?'MONTATA':'NON MONTATA')+'</b><br>SPI '+spiTxt+'<br>Init '+sdInitName(s.init_code)+'<br>Tentativi '+Number(s.mount_attempts||0);
 if(E('sdIoInfo'))E('sdIoInfo').innerHTML='Scritti <b>'+Number(s.written||0)+'</b><br>In coda '+Number(s.queue_depth||0)+'<br>Drop '+Number(s.dropped||0)+'<br>Errori '+Number(s.write_errors||0)+' · SdFat 0x'+Number(s.sd_error||0).toString(16).toUpperCase().padStart(2,'0')+'/0x'+Number(s.sd_error_data||0).toString(16).toUpperCase().padStart(2,'0');
 if(E('sdCardSize')&&s.mounted)E('sdCardSize').textContent=sdBytes(card)+' · liberi '+sdBytes(free)+' · SPI '+spiTxt;
}
async function loadSdPanel(){
 try{
  if(!sdPanelProbeDone){
   sdPanelProbeDone=true;
   const r=await fetch('/api/sd',{cache:'no-store'});if(r.ok){const j=await r.json(),s=j.status||{};if(s.supported&&!s.mounted)await fetch('/api/sd/remount',{method:'POST',cache:'no-store'});}
  }
 }catch(e){}
 await loadSd();
 await loadSdFiles();
}
async function loadSdFiles(){
 const body=E('sdFilesRows');if(body)body.innerHTML='<tr><td colspan="3" class="muted">Lettura archivio...</td></tr>';
 try{
  const r=await fetch('/api/sd/files',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const j=await r.json(),s=j.status||{},files=Array.isArray(j.files)?j.files:[];sdRenderExtended(s);sdFilesCache=files.slice().sort((a,b)=>String(b.path).localeCompare(String(a.path)));
  if(!body)return;
  if(!s.mounted){body.innerHTML='<tr><td colspan="3" class="muted">Scheda non montata. Usa Rimonta scheda oppure reinserisci la microSD.</td></tr>';return}
  if(!sdFilesCache.length){body.innerHTML='<tr><td colspan="3" class="muted">Nessun CSV presente in /weather.</td></tr>';return}
  body.innerHTML=sdFilesCache.map((f,i)=>'<tr><td>'+sdEsc(f.path)+'</td><td>'+sdBytes(f.size)+'</td><td><button class="modeBtn" onclick="downloadSdFile('+i+')">Scarica</button></td></tr>').join('');
  if(j.truncated&&E('sdDownloadProgress'))E('sdDownloadProgress').textContent='Mostrati i primi '+sdFilesCache.length+' file; archivio piu grande del limite di elenco.';
 }catch(e){if(body)body.innerHTML='<tr><td colspan="3" class="bad">Errore lettura archivio: '+sdEsc(e)+'</td></tr>'}
}
async function downloadSdPath(path,size){
 const total=Number(size||0),parts=[];let off=0;const step=6144,progress=E('sdDownloadProgress');
 try{
  while(off<total){
   const q=new URLSearchParams({path:String(path),offset:String(off),limit:String(Math.min(step,total-off))});
   const r=await fetch('/api/sd/read?'+q.toString(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status+' '+await r.text());
   const b=await r.arrayBuffer();if(!b.byteLength&&off<total)throw new Error('chunk vuoto');parts.push(b);off+=b.byteLength;
   if(progress)progress.textContent='Download '+path+' · '+sdBytes(off)+' / '+sdBytes(total)+' ('+(total?Math.min(100,off*100/total).toFixed(0):100)+'%)';
  }
  const blob=new Blob(parts,{type:'text/csv;charset=utf-8'}),a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download=String(path).split('/').pop()||'weather.csv';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);if(progress)progress.textContent='Download completato · '+a.download+' · '+sdBytes(total);
 }catch(e){if(progress)progress.textContent='Download fallito: '+e;alert('Download microSD fallito: '+e)}
}
function downloadSdFile(i){const f=sdFilesCache[Number(i)];if(f)downloadSdPath(f.path,f.size)}
async function downloadSdCurrent(){try{const r=await fetch('/api/sd',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const j=await r.json(),p=String((j.status||{}).file||'');if(!p){alert('Nessun file corrente disponibile.');return}let f=sdFilesCache.find(x=>x.path===p);if(!f){await loadSdFiles();f=sdFilesCache.find(x=>x.path===p)}if(!f){alert('File corrente non ancora presente nell elenco.');return}downloadSdPath(f.path,f.size)}catch(e){alert('Download file corrente: '+e)}}
'''
if "ADMIN_SENSOR_SD_BROWSER_V1" not in d:
    anchor = "function sdBytes(v){"
    pos = d.find(anchor)
    if pos < 0:
        raise RuntimeError("SD browser: sdBytes Javascript anchor missing")
    d = d[:pos] + browser_js + d[pos:]

# Remote UI: do not let the 4 s SD badge poll compete with /api/state on the
# single bounded WSS HTTP queue. Local UI keeps the original 4 s freshness.
old_poll = "refreshSdHeader();setInterval(refreshSdHeader,4000);"
new_poll = "setTimeout(refreshSdHeader,remoteUi?3500:0);setInterval(refreshSdHeader,remoteUi?15000:4000);"
if old_poll in d:
    d = d.replace(old_poll, new_poll, 1)
elif new_poll not in d:
    # tolerate pretty-printed variants from a source archive
    d2, n = re.subn(r"refreshSdHeader\(\);\s*setInterval\(refreshSdHeader\s*,\s*4000\s*\);", new_poll, d, count=1)
    if n:
        d = d2
    else:
        raise RuntimeError("SD browser: SD header polling anchor missing")

write(d_path, d)
print("SD browser: final MICROSD page repaired, archive browser enabled, remote SD poll reduced")
