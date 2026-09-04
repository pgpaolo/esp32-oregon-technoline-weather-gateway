#!/usr/bin/env python3
"""Apply isolated Oregon V2.1 recovery for UVR128/EC70 and THGR122NX/1D20.

UVR128 is a special V2.1 transmitter: the complete message is repeated with no
inter-copy pause. The second 16-one preamble therefore lives inside the same RF
burst. Keep enough raw edges to preserve both copies, while the actual recovery
continues to accept only EC70/1D20 frames with a valid protocol checksum.

The normal streaming V2.1, OSV3 and Technoline decoders remain unchanged.
"""

from pathlib import Path

Import("env")
ROOT = Path(env.subst("$PROJECT_DIR"))
PATH = ROOT / "src" / "oregon_receiver.cpp"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    if "bool decodeV21TargetBurstFromStart(" in text:
        print("V2.1 EC70/1D20 recovery: source already patched")
        return

    # UVR128 can produce one continuous double-copy V2.1 burst. A synthetic
    # standards-compliant EC70 double message already reaches ~386 intervals,
    # while real slicer distortion/noise can add more edges. 672 covers the
    # theoretical worst region with margin and costs RAM only, not app Flash.
    text = replace_once(
        text,
        "constexpr uint16_t BURST_EDGE_BUFFER_SIZE = 384;",
        "constexpr uint16_t BURST_EDGE_BUFFER_SIZE = 672;",
        "UVR128 double-copy edge buffer",
    )

    # Compensate the larger raw edge buffer by keeping shorter diagnostic
    # histories. These are display/debug history only and do not affect decode.
    text = replace_once(
        text,
        "constexpr uint8_t BURST_HISTORY_SIZE = 24;",
        "constexpr uint8_t BURST_HISTORY_SIZE = 12;",
        "compact universal burst history",
    )
    if "constexpr uint8_t WGR_PROBE_HISTORY_SIZE = 24;" in text:
        text = text.replace(
            "constexpr uint8_t WGR_PROBE_HISTORY_SIZE = 24;",
            "constexpr uint8_t WGR_PROBE_HISTORY_SIZE = 8;",
            1,
        )

    function_marker = "bool looksLikeTechnolineBurst(const RfBurstRecord &rec) {"
    recovery = r'''// -----------------------------------------------------------------------------
// Oregon V2.1 targeted phase recovery: UVR128/EC70 + THGR122NX/1D20
//
// UVR128 repeats the complete V2.1 message without a pause. The bounded burst
// buffer is therefore deliberately large enough to retain the second preamble
// and second payload. This scanner may start at any edge and consequently can
// recover either copy when the first preamble was clipped by the SX1278 slicer.
// Only exact EC70/1D20 + checksum-valid frames can reach the packet queue.
// -----------------------------------------------------------------------------
bool decodeV21TargetBurstFromStart(const BurstAccumulator &burst,
                                   uint16_t startIndex,
                                   uint8_t initialPhysicalBit,
                                   bool useStateTiming,
                                   bool invertLevel) {
    uint8_t frame[9]{};
    uint8_t lastPhysicalBit = initialPhysicalBit & 1U;
    bool havePairFirst = false;
    uint8_t pairFirst = 0;
    uint8_t decodedBits = 0;
    uint8_t expectedBytes = 0;
    uint16_t expectedBits = 0;
    uint16_t sensorCode = 0;
    uint16_t i = startIndex;

    while (i < burst.storedEdges && decodedBits < 72U) {
        IntervalKind kind;
        if (useStateTiming) {
            const uint8_t level = static_cast<uint8_t>(
                (burst.levels[i] ^ (invertLevel ? 1U : 0U)) & 1U);
            kind = classifyStateInterval(burst.durations[i], level);
        } else {
            kind = classifyInterval(burst.durations[i]);
        }

        uint8_t physicalBit = lastPhysicalBit;
        if (kind == IntervalKind::Long) {
            lastPhysicalBit ^= 1U;
            physicalBit = lastPhysicalBit;
            ++i;
        } else if (kind == IntervalKind::Short) {
            if (static_cast<uint16_t>(i + 1U) >= burst.storedEdges) return false;
            IntervalKind kind2;
            if (useStateTiming) {
                const uint8_t level2 = static_cast<uint8_t>(
                    (burst.levels[i + 1U] ^ (invertLevel ? 1U : 0U)) & 1U);
                kind2 = classifyStateInterval(burst.durations[i + 1U], level2);
            } else {
                kind2 = classifyInterval(burst.durations[i + 1U]);
            }
            if (kind2 != IntervalKind::Short) return false;
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

        // V2.1 transmits [inverse, original], so the second physical bit is data.
        if (physicalBit) {
            const uint8_t byteIndex = static_cast<uint8_t>(decodedBits / 8U);
            const uint8_t bitIndex = static_cast<uint8_t>(decodedBits % 8U);
            frame[byteIndex] |= OREGON_BIT_MASK[bitIndex];
        }
        ++decodedBits;

        if (decodedBits == 4U && (frame[0] & 0xF0U) != 0xA0U) return false;
        if (decodedBits == 20U) {
            sensorCode = rawSensorCode(frame);
            if (sensorCode == 0xEC70U) expectedBytes = 8U;
            else if (sensorCode == 0x1D20U) expectedBytes = 9U;
            else return false;
            expectedBits = static_cast<uint16_t>(expectedBytes) * 8U;
        }
        if (expectedBits != 0U && decodedBits >= expectedBits) break;
    }

    if (expectedBits == 0U || decodedBits != expectedBits) return false;
    stats.v21Candidates++;
    if (sensorCode == 0xEC70U) stats.v21UvCandidates++;
    const uint8_t csPos = sensorCode == 0xEC70U ? 13U : 16U;
    if (!validateFrameChecksumAt(frame, expectedBytes, csPos)) {
        stats.v21ChecksumFail++;
        return false;
    }
    return queuePacket(frame, expectedBytes, OregonDecodeSource::EdgeTimingV21);
}

bool tryV21TargetBurstRecovery() {
    if (burstCurrent.storedEdges < 48U ||
        burstCurrent.storedEdges > BURST_EDGE_BUFFER_SIZE) return false;

    const uint16_t lastStart = burstCurrent.storedEdges > 20U
        ? static_cast<uint16_t>(burstCurrent.storedEdges - 20U) : 0U;

    // Duration-only pass first: smallest and historically successful path.
    for (uint16_t start = 0; start < lastStart; ++start) {
        for (uint8_t initial = 0; initial < 2U; ++initial) {
            if (decodeV21TargetBurstFromStart(
                    burstCurrent, start, initial, false, false)) return true;
        }
    }

    // RF-level-aware fallback, both polarities. Because the complete UVR128
    // double burst is now retained, this pass can reach the second preamble.
    for (uint8_t inv = 0; inv < 2U; ++inv) {
        for (uint16_t start = 0; start < lastStart; ++start) {
            for (uint8_t initial = 0; initial < 2U; ++initial) {
                if (decodeV21TargetBurstFromStart(
                        burstCurrent, start, initial, true, inv != 0U)) return true;
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
        "V2.1 target recovery function insertion",
    )

    finalize_marker = '''    // V6.3: Technoline viene gia' decodificata LIVE da ogni fronte con un
    // demodulatore PWM molto leggero (rtl_433-style). Questo recovery offline
    // e' opzionale e serve soltanto a recuperare un bordo iniziale/finale perso.
