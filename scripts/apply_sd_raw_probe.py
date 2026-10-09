Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
header = root / "src/sd_logger.h"
cpp_path = root / "src/sd_logger.cpp"
dash_path = root / "web/dashboard.html"

# ---------------------------------------------------------------------------
# Low-level microSD probe for T3 V1.6.1.
#
# This runs only after all normal SD.begin() attempts have failed. It sends the
# universal SD CMD0 command directly at 400 kHz. A real card should answer 0x01
# (idle state). 0xFF means no response/MISO remains high; 0x00 usually means a
# line stuck low or an electrical short. No filesystem operation is involved.
# ---------------------------------------------------------------------------

# ---- status fields ---------------------------------------------------------
h = header.read_text(encoding="utf-8")
if "rawCmd0R1" not in h:
    anchor = "    uint8_t initCode{0};\n"
    if anchor not in h:
        raise RuntimeError("SD raw probe: initCode field missing in sd_logger.h")
    h = h.replace(
        anchor,
        anchor
        + "    uint8_t rawProbeIdle{0xFF};\n"
        + "    uint8_t rawCmd0R1{0xFF};\n",
        1,
    )
    header.write_text(h, encoding="utf-8")
    print("SD raw probe: added status fields")
else:
    print("SD raw probe: status fields already present")

# ---- C++ helper + invocation + JSON ---------------------------------------
cpp = cpp_path.read_text(encoding="utf-8")

probe_marker = "// SD_RAW_CMD0_PROBE_V1"
if probe_marker not in cpp:
    mount_sig = "bool mountSdAdaptive(bool formatIfEmpty) {"
    pos = cpp.find(mount_sig)
    if pos < 0:
        raise RuntimeError("SD raw probe: mountSdAdaptive() missing")

    probe = r'''// SD_RAW_CMD0_PROBE_V1
void runRawSdCmd0Probe() {
#if SDCARD_SUPPORTED
    status.rawProbeIdle = 0xFFU;
    status.rawCmd0R1 = 0xFFU;

    // Start from a completely released Arduino-SD/SPI state.
    SD.end();
    if (spiStarted) {
        sdSpi.end();
        spiStarted = false;
    }

    pinMode(SDCARD_CS_PIN, OUTPUT);
    digitalWrite(SDCARD_CS_PIN, HIGH);
    delay(2);

    sdSpi.begin(SDCARD_SCLK_PIN, SDCARD_MISO_PIN,
                SDCARD_MOSI_PIN, SDCARD_CS_PIN);
    spiStarted = true;
    sdSpi.beginTransaction(SPISettings(400000U, MSBFIRST, SPI_MODE0));

    // SD SPI initialization requires >=74 clock pulses with CS high.
    uint8_t idleRx = 0xFFU;
    digitalWrite(SDCARD_CS_PIN, HIGH);
    for (uint8_t i = 0; i < 12U; ++i) {
        idleRx = sdSpi.transfer(0xFFU);
    }
    status.rawProbeIdle = idleRx;

    // CMD0: GO_IDLE_STATE, valid CRC required before SPI mode is established.
    digitalWrite(SDCARD_CS_PIN, LOW);
    sdSpi.transfer(0x40U);
    sdSpi.transfer(0x00U);
    sdSpi.transfer(0x00U);
    sdSpi.transfer(0x00U);
    sdSpi.transfer(0x00U);
    sdSpi.transfer(0x95U);

    uint8_t r1 = 0xFFU;
    for (uint8_t i = 0; i < 20U; ++i) {
        r1 = sdSpi.transfer(0xFFU);
        if (r1 != 0xFFU) break;
    }
    status.rawCmd0R1 = r1;

    digitalWrite(SDCARD_CS_PIN, HIGH);
    sdSpi.transfer(0xFFU);
    sdSpi.endTransaction();

    Serial.printf("[SD-PROBE] idle=0x%02X CMD0=0x%02X (%s)\n",
                  static_cast<unsigned>(status.rawProbeIdle),
                  static_cast<unsigned>(status.rawCmd0R1),
                  status.rawCmd0R1 == 0x01U ? "CARD_RESPONDS" :
                  (status.rawCmd0R1 == 0xFFU ? "NO_RESPONSE" :
                   (status.rawCmd0R1 == 0x00U ? "MISO_LOW" : "OTHER_R1")));

    sdSpi.end();
    spiStarted = false;
    digitalWrite(SDCARD_CS_PIN, HIGH);
#endif
}

'''
    cpp = cpp[:pos] + probe + cpp[pos:]
    print("SD raw probe: inserted CMD0 helper")

