from pathlib import Path
import re


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Header: mode setter now reports persistence/runtime failure.
p = Path('src/oregon_receiver.h')
s = p.read_text(encoding='utf-8')
s = replace_once(s,
    'void setRfProtocolMode(RfProtocolMode mode);',
    'bool setRfProtocolMode(RfProtocolMode mode);',
    'RF mode setter declaration')
p.write_text(s, encoding='utf-8')


p = Path('src/oregon_receiver.cpp')
s = p.read_text(encoding='utf-8')

old = '''bool prefPutUCharIfChanged(Preferences &p, const char *key, uint8_t value) {
    const uint8_t old = p.getUChar(key, 0xFFU);
    if (old == value) return false;
    p.putUChar(key, value);
    return true;
}

bool prefPutUShortIfChanged(Preferences &p, const char *key, uint16_t value) {
    const uint16_t old = p.getUShort(key, 0xFFFFU);
    if (old == value) return false;
    p.putUShort(key, value);
    return true;
}

bool prefPutBoolIfChanged(Preferences &p, const char *key, bool value) {
    const bool old = p.getBool(key, false);
    if (old == value) return false;
    p.putBool(key, value);
    return true;
}
'''
new = '''bool prefPutUCharIfChanged(Preferences &p, const char *key, uint8_t value) {
    const uint8_t old = p.getUChar(key, 0xFFU);
    if (old == value) return true;
    p.putUChar(key, value);
    const bool ok = p.getUChar(key, 0xFFU) == value;
    if (!ok) Serial.printf("[RF] NVS verify KO key=%s\\n", key);
    return ok;
}

bool prefPutUShortIfChanged(Preferences &p, const char *key, uint16_t value) {
    const uint16_t old = p.getUShort(key, 0xFFFFU);
    if (old == value) return true;
    p.putUShort(key, value);
    const bool ok = p.getUShort(key, 0xFFFFU) == value;
    if (!ok) Serial.printf("[RF] NVS verify KO key=%s\\n", key);
    return ok;
}

bool prefPutBoolIfChanged(Preferences &p, const char *key, bool value) {
    const bool old = p.getBool(key, false);
    if (old == value) return true;
    p.putBool(key, value);
    const bool ok = p.getBool(key, !value) == value;
    if (!ok) Serial.printf("[RF] NVS verify KO key=%s\\n", key);
    return ok;
}
'''
s = replace_once(s, old, new, 'RF preference read-back helpers')

old = '''void persistOregonFrontend(RfFrontendProfile profile, float bandwidthKhz, uint8_t gain) {
    gainOregon = gain;
    bandwidthOregon = bandwidthKhz;
    currentFrontendProfile = profile;
    rfPrefs.begin("rfrx", false);
    prefPutUCharIfChanged(rfPrefs, "gainO", gainOregon);
    prefPutUShortIfChanged(rfPrefs, "bwO10", static_cast<uint16_t>(bandwidthOregon * 10.0f + 0.5f));
    prefPutUCharIfChanged(rfPrefs, "profileO", static_cast<uint8_t>(profile));
    prefPutUCharIfChanged(rfPrefs, "cfgVer", 59U);
    rfPrefs.end();
}
'''
new = '''bool persistOregonFrontend(RfFrontendProfile profile, float bandwidthKhz, uint8_t gain) {
    if (!rfPrefs.begin("rfrx", false)) {
        Serial.println(F("[RF] ERRORE apertura NVS rfrx per profilo"));
        return false;
    }
    bool ok = true;
    ok = prefPutUCharIfChanged(rfPrefs, "gainO", gain) && ok;
    ok = prefPutUShortIfChanged(rfPrefs, "bwO10", static_cast<uint16_t>(bandwidthKhz * 10.0f + 0.5f)) && ok;
    ok = prefPutUCharIfChanged(rfPrefs, "profileO", static_cast<uint8_t>(profile)) && ok;
    ok = prefPutUCharIfChanged(rfPrefs, "cfgVer", 59U) && ok;
    if (rfMode == RfProtocolMode::Dual) {
        ok = prefPutUCharIfChanged(rfPrefs, "gainL", gain) && ok;
        ok = prefPutUShortIfChanged(rfPrefs, "bwL10", static_cast<uint16_t>(bandwidthKhz * 10.0f + 0.5f)) && ok;
    }
    rfPrefs.end();
    if (!ok) return false;

    gainOregon = gain;
    bandwidthOregon = bandwidthKhz;
    currentFrontendProfile = profile;
    if (rfMode == RfProtocolMode::Dual) {
        gainLaCrosse = gain;
        bandwidthLaCrosse = bandwidthKhz;
    }
    return true;
}
'''
s = replace_once(s, old, new, 'RF frontend persistence')

