#!/usr/bin/env python3
"""Apply cycle-aware session quality for Oregon V2.1 1D20 and EC70.

Diagnostic/statistical layer only: no RF decoder, timing, AGC, bandwidth,
checksum, MQTT, SD or OLED behavior is changed. The script intentionally runs
after the existing multi-UV and sensor-status patchers and before Web UI
compression.
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

    # At this point apply_multi_uv_dashboard.py and apply_sensor_status_ui.py
    # have already enriched the session slot with uvIndex and batteryState.
    old_struct = '''struct OregonSessionSensor {
    SensorType type{SensorType::Unknown};
    uint16_t code{0};
    uint8_t channel{0};
    uint8_t rollingCode{0};
    uint8_t protocolVersion{0};
    uint8_t cadenceSamples{0};
    int8_t uvIndex{-1}; // compact per-transmitter UV value; also fills existing alignment gap
    uint8_t batteryState{0}; // compact session battery: 0=N/D, 1=OK, 2=LOW
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
    int8_t uvIndex{-1}; // compact per-transmitter UV value; also fills existing alignment gap
    uint8_t batteryState{0}; // compact session battery: 0=N/D, 1=OK, 2=LOW
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
// 1D20 e EC70 inviano copie ridondanti ravvicinate. Nei log reali 1D20 mostra
// tipicamente la seconda copia dopo ~0,2 s, contro un ciclo reale ~39/41/43 s.
// La finestra viene applicata SOLO a questi due codici V2.1.
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

    # Replace only the accounting block. UV value and battery updates appended
    # by previous patchers remain untouched below sensor->lastRssi.
    old_accounting = '''    if (sensor->received == 0) {
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
'''
    new_accounting = '''    const bool cycleTracked = v21CycleTrackedCode(reading.sensorCode);
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
                // A missed transmission gives 2x/3x cadence. Keeping the minimum
                // valid cycle interval therefore converges to the base cadence.
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
'''
    text = replace_once(text, old_accounting, new_accounting, "cycle-aware session accounting")

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
    for old, new in [
        ('windSeen = true; sessionWind += sensor.received; expWind += expected;',
         'windSeen = true; sessionWind += qualityRx; expWind += expected;'),
        ('rainSeen = true; sessionRain += sensor.received; expRain += expected;',
         'rainSeen = true; sessionRain += qualityRx; expRain += expected;'),
        ('uvSeen = true; sessionUv += sensor.received; expUv += expected;',
         'uvSeen = true; sessionUv += qualityRx; expUv += expected;'),
    ]:
        if text.count(old) != 1:
            raise RuntimeError(f"aggregate marker missing: {old}")
        text = text.replace(old, new, 1)

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

    # Existing UI patchers have already converted RSSI and battery to badges.
    marker = "rssi=rssiBadge(x.rssi);return"
    replacement = "rssi=rssiBadge(x.rssi),cycle=!!x.cycle,cycleMeta=cycle?' · frame '+Number(x.fr||0)+' · copie '+Number(x.dup||0)+(Number(x.obs||0)?' · osservata ~'+Number(x.obs)+' s':''):'';return"
    text = replace_once(text, marker, replacement, "cycle UI variables")

    meta_marker = "+rssi+' · '+batteryBadge(x.bat)+' · '+(x.cad?'~'+x.cad+' s '+source:source)+'</small>"
    meta_replacement = "+rssi+' · '+batteryBadge(x.bat)+' · '+(x.cad?'~'+x.cad+' s '+source:source)+cycleMeta+'</small>"
    text = replace_once(text, meta_marker, meta_replacement, "cycle UI metadata")

    footer = "Una riga per trasmettitore · Persi = attesi − ricevuti · CAL = stima della cadenza in corso.<br>Sessione azzerata al cambio protocollo/gain."
    footer_new = "Per 1D20/EC70 Rx = cicli unici: le copie ridondanti ravvicinate restano diagnostiche e non aumentano la qualita. Per gli altri sensori Rx = frame validi.<br>Persi = attesi − Rx · CAL = stima cadenza · sessione azzerata al cambio protocollo/gain."
    text = replace_once(text, footer, footer_new, "cycle UI footer")

    DASH.write_text(text, encoding="utf-8")
    print("V2.1 cycle quality UI: patched dashboard.html")


patch_web_cpp()
patch_dashboard()
