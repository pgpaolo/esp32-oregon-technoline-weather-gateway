Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Technoline rain derived values: 5-minute estimated rate, 1h and 24h totals.
# Keep the history deliberately compact: 320 samples x 5 minutes ~= 26.7 h.
# Each sample is uint32_t + float (8 bytes on ESP32), about 2.5 KiB RAM.
# ---------------------------------------------------------------------------
h = read("src/station_state.h")
if "rainRate5mMmH" not in h:
    old = '''    float rainTotalMm{NAN};
    float rainIncrementMm{NAN};
    uint32_t rainUpdatedMs{0};
    bool rainValid{false};
    bool rainIncrementValid{false};
'''
    new = '''    float rainTotalMm{NAN};
    float rainIncrementMm{NAN};
    float rainRate5mMmH{NAN};
    float rainLastHourMm{NAN};
    float rainLast24hMm{NAN};
    uint32_t rainUpdatedMs{0};
    bool rainValid{false};
    bool rainIncrementValid{false};
    bool rainRate5mValid{false};
    bool rainLastHourValid{false};
    bool rainLast24hValid{false};
'''
    if old not in h:
        raise RuntimeError("Technoline rain: station_state.h anchor missing")
    h = h.replace(old, new, 1)
    write("src/station_state.h", h)

cpp = read("src/station_state.cpp")
if "LC_RAIN_HISTORY_SIZE" not in cpp:
    anchor = '''RainHistorySample rainHistory[RAIN_HISTORY_SIZE];
uint16_t rainHistoryHead = 0;
uint16_t rainHistoryCount = 0;
'''
    block = '''RainHistorySample rainHistory[RAIN_HISTORY_SIZE];
uint16_t rainHistoryHead = 0;
uint16_t rainHistoryCount = 0;

// Technoline/WS23xx does not transmit an instantaneous rain rate.  Keep a
// compact 5-minute history and derive an average rate plus 1h/24h accumulations
// from the cumulative rain counter.  The RF decoder never touches this buffer.
constexpr uint16_t LC_RAIN_HISTORY_SIZE = 320;
constexpr uint32_t LC_RAIN_HISTORY_SPACING_MS = 5UL * 60UL * 1000UL;
RainHistorySample lcRainHistory[LC_RAIN_HISTORY_SIZE];
uint16_t lcRainHistoryHead = 0;
uint16_t lcRainHistoryCount = 0;

void clearLcRainHistory() {
    lcRainHistoryHead = 0;
    lcRainHistoryCount = 0;
}

void addLcRainHistory(uint32_t nowMs, float totalMm) {
    if (lcRainHistoryCount > 0) {
        const int lastIdx = (static_cast<int>(lcRainHistoryHead) - 1 + LC_RAIN_HISTORY_SIZE) % LC_RAIN_HISTORY_SIZE;
        const RainHistorySample &last = lcRainHistory[lastIdx];
        if (static_cast<uint32_t>(nowMs - last.ms) < LC_RAIN_HISTORY_SPACING_MS) return;
    }
    lcRainHistory[lcRainHistoryHead].ms = nowMs;
    lcRainHistory[lcRainHistoryHead].totalMm = totalMm;
    lcRainHistoryHead = static_cast<uint16_t>((lcRainHistoryHead + 1U) % LC_RAIN_HISTORY_SIZE);
    if (lcRainHistoryCount < LC_RAIN_HISTORY_SIZE) lcRainHistoryCount++;
}

bool lcRainBaseline(uint32_t nowMs, uint32_t targetAgeMs, float &baselineMm, uint32_t &baselineMs) {
    if (lcRainHistoryCount < 2) return false;
    for (uint16_t n = 1; n < lcRainHistoryCount; ++n) {
        const int idx = (static_cast<int>(lcRainHistoryHead) - 1 - n + LC_RAIN_HISTORY_SIZE) % LC_RAIN_HISTORY_SIZE;
        const RainHistorySample &s = lcRainHistory[idx];
        if (static_cast<uint32_t>(nowMs - s.ms) >= targetAgeMs) {
            baselineMm = s.totalMm;
            baselineMs = s.ms;
            return true;
        }
    }
    return false;
}
'''
    if anchor not in cpp:
        raise RuntimeError("Technoline rain: history anchor missing")
    cpp = cpp.replace(anchor, block, 1)