# AUTO SCAN completion: do not silently claim persistence if NVS failed.
s = replace_once(s,
    '''    persistOregonFrontend(bestProfile, bw, gain);
    applyRadioFrontendRuntime(bw, gain);
''',
    '''    if (!persistOregonFrontend(bestProfile, bw, gain)) {
        Serial.println(F("[RF-AUTO] ATTENZIONE: profilo migliore non persistito in NVS"));
    }
    applyRadioFrontendRuntime(bw, gain);
''',
    'AUTO profile persistence result')

# Replace gain setter as one unit.
pattern = re.compile(r'bool setRadioGainForMode\(RfProtocolMode mode, uint8_t gain\) \{.*?\n\}\n\nbool setRadioFrontendProfile', re.S)
replacement = '''bool setRadioGainForMode(RfProtocolMode mode, uint8_t gain) {
    if (gain > 3U) return false;
    burstStats.autoActive = false;

    if (mode == RfProtocolMode::Dual) {
        const bool already = gain == gainOregon && gain == gainLaCrosse &&
                             currentFrontendProfile == RfFrontendProfile::Manual && gain == currentGain;
        if (already) return true;
        if (!rfPrefs.begin("rfrx", false)) {
            Serial.println(F("[RF] ERRORE apertura NVS rfrx per gain DUAL"));
            return false;
        }
        bool ok = true;
        ok = prefPutUCharIfChanged(rfPrefs, "gainO", gain) && ok;
        ok = prefPutUCharIfChanged(rfPrefs, "gainL", gain) && ok;
        ok = prefPutUCharIfChanged(rfPrefs, "profileO", static_cast<uint8_t>(RfFrontendProfile::Manual)) && ok;
        rfPrefs.end();
        if (!ok) return false;
        gainOregon = gain;
        gainLaCrosse = gain;
        currentFrontendProfile = RfFrontendProfile::Manual;
        return applyRadioGainRuntime(gain);
    }

    const bool already = (mode == RfProtocolMode::LaCrosse ? gainLaCrosse : gainOregon) == gain &&
                         (mode != RfProtocolMode::Oregon || currentFrontendProfile == RfFrontendProfile::Manual);
    if (already && mode != rfMode) return true;

    if (!rfPrefs.begin("rfrx", false)) {
        Serial.println(F("[RF] ERRORE apertura NVS rfrx per gain"));
        return false;
    }
    bool ok = prefPutUCharIfChanged(rfPrefs, mode == RfProtocolMode::LaCrosse ? "gainL" : "gainO", gain);
    if (mode == RfProtocolMode::Oregon) {
        ok = prefPutUCharIfChanged(rfPrefs, "profileO", static_cast<uint8_t>(RfFrontendProfile::Manual)) && ok;
    }
    rfPrefs.end();
    if (!ok) return false;

    if (mode == RfProtocolMode::LaCrosse) gainLaCrosse = gain;
    else {
        gainOregon = gain;
        if (mode == rfMode) currentFrontendProfile = RfFrontendProfile::Manual;
    }
    if (mode == rfMode) return applyRadioGainRuntime(gain);
    return true;
}

bool setRadioFrontendProfile'''
s, count = pattern.subn(replacement, s, count=1)
if count != 1:
    raise SystemExit(f'RF gain setter: expected 1 match, found {count}')

