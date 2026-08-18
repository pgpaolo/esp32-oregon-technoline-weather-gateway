/*
 * Technoline / La Crosse WS23xx decoder support.
 *
 * Protocol/timing and decoder logic were developed with reference to:
 *   - rtl_433, src/devices/lacrossews.c (GPL-2.0-or-later)
 *   - PracticalArduino WeatherStationReceiver (GPL-3.0-or-later)
 *
 * PracticalArduino upstream copyright notices:
 *   Copyright 2009 Marc Alexander
 *   Copyright 2009 Jonathan Oxer
 *
 * See the repository NOTICE file for full attribution.
 * This project is distributed under GPL-3.0-or-later.
 */

#include "lacrosse_ws23xx.h"
#include <Arduino.h>
#include <string.h>
#include "config.h"

namespace {

constexpr uint8_t QUEUE_SIZE = 6;
LaCrossePacket packetQueue[QUEUE_SIZE];
uint8_t queueHead = 0;
uint8_t queueTail = 0;
LaCrosseRxStats stats{};

uint8_t lastFrame[LACROSSE_WS23XX_NIBBLES]{};
uint32_t lastFrameMs = 0;

// rtl_433 lacrossews.c: OOK_PULSE_PWM, short 368 us, long 1464 us,
// reset_limit 8000 us. Sul SX1278 dell'impianto sono stati osservati short
// intorno a 260-300 us e long ~1.35-1.45 ms: finestre ampie, ma il frame entra
// solo dopo header/complement/parity/checksum validi.
constexpr uint16_t TECH_SHORT_DEFAULT_US = LACROSSE_SHORT_PULSE_US;
constexpr uint16_t TECH_LONG_DEFAULT_US  = LACROSSE_LONG_PULSE_US;
constexpr uint16_t TECH_SHORT_MIN_US     = 100U;
constexpr uint16_t TECH_SHORT_MAX_US     = 780U;
constexpr uint16_t TECH_LONG_MIN_US      = 850U;
constexpr uint16_t TECH_LONG_MAX_US      = 2150U;
constexpr uint16_t TECH_GAP_MIN_US       = 650U;
constexpr uint16_t TECH_GAP_MAX_US       = 2300U;

uint16_t absDiff(uint16_t a, uint16_t b) {
    return a > b ? static_cast<uint16_t>(a - b) : static_cast<uint16_t>(b - a);
}

void updateAverage(uint16_t &avg, uint16_t v) {
    if (!avg) avg = v;
    else avg = static_cast<uint16_t>((static_cast<uint32_t>(avg) * 7U + v) / 8U);
}

void accountIntervalBin(uint16_t us) {
    if (us < 200U) stats.intervalBins[0]++;
    else if (us < 600U) stats.intervalBins[1]++;
    else if (us < 1100U) stats.intervalBins[2]++;
    else if (us < 1800U) stats.intervalBins[3]++;
    else if (us < 3500U) stats.intervalBins[4]++;
    else stats.intervalBins[5]++;
}

bool pulsePlausible(uint16_t us) {
    return (us >= TECH_SHORT_MIN_US && us <= TECH_SHORT_MAX_US) ||
           (us >= TECH_LONG_MIN_US && us <= TECH_LONG_MAX_US);
}

bool classifyPulse(uint16_t us, bool &isShort) {
    if (!pulsePlausible(us)) return false;
    const uint16_t shortCenter = stats.shortPulseAverageUs ? stats.shortPulseAverageUs : TECH_SHORT_DEFAULT_US;
    const uint16_t longCenter = stats.longPulseAverageUs ? stats.longPulseAverageUs : TECH_LONG_DEFAULT_US;
    const uint16_t ds = absDiff(us, shortCenter);
    const uint16_t dl = absDiff(us, longCenter);
    isShort = ds <= dl;
    return true;
}

void bitsToNibbles(const uint8_t bits[52], uint8_t n[13]) {
    memset(n, 0, 13);
    for (uint8_t i = 0; i < 52U; ++i) {
        n[i / 4U] |= static_cast<uint8_t>((bits[i] & 1U) << (3U - (i % 4U)));
    }
}

bool validateCandidate(const uint8_t bits[52], const uint8_t n[13], bool countFails = true) {
    if (n[0] != 0x0U || (n[1] != 0x9U && n[1] != 0x6U)) {
        if (countFails) stats.headerFails++;
        return false;
    }

    if (!(n[7] == static_cast<uint8_t>(n[10] ^ 0x0FU) &&
          n[8] == static_cast<uint8_t>(n[11] ^ 0x0FU))) {
        if (countFails) stats.complementFails++;
        return false;
    }

    uint8_t parity = 0;
    for (uint8_t i = 0; i < 52U; ++i) {
        if (i == 9U || (i >= 27U && i <= 39U)) parity = static_cast<uint8_t>(parity + bits[i]);
    }
    if ((parity & 1U) != 1U) {
        if (countFails) stats.parityFails++;
        return false;
    }

    uint8_t checksum = 0;
    for (uint8_t i = 0; i < 12U; ++i) checksum = static_cast<uint8_t>(checksum + n[i]);
    checksum &= 0x0FU;
    if (checksum != n[12]) {
        if (countFails) stats.checksumFails++;
        return false;
    }
    return true;
}

bool queueFrame(const uint8_t n[13], uint8_t hypothesis, float rssi = NAN, uint8_t decoder = 0U) {
    const uint32_t now = millis();
    if (static_cast<uint32_t>(now - lastFrameMs) < 180U && memcmp(lastFrame, n, 13) == 0) {
        stats.duplicateFrames++;
        return false;
    }
    const uint8_t next = static_cast<uint8_t>((queueHead + 1U) % QUEUE_SIZE);
    if (next == queueTail) {
        stats.queueDrops++;
        return false;
    }

    LaCrossePacket &p = packetQueue[queueHead];
    memcpy(p.nibbles, n, 13);
    p.receivedAtMs = now;
    p.rssi = rssi;
    p.pulseLevel = static_cast<uint8_t>((hypothesis >> 1U) & 1U);
    p.hypothesis = hypothesis;
    p.decoder = decoder;
    queueHead = next;

    memcpy(lastFrame, n, 13);
    lastFrameMs = now;
    stats.validFrames++;
    stats.activeHypothesis = static_cast<int8_t>(hypothesis);
    stats.hypothesisValid[hypothesis & 3U]++;
    return true;
}

struct PulseStream {
    uint8_t level{0};
    uint8_t bitClass[52]{};     // 1 = short, 0 = long
    uint16_t widths[52]{};
    uint8_t head{0};            // prossimo slot da scrivere
    uint8_t count{0};

