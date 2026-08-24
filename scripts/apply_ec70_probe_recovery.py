#!/usr/bin/env python3
"""Instrument the existing EC70/1D20 recovery with a passive EC70 probe.

Runs after apply_uvr128_recovery.py. No additional decoder pass is introduced:
the probe only records progress made by phase-scan attempts that already run.
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
    if "struct Ec70ProbeScratch" in text:
        print("EC70 passive probe: source already patched")
        return

    marker = "bool decodeV21TargetBurstFromStart(const BurstAccumulator &burst,\n"
    helpers = r'''struct Ec70ProbeScratch {
    bool headerA{false};
    bool twentyBit{false};
    bool nearEc70{false};
    bool exactEc70{false};
    bool checksumOk{false};
    uint16_t bestCode{0};
    uint8_t bestDistance{0xFFU};
};
Ec70ProbeScratch ec70ProbeScratch{};

uint8_t ec70BitDistance(uint16_t code) {
    uint16_t v = static_cast<uint16_t>(code ^ 0xEC70U);
    uint8_t n = 0;
    while (v) {
        n = static_cast<uint8_t>(n + (v & 1U));
        v >>= 1U;
    }
    return n;
}

void resetEc70ProbeScratch() {
    ec70ProbeScratch = Ec70ProbeScratch{};
}

void commitEc70ProbeBurst(const BurstAccumulator &burst) {
    stats.ec70ProbeBursts++;
    if (ec70ProbeScratch.headerA) stats.ec70ProbeHeaderA++;
    if (ec70ProbeScratch.twentyBit) stats.ec70Probe20Bit++;
    if (ec70ProbeScratch.nearEc70) stats.ec70ProbeNear++;
    if (ec70ProbeScratch.exactEc70) stats.ec70ProbeExact++;
    if (ec70ProbeScratch.checksumOk) stats.ec70ProbeChecksumOk++;

    if (ec70ProbeScratch.twentyBit) {
        stats.ec70ProbeLastBestCode = ec70ProbeScratch.bestCode;
        stats.ec70ProbeLastDistance = ec70ProbeScratch.bestDistance;
        const uint32_t durationMs = (burst.durationUs + 500UL) / 1000UL;
        stats.ec70ProbeLastDurationMs = static_cast<uint16_t>(durationMs > 65535UL ? 65535UL : durationMs);
        stats.ec70ProbeLastEdges = burst.edges;
        stats.ec70ProbeLastRssi10 = isfinite(burst.rssi)
            ? static_cast<int16_t>(burst.rssi * 10.0f) : 0;
    }

    if (ec70ProbeScratch.nearEc70) {
        const uint32_t nowMs = millis();
        if (stats.ec70ProbeLastNearMs != 0U)
            stats.ec70ProbeLastNearDeltaMs = static_cast<uint32_t>(nowMs - stats.ec70ProbeLastNearMs);
        stats.ec70ProbeLastNearMs = nowMs;
    }
}

'''
    text = replace_once(text, marker, helpers + marker, "EC70 probe helper insertion")

    old_nibble = "        if (decodedBits == 4U && (frame[0] & 0xF0U) != 0xA0U) return false;\n"
    new_nibble = "        if (decodedBits == 4U && (frame[0] & 0xF0U) != 0xA0U) return false;\n        if (decodedBits == 4U) ec70ProbeScratch.headerA = true;\n"
    text = replace_once(text, old_nibble, new_nibble, "EC70 probe A-header progress")

    old_20 = '''        if (decodedBits == 20U) {
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
'''
    new_20 = '''        if (decodedBits == 20U) {
            sensorCode = rawSensorCode(frame);
            ec70ProbeScratch.twentyBit = true;
            const uint8_t distance = ec70BitDistance(sensorCode);
            if (distance < ec70ProbeScratch.bestDistance) {
                ec70ProbeScratch.bestDistance = distance;
                ec70ProbeScratch.bestCode = sensorCode;
            }
            if (distance <= 2U) ec70ProbeScratch.nearEc70 = true;
            if (sensorCode == 0xEC70U) {
                ec70ProbeScratch.exactEc70 = true;
                expectedBytes = 8U;
            } else if (sensorCode == 0x1D20U) {
                expectedBytes = 9U;
            } else {
                return false;
            }
            expectedBits = static_cast<uint16_t>(expectedBytes) * 8U;
        }
'''
    text = replace_once(text, old_20, new_20, "EC70 probe 20-bit progress")

    old_queue = '''    if (!validateFrameChecksumAt(frame, expectedBytes, csPos)) {
        stats.v21ChecksumFail++;
        return false;
    }

    return queuePacket(frame, expectedBytes, OregonDecodeSource::EdgeTimingV21);
'''
    new_queue = '''    if (!validateFrameChecksumAt(frame, expectedBytes, csPos)) {
        stats.v21ChecksumFail++;
        return false;
    }
    if (sensorCode == 0xEC70U) ec70ProbeScratch.checksumOk = true;

    return queuePacket(frame, expectedBytes, OregonDecodeSource::EdgeTimingV21);
'''
    text = replace_once(text, old_queue, new_queue, "EC70 probe checksum progress")

    old_start = '''    if (burstCurrent.storedEdges < 48U ||
        burstCurrent.storedEdges > BURST_EDGE_BUFFER_SIZE) {
        return false;
    }

    const uint16_t lastStart = burstCurrent.storedEdges > 20U
'''
    new_start = '''    if (burstCurrent.storedEdges < 48U ||
        burstCurrent.storedEdges > BURST_EDGE_BUFFER_SIZE) {
        return false;
    }
    resetEc70ProbeScratch();

    const uint16_t lastStart = burstCurrent.storedEdges > 20U
'''
    text = replace_once(text, old_start, new_start, "EC70 probe burst reset")

    old_success1 = '''            if (decodeV21TargetBurstFromStart(
                    burstCurrent, start, initial, false, false)) {
                return true;
            }
'''
    new_success1 = '''            if (decodeV21TargetBurstFromStart(
                    burstCurrent, start, initial, false, false)) {
                commitEc70ProbeBurst(burstCurrent);
                return true;
            }
'''
    text = replace_once(text, old_success1, new_success1, "EC70 probe duration-pass commit")

    old_success2 = '''                if (decodeV21TargetBurstFromStart(
                        burstCurrent, start, initial, true, inv != 0U)) {
                    return true;
                }
'''
    new_success2 = '''                if (decodeV21TargetBurstFromStart(
                        burstCurrent, start, initial, true, inv != 0U)) {
                    commitEc70ProbeBurst(burstCurrent);
                    return true;
                }
'''
    text = replace_once(text, old_success2, new_success2, "EC70 probe state-pass commit")

    end_marker = '''    }
    return false;
}

bool looksLikeTechnolineBurst'''
    end_new = '''    }
    commitEc70ProbeBurst(burstCurrent);
    return false;
}

bool looksLikeTechnolineBurst'''
    text = replace_once(text, end_marker, end_new, "EC70 probe failed-burst commit")

    PATH.write_text(text, encoding="utf-8")
    print("EC70 passive probe: instrumented existing phase scan")


main()
