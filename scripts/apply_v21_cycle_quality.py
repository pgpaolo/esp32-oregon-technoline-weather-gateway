#!/usr/bin/env python3
"""Apply V2.1 cycle-aware quality accounting for 1D20 and EC70.

This patch is deliberately diagnostic/statistical only. It does not touch the
RF decoder, timings, AGC, bandwidth, packet checksum, MQTT, SD or OLED paths.
For Oregon V2.1 1D20/EC70 the sensor can emit redundant copies a few hundred
milliseconds apart. The dashboard must compare transmission cycles with the
nominal cadence, not raw valid frames with the nominal cadence.
"""
from pathlib import Path

Import("env")
ROOT = Path(env.subst("$PROJECT_DIR"))
WEB_CPP = ROOT / "src" / "web_manager.cpp"
DASH = ROOT / "web" / "dashboard.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def patch_web_cpp() -> None:
    text = WEB_CPP.read_text(encoding="utf-8")
    if "V21_CYCLE_COPY_WINDOW_MS" in text:
        print("V2.1 cycle quality API: source already patched")
        return

    old_struct = '''struct OregonSessionSensor {
    SensorType type{SensorType::Unknown};
    uint16_t code{0};
    uint8_t channel{0};
    uint8_t rollingCode{0};
    uint8_t protocolVersion{0};
    uint8_t cadenceSamples{0};
    uint32_t firstMs{0};
    uint32_t lastMs{0};
    uint32_t received{0};
    uint32_t observedCadenceMs{0};
    float lastRssi{NAN};
};'''
    new_struct = '''struct OregonSessionSensor {
    SensorType type{SensorType::Unknown};
    uint16_t code{0};
    uint8_t channel{0};
    uint8_t rollingCode{0};
    uint8_t protocolVersion{0};
    uint8_t cadenceSamples{0};
    uint32_t firstMs{0};
    uint32_t lastMs{0};
    uint32_t received{0};          // tutti i frame validi, incluse copie ridondanti
    uint32_t cycles{0};            // cicli RF unici per 1D20/EC70
    uint32_t copies{0};            // copie valide ravvicinate dello stesso ciclo
    uint32_t lastCycleMs{0};
    uint32_t lastCycleIntervalMs{0};
    uint32_t observedCadenceMs{0}; // minimo intervallo valido fra cicli reali
    float lastRssi{NAN};
};'''
    text = replace_once(text, old_struct, new_struct, "session sensor struct")

    cadence_marker = '''uint32_t effectiveOregonCadenceMs(const OregonSessionSensor &sensor) {
    const uint32_t nominal = nominalOregonCadenceMs(sensor.type, sensor.code, sensor.channel);
    if (nominal != 0) return nominal;
    return sensor.cadenceSamples >= 3U ? sensor.observedCadenceMs : 0UL;
}
'''
    cadence_new = cadence_marker + '''
// 1D20 e EC70 trasmettono copie ridondanti molto ravvicinate. Nei log reali
// 1D20 mostra tipicamente la seconda copia dopo ~0,2 s, mentre il ciclo vero e'
// ~39/41/43 s. Una finestra di 1,5 s e' quindi molto conservativa e viene
// applicata SOLO a questi due codici V2.1.
constexpr uint32_t V21_CYCLE_COPY_WINDOW_MS = 1500UL;
constexpr uint32_t V21_CYCLE_MIN_INTERVAL_MS = 10000UL;
constexpr uint32_t V21_CYCLE_MAX_INTERVAL_MS = 300000UL;

bool v21CycleTrackedCode(uint16_t code) {
    return code == 0x1D20U || code == 0xEC70U;
}

uint32_t qualityReceivedForSensor(const OregonSessionSensor &sensor) {
    return v21CycleTrackedCode(sensor.code) ? sensor.cycles : sensor.received;
}
'''
    text = replace_once(text, cadence_marker, cadence_new, "cycle helper insertion")

    old_note = '''void noteOregonSessionSensor(const WeatherReading &reading, uint8_t decodeSource) {
    OregonSessionSensor *freeSlot = nullptr;
    OregonSessionSensor *sensor = nullptr;
    for (uint8_t i = 0; i < OREGON_SESSION_SENSOR_MAX; ++i) {
        OregonSessionSensor &candidate = rfSession.oregon[i];
        if (candidate.received == 0) {
            if (!freeSlot) freeSlot = &candidate;
            continue;
        }
        if (candidate.type == reading.type && candidate.code == reading.sensorCode &&
            candidate.channel == reading.channel && candidate.rollingCode == reading.rollingCode) {
            sensor = &candidate;
            break;
        }
    }
    if (!sensor) sensor = freeSlot;
    if (!sensor) {
        if (rfSession.oregonOverflow < 255U) rfSession.oregonOverflow++;
        return;
    }
    if (sensor->received == 0) {
        sensor->type = reading.type;
        sensor->code = reading.sensorCode;
        sensor->channel = reading.channel;
        sensor->rollingCode = reading.rollingCode;
        sensor->protocolVersion = decodeSource == static_cast<uint8_t>(OregonDecodeSource::EdgeTimingV21) ? 2U : 3U;
        sensor->firstMs = reading.receivedAtMs;
    } else {
        const uint32_t interval = static_cast<uint32_t>(reading.receivedAtMs - sensor->lastMs);
        if (interval >= 5000UL && interval <= 180000UL &&
            nominalOregonCadenceMs(sensor->type, sensor->code, sensor->channel) == 0) {
            if (sensor->cadenceSamples == 0 || interval < sensor->observedCadenceMs)
                sensor->observedCadenceMs = interval;
            if (sensor->cadenceSamples < 255U) sensor->cadenceSamples++;
        }
    }
    sensor->lastMs = reading.receivedAtMs;
    sensor->lastRssi = reading.rssi;
    sensor->received++;
}
'''
    new_note = '''void noteOregonSessionSensor(const WeatherReading &reading, uint8_t decodeSource) {
    OregonSessionSensor *freeSlot = nullptr;
    OregonSessionSensor *sensor = nullptr;
    for (uint8_t i = 0; i < OREGON_SESSION_SENSOR_MAX; ++i) {
        OregonSessionSensor &candidate = rfSession.oregon[i];
        if (candidate.received == 0) {
            if (!freeSlot) freeSlot = &candidate;
            continue;
        }
        if (candidate.type == reading.type && candidate.code == reading.sensorCode &&
            candidate.channel == reading.channel && candidate.rollingCode == reading.rollingCode) {
            sensor = &candidate;
            break;
        }
    }
    if (!sensor) sensor = freeSlot;
    if (!sensor) {
        if (rfSession.oregonOverflow < 255U) rfSession.oregonOverflow++;
        return;
    }

    const bool cycleTracked = v21CycleTrackedCode(reading.sensorCode);
    if (sensor->received == 0) {
        sensor->type = reading.type;
        sensor->code = reading.sensorCode;
        sensor->channel = reading.channel;
        sensor->rollingCode = reading.rollingCode;
        sensor->protocolVersion = decodeSource == static_cast<uint8_t>(OregonDecodeSource::EdgeTimingV21) ? 2U : 3U;
        sensor->firstMs = reading.receivedAtMs;
        if (cycleTracked) {
            sensor->cycles = 1U;
            sensor->lastCycleMs = reading.receivedAtMs;
        }
    } else if (cycleTracked) {
        const uint32_t cycleInterval = static_cast<uint32_t>(reading.receivedAtMs - sensor->lastCycleMs);
        if (cycleInterval <= V21_CYCLE_COPY_WINDOW_MS) {
            if (sensor->copies < 0xFFFFFFFFUL) sensor->copies++;
        } else {
            if (sensor->cycles < 0xFFFFFFFFUL) sensor->cycles++;
            sensor->lastCycleIntervalMs = cycleInterval;
            if (cycleInterval >= V21_CYCLE_MIN_INTERVAL_MS && cycleInterval <= V21_CYCLE_MAX_INTERVAL_MS) {
                // Il minimo intervallo fra cicli e' robusto ai cicli saltati: una
                // perdita produce 2x/3x la cadenza, non una cadenza artificialmente corta.
                if (sensor->cadenceSamples == 0U || cycleInterval < sensor->observedCadenceMs)
                    sensor->observedCadenceMs = cycleInterval;
                if (sensor->cadenceSamples < 255U) sensor->cadenceSamples++;
            }
            sensor->lastCycleMs = reading.receivedAtMs;
        }
    } else {
        const uint32_t interval = static_cast<uint32_t>(reading.receivedAtMs - sensor->lastMs);
        if (interval >= 5000UL && interval <= 180000UL &&
            nominalOregonCadenceMs(sensor->type, sensor->code, sensor->channel) == 0) {
            if (sensor->cadenceSamples == 0 || interval < sensor->observedCadenceMs)
                sensor->observedCadenceMs = interval;
            if (sensor->cadenceSamples < 255U) sensor->cadenceSamples++;
        }
    }
    sensor->lastMs = reading.receivedAtMs;
    sensor->lastRssi = reading.rssi;
    sensor->received++;
}
'''
    text = replace_once(text, old_note, new_note, "cycle-aware session accounting")

    agg_marker = '''        const uint32_t cadence = effectiveOregonCadenceMs(sensor);
        const uint32_t expected = cadence ? expectedPacketsSinceFirst(now, sensor.firstMs, cadence) : 0;
        switch (sensor.type) {
            case SensorType::ThermoHygro:
                thermoSeenCount++; sessionThermo += sensor.received; expThermo += expected;
'''
    agg_new = '''        const uint32_t cadence = effectiveOregonCadenceMs(sensor);
        const uint32_t expected = cadence ? expectedPacketsSinceFirst(now, sensor.firstMs, cadence) : 0;
        const uint32_t qualityRx = qualityReceivedForSensor(sensor);
        switch (sensor.type) {
            case SensorType::ThermoHygro:
                thermoSeenCount++; sessionThermo += qualityRx; expThermo += expected;
'''
    text = replace_once(text, agg_marker, agg_new, "aggregate quality rx")
    text = text.replace('windSeen = true; sessionWind += sensor.received; expWind += expected;',
                        'windSeen = true; sessionWind += qualityRx; expWind += expected;', 1)
    text = text.replace('rainSeen = true; sessionRain += sensor.received; expRain += expected;',
                        'rainSeen = true; sessionRain += qualityRx; expRain += expected;', 1)
    text = text.replace('uvSeen = true; sessionUv += sensor.received; expUv += expected;',
                        'uvSeen = true; sessionUv += qualityRx; expUv += expected;', 1)

    per_sensor_marker = '''        const uint32_t nominal = nominalOregonCadenceMs(sensor.type, sensor.code, sensor.channel);
        const uint32_t cadence = effectiveOregonCadenceMs(sensor);
        const uint32_t expected = cadence ? expectedPacketsSinceFirst(now, sensor.firstMs, cadence) : 0;
        const int quality = qualityPct(sensor.received, expected);
'''
    per_sensor_new = '''        const uint32_t nominal = nominalOregonCadenceMs(sensor.type, sensor.code, sensor.channel);
        const uint32_t cadence = effectiveOregonCadenceMs(sensor);
        const uint32_t expected = cadence ? expectedPacketsSinceFirst(now, sensor.firstMs, cadence) : 0;
        const uint32_t qualityRx = qualityReceivedForSensor(sensor);
        const bool cycleTracked = v21CycleTrackedCode(sensor.code);
        const int quality = qualityPct(qualityRx, expected);
'''
    text = replace_once(text, per_sensor_marker, per_sensor_new, "per-sensor quality rx")

    json_marker = '''        out += ",\\\"rx\\\":" + String(sensor.received);
        out += ",\\\"ex\\\":" + String(expected);
        out += ",\\\"q\\\":" + String(quality);
        out += ",\\\"lost\\\":" + String(expected > sensor.received ? expected - sensor.received : 0UL);
        out += ",\\\"cad\\\":" + String(cadence / 1000UL);
        out += ",\\\"rssi\\\":" + jsonFloat(sensor.lastRssi, 1);
'''
    json_new = '''        out += ",\\\"rx\\\":" + String(qualityRx);
        out += ",\\\"fr\\\":" + String(sensor.received);
        out += ",\\\"cy\\\":" + String(cycleTracked ? sensor.cycles : sensor.received);
        out += ",\\\"dup\\\":" + String(cycleTracked ? sensor.copies : 0UL);
        out += ",\\\"cycle\\\":"; out += cycleTracked ? "true" : "false";
        out += ",\\\"ex\\\":" + String(expected);
        out += ",\\\"q\\\":" + String(quality);
        out += ",\\\"lost\\\":" + String(expected > qualityRx ? expected - qualityRx : 0UL);
        out += ",\\\"cad\\\":" + String(cadence / 1000UL);
        out += ",\\\"obs\\\":" + String(sensor.observedCadenceMs / 1000UL);
        out += ",\\\"last_i\\\":" + String(sensor.lastCycleIntervalMs / 1000UL);
        out += ",\\\"rssi\\\":" + jsonFloat(sensor.lastRssi, 1);
'''
    text = replace_once(text, json_marker, json_new, "cycle JSON fields")

    WEB_CPP.write_text(text, encoding="utf-8")
    print("V2.1 cycle quality API: patched web_manager.cpp")