# Profile setter: persist first; DUAL synchronization is handled by persistence helper.
old = '''    if (rfMode == RfProtocolMode::Oregon || rfMode == RfProtocolMode::Dual) {
        persistOregonFrontend(profile, bw, gain);
        if (rfMode == RfProtocolMode::Dual) {
            bandwidthLaCrosse = bw;
            gainLaCrosse = gain;
            rfPrefs.begin("rfrx", false);
            prefPutUCharIfChanged(rfPrefs, "gainL", gainLaCrosse);
            prefPutUShortIfChanged(rfPrefs, "bwL10", static_cast<uint16_t>(bandwidthLaCrosse * 10.0f + 0.5f));
            rfPrefs.end();
        }
        return applyRadioFrontendRuntime(bw, gain);
    }
'''
new = '''    if (rfMode == RfProtocolMode::Oregon || rfMode == RfProtocolMode::Dual) {
        if (!persistOregonFrontend(profile, bw, gain)) return false;
        return applyRadioFrontendRuntime(bw, gain);
    }
'''
s = replace_once(s, old, new, 'RF profile setter persistence')

# Burst EXTRA is a persistent Web setting, so apply runtime only after NVS verifies.
old = '''bool setBurstRecoveryEnabled(bool enabled) {
    if (burstExtraEnabled == enabled) return true;
    burstExtraEnabled = enabled;
    burstCurrent.reset();
    burstHistoryHead = 0;
    burstHistoryCount = 0;
    rfPrefs.begin("rfrx", false);
    prefPutBoolIfChanged(rfPrefs, "burstX", burstExtraEnabled);
    rfPrefs.end();
    Serial.print(F("[RF] BURST EXTRA -> "));
    Serial.println(burstExtraEnabled ? F("ON") : F("OFF"));
    return true;
}
'''
new = '''bool setBurstRecoveryEnabled(bool enabled) {
    if (burstExtraEnabled == enabled) return true;
    if (!rfPrefs.begin("rfrx", false)) {
        Serial.println(F("[RF] ERRORE apertura NVS rfrx per BURST EXTRA"));
        return false;
    }
    const bool ok = prefPutBoolIfChanged(rfPrefs, "burstX", enabled);
    rfPrefs.end();
    if (!ok) return false;

    burstExtraEnabled = enabled;
    burstCurrent.reset();
    burstHistoryHead = 0;
    burstHistoryCount = 0;
    Serial.print(F("[RF] BURST EXTRA -> "));
    Serial.println(burstExtraEnabled ? F("ON") : F("OFF"));
    return true;
}
'''
s = replace_once(s, old, new, 'BURST EXTRA persistence')

# RF mode is a persistent Web setting. Persist and verify before changing runtime.
pattern = re.compile(r'void setRfProtocolMode\(RfProtocolMode mode\) \{.*?\n\}\n\nbool initOregonReceiver', re.S)
replacement = '''bool setRfProtocolMode(RfProtocolMode mode) {
    if (rfMode == mode) return true;
    if (!rfPrefs.begin("rfmode", false)) {
        Serial.println(F("[RF] ERRORE apertura NVS rfmode"));
        return false;
    }
    const bool persisted = prefPutUCharIfChanged(rfPrefs, "mode", static_cast<uint8_t>(mode));
    rfPrefs.end();
    if (!persisted) return false;

    burstStats.autoActive = false;
    finalizeRfBurst();
    if (wgrProbeOn) resetWgrProbeStatsInternal();
    rfMode = mode;
#if OREGON_RAW_EDGE_MODE
    strongDecoder.resetSearch();
    stateDecoder[0].resetSearch();
    stateDecoder[1].resetSearch();
    for (auto &w : windScan) w.reset();
    noInterrupts();
    edgeTail = edgeHead;
    lastEdgeUs = micros();
    edgePrimed = false;
    interrupts();
#endif
    packetHead = packetTail = 0;
    resetLaCrosseDecoderState();

    currentGain = mode == RfProtocolMode::LaCrosse ? gainLaCrosse : gainOregon;
    currentBandwidth = mode == RfProtocolMode::LaCrosse ? bandwidthLaCrosse : bandwidthOregon;
    if (mode == RfProtocolMode::Oregon || mode == RfProtocolMode::Dual) {
        uint8_t savedProfile = static_cast<uint8_t>(RfFrontendProfile::Stable);
        if (rfPrefs.begin("rfrx", true)) {
            savedProfile = rfPrefs.getUChar("profileO", savedProfile);
            rfPrefs.end();
        } else {
            Serial.println(F("[RF] ATTENZIONE: impossibile leggere profileO da NVS"));
        }
        currentFrontendProfile = savedProfile <= static_cast<uint8_t>(RfFrontendProfile::WideMaxGain)
            ? static_cast<RfFrontendProfile>(savedProfile) : RfFrontendProfile::Manual;
    } else {
        currentFrontendProfile = RfFrontendProfile::Manual;
    }
    const bool applied = applyRadioFrontendRuntime(currentBandwidth, currentGain);
    Serial.print(F("[RF] modalita' ricezione -> "));
    Serial.println(rfProtocolModeName(mode));
    return applied;
}

bool initOregonReceiver'''
s, count = pattern.subn(replacement, s, count=1)
if count != 1:
    raise SystemExit(f'RF mode setter: expected 1 match, found {count}')