if "void updateLaCrosseRainDerived(" not in cpp:
    anchor = "float calculateDewPoint(float tempC, float humidity) {\n"
    func = '''void updateLaCrosseRainDerived(LaCrosseStationState &lc, float newTotalMm, uint32_t nowMs) {
    if (lc.rainValid && isfinite(lc.rainTotalMm)) {
        const float delta = newTotalMm - lc.rainTotalMm;
        if (delta >= -0.001f && delta < 500.0f) {
            lc.rainIncrementMm = delta > 0.0f ? delta : 0.0f;
            lc.rainIncrementValid = true;
        } else {
            clearLcRainHistory();
            lc.rainIncrementMm = 0.0f;
            lc.rainIncrementValid = true;
            lc.rainRate5mValid = false;
            lc.rainLastHourValid = false;
            lc.rainLast24hValid = false;
        }
    } else {
        lc.rainIncrementMm = 0.0f;
        lc.rainIncrementValid = true;
    }

    addLcRainHistory(nowMs, newTotalMm);

    float baseline = 0.0f;
    uint32_t baselineMs = 0;
    if (lcRainBaseline(nowMs, 5UL * 60UL * 1000UL, baseline, baselineMs)) {
        const uint32_t elapsedMs = static_cast<uint32_t>(nowMs - baselineMs);
        if (elapsedMs > 0) {
            const float deltaMm = max(0.0f, newTotalMm - baseline);
            lc.rainRate5mMmH = deltaMm * (3600000.0f / static_cast<float>(elapsedMs));
            lc.rainRate5mValid = true;
        }
    }
    if (lcRainBaseline(nowMs, 60UL * 60UL * 1000UL, baseline, baselineMs)) {
        lc.rainLastHourMm = max(0.0f, newTotalMm - baseline);
        lc.rainLastHourValid = true;
    }
    if (lcRainBaseline(nowMs, 24UL * 60UL * 60UL * 1000UL, baseline, baselineMs)) {
        lc.rainLast24hMm = max(0.0f, newTotalMm - baseline);
        lc.rainLast24hValid = true;
    }
}

'''
    if anchor not in cpp:
        raise RuntimeError("Technoline rain: derived function anchor missing")
    cpp = cpp.replace(anchor, func + anchor, 1)

old_rain_case = '''        case LaCrosseType::Rain:
            lc.rainPacketCount++;
            if (reading.rainValid) {
                if (lc.rainValid && isfinite(lc.rainTotalMm)) {
                    const float delta = reading.rainTotalMm - lc.rainTotalMm;
                    lc.rainIncrementMm = (delta >= 0.0f && delta < 500.0f) ? delta : 0.0f;
                    lc.rainIncrementValid = delta >= 0.0f && delta < 500.0f;
                } else {
                    lc.rainIncrementMm = 0.0f;
                    lc.rainIncrementValid = true;
                }
                lc.rainTotalMm = reading.rainTotalMm;
                lc.rainValid = true;
                lc.rainUpdatedMs = reading.receivedAtMs;
            }
            break;
'''
new_rain_case = '''        case LaCrosseType::Rain:
            lc.rainPacketCount++;
            if (reading.rainValid) {
                updateLaCrosseRainDerived(lc, reading.rainTotalMm, reading.receivedAtMs);
                lc.rainTotalMm = reading.rainTotalMm;
                lc.rainValid = true;
                lc.rainUpdatedMs = reading.receivedAtMs;
            }
            break;
'''
if old_rain_case in cpp:
    cpp = cpp.replace(old_rain_case, new_rain_case, 1)
elif new_rain_case not in cpp:
    raise RuntimeError("Technoline rain: LaCrosse rain case anchor missing")
write("src/station_state.cpp", cpp)


# ---------------------------------------------------------------------------
# Asynchronous Wi-Fi scan API.  The scan is started only by explicit Web action
# and does not block the main loop waiting for results.
# ---------------------------------------------------------------------------
nh = read("src/network_manager.h")
if "networkWifiScanStart" not in nh:
    anchor = "bool networkWifiCredentialTrialPending();\n"
    decl = '''bool networkWifiCredentialTrialPending();
bool networkWifiScanStart();
String networkWifiScanJson();
'''
    if anchor not in nh:
        raise RuntimeError("Wi-Fi scan: network_manager.h anchor missing")
    nh = nh.replace(anchor, decl, 1)
    write("src/network_manager.h", nh)