def patch_dashboard() -> None:
    text = DASH.read_text(encoding="utf-8")
    if "cicli unici" in text:
        print("V2.1 cycle quality UI: source already patched")
        return

    old = '''const oqSensor=x=>{const ready=Number(x.q)>=0,loss=ready?Math.max(0,100-Number(x.q)):0,proto=Number(x.v)===2?'V2.1':'OSV3',source=x.src==='nom'?'nominale':(x.src==='auto'?'adattiva':'calibrazione'),rssi=x.rssi==null?'RSSI N/D':'RSSI '+Number(x.rssi).toFixed(1)+' dBm';return '<div class="qrow"><span><b>'+x.m+'</b><small class="qmeta">'+x.t+' · '+proto+' · 0x'+x.c+' · CH'+x.ch+' · ID '+x.id+' · '+rssi+' · '+(x.cad?'~'+x.cad+' s '+source:source)+'</small></span><span>'+x.rx+'/'+(ready?x.ex:'—')+'</span><span class="'+(ready?qClass(Number(x.q)):'qwarn')+'">'+(ready?x.lost+' · '+loss+'%':'CAL')+'</span><span class="'+(ready?qClass(Number(x.q)):'qgood')+'">'+(ready?qText(Number(x.q)):'LINK')+'</span></div>'};
const renderOregonQuality=s=>{const rows=Array.isArray(s.oregon_sensors)?s.oregon_sensors:[],overflow=Number(s.oregon_sensor_overflow||0);return '<b>Qualita sessione Oregon</b><div class="qrow qhdr"><span>Trasmettitore</span><span>Rx/Attesi</span><span>Persi</span><span>Qualita</span></div>'+(rows.length?rows.map(oqSensor).join(''):'<div class="muted" style="padding-top:6px">Nessun sensore Oregon rilevato nella sessione.</div>')+(overflow?'<div class="qbad" style="margin-top:6px">Registro pieno: '+overflow+' frame senza riga dedicata.</div>':'')+'<div class="muted" style="margin-top:7px">Una riga per trasmettitore · Persi = attesi − ricevuti · CAL = stima della cadenza in corso.<br>Sessione azzerata al cambio protocollo/gain.</div>'};'''
    new = '''const oqSensor=x=>{const ready=Number(x.q)>=0,loss=ready?Math.max(0,100-Number(x.q)):0,proto=Number(x.v)===2?'V2.1':'OSV3',source=x.src==='nom'?'nominale':(x.src==='auto'?'adattiva':'calibrazione'),rssi=x.rssi==null?'RSSI N/D':'RSSI '+Number(x.rssi).toFixed(1)+' dBm',cycle=!!x.cycle,cycleMeta=cycle?' · frame '+Number(x.fr||0)+' · copie '+Number(x.dup||0)+(Number(x.obs||0)?' · osservata ~'+Number(x.obs)+' s':''):'',rxLabel=cycle?Number(x.cy||x.rx):x.rx;return '<div class="qrow"><span><b>'+x.m+'</b><small class="qmeta">'+x.t+' · '+proto+' · 0x'+x.c+' · CH'+x.ch+' · ID '+x.id+' · '+rssi+' · '+(x.cad?'~'+x.cad+' s '+source:source)+cycleMeta+'</small></span><span>'+rxLabel+'/'+(ready?x.ex:'—')+'</span><span class="'+(ready?qClass(Number(x.q)):'qwarn')+'">'+(ready?x.lost+' · '+loss+'%':'CAL')+'</span><span class="'+(ready?qClass(Number(x.q)):'qgood')+'">'+(ready?qText(Number(x.q)):'LINK')+'</span></div>'};
const renderOregonQuality=s=>{const rows=Array.isArray(s.oregon_sensors)?s.oregon_sensors:[],overflow=Number(s.oregon_sensor_overflow||0);return '<b>Qualita sessione Oregon</b><div class="qrow qhdr"><span>Trasmettitore</span><span>Rx/Attesi</span><span>Persi</span><span>Qualita</span></div>'+(rows.length?rows.map(oqSensor).join(''):'<div class="muted" style="padding-top:6px">Nessun sensore Oregon rilevato nella sessione.</div>')+(overflow?'<div class="qbad" style="margin-top:6px">Registro pieno: '+overflow+' frame senza riga dedicata.</div>':'')+'<div class="muted" style="margin-top:7px">Per 1D20/EC70 Rx = cicli unici: le copie ridondanti ravvicinate restano visibili come diagnostica ma non aumentano la qualita. Per gli altri sensori Rx resta il numero di frame validi.<br>Persi = attesi − cicli/ricevuti · CAL = stima della cadenza in corso · sessione azzerata al cambio protocollo/gain.</div>'};'''
    text = replace_once(text, old, new, "quality UI renderer")
    DASH.write_text(text, encoding="utf-8")
    print("V2.1 cycle quality UI: patched dashboard.html")


patch_web_cpp()
patch_dashboard()