    void reset() {
        head = 0;
        count = 0;
        memset(bitClass, 0, sizeof(bitClass));
        memset(widths, 0, sizeof(widths));
    }

    void append(bool isShort, uint16_t width) {
        bitClass[head] = isShort ? 1U : 0U;
        widths[head] = width;
        head = static_cast<uint8_t>((head + 1U) % 52U);
        if (count < 52U) count++;
    }

    uint8_t oldestIndex() const { return count < 52U ? 0U : head; }

    uint8_t clsAt(uint8_t pos) const {
        const uint8_t idx = count < 52U ? pos : static_cast<uint8_t>((head + pos) % 52U);
        return bitClass[idx];
    }

    uint16_t widthAt(uint8_t pos) const {
        const uint8_t idx = count < 52U ? pos : static_cast<uint8_t>((head + pos) % 52U);
        return widths[idx];
    }
};

PulseStream streams[2];

// Decoder state-machine derivato dal ricevitore PracticalArduino per il
// trasmettitore centrale WS-2300-25S. Sul protocollo reale il bit e' codificato
// dalla sola durata del periodo HIGH: short=1, long=0; il periodo LOW seguente
// non contiene il bit. Poiche' DIO2 dell'SX1278 puo' essere invertito, teniamo
// due istanze e proviamo entrambi i livelli come "HIGH logico".
struct LeaderDecoder {
    uint8_t pulseLevel{0};
    uint8_t preBits[5]{};
    uint16_t preWidths[5]{};
    uint8_t preCount{0};
    bool loading{false};
    uint8_t bits[52]{};
    uint16_t widths[52]{};
    uint8_t bitCount{0};