nc = read("src/network_manager.cpp")
if "String networkWifiScanJson()" not in nc:
    append = r'''

bool networkWifiScanStart() {
    const int state = WiFi.scanComplete();
    if (state == -1) return true;  // already running
    if (state >= 0) WiFi.scanDelete();
    const int rc = WiFi.scanNetworks(true, true);
    return rc == -1 || rc >= 0;
}

String networkWifiScanJson() {
    const int n = WiFi.scanComplete();
    if (n == -1) return String("{\"status\":\"running\",\"networks\":[]}");
    if (n < 0) return String("{\"status\":\"idle\",\"networks\":[]}");

    auto escapeJson = [](const String &value) {
        String out;
        out.reserve(value.length() + 8U);
        for (size_t i = 0; i < value.length(); ++i) {
            const char c = value[i];
            if (c == '\\' || c == '"') { out += '\\'; out += c; }
            else if (static_cast<uint8_t>(c) >= 0x20U) out += c;
        }
        return out;
    };

    String out;
    out.reserve(2200);
    out = "{\"status\":\"done\",\"networks\":[";
    String seen[20];
    uint8_t used = 0;
    for (int i = 0; i < n && used < 20U; ++i) {
        const String ssid = WiFi.SSID(i);
        if (ssid.length() == 0U) continue;
        bool duplicate = false;
        for (uint8_t j = 0; j < used; ++j) {
            if (seen[j] == ssid) { duplicate = true; break; }
        }
        if (duplicate) continue;
        seen[used] = ssid;
        if (used) out += ',';
        const bool open = WiFi.encryptionType(i) == WIFI_AUTH_OPEN;
        out += "{\"ssid\":\"" + escapeJson(ssid) + "\"";
        out += ",\"rssi\":" + String(WiFi.RSSI(i));
        out += ",\"channel\":" + String(WiFi.channel(i));
        out += ",\"security\":\"" + String(open ? "OPEN" : "PROTETTA") + "\"}";
        used++;
    }
    out += "]}";
    WiFi.scanDelete();
    return out;
}
'''
    nc += append
    write("src/network_manager.cpp", nc)


# ---------------------------------------------------------------------------
# Web API: expose Technoline derived rain values and authenticated Wi-Fi scan.
# This script intentionally runs after apply_web_provisioning_ota_auth.py.
# ---------------------------------------------------------------------------
w = read("src/web_manager.cpp")
if '\"rain_rate_5m_mmh\"' not in w:
    anchor = '    out += ",\\\"rain_increment_mm\\\":" + jsonFloat(lc.rainIncrementMm, 2);\n'
    extra = anchor + '''    out += ",\\\"rain_rate_5m_mmh\\\":" + jsonFloat(lc.rainRate5mValid ? lc.rainRate5mMmH : NAN, 2);
    out += ",\\\"rain_last_hour_mm\\\":" + jsonFloat(lc.rainLastHourValid ? lc.rainLastHourMm : NAN, 2);
    out += ",\\\"rain_last_24h_mm\\\":" + jsonFloat(lc.rainLast24hValid ? lc.rainLast24hMm : NAN, 2);
'''
    if anchor not in w:
        raise RuntimeError("Technoline rain: Web JSON anchor missing")
    w = w.replace(anchor, extra, 1)

if "void handleNetworkWifiScanStart()" not in w:
    anchor = "} // namespace\n\nvoid initWeb(StationState &stateRef) {\n"
    handlers = r'''void handleNetworkWifiScanStart() {
    if (!networkWifiScanStart()) {
        server.send(500, "application/json", "{\"ok\":false,\"error\":\"scan start failed\"}");
        return;
    }
    sendNoCache();
    server.send(202, "application/json", "{\"ok\":true,\"status\":\"running\"}");
}

void handleNetworkWifiScanGet() {
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", networkWifiScanJson());
}

'''
    if anchor not in w:
        raise RuntimeError("Wi-Fi scan: web namespace anchor missing")
    w = w.replace(anchor, handlers + anchor, 1)