'''
    finalize_replacement = '''    // EC70/1D20 recovery is independent from BURST DEBUG. Technoline
    // offline recovery below stays explicitly gated by the debug option.
    if (rfMode != RfProtocolMode::LaCrosse) tryV21TargetBurstRecovery();

''' + finalize_marker
    text = replace_once(
        text,
        finalize_marker,
        finalize_replacement,
        "V2.1 target finalize hook",
    )

    service_start = '''    uint16_t durationUs = 0;
    uint8_t level = 0;
    uint16_t processed = 0;
    while (processed < 1536 && popEdge(durationUs, level)) {
'''
    service_start_replacement = '''    uint16_t durationUs = 0;
    uint8_t level = 0;
    uint16_t processed = 0;
    // The same bounded burst capture serves EC70/1D20 recovery and, when
    // enabled, the universal BURST DEBUG view. No second raw buffer is needed.
    const bool v21TargetBurstCapture =
        (rfMode == RfProtocolMode::Oregon || rfMode == RfProtocolMode::Dual);
    while (processed < 1536 && popEdge(durationUs, level)) {
'''
    text = replace_once(
        text,
        service_start,
        service_start_replacement,
        "V2.1 target service capture flag",
    )

    capture_marker = '''        // Il Burst Analyzer/recovery e' EXTRA e di default OFF. In AUTO SCAN
        // resta forzato ON perche' serve a calcolare il punteggio dei profili.
        if (burstExtraEnabled || burstStats.autoActive) {
            processRfBurstEdge(durationUs, level);
        }
'''
    capture_replacement = '''        // One shared raw burst accumulator: V2.1 support always gets the data it
        // needs; BURST DEBUG/AUTO only add diagnostic or optional recovery work.
        if (v21TargetBurstCapture || burstExtraEnabled || burstStats.autoActive) {
            processRfBurstEdge(durationUs, level);
        }
'''
    text = replace_once(
        text,
        capture_marker,
        capture_replacement,
        "shared burst edge capture",
    )

    finalization_marker = '''    if ((burstExtraEnabled || burstStats.autoActive) && burstCurrent.active) {
'''
    finalization_replacement = '''    if ((v21TargetBurstCapture || burstExtraEnabled || burstStats.autoActive) && burstCurrent.active) {
'''
    text = replace_once(
        text,
        finalization_marker,
        finalization_replacement,
        "shared burst finalization",
    )

    PATH.write_text(text, encoding="utf-8")
    print("V2.1 EC70/1D20 recovery: no-gap UVR128 burst preserved (672 edges)")


main()