    void clear() {
        preCount = 0;
        loading = false;
        bitCount = 0;
        memset(preBits, 0, sizeof(preBits));
        memset(preWidths, 0, sizeof(preWidths));
        memset(bits, 0, sizeof(bits));
        memset(widths, 0, sizeof(widths));
    }

    void updateProgressStat() const {
        const uint8_t progress = loading ? bitCount : preCount;
        if (pulseLevel == 0U) stats.leaderBits0 = progress;
        else stats.leaderBits1 = progress;
    }

    void resetPartial(bool countReset = true) {
        if (countReset && (loading || preCount)) stats.leaderResets++;
        clear();
        updateProgressStat();
    }

    void pushPreambleBit(uint8_t bit, uint16_t width) {
        if (preCount < 5U) {
            preBits[preCount] = bit;
            preWidths[preCount] = width;
            preCount++;
        } else {
            memmove(preBits, preBits + 1, 4U);
            memmove(preWidths, preWidths + 1, 4U * sizeof(uint16_t));
            preBits[4] = bit;
            preWidths[4] = width;
        }
    }

    bool preambleIs(uint8_t a, uint8_t b, uint8_t c, uint8_t d, uint8_t e) const {
        return preCount == 5U && preBits[0] == a && preBits[1] == b &&
               preBits[2] == c && preBits[3] == d && preBits[4] == e;
    }

    void beginNormalLeader() {
        memcpy(bits, preBits, 5U);
        memcpy(widths, preWidths, 5U * sizeof(uint16_t));
        bitCount = 5U;
        loading = true;
        stats.leaderStarts++;
        updateProgressStat();
    }

    void beginLostFirstZeroLeader() {
        // PracticalArduino accetta 00010 quando il primissimo zero non e'
        // stato catturato e inserisce il bit mancante. La sequenza canonica
        // iniziale diventa quindi 000010 (6 bit), dove i cinque bit osservati
        // corrispondono alle posizioni 1..5.
        bits[0] = 0U;
        widths[0] = stats.longPulseAverageUs ? stats.longPulseAverageUs : TECH_LONG_DEFAULT_US;
        for (uint8_t i = 0; i < 5U; ++i) {
            bits[i + 1U] = preBits[i];
            widths[i + 1U] = preWidths[i];
        }
        bitCount = 6U;
        loading = true;
        stats.leaderStarts++;
        stats.leaderLostZeroStarts++;
        updateProgressStat();
    }

    void calibrateValidFrame() const {
        for (uint8_t i = 0; i < 52U; ++i) {
            if (bits[i]) updateAverage(stats.shortPulseAverageUs, widths[i]);
            else updateAverage(stats.longPulseAverageUs, widths[i]);
        }
    }

    void finishFrame() {
        stats.leaderFrames++;
        stats.candidates++;
        uint8_t n[13]{};
        bitsToNibbles(bits, n);
        if (validateCandidate(bits, n)) {
            stats.leaderValidFrames++;
            calibrateValidFrame();
            // Short=1 / long=0 e' la polarita' documentata. hypothesis usa il
            // bit alto per il livello RF, mantenendo compatibilita' con la UI.
            const uint8_t hyp = static_cast<uint8_t>(pulseLevel * 2U);
            (void)queueFrame(n, hyp, NAN, 1U);
        } else {
            stats.leaderInvalidFrames++;
        }
        clear();
        updateProgressStat();
    }