# Initial NVS reads: safe fallback if a namespace cannot be opened.
old = '''bool initOregonReceiver() {
    rfPrefs.begin("rfmode", true);
    const uint8_t savedMode = rfPrefs.getUChar("mode", 0);
    rfPrefs.end();
    rfMode = savedMode == 1 ? RfProtocolMode::LaCrosse : (savedMode == 2 ? RfProtocolMode::Dual : RfProtocolMode::Oregon);

    rfPrefs.begin("rfrx", true);
    gainOregon = rfPrefs.getUChar("gainO", OREGON_RX_GAIN);
    gainLaCrosse = rfPrefs.getUChar("gainL", OREGON_RX_GAIN);
    uint16_t bwO10 = rfPrefs.getUShort("bwO10", static_cast<uint16_t>(OREGON_RX_BW_KHZ * 10.0f + 0.5f));
    uint16_t bwL10 = rfPrefs.getUShort("bwL10", static_cast<uint16_t>(OREGON_RX_BW_KHZ * 10.0f + 0.5f));
    uint8_t savedProfile = rfPrefs.getUChar("profileO", static_cast<uint8_t>(RfFrontendProfile::Stable));
    const uint8_t savedRfCfgVer = rfPrefs.getUChar("cfgVer", 0);
    burstExtraEnabled = rfPrefs.getBool("burstX", false);
    rfPrefs.end();
'''
new = '''bool initOregonReceiver() {
    uint8_t savedMode = 0;
    if (rfPrefs.begin("rfmode", true)) {
        savedMode = rfPrefs.getUChar("mode", 0);
        rfPrefs.end();
    } else {
        Serial.println(F("[RF] NVS rfmode non disponibile: default OREGON"));
    }
    rfMode = savedMode == 1 ? RfProtocolMode::LaCrosse : (savedMode == 2 ? RfProtocolMode::Dual : RfProtocolMode::Oregon);

    uint16_t bwO10 = static_cast<uint16_t>(OREGON_RX_BW_KHZ * 10.0f + 0.5f);
    uint16_t bwL10 = bwO10;
    uint8_t savedProfile = static_cast<uint8_t>(RfFrontendProfile::Stable);
    uint8_t savedRfCfgVer = 0;
    burstExtraEnabled = false;
    gainOregon = OREGON_RX_GAIN;
    gainLaCrosse = OREGON_RX_GAIN;
    if (rfPrefs.begin("rfrx", true)) {
        gainOregon = rfPrefs.getUChar("gainO", OREGON_RX_GAIN);
        gainLaCrosse = rfPrefs.getUChar("gainL", OREGON_RX_GAIN);
        bwO10 = rfPrefs.getUShort("bwO10", bwO10);
        bwL10 = rfPrefs.getUShort("bwL10", bwL10);
        savedProfile = rfPrefs.getUChar("profileO", savedProfile);
        savedRfCfgVer = rfPrefs.getUChar("cfgVer", 0);
        burstExtraEnabled = rfPrefs.getBool("burstX", false);
        rfPrefs.end();
    } else {
        Serial.println(F("[RF] NVS rfrx non disponibile: uso baseline firmware"));
    }
'''
s = replace_once(s, old, new, 'RF initial NVS reads')