# Reset the probe result at the start of each normal mount attempt.
reset_anchor = "    status.initCode = 0;\n"
reset_block = (
    "    status.initCode = 0;\n"
    "    status.rawProbeIdle = 0xFFU;\n"
    "    status.rawCmd0R1 = 0xFFU;\n"
)
if "status.rawProbeIdle = 0xFFU;\n    status.rawCmd0R1 = 0xFFU;" not in cpp:
    if reset_anchor not in cpp:
        raise RuntimeError("SD raw probe: mount diagnostics reset anchor missing")
    cpp = cpp.replace(reset_anchor, reset_block, 1)

# Run the raw probe only after all SD.begin/cardType attempts have failed.
call_marker = "    runRawSdCmd0Probe();\n    Serial.printf(\"[SD] mount FAIL"
if "runRawSdCmd0Probe();" not in cpp[cpp.find("bool mountSdAdaptive"):]:
    fail_anchor = '    Serial.printf("[SD] mount FAIL try=0x%02X beginFail=0x%02X code=%u\\n",\n'
    if fail_anchor not in cpp:
        raise RuntimeError("SD raw probe: final mount FAIL anchor missing")
    cpp = cpp.replace(fail_anchor, "    runRawSdCmd0Probe();\n" + fail_anchor, 1)
    print("SD raw probe: linked after adaptive mount failure")

# Expose probe bytes in /api/sd status JSON.
if '\\\"raw_cmd0\\\"' not in cpp:
    json_anchor = '    out += ",\\\"init_code\\\":" + String(s.initCode);\n'
    if json_anchor not in cpp:
        raise RuntimeError("SD raw probe: init_code JSON anchor missing")
    cpp = cpp.replace(
        json_anchor,
        json_anchor
        + '    out += ",\\\"raw_idle\\\":" + String(s.rawProbeIdle);\n'
        + '    out += ",\\\"raw_cmd0\\\":" + String(s.rawCmd0R1);\n',
        1,
    )
    print("SD raw probe: exposed JSON diagnostics")

cpp_path.write_text(cpp, encoding="utf-8")

# ---- Dashboard -------------------------------------------------------------
d = dash_path.read_text(encoding="utf-8")

# Add CMD0 result to the compact summary only when the card is not mounted.
if "CMD0 0x" not in d:
    old = "+' / fail 0x'+Number(s.spi_fail||0).toString(16).toUpperCase();"
    new = "+' / fail 0x'+Number(s.spi_fail||0).toString(16).toUpperCase()+((!s.mounted&&Number(s.init_code)===2)?(' · CMD0 0x'+Number(s.raw_cmd0==null?255:s.raw_cmd0).toString(16).toUpperCase().padStart(2,'0')):'');"
    if old in d:
        d = d.replace(old, new, 1)
        print("SD raw probe: added CMD0 to Web summary")
    else:
        print("SD raw probe: summary anchor unavailable; continuing")

# Upgrade the friendly format failure message with the raw transport result.
old_msg = "if(!r.ok){let msg='Formattazione microSD fallita.';try{const j=await r.json(),s=j.status||{};if(Number(s.init_code)===2){msg='microSD non inizializzata: SD.begin() fallito a tutte le velocita provate (try 0x'+Number(s.spi_try||0).toString(16).toUpperCase()+', fail 0x'+Number(s.spi_fail||0).toString(16).toUpperCase()+'). La formattazione non puo partire finche la scheda non comunica via SPI.'}else if(Number(s.init_code)===3){msg='microSD rilevata dal bus ma CARD_NONE: controllare scheda/contatti.'}}catch(e){}alert(msg);await loadSd();return}"
if old_msg in d:
    new_msg = "if(!r.ok){let msg='Formattazione microSD fallita.';try{const j=await r.json(),s=j.status||{},cmd=Number(s.raw_cmd0==null?255:s.raw_cmd0),hx='0x'+cmd.toString(16).toUpperCase().padStart(2,'0');if(Number(s.init_code)===2){if(cmd===1)msg='La microSD risponde al comando hardware CMD0 ('+hx+'), ma SD.begin() fallisce: il collegamento SPI e vivo e il problema e nel livello libreria/inizializzazione.';else if(cmd===255)msg='La microSD non risponde nemmeno al comando hardware CMD0 ('+hx+'). Controllare presenza scheda, alimentazione/slot e linee CS=13, SCK=14, MOSI=15, MISO=2.';else if(cmd===0)msg='CMD0 restituisce 0x00: possibile MISO bloccato basso/corto o problema elettrico sullo slot microSD.';else msg='La microSD risponde a CMD0 con '+hx+', valore anomalo. Il bus SPI e attivo ma la scheda non entra correttamente nello stato IDLE.';}else if(Number(s.init_code)===3){msg='microSD rilevata dal bus ma CARD_NONE: controllare scheda/contatti.'}}catch(e){}alert(msg);await loadSd();return}"
    d = d.replace(old_msg, new_msg, 1)
    print("SD raw probe: upgraded FORMATTA diagnostics")
else:
    print("SD raw probe: friendly error anchor unavailable; continuing")

dash_path.write_text(d, encoding="utf-8")
print("SD raw probe: completed")