if 'server.on("/api/network/scan"' not in w:
    nf = "    server.onNotFound("
    pos = w.find(nf)
    if pos < 0:
        raise RuntimeError("Wi-Fi scan: onNotFound route anchor missing")
    routes = '''    server.on("/api/network/scan", HTTP_POST, [](){ if (!requireWebAuth()) return; handleNetworkWifiScanStart(); });
    server.on("/api/network/scan", HTTP_GET, [](){ if (!requireWebAuth()) return; handleNetworkWifiScanGet(); });
'''
    w = w[:pos] + routes + w[pos:]
write("src/web_manager.cpp", w)


# ---------------------------------------------------------------------------
# Dashboard: Technoline rain rows + manual Wi-Fi scan selector.
# ---------------------------------------------------------------------------
d = read("web/dashboard.html")
if 'id="lcRainRate"' not in d:
    old = '''<section class="card good"><div class="cardTitle">Pioggia<svg class="spark" id="spLcRain"></svg></div><div class="body">
<div class="row"><div class="name">Totale sensore</div><div><div class="value" id="lcRain">--</div><div class="age" id="lcAgeR"></div></div></div>
<div class="row"><div class="name">Incremento ultimo frame</div><div class="value" id="lcRainInc">--</div></div>
</div><div class="foot" id="lcFootR"></div></section>
'''
    new = '''<section class="card good"><div class="cardTitle">Pioggia<svg class="spark" id="spLcRain"></svg></div><div class="body">
<div class="row"><div class="name">Intensita stimata 5 min</div><div><div class="value" id="lcRainRate">--</div><div class="age" id="lcAgeR"></div></div></div>
<div class="row"><div class="name">Ultima ora</div><div class="value" id="lcRain1h">--</div></div>
<div class="row"><div class="name">Ultime 24 ore</div><div class="value" id="lcRain24">--</div></div>
<div class="row"><div class="name">Totale sensore</div><div class="value" id="lcRain">--</div></div>
<div class="row"><div class="name">Incremento ultimo frame</div><div class="value" id="lcRainInc">--</div></div>
</div><div class="foot" id="lcFootR"></div></section>
'''
    if old not in d:
        raise RuntimeError("Technoline rain: dashboard card anchor missing")
    d = d.replace(old, new, 1)

old_js = "if(isT&&!sess.lc_rain_acquired){showOrWait(E('lcRain'),false,'');showOrWait(E('lcRainInc'),false,'')}else{showOrWait(E('lcRain'),true,f(lc.rain_total_mm,2,' mm'));showOrWait(E('lcRainInc'),true,f(lc.rain_increment_mm,2,' mm'))}"
new_js = "if(isT&&!sess.lc_rain_acquired){showOrWait(E('lcRainRate'),false,'');showOrWait(E('lcRain1h'),false,'');showOrWait(E('lcRain24'),false,'');showOrWait(E('lcRain'),false,'');showOrWait(E('lcRainInc'),false,'')}else{showOrWait(E('lcRainRate'),true,f(lc.rain_rate_5m_mmh,2,' mm/h'));showOrWait(E('lcRain1h'),true,f(lc.rain_last_hour_mm,2,' mm'));showOrWait(E('lcRain24'),true,f(lc.rain_last_24h_mm,2,' mm'));showOrWait(E('lcRain'),true,f(lc.rain_total_mm,2,' mm'));showOrWait(E('lcRainInc'),true,f(lc.rain_increment_mm,2,' mm'))}"
if old_js in d:
    d = d.replace(old_js, new_js, 1)
elif new_js not in d:
    raise RuntimeError("Technoline rain: dashboard JS anchor missing")

d = d.replace("E('lcFootR').textContent='Rain '+lc.rain_packets+' · sessione '+sess.lc_rain_received+' · incremento locale'", "E('lcFootR').textContent='Rain '+lc.rain_packets+' · sessione '+sess.lc_rain_received+' · rate 5 min · storico 1h/24h locale'", 1)
d = d.replace("push('lcRain',lc.rain_total_mm)", "push('lcRain',lc.rain_rate_5m_mmh)", 1)