    void feedBit(uint8_t bit, uint16_t width) {
        if (!loading) {
            pushPreambleBit(bit, width);
            if (preambleIs(0, 0, 0, 0, 1)) beginNormalLeader();
            else if (preambleIs(0, 0, 0, 1, 0)) beginLostFirstZeroLeader();
            updateProgressStat();
            return;
        }

        if (bitCount < 52U) {
            bits[bitCount] = bit;
            widths[bitCount] = width;
            bitCount++;
        }
        updateProgressStat();
        if (bitCount == 52U) finishFrame();
    }
};

LeaderDecoder leaderDecoders[2];

bool classifyLeaderPulse(uint16_t us, uint8_t &bit) {
    // PracticalArduino originale usa 300..600 us (1) e 1200..1800 us (0).
    // Il data slicer SX1278 del nostro T3 ha mostrato short ~260..300 us,
    // quindi manteniamo finestre piu' ampie senza sovrapporle.
    if (us >= TECH_SHORT_MIN_US && us <= 700U) { bit = 1U; return true; }
    if (us >= 900U && us <= 1900U) { bit = 0U; return true; }
    return false;
}

void resetLeaderDecoders(bool countReset = true) {
    leaderDecoders[0].resetPartial(countReset);
    leaderDecoders[1].resetPartial(countReset);
}

void feedLeaderDecoders(uint16_t durationUs, uint8_t previousRfLevel) {
    if (durationUs >= LACROSSE_RESET_MIN_US) {
        resetLeaderDecoders(true);
        return;
    }

    LeaderDecoder &d = leaderDecoders[previousRfLevel & 1U];
    uint8_t bit = 0;
    if (!classifyLeaderPulse(durationUs, bit)) {
        // Un periodo sul livello candidato "HIGH" che cade nella dead-zone e'
        // incompatibile con il frame WS-2300-25S. Non tocchiamo l'altra
        // polarita', che potrebbe essere quella reale.
        if (durationUs >= 50U && durationUs <= 4000U) {
            stats.leaderPulseRejects++;
            if (d.loading) d.resetPartial(true);
            else {
                d.preCount = 0;
                d.updateProgressStat();
            }
        }
        return;
    }

    d.feedBit(bit, durationUs);
}

void calibrateValidStream(const PulseStream &s) {
    for (uint8_t i = 0; i < 52U; ++i) {
        if (s.clsAt(i)) updateAverage(stats.shortPulseAverageUs, s.widthAt(i));
        else updateAverage(stats.longPulseAverageUs, s.widthAt(i));
    }
}

bool tryPulseWindow(PulseStream &s) {
    if (s.count < 52U) return false;
    stats.streamWindows++;
    stats.sequenceWindows = stats.streamWindows;

    // rtl_433 OOK_PULSE_PWM decide il bit dalla durata dell'impulso. La
    // polarita' short/long -> 0/1 puo' dipendere dal demodulatore: proviamo le
    // due ipotesi, ma il checksum rende deterministica l'accettazione.
    for (uint8_t polarity = 0; polarity < 2U; ++polarity) {
        uint8_t bits[52]{};
        for (uint8_t i = 0; i < 52U; ++i) {
            const uint8_t shortBit = s.clsAt(i);
            bits[i] = polarity == 0U ? shortBit : static_cast<uint8_t>(shortBit ^ 1U);
        }

        // Prefiltro cheap: i primi 8 bit devono essere 0x09 o 0x06.
        uint8_t first = 0;
        for (uint8_t i = 0; i < 8U; ++i) first = static_cast<uint8_t>((first << 1U) | bits[i]);
        if (first != 0x09U && first != 0x06U) continue;

        stats.streamHeaderMatches++;
        stats.sequenceHeaderMatches = stats.streamHeaderMatches;
        stats.candidates++;
        uint8_t n[13]{};
        bitsToNibbles(bits, n);
        if (!validateCandidate(bits, n)) continue;

        const uint8_t hyp = static_cast<uint8_t>(s.level * 2U + polarity);
        if (queueFrame(n, hyp)) {
            stats.streamValidFrames++;
            stats.sequenceValidFrames = stats.streamValidFrames;
            stats.sequencePulseLevel = static_cast<int8_t>(s.level);
            calibrateValidStream(s);
        }
        return true;
    }
    return false;
}

void feedPulseStream(uint16_t durationUs, uint8_t previousRfLevel) {
    if (durationUs >= LACROSSE_RESET_MIN_US) {
        stats.resetGaps++;
        stats.streamResets++;
        stats.sequenceRestarts = stats.streamResets;
        streams[0].reset();
        streams[1].reset();
        return;
    }

    if (durationUs < 50U || durationUs > 4000U) return;
    bool isShort = false;
    if (!classifyPulse(durationUs, isShort)) {
        // Non azzeriamo l'altro livello: un gap o un disturbo non deve rompere
        // la finestra del livello che rappresenta realmente gli impulsi PWM.
        stats.streamPulseRejects++;
        stats.sequencePulseRejects = stats.streamPulseRejects;
        return;
    }

    PulseStream &s = streams[previousRfLevel & 1U];
    s.append(isShort, durationUs);
    stats.streamPulses++;
    stats.sequencePairs = stats.streamPulses;
    stats.pulsePairs = stats.streamPulses;
    stats.streamBits0 = streams[0].count;
    stats.streamBits1 = streams[1].count;
    stats.lastSequenceBits0 = stats.streamBits0;
    stats.lastSequenceBits1 = stats.streamBits1;
    (void)tryPulseWindow(s);
}

bool tryBitsAndQueue(const uint8_t *classes, const uint16_t *widths, uint8_t count,
                    uint8_t pulseLevel, float rssi, bool missingEdgeRecovery) {
    if (count != 52U) return false;
    for (uint8_t polarity = 0; polarity < 2U; ++polarity) {
        uint8_t bits[52]{};
        for (uint8_t i = 0; i < 52U; ++i)
            bits[i] = polarity == 0U ? classes[i] : static_cast<uint8_t>(classes[i] ^ 1U);
        uint8_t first = 0;
        for (uint8_t i = 0; i < 8U; ++i) first = static_cast<uint8_t>((first << 1U) | bits[i]);
        if (first != 0x09U && first != 0x06U) continue;
        stats.candidates++;
        uint8_t n[13]{};
        bitsToNibbles(bits, n);
        if (!validateCandidate(bits, n)) continue;
        const uint8_t hyp = static_cast<uint8_t>(pulseLevel * 2U + polarity);
        if (queueFrame(n, hyp, rssi, 2U)) {
            stats.burstValidFrames++;
            if (missingEdgeRecovery) stats.burstRecoveredMissingEdge++;
            for (uint8_t i = 0; i < 52U; ++i) {
                if (classes[i]) updateAverage(stats.shortPulseAverageUs, widths[i]);
                else updateAverage(stats.longPulseAverageUs, widths[i]);
            }
        }
        return true;
    }
    return false;
}

bool tryBurstPulseList(const uint16_t *pulseWidths, uint8_t pulseCount,
                       uint8_t pulseLevel, float rssi) {
    if (pulseCount < 50U || pulseCount > 60U) return false;
    uint8_t cls[60]{};
    for (uint8_t i = 0; i < pulseCount; ++i) {
        bool isShort = false;
        if (!classifyPulse(pulseWidths[i], isShort)) return false;
        cls[i] = isShort ? 1U : 0U;
    }

    // Caso normale: almeno 52 impulsi, prova tutte le finestre consecutive.
    if (pulseCount >= 52U) {
        for (uint8_t start = 0; start + 52U <= pulseCount; ++start) {
            stats.burstWindows++;
            if (tryBitsAndQueue(cls + start, pulseWidths + start, 52U, pulseLevel, rssi, false)) return true;
        }
    }

    // Il primo intervallo dopo un lungo silenzio puo' essere il reset OFF e
    // quindi il burst catturato puo' contenere soltanto 51 impulsi. Ricostruiamo
    // un singolo bit mancante all'inizio o alla fine e lasciamo decidere al MIC.
    if (pulseCount == 51U) {
        uint8_t c52[52]{};
        uint16_t w52[52]{};
        for (uint8_t bit = 0; bit < 2U; ++bit) {
            c52[0] = bit;
            w52[0] = bit ? (stats.shortPulseAverageUs ? stats.shortPulseAverageUs : TECH_SHORT_DEFAULT_US)
                         : (stats.longPulseAverageUs ? stats.longPulseAverageUs : TECH_LONG_DEFAULT_US);
            memcpy(c52 + 1, cls, 51U);
            memcpy(w52 + 1, pulseWidths, 51U * sizeof(uint16_t));
            stats.burstWindows++;
            if (tryBitsAndQueue(c52, w52, 52U, pulseLevel, rssi, true)) return true;

            memcpy(c52, cls, 51U);
            memcpy(w52, pulseWidths, 51U * sizeof(uint16_t));
            c52[51] = bit;
            w52[51] = w52[0];
            stats.burstWindows++;
            if (tryBitsAndQueue(c52, w52, 52U, pulseLevel, rssi, true)) return true;
        }
    }
    return false;
}

uint8_t msgType(const uint8_t n[13]) {
    return static_cast<uint8_t>(((n[2] >> 1U) & 0x4U) + (n[2] & 0x3U));
}

} // namespace

