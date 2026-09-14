"""Build-time-only compaction for CONFIGURAZIONE.

The canonical web/dashboard.html is intentionally left untouched because many
PlatformIO pre-scripts use stable HTML anchors across repeated builds.  This
module transforms only the in-memory copy that generate_web_ui.py compresses
into firmware.

Goals:
- keep every field ID, API and JavaScript handler unchanged;
- make all configuration pages visually uniform and denser;
- shorten explanatory copy without removing the useful guidance;
- reduce the compressed Web payload where possible;
- never change RF, Wi-Fi, MQTT, NVS or runtime behaviour.
"""

from __future__ import annotations

import re

MARKER = "CONFIG_UI_COMPACT_V1"

_CFG_CSS_RE = re.compile(r"\.cfgPanel\{.*?\.cfgHelp\{[^{}]*\}", re.S)

_COMPACT_CSS = r'''/*CONFIG_UI_COMPACT_V1*/
.cfgPanel{padding:0}.cfgTabs{display:flex;gap:5px;padding:8px 10px;overflow:auto;border-bottom:1px solid var(--border);background:#0a1525}.cfgTab{border:1px solid var(--border);background:#101c2d;color:#b9cbe1;padding:7px 10px;border-radius:8px;cursor:pointer;font-size:.76rem;font-weight:750;white-space:nowrap}.cfgTab.active{background:#174d66;border-color:#4aaad8;color:#fff}.cfgPage{display:none}.cfgPage.active{display:block}
.cfgGrid,.fieldGrid,.cfgOptionGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:10px 12px}.cfgGrid label,.cfgOption label{display:flex;flex-direction:column;gap:4px;color:var(--muted);font-size:.76rem}.cfgGrid input[type=text],.cfgGrid input[type=password],.cfgGrid input[type=number],.cfgGrid select,.cfgGrid textarea,.cfgOption input[type=number],.cfgOption select{width:100%;background:#081423;border:1px solid var(--border);color:var(--text);border-radius:7px;padding:8px}.cfgGrid textarea{min-height:105px;resize:vertical;font:11px ui-monospace,SFMono-Regular,Consolas,monospace}.cfgWide{grid-column:1/-1}.cfgGrid .checkLine,.cfgOption .cfgCheck{flex-direction:row;align-items:center}.fieldGrid{padding-top:2px}.fieldGroup,.cfgSection,.cfgOption{border:1px solid var(--border);border-radius:9px;background:#0b1727}.fieldGroup{padding:9px}.fieldGroup b{display:block;margin-bottom:6px;font-size:.8rem}.fieldCheck{display:flex;gap:6px;align-items:center;color:#b5c8e1;font-size:.75rem;padding:2px 0}
.cfgActions{display:flex;gap:7px;align-items:center;flex-wrap:wrap;padding:8px 12px 10px;border-top:1px solid #1c2b3e;background:#0a1525}.cfgActions .modeBtn{padding:7px 10px;font-size:.76rem}.cfgNote{padding:7px 12px 9px;color:var(--muted);font-size:.72rem;line-height:1.35}.cfgExplain{display:grid;gap:8px;padding:10px 12px}.cfgSection{overflow:hidden}.cfgSectionHead{padding:9px 11px;background:#0e1b2d;border-bottom:1px solid var(--border);font-size:.8rem;font-weight:800}.cfgSectionSub{display:block;color:var(--muted);font-size:.68rem;font-weight:500;margin-top:2px}.cfgOptionGrid{padding:8px}.cfgOption{padding:8px;background:#0d1929}.cfgOption label{font-weight:750}.cfgHelp{color:var(--muted);font-size:.68rem;line-height:1.3;margin-top:4px}
@media(max-width:1220px){.cfgOptionGrid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.cfgTabs{padding:7px 8px}.cfgTab{padding:7px 9px}.cfgOptionGrid{grid-template-columns:1fr}.cfgGrid,.fieldGrid,.cfgExplain{padding-left:9px;padding-right:9px}.cfgActions,.cfgNote{padding-left:9px;padding-right:9px}}
'''

