#!/usr/bin/env python3
"""Apply the isolated UVR128/EC70 V2.1 recovery to oregon_receiver.cpp.

This is intentionally a pre-build patch on the hardware-validation branch.
Once the real UVR128 test is successful, the generated source change can be
folded into oregon_receiver.cpp and this helper removed.
"""

from pathlib import Path

Import("env")  # PlatformIO/SCons injects this symbol.
ROOT = Path(env.subst("$PROJECT_DIR"))
PATH = ROOT / "src" / "oregon_receiver.cpp"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    # Idempotent: a second PlatformIO environment in the same workspace must
    # not patch an already generated source a second time.
    if "bool decodeUvr128BurstFromStart(" in text:
        print("UVR128 recovery: source already patched")
        return

    function_marker = "bool looksLikeTechnolineBurst(const RfBurstRecord &rec) {"
    recovery = r'''// -----------------------------------------------------------------------------
// UVR128 / EC70 Oregon V2.1 phase recovery
//
// The normal streaming V2.1 decoder is deliberately unchanged. UVR128 sends a
// long no-pause transmission and the SX1278 slicer can expose it with the first
// edge/phase clipped. At the end of an RF burst this fallback scans possible
// edge starts and both initial physical polarities. Random starts are rejected
// after 4 or 20 logical bits; only EC70 with valid V2.1 checksum is queued.
// -----------------------------------------------------------------------------
bool decodeUvr128BurstFromStart(const BurstAccumulator &burst,
                                uint16_t startIndex,
                                uint8_t initialPhysicalBit) {
    uint8_t frame[8]{};
    uint8_t lastPhysicalBit = initialPhysicalBit & 1U;
    bool havePairFirst = false;
    uint8_t pairFirst = 0;
    uint8_t decodedBits = 0;
    uint16_t i = startIndex;

    while (i < burst.storedEdges && decodedBits < 64U) {
        const IntervalKind kind = classifyInterval(burst.durations[i]);
        uint8_t physicalBit = lastPhysicalBit;

        if (kind == IntervalKind::Long) {
            lastPhysicalBit ^= 1U;
            physicalBit = lastPhysicalBit;
            ++i;
        } else if (kind == IntervalKind::Short) {
            if (static_cast<uint16_t>(i + 1U) >= burst.storedEdges ||
                classifyInterval(burst.durations[i + 1U]) != IntervalKind::Short) {
                return false;
            }
            physicalBit = lastPhysicalBit;
            i = static_cast<uint16_t>(i + 2U);
        } else {
            return false;
        }

        if (!havePairFirst) {
            pairFirst = physicalBit;
            havePairFirst = true;
            continue;
        }
        if (pairFirst == physicalBit) return false;
        havePairFirst = false;

        // Oregon V2.1 transmits [inverse, original]; the second physical bit is
        // the logical data bit.
        if (physicalBit) {
            const uint8_t byteIndex = static_cast<uint8_t>(decodedBits / 8U);
            const uint8_t bitIndex = static_cast<uint8_t>(decodedBits % 8U);
            frame[byteIndex] |= OREGON_BIT_MASK[bitIndex];
        }
        ++decodedBits;

        if (decodedBits == 4U && (frame[0] & 0xF0U) != 0xA0U) return false;
        if (decodedBits == 20U && rawSensorCode(frame) != 0xEC70U) return false;
    }

    if (decodedBits != 64U || rawSensorCode(frame) != 0xEC70U) return false;

    stats.v21Candidates++;
    stats.v21UvCandidates++;
    if (!validateFrameChecksumAt(frame, 8U, 13U)) {
        stats.v21ChecksumFail++;
        return false;
    }

    return queuePacket(frame, 8U, OregonDecodeSource::EdgeTimingV21);
}

bool tryUvr128BurstRecovery() {
    if (burstCurrent.storedEdges < 48U ||
        burstCurrent.storedEdges > BURST_EDGE_BUFFER_SIZE) {
        return false;
    }

    const uint16_t lastStart = burstCurrent.storedEdges > 16U
        ? static_cast<uint16_t>(burstCurrent.storedEdges - 16U) : 0U;

    for (uint16_t start = 0; start < lastStart; ++start) {
        for (uint8_t initial = 0; initial < 2U; ++initial) {
            if (decodeUvr128BurstFromStart(burstCurrent, start, initial)) {
                return true;
            }
        }
    }
    return false;
}

'''
    text = replace_once(
        text,
        function_marker,
        recovery + function_marker,
        "UVR128 function insertion",
    )

    finalize_marker = '''    // V6.3: Technoline viene gia' decodificata LIVE da ogni fronte con un
    // demodulatore PWM molto leggero (rtl_433-style). Questo recovery offline
    // e' opzionale e serve soltanto a recuperare un bordo iniziale/finale perso.
'''
    finalize_replacement = '''    // UVR128 V2.1 recovery is independent from BURST EXTRA. Technoline burst
    // decoding below stays gated exactly as before.
    if (rfMode != RfProtocolMode::LaCrosse) {
        tryUvr128BurstRecovery();
    }

''' + finalize_marker
    text = replace_once(
        text,
        finalize_marker,
        finalize_replacement,
        "UVR128 finalize hook",
    )

    service_start = '''    uint16_t durationUs = 0;
    uint8_t level = 0;
    uint16_t processed = 0;
    while (processed < 1536 && popEdge(durationUs, level)) {
'''
    service_start_replacement = '''    uint16_t durationUs = 0;
    uint8_t level = 0;
    uint16_t processed = 0;
    // EC70 recovery needs the raw Oregon burst even when the optional generic
    // BURST EXTRA decoder is OFF. This only records bounded edge/timing data;
    // the costly Technoline burst recovery remains controlled by burstExtraEnabled.
    const bool uvrBurstCapture =
        (rfMode == RfProtocolMode::Oregon || rfMode == RfProtocolMode::Dual);
    while (processed < 1536 && popEdge(durationUs, level)) {
'''
    text = replace_once(
        text,
        service_start,
        service_start_replacement,
        "UVR128 service capture flag",
    )

    capture_marker = '''        // Il Burst Analyzer/recovery e' EXTRA e di default OFF. In AUTO SCAN
        // resta forzato ON perche' serve a calcolare il punteggio dei profili.
        if (burstExtraEnabled || burstStats.autoActive) {
            processRfBurstEdge(durationUs, level);
        }
'''
    capture_replacement = '''        // Keep a bounded raw burst for EC70 phase recovery whenever Oregon is
        // active. Generic/Technoline burst decoding is still gated in finalizeRfBurst().
        if (uvrBurstCapture || burstExtraEnabled || burstStats.autoActive) {
            processRfBurstEdge(durationUs, level);
        }
'''
    text = replace_once(
        text,
        capture_marker,
        capture_replacement,
        "UVR128 edge capture",
    )

    finalization_marker = '''    if ((burstExtraEnabled || burstStats.autoActive) && burstCurrent.active) {
'''
    finalization_replacement = '''    if ((uvrBurstCapture || burstExtraEnabled || burstStats.autoActive) && burstCurrent.active) {
'''
    text = replace_once(
        text,
        finalization_marker,
        finalization_replacement,
        "UVR128 burst finalization",
    )

    PATH.write_text(text, encoding="utf-8")
    print("UVR128 recovery: patched oregon_receiver.cpp")


# PlatformIO executes extra_scripts through SCons exec(), so __name__ is not
# guaranteed to be "__main__". Execute the idempotent patch unconditionally.
main()