void resetLaCrosseDecoderState() {
    queueHead = queueTail = 0;
    streams[0] = PulseStream{}; streams[0].level = 0;
    streams[1] = PulseStream{}; streams[1].level = 1;
    streams[0].reset(); streams[1].reset();
    leaderDecoders[0] = LeaderDecoder{}; leaderDecoders[0].pulseLevel = 0;
    leaderDecoders[1] = LeaderDecoder{}; leaderDecoders[1].pulseLevel = 1;
    leaderDecoders[0].clear(); leaderDecoders[1].clear();
    stats.activeHypothesis = -1;
}

void initLaCrosseWs23xx() {
    stats = LaCrosseRxStats{};
    resetLaCrosseDecoderState();
}

void processLaCrosseEdge(uint16_t durationUs, uint8_t previousRfLevel) {
#if LACROSSE_WS23XX_ENABLE
    stats.edgesSeen++;
    accountIntervalBin(durationUs);
    // Due decoder live in parallelo: il pulse-window rtl_433-style e la state
    // machine PracticalArduino con leader 00001. Entrambi sono leggeri e
    // condividono la stessa validazione MIC prima di accodare un frame.
    feedLeaderDecoders(durationUs, previousRfLevel & 1U);
    feedPulseStream(durationUs, previousRfLevel & 1U);
#else
    (void)durationUs; (void)previousRfLevel;
#endif
}

