#!/usr/bin/env python3
"""Apply isolated Oregon V2.1 recovery for UVR128/EC70 and THGR122NX/1D20.

Patch V2 is deliberately checksum-gated and leaves the normal streaming decoder
untouched.  It also upgrades an older in-place generated patch instead of
silently keeping it forever in a developer working tree.
"""

from pathlib import Path

Import("env")  # PlatformIO/SCons injects this symbol.
ROOT = Path(env.subst("$PROJECT_DIR"))
PATH = ROOT / "src" / "oregon_receiver.cpp"

PATCH_VERSION = "V21_TARGET_RECOVERY_PATCH_V2"
FUNCTION_MARKER = "bool looksLikeTechnolineBurst(const RfBurstRecord &rec) {"
RECOVERY_FN_MARKER = "bool decodeV21TargetBurstFromStart("


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


RECOVERY_FUNCTIONS = r'''// V21_TARGET_RECOVERY_PATCH_V2
bool decodeV21TargetBurstFromStart(const BurstAccumulator &burst,
                                   const RfBurstRecord &rec,
                                   uint16_t startIndex,
                                   uint8_t initialPhysicalBit,
                                   uint8_t timingMode,
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

    auto classify = [&](uint16_t index) -> IntervalKind {
        if (index >= burst.storedEdges) return IntervalKind::Invalid;
        if (timingMode == 0U) {
            return classifyInterval(burst.durations[index]);
        }
        if (timingMode == 1U) {
            const uint8_t level = static_cast<uint8_t>(
                (burst.levels[index] ^ (invertLevel ? 1U : 0U)) & 1U);
            return classifyStateInterval(burst.durations[index], level);
        }
        // Mode 2 learns the local ON/OFF timing from this exact burst.  This is
        // intentionally used only by the EC70/1D20 checksum-gated fallback.
        return classifyAdaptiveBurstInterval(
            burst.durations[index], burst.levels[index], rec, invertLevel);
    };

    while (i < burst.storedEdges && decodedBits < 72U) {
        const IntervalKind kind = classify(i);

        uint8_t physicalBit = lastPhysicalBit;
        if (kind == IntervalKind::Long) {
            lastPhysicalBit ^= 1U;
            physicalBit = lastPhysicalBit;
            ++i;
        } else if (kind == IntervalKind::Short) {
            if (static_cast<uint16_t>(i + 1U) >= burst.storedEdges) return false;
            if (classify(static_cast<uint16_t>(i + 1U)) != IntervalKind::Short) return false;
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

        // Oregon V2.1 transmits [inverse, original].
        if (physicalBit) {
            const uint8_t byteIndex = static_cast<uint8_t>(decodedBits / 8U);
            const uint8_t bitIndex = static_cast<uint8_t>(decodedBits % 8U);
            frame[byteIndex] |= OREGON_BIT_MASK[bitIndex];
        }
        ++decodedBits;

        // Reject noise as early as possible.  Keeping the sync nibble in the
        // internal buffer matches the normal decoder and the parser layout.
        if (decodedBits == 4U && (frame[0] & 0xF0U) != 0xA0U) return false;
        if (decodedBits == 20U) {
            sensorCode = rawSensorCode(frame);
            if (sensorCode == 0xEC70U) {
                expectedBytes = 8U;
            } else if (sensorCode == 0x1D20U) {
                expectedBytes = 9U;
            } else {
                return false;
            }
            expectedBits = static_cast<uint16_t>(expectedBytes) * 8U;
        }
        if (expectedBits != 0U && decodedBits >= expectedBits) break;
    }

    if (expectedBits == 0U || decodedBits != expectedBits) return false;
    if (sensorCode != 0xEC70U && sensorCode != 0x1D20U) return false;

    stats.v21Candidates++;
    if (sensorCode == 0xEC70U) stats.v21UvCandidates++;
    const uint8_t csPos = sensorCode == 0xEC70U ? 13U : 16U;
    if (!validateFrameChecksumAt(frame, expectedBytes, csPos)) {
        stats.v21ChecksumFail++;
        return false;
    }

    return queuePacket(frame, expectedBytes, OregonDecodeSource::EdgeTimingV21);
}

bool tryV21TargetBurstRecovery(const RfBurstRecord &rec) {
    if (burstCurrent.storedEdges < 48U ||
        burstCurrent.storedEdges > BURST_EDGE_BUFFER_SIZE) {
        return false;
    }

    // Do not waste time on starts that cannot possibly contain even the short
    // EC70 frame.  The exact interval count varies with consecutive equal bits,
    // so keep a deliberately generous 40-edge tail margin.
    const uint16_t lastStart = burstCurrent.storedEdges > 40U
        ? static_cast<uint16_t>(burstCurrent.storedEdges - 40U) : 0U;

    // Pass 1: legacy duration-only classifier, retained as the known baseline.
    for (uint16_t start = 0; start < lastStart; ++start) {
        for (uint8_t initial = 0; initial < 2U; ++initial) {
            if (decodeV21TargetBurstFromStart(
                    burstCurrent, rec, start, initial, 0U, false)) {
                return true;
            }
        }
    }

    // Pass 2: static level-aware timing in both RF polarities.
    for (uint8_t inv = 0; inv < 2U; ++inv) {
        for (uint16_t start = 0; start < lastStart; ++start) {
            for (uint8_t initial = 0; initial < 2U; ++initial) {
                if (decodeV21TargetBurstFromStart(
                        burstCurrent, rec, start, initial, 1U, inv != 0U)) {
                    return true;
                }
            }
        }
    }

    // Pass 3: burst-adaptive timing.  Real UVR128 units can be shifted enough
    // by the SX1278 OOK slicer to sit outside the static ON/OFF windows.  Local
    // centres are learned from the same bounded burst, while EC70/1D20 ID plus
    // checksum remain mandatory before a packet can reach the parser.
    for (uint8_t inv = 0; inv < 2U; ++inv) {
        for (uint16_t start = 0; start < lastStart; ++start) {
            for (uint8_t initial = 0; initial < 2U; ++initial) {
                if (decodeV21TargetBurstFromStart(
                        burstCurrent, rec, start, initial, 2U, inv != 0U)) {
                    return true;
                }
            }
        }
    }
    return false;
}

'''

