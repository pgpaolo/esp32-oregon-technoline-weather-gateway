#!/usr/bin/env python3
"""Final idempotent dashboard consistency pass.

Runs after feature-specific dashboard patchers and before generate_web_ui.py.
It deliberately does not touch RF decoder/state logic.
"""
from pathlib import Path
import re

Import("env")
ROOT = Path(env.subst("$PROJECT_DIR"))
DASH = ROOT / "web" / "dashboard.html"

text = DASH.read_text(encoding="utf-8")
changed = False

# Technoline WS23xx does not carry UV. Remove the legacy placeholder card even
# if previous in-place builds changed whitespace/classes around it.
tech_start = text.find('<div class="panel stationTechnoline" id="lacrossePanel">')
tech_end = text.find('<div class="panel stationBme', tech_start) if tech_start >= 0 else -1
if tech_start >= 0 and tech_end > tech_start:
    panel = text[tech_start:tech_end]
    uv_pattern = re.compile(
        r'<section\b[^>]*class="[^"]*uvCard[^"]*"[^>]*>.*?'
        r'(?:WS-2305|Il protocollo WS-23xx non contiene un dato UV\.).*?'</section>',
        re.S,
    )
    panel2, n = uv_pattern.subn('', panel)
    if n:
        panel = panel2
        changed = True
        print(f"Dashboard consistency: removed {n} Technoline UV placeholder card(s)")

    # With TEMP/HUM, WIND and RAIN there are exactly three useful cards.
    if '<div class="weatherGrid technolineGrid">' not in panel:
        panel2 = panel.replace('<div class="weatherGrid">', '<div class="weatherGrid technolineGrid">', 1)
        if panel2 != panel:
            panel = panel2
            changed = True
            print("Dashboard consistency: normalized Technoline 3-column grid")

    text = text[:tech_start] + panel + text[tech_end:]
else:
    print("Dashboard consistency: Technoline panel anchor unavailable")

# SD failure state must not be rendered in green.
old_card_state = "E('sdCardSize').textContent=s.mounted?(sdBytes(s.card_size)+' · usati '+sdBytes(s.used_bytes)"
if old_card_state in text and "E('sdCardSize').className='heroState '" not in text:
    # Insert the class assignment immediately after the complete textContent
    # statement, without depending on the negotiated-SPI wording.
    m = re.search(r"E\('sdCardSize'\)\.textContent=.*?;", text)
    if m:
        inject = m.group(0) + "E('sdCardSize').className='heroState '+(s.mounted?'ok':'bad');"
        text = text[:m.start()] + inject + text[m.end():]
        changed = True
        print("Dashboard consistency: SD card failure subtitle now red")

# Replace raw JSON FORMATTA error with a compact diagnostic message. Keep the
# detailed values visible in the normal SD summary for troubleshooting.
raw_error = "if(!r.ok){alert('Formattazione microSD fallita: '+await r.text());await loadSd();return}"
if raw_error in text:
    friendly_error = """if(!r.ok){let msg='Formattazione microSD fallita.';try{const j=await r.json(),s=j.status||{};if(Number(s.init_code)===2){msg='microSD non inizializzata: SD.begin() fallito a tutte le velocita provate (try 0x'+Number(s.spi_try||0).toString(16).toUpperCase()+', fail 0x'+Number(s.spi_fail||0).toString(16).toUpperCase()+'). La formattazione non puo partire finche la scheda non comunica via SPI.'}else if(Number(s.init_code)===3){msg='microSD rilevata dal bus ma CARD_NONE: controllare scheda/contatti.'}}catch(e){}alert(msg);await loadSd();return}"""
    text = text.replace(raw_error, friendly_error, 1)
    changed = True
    print("Dashboard consistency: human-readable SD format failure")

# Clarify that formatting cannot repair a transport-level SPI failure.
note = "FORMATTA ricrea FAT se non valido oppure azzera il contenuto se gia FAT."
clarified = "FORMATTA ricrea FAT se non valido oppure azzera il contenuto se gia FAT; richiede comunque che la microSD risponda correttamente via SPI."
if note in text and clarified not in text:
    text = text.replace(note, clarified, 1)
    changed = True

if changed:
    DASH.write_text(text, encoding="utf-8")
    print("Dashboard consistency: completed with changes")
else:
    print("Dashboard consistency: already consistent")