bool processLaCrosseBurst(const uint16_t *durations, const uint8_t *levels,
                          uint16_t count, float rssi) {
#if LACROSSE_WS23XX_ENABLE
    if (!durations || !levels || count < 80U) { stats.burstTooShort++; return false; }
    stats.burstAttempts++;
    stats.lastBurstIntervals = count;

    bool recovered = false;
    for (uint8_t pulseLevel = 0; pulseLevel < 2U && !recovered; ++pulseLevel) {
        uint16_t pulses[60]{};
        uint8_t pc = 0;
        uint32_t gapSum = 0;
        uint16_t gapCount = 0;
        for (uint16_t i = 0; i < count; ++i) {
            const uint16_t us = durations[i];
            const uint8_t level = levels[i] & 1U;
            if (level == pulseLevel && pulsePlausible(us)) {
                if (pc < 60U) pulses[pc++] = us;
            } else if (level != pulseLevel && us >= TECH_GAP_MIN_US && us <= TECH_GAP_MAX_US) {
                gapSum += us;
                gapCount++;
            }
        }
        if (pulseLevel == 0U) stats.lastBurstPulseCount0 = pc;
        else stats.lastBurstPulseCount1 = pc;
        if (gapCount) updateAverage(stats.gapAverageUs, static_cast<uint16_t>(gapSum / gapCount));
        recovered = tryBurstPulseList(pulses, pc, pulseLevel, rssi);
        if (recovered) stats.burstPulseLevel = static_cast<int8_t>(pulseLevel);
    }
    if (!recovered) stats.burstRejects++;
    stats.burstPulseWindows = stats.burstWindows;
    return recovered;
#else
    (void)durations; (void)levels; (void)count; (void)rssi;
    return false;
#endif
}

bool getLaCrossePacket(LaCrossePacket &packet) {
    if (queueTail == queueHead) return false;
    packet = packetQueue[queueTail];
    queueTail = static_cast<uint8_t>((queueTail + 1U) % QUEUE_SIZE);
    return true;
}