# Shorter wording deliberately preserves the same controls and semantics.
_TEXT_REPLACEMENTS = {
    ">RETE / IP</button>": ">RETE</button>",
    ">MQTT / TLS</button>": ">MQTT</button>",
    ">DISPLAY</button>": ">OLED</button>",
    ">⚡ AS3935</button>": ">AS3935</button>",
    ">BACKUP / RESTORE</button>": ">BACKUP</button>",
    "Configurazione dispositivo <span class=\"muted\">NVS solo su modifica</span>": "Configurazione <span class=\"muted\">NVS solo su modifica</span>",
    "Canale meteo principale": "Canale principale",
    "Mostra/pubblica automaticamente i canali rilevati": "Auto-pubblica canali rilevati",
    "cancella password salvata": "Cancella password",
    "Cambio pagina (secondi)": "Cambio pagina · s",
    "Contrasto OLED (8-255)": "Contrasto · 8-255",
    "Se disattivato il chip viene messo in power-down e non genera IRQ o pubblicazioni MQTT.": "OFF = power-down, nessun IRQ/MQTT.",
    "Indoor riduce il guadagno per ambienti elettricamente rumorosi; Outdoor aumenta la sensibilita.": "Indoor = meno guadagno; Outdoor = piu sensibilita.",
    "Default del modulo: 0x03. Cambialo solo se i pin di indirizzo del breakout sono configurati diversamente.": "Default 0x03; cambia solo se il breakout e cablato diversamente.",
    "Ingresso interrupt dedicato all'AS3935. Sul T3 V1.6.1 il default e GPIO34; i pin usati da radio, I2C, LED e flash sono rifiutati.": "IRQ T3 V1.6.1: GPIO34; i pin riservati sono rifiutati.",
    "Soglia del rumore ambientale. Aumentala solo se il contatore Noise cresce troppo; valori alti riducono la sensibilita.": "Aumenta solo se Noise cresce; valori alti riducono sensibilita.",
    "Rende piu severa la qualificazione del segnale. Aumentarlo aiuta contro impulsi deboli o spurii.": "Valore alto = qualificazione piu severa del segnale.",
    "Filtro contro picchi impulsivi brevi. Un valore maggiore scarta piu facilmente disturbi non atmosferici.": "Valore alto = scarta piu impulsi brevi/spurii.",
    "Soglia di conferma interna del chip: 1 e la piu reattiva, 5/9/16 sono piu conservative.": "1 e reattivo; 5/9/16 sono piu conservativi.",
    "Impedisce ai disturbi classificati come Disturber di generare IRQ. Per la fase di test conviene lasciarlo spento per misurare l'EMI reale.": "Durante i test lascialo OFF per osservare i Disturber reali.",
    "Fa cercare automaticamente al driver il condensatore di tuning piu vicino alla risonanza nominale.": "Ricerca automatica della risonanza vicina a 500 kHz.",
    "Usato solo con Auto-tuning disattivato. Dopo la modifica controlla il valore di risonanza mostrato nello stato.": "Usato solo con Auto-tuning OFF; poi verifica la risonanza.",
    "Parametri hardware e sensibilita di base del front-end AS3935.": "Hardware e sensibilita di base.",
    "Servono a bilanciare sensibilita e falsi eventi dovuti a disturbi elettrici.": "Bilanciamento sensibilita / falsi eventi.",
    "La rete LC del sensore deve essere centrata vicino a 500 kHz.": "Risonanza antenna vicina a 500 kHz.",
    "Suggerimento di collaudo: prima verifica <b>RILEVATO / IRQ OK / CAL OK</b>, poi osserva Noise e Disturber per qualche ora prima di irrigidire i filtri. La ricezione Oregon/Technoline resta indipendente.": "Collaudo: verifica <b>RILEVATO / IRQ OK / CAL OK</b>, poi osserva Noise/Disturber prima di irrigidire i filtri.",
    "Le pagine disabilitate vengono saltate automaticamente. Intervallo e campi sono persistenti in NVS e vengono scritti solo quando cambiano. Se il Gust Technoline non e' stato ricevuto il display mostra <code>G --</code>, mai uno zero artificiale.": "Le pagine OFF vengono saltate. NVS e aggiornata solo su modifica. Gust assente = <code>G --</code>.",
    "Taratura altimetrica: la pressione assoluta del BME280 viene riportata al livello del mare usando questa quota. Cambiando quota lo storico del trend viene azzerato per evitare un falso salto di pressione.": "Quota usata per il livello del mare; al cambio quota il trend viene azzerato.",
    "La conversione riguarda la Web UI. Acquisizione, calcoli, MQTT, Weather Realtime API e COMPATIBLE MB restano in hPa.": "Solo Web UI: calcoli, MQTT/API e COMPATIBLE MB restano in hPa.",
    "Le categorie grafiche seguono quelle esposte dalla WMR200. Il protocollo Oregon disponibile trasmette il risultato della console ma non documenta la formula proprietaria: il gateway usa pressione al livello del mare, trend 3 h e temperatura esterna per classificare la neve.": "Forecast WMR-style da pressione al livello del mare, trend 3 h e temperatura esterna.",
    "Scanner manuale del bus condiviso e stato dei sensori locali. Nessuna scrittura NVS.": "Bus condiviso e sensori locali; nessuna scrittura NVS.",
    "Il gateway usa normalmente 100 kHz per aumentare il margine con più dispositivi sul bus. La scansione a 400 kHz è solo un test manuale di margine. Cavi I²C lunghi possono causare ACK mancanti anche con SDA/SCL correttamente alte a riposo.": "Runtime 100 kHz; 400 kHz e solo stress test. Cavi lunghi possono ridurre il margine I²C.",
}

_REQUIRED_TOKENS = (
    'id="cfgNet"',
    'id="cfgThermo"',
    'id="cfgMqtt"',
    'id="cfgDisplay"',
    'id="cfgLightning"',
    'id="cfgBackup"',
    'saveNetwork()',
    'saveThermo()',
    'saveMqtt()',
    'saveDisplayConfig()',
    'saveLightning()',
    'exportConfig()',
)


def compact_config_ui(html: str) -> str:
    """Return the compact firmware copy of the dashboard without mutating source."""
    if not isinstance(html, str) or not html:
        raise RuntimeError("Compact config UI: empty dashboard")

    for token in _REQUIRED_TOKENS:
        if token not in html:
            raise RuntimeError(f"Compact config UI: required token missing before transform: {token}")

    out, count = _CFG_CSS_RE.subn(_COMPACT_CSS, html, count=1)
    if count != 1:
        raise RuntimeError("Compact config UI: configuration CSS anchor missing or ambiguous")

    for old, new in _TEXT_REPLACEMENTS.items():
        out = out.replace(old, new)

    for token in _REQUIRED_TOKENS:
        if token not in out:
            raise RuntimeError(f"Compact config UI: required token lost after transform: {token}")

    if MARKER not in out:
        raise RuntimeError("Compact config UI: marker missing after transform")
    if len(out.encode("utf-8")) >= len(html.encode("utf-8")):
        raise RuntimeError("Compact config UI: transform did not reduce raw Web payload")

    return out