RECOVERY_BANNER = r'''// -----------------------------------------------------------------------------
// Oregon V2.1 targeted phase recovery: UVR128/EC70 + THGR122NX/1D20
//
// Normal streaming V2.1 decoding remains untouched.  The bounded end-of-burst
// fallback scans arbitrary starts and both polarities; V2 additionally tries
// per-burst adaptive timing.  Only EC70/1D20 with a valid checksum are queued.
// -----------------------------------------------------------------------------
'''


def install_hooks(text: str) -> str:
    finalize_marker = '''    // V6.3: Technoline viene gia' decodificata LIVE da ogni fronte con un
    // demodulatore PWM molto leggero (rtl_433-style). Questo recovery offline
    // e' opzionale e serve soltanto a recuperare un bordo iniziale/finale perso.
'''
    finalize_replacement = '''    // EC70/1D20 V2.1 recovery is independent from BURST EXTRA. Technoline
    // burst decoding below stays gated exactly as before.
    if (rfMode != RfProtocolMode::LaCrosse) {
        tryV21TargetBurstRecovery(rec);
    }

''' + finalize_marker
    text = replace_once(
        text, finalize_marker, finalize_replacement,
        "V2.1 target finalize hook")

    service_start = '''    uint16_t durationUs = 0;
    uint8_t level = 0;
    uint16_t processed = 0;
    while (processed < 1536 && popEdge(durationUs, level)) {
'''
    service_start_replacement = '''    uint16_t durationUs = 0;
    uint8_t level = 0;
    uint16_t processed = 0;
    // EC70/1D20 recovery needs the bounded raw Oregon burst even when the
    // optional generic BURST EXTRA decoder is OFF.
    const bool v21TargetBurstCapture =
        (rfMode == RfProtocolMode::Oregon || rfMode == RfProtocolMode::Dual);
    while (processed < 1536 && popEdge(durationUs, level)) {
'''
    text = replace_once(
        text, service_start, service_start_replacement,
        "V2.1 target service capture flag")

    capture_marker = '''        // Il Burst Analyzer/recovery e' EXTRA e di default OFF. In AUTO SCAN
        // resta forzato ON perche' serve a calcolare il punteggio dei profili.
        if (burstExtraEnabled || burstStats.autoActive) {
            processRfBurstEdge(durationUs, level);
        }
'''
    capture_replacement = '''        // Keep a bounded raw burst for EC70/1D20 recovery whenever Oregon is
        // active. Generic/Technoline burst decoding remains gated in finalize.
        if (v21TargetBurstCapture || burstExtraEnabled || burstStats.autoActive) {
            processRfBurstEdge(durationUs, level);
        }
'''
    text = replace_once(
        text, capture_marker, capture_replacement,
        "V2.1 target edge capture")

    finalization_marker = '''    if ((burstExtraEnabled || burstStats.autoActive) && burstCurrent.active) {
'''
    finalization_replacement = '''    if ((v21TargetBurstCapture || burstExtraEnabled || burstStats.autoActive) && burstCurrent.active) {
'''
    text = replace_once(
        text, finalization_marker, finalization_replacement,
        "V2.1 target burst finalization")
    return text


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    # The same source tree is reused by PlatformIO environments.  V2 is
    # idempotent, but unlike V1 it can also replace an older already-generated
    # recovery block left in a developer working tree by a previous build.
    if PATCH_VERSION in text:
        print("V2.1 EC70/1D20 recovery V2: source already current")
        return

    if RECOVERY_FN_MARKER in text:
        start = text.index(RECOVERY_FN_MARKER)
        end = text.index(FUNCTION_MARKER, start)
        text = text[:start] + RECOVERY_FUNCTIONS + text[end:]
        PATH.write_text(text, encoding="utf-8")
        print("V2.1 EC70/1D20 recovery: upgraded generated V1 block -> V2")
        return

    text = replace_once(
        text,
        FUNCTION_MARKER,
        RECOVERY_BANNER + RECOVERY_FUNCTIONS + FUNCTION_MARKER,
        "V2.1 target recovery function insertion",
    )
    text = install_hooks(text)
    PATH.write_text(text, encoding="utf-8")
    print("V2.1 EC70/1D20 recovery V2: patched oregon_receiver.cpp")


# PlatformIO executes extra_scripts through SCons exec(), so __name__ is not
# guaranteed to be "__main__". Execute the idempotent patch unconditionally.
main()