if 'id="netScanRows"' not in d:
    anchor = '<label class="cfgWide"><span>AP di recupero</span><input id="netRecovery" type="text" readonly value="si attiva automaticamente se la STA non torna disponibile"></label>\n'
    block = anchor + '''<div class="cfgWide"><div class="cfgActions" style="padding:0 0 8px"><button id="netScanBtn" class="modeBtn" type="button" onclick="scanWifiNetworks()">Scansiona reti Wi-Fi</button><span id="netScanSummary" class="muted">scansione manuale · nessun polling automatico</span></div><div class="rawWrap" style="padding:0"><table><thead><tr><th>SSID</th><th>RSSI</th><th>CH</th><th>Sicurezza</th></tr></thead><tbody id="netScanRows"><tr><td colspan="4" class="muted">Premi Scansiona reti Wi-Fi</td></tr></tbody></table></div></div>
'''
    if anchor not in d:
        raise RuntimeError("Wi-Fi scan: dashboard network anchor missing")
    d = d.replace(anchor, block, 1)

if "async function scanWifiNetworks()" not in d:
    js = r'''
function renderWifiNetworks(list){const rows=E('netScanRows');rows.innerHTML='';if(!list||!list.length){rows.innerHTML='<tr><td colspan="4" class="muted">Nessuna rete 2,4 GHz rilevata</td></tr>';return}for(const n of list){const tr=document.createElement('tr');const tdS=document.createElement('td');const b=document.createElement('button');b.type='button';b.className='modeBtn';b.textContent=n.ssid||'(senza nome)';b.onclick=()=>{E('netSsid').value=n.ssid||'';E('netScanSummary').textContent='SSID selezionato: '+(n.ssid||'')};tdS.appendChild(b);const tdR=document.createElement('td');tdR.textContent=Number(n.rssi)+' dBm';const tdC=document.createElement('td');tdC.textContent=n.channel;const tdSec=document.createElement('td');tdSec.textContent=n.security||'PROTETTA';tr.append(tdS,tdR,tdC,tdSec);rows.appendChild(tr)}}
async function scanWifiNetworks(){const btn=E('netScanBtn');btn.disabled=true;E('netScanSummary').textContent='scansione 2,4 GHz in corso...';try{const start=await fetch('/api/network/scan',{method:'POST',cache:'no-store'});if(!start.ok)throw new Error(await start.text());for(let i=0;i<24;i++){await new Promise(r=>setTimeout(r,500));const res=await fetch('/api/network/scan',{cache:'no-store'});if(!res.ok)throw new Error(await res.text());const j=await res.json();if(j.status==='done'){renderWifiNetworks(j.networks||[]);E('netScanSummary').textContent=(j.networks||[]).length+' reti rilevate · clicca SSID per selezionarlo';btn.disabled=false;return}}throw new Error('timeout scansione')}catch(e){E('netScanSummary').textContent='scansione Wi-Fi fallita';btn.disabled=false}}
'''
    end = "</script>"
    if end not in d:
        raise RuntimeError("Wi-Fi scan: dashboard script end missing")
    d = d.replace(end, js + end, 1)
write("web/dashboard.html", d)

# Final idempotence / integration guards.
checks = {
    "src/station_state.h": ["rainRate5mMmH", "rainLast24hValid"],
    "src/station_state.cpp": ["LC_RAIN_HISTORY_SIZE = 320", "updateLaCrosseRainDerived"],
    "src/network_manager.h": ["networkWifiScanStart", "networkWifiScanJson"],
    "src/network_manager.cpp": ["WiFi.scanNetworks(true, true)", "String networkWifiScanJson()"],
    "src/web_manager.cpp": ["rain_rate_5m_mmh", "/api/network/scan"],
    "web/dashboard.html": ["lcRainRate", "netScanRows", "scanWifiNetworks"],
}
for path, markers in checks.items():
    text = read(path)
    for marker in markers:
        if marker not in text:
            raise RuntimeError(f"Technoline rain/Wi-Fi scan integration missing {marker} in {path}")

print("Technoline rain: 5m rate + 1h/24h derived history enabled (~2.5 KiB RAM)")
print("Wi-Fi: authenticated asynchronous manual scan enabled")