p.write_text(s, encoding='utf-8')


# Web endpoints and backup/restore must propagate RF persistence failures.
p = Path('src/web_manager.cpp')
s = p.read_text(encoding='utf-8')
pattern = re.compile(r'void handleRfMode\(\) \{.*?\n\}\n\nvoid handleRfGain', re.S)
replacement = '''void handleRfMode() {
    if (!server.hasArg("mode")) { server.send(400, "application/json", "{\\"ok\\":false,\\"error\\":\\"mode missing\\"}"); return; }
    const String m = server.arg("mode");
    bool ok = false;
    if (m == "oregon") ok = setRfProtocolMode(RfProtocolMode::Oregon);
    else if (m == "lacrosse" || m == "technoline") ok = setRfProtocolMode(RfProtocolMode::LaCrosse);
    else if (m == "dual") ok = setRfProtocolMode(RfProtocolMode::Dual);
    else { server.send(400, "application/json", "{\\"ok\\":false,\\"error\\":\\"invalid mode\\"}"); return; }
    if (!ok) {
        server.send(500, "application/json", "{\\"ok\\":false,\\"error\\":\\"RF mode NVS/runtime apply failed\\"}");
        return;
    }

    resetRfSession(true);
    sendNoCache();
    server.send(200, "application/json", String("{\\"ok\\":true,\\"mode\\":\\"") + rfProtocolModeName(getRfProtocolMode()) + "\\"}");
}

void handleRfGain'''
s, count = pattern.subn(replacement, s, count=1)
if count != 1:
    raise SystemExit(f'Web RF mode endpoint: expected 1 match, found {count}')

old = '''    const RfProtocolMode desiredMode = static_cast<RfProtocolMode>(rfMode);
    setRfProtocolMode(RfProtocolMode::Oregon);
    setRadioGainForMode(RfProtocolMode::LaCrosse, static_cast<uint8_t>(gainL));
    if (profile <= static_cast<uint8_t>(RfFrontendProfile::WideMaxGain)) {
        setRadioFrontendProfile(static_cast<RfFrontendProfile>(profile));
    } else {
        setRadioGainForMode(RfProtocolMode::Oregon, static_cast<uint8_t>(gainO));
    }
    setBurstRecoveryEnabled(burstExtra);
    setRfProtocolMode(desiredMode);
    resetRfSession(true);
'''
new = '''    const RfProtocolMode desiredMode = static_cast<RfProtocolMode>(rfMode);
    bool rfSaved = setRfProtocolMode(RfProtocolMode::Oregon);
    rfSaved = setRadioGainForMode(RfProtocolMode::LaCrosse, static_cast<uint8_t>(gainL)) && rfSaved;
    if (profile <= static_cast<uint8_t>(RfFrontendProfile::WideMaxGain)) {
        rfSaved = setRadioFrontendProfile(static_cast<RfFrontendProfile>(profile)) && rfSaved;
    } else {
        rfSaved = setRadioGainForMode(RfProtocolMode::Oregon, static_cast<uint8_t>(gainO)) && rfSaved;
    }
    rfSaved = setBurstRecoveryEnabled(burstExtra) && rfSaved;
    rfSaved = setRfProtocolMode(desiredMode) && rfSaved;
    if (!rfSaved) {
        server.send(500, "application/json", "{\\"ok\\":false,\\"error\\":\\"could not persist imported RF configuration\\"}");
        return;
    }
    resetRfSession(true);
'''
s = replace_once(s, old, new, 'backup RF persistence verification')
p.write_text(s, encoding='utf-8')

print('RF persistence hardening applied successfully')