bool parseLaCrossePacket(const LaCrossePacket &packet, LaCrosseReading &reading) {
    reading = LaCrosseReading{};
    const uint8_t *n = packet.nibbles;
    if (n[0] != 0 || (n[1] != 9 && n[1] != 6)) return false;

    reading.wsId = static_cast<uint8_t>((n[0] << 4U) | n[1]);
    reading.sensorId = static_cast<uint8_t>((n[3] << 4U) | n[4]);
    reading.dataFlags = n[5];
    reading.updateFlags = n[6];
    reading.nextUpdateCode = static_cast<uint8_t>((n[6] >> 1U) & 0x03U);
    reading.receivedAtMs = packet.receivedAtMs;
    reading.rssi = packet.rssi;

    const uint8_t type = msgType(n);
    const int valueBcd = static_cast<int>(n[7]) * 100 + static_cast<int>(n[8]) * 10 + n[9];
    const int valueBcd2 = static_cast<int>(n[7]) * 10 + n[8];
    const int valueBin = static_cast<int>(n[7]) * 256 + static_cast<int>(n[8]) * 16 + n[9];

    switch (type) {
        case 0: {
            reading.type = LaCrosseType::Temperature;
            const float offset = (reading.wsId == 0x06U) ? 400.0f : 300.0f;
            const float t = (static_cast<float>(valueBcd) - offset) * 0.1f;
            if (t < -60.0f || t > 80.0f) return false;
            reading.temperatureC = t;
            reading.temperatureValid = true;
            stats.temperatureFrames++;
            return true;
        }
        case 1:
            reading.type = LaCrosseType::Humidity;
            if (n[7] == 0xAU && n[8] == 0xAU) return false;
            if (valueBcd2 < 0 || valueBcd2 > 100) return false;
            reading.humidityPct = static_cast<float>(valueBcd2);
            reading.humidityValid = true;
            stats.humidityFrames++;
            return true;
        case 2:
            reading.type = LaCrosseType::Rain;
            reading.rainTotalMm = 0.5180f * static_cast<float>(valueBin);
            if (reading.rainTotalMm < 0.0f || reading.rainTotalMm > 100000.0f) return false;
            reading.rainValid = true;
            stats.rainFrames++;
            return true;
        case 3:
        case 7: {
            const float speedMs = static_cast<float>(n[7] * 16U + n[8]) * 0.1f;
            if (n[7] == 0xFU && n[8] == 0xEU) return false;
            if (speedMs < 0.0f || speedMs > 100.0f || n[9] > 15U) return false;
            reading.directionIndex = n[9];
            reading.directionDeg = static_cast<float>(n[9]) * 22.5f;
            reading.directionValid = true;
            if (type == 3) {
                reading.type = LaCrosseType::Wind;
                reading.windKmh = speedMs * 3.6f;
                reading.windValid = true;
                stats.windFrames++;
            } else {
                reading.type = LaCrosseType::Gust;
                reading.gustKmh = speedMs * 3.6f;
                reading.gustValid = true;
                stats.gustFrames++;
            }
            return true;
        }
        default:
            reading.type = LaCrosseType::Unknown;
            return false;
    }
}

LaCrosseRxStats getLaCrosseRxStats() { return stats; }

const char *laCrosseTypeName(LaCrosseType type) {
    switch (type) {
        case LaCrosseType::Temperature: return "temperature";
        case LaCrosseType::Humidity: return "humidity";
        case LaCrosseType::Rain: return "rain";
        case LaCrosseType::Wind: return "wind";
        case LaCrosseType::Gust: return "gust";
        default: return "unknown";
    }
}

const char *laCrosseModelName(uint8_t wsId) {
    return wsId == 0x06U ? "WS-3600 compatible" : "Technoline WS230x / LaCrosse WS-2310";
}

const char *laCrosseWindDirectionName(uint8_t index) {
    static const char *dirs[16] = {
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
    };
    return dirs[index & 0x0FU];
}

const char *laCrosseNextUpdateName(uint8_t code) {
    switch (code & 0x03U) {
        case 0: return "8s";
        case 1: return "32s";
        case 3: return "128s";
        default: return "N/D";
    }
}

uint32_t laCrosseNextUpdateMs(uint8_t code) {
    switch (code & 0x03U) {
        case 0: return 8000UL;
        case 1: return 32000UL;
        case 3: return 128000UL;
        default: return 0UL;
    }
}
