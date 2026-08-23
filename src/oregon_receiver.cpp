#include "oregon_receiver.h"
#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <driver/gpio.h>
#include <Preferences.h>
#include "board_config.h"
#include "config.h"
#include "lacrosse_ws23xx.h"

namespace {

SX1278 radio = new Module(RADIO_CS_PIN, RADIO_DIO0_PIN, RADIO_RST_PIN, RADIO_DIO1_PIN);

constexpr uint8_t PACKET_QUEUE_SIZE = 6;
OregonPacket packetQueue[PACKET_QUEUE_SIZE];
uint8_t packetHead = 0;
uint8_t packetTail = 0;

OregonRxStats stats{};
String lastError;
Preferences rfPrefs;

bool prefPutUCharIfChanged(Preferences &p, const char *key, uint8_t value) {
    const uint8_t old = p.getUChar(key, 0xFFU);
    if (old == value) return true;
    p.putUChar(key, value);
    const bool ok = p.getUChar(key, 0xFFU) == value;
    if (!ok) Serial.printf("[RF] NVS verify KO key=%s\n", key);
    return ok;
}

bool prefPutUShortIfChanged(Preferences &p, const char *key, uint16_t value) {
    const uint16_t old = p.getUShort(key, 0xFFFFU);
    if (old == value) return true;
    p.putUShort(key, value);
    const bool ok = p.getUShort(key, 0xFFFFU) == value;
    if (!ok) Serial.printf("[RF] NVS verify KO key=%s\n", key);
    return ok;
}

bool prefPutBoolIfChanged(Preferences &p, const char *key, bool value) {
    const bool old = p.getBool(key, false);
    if (old == value) return true;
    p.putBool(key, value);
    const bool ok = p.getBool(key, !value) == value;
    if (!ok) Serial.printf("[RF] NVS verify KO key=%s\n", key);
    return ok;
}
RfProtocolMode rfMode = RfProtocolMode::Oregon;
bool burstExtraEnabled = false;
uint8_t gainOregon = OREGON_RX_GAIN;
uint8_t gainLaCrosse = OREGON_RX_GAIN;
uint8_t currentGain = OREGON_RX_GAIN;
float bandwidthOregon = OREGON_RX_BW_KHZ;
float bandwidthLaCrosse = OREGON_RX_BW_KHZ;
float currentBandwidth = OREGON_RX_BW_KHZ;
RfFrontendProfile currentFrontendProfile = RfFrontendProfile::Stable;
bool radioReady = false;

constexpr uint8_t BURST_HISTORY_SIZE = 24;
constexpr uint16_t BURST_EDGE_BUFFER_SIZE = 384;
constexpr uint32_t BURST_GAP_US = 5000UL;
constexpr uint16_t BURST_MIN_EDGES = 24;
constexpr uint16_t BURST_OSV3_MIN_MS = 55;
constexpr uint16_t BURST_OSV3_MAX_MS = 170;
constexpr uint8_t BURST_OSV3_MIN_MATCH_PCT = 55;
constexpr uint32_t AUTO_PROFILE_STEP_MS = 45000UL;

RfBurstRecord burstHistory[BURST_HISTORY_SIZE]{};
uint8_t burstHistoryHead = 0;
uint8_t burstHistoryCount = 0;
RfBurstAnalyzerStats burstStats{};

struct BurstAccumulator {
    bool active{false};
    uint32_t durationUs{0};
    uint16_t edges{0};
    uint16_t timingValid{0};
    uint32_t onShortSum{0}; uint16_t onShortCount{0};
    uint32_t onLongSum{0}; uint16_t onLongCount{0};
    uint32_t offShortSum{0}; uint16_t offShortCount{0};
    uint32_t offLongSum{0}; uint16_t offLongCount{0};
    float rssi{NAN};
    uint16_t storedEdges{0};
    uint16_t durations[BURST_EDGE_BUFFER_SIZE]{};
    uint8_t levels[BURST_EDGE_BUFFER_SIZE]{};

    void reset() {
        active = false; durationUs = 0; edges = 0; timingValid = 0;
        onShortSum = onShortCount = onLongSum = onLongCount = 0;
        offShortSum = offShortCount = offLongSum = offLongCount = 0;
        rssi = NAN; storedEdges = 0;
    }
};
BurstAccumulator burstCurrent{};

// -----------------------------------------------------------------------------
// V6.3 - WGR800 1984 RF Probe
//
// Sonda diagnostica separata dai decoder. Serve a distinguere:
//  1) portante/burst OSV3 presente ma frame non ricostruito;
//  2) burst RF realmente assente.
//
// Non salva nulla in NVS, e' OFF al boot e quando e' OFF non esegue lavoro
// aggiuntivo sul flusso RF.
// -----------------------------------------------------------------------------
constexpr uint8_t WGR_PROBE_HISTORY_SIZE = 24;
constexpr uint32_t WGR_PROBE_GAP_US = 5000UL;
constexpr uint16_t WGR_PROBE_MIN_EDGES = 24;
constexpr uint16_t WGR_PROBE_OSV3_MIN_MS = 55;
constexpr uint16_t WGR_PROBE_OSV3_MAX_MS = 170;
constexpr uint8_t WGR_PROBE_OSV3_MIN_MATCH_PCT = 55;
constexpr uint32_t WGR_CADENCE_MIN_MS = 11000UL;
constexpr uint32_t WGR_CADENCE_MAX_MS = 17000UL;

bool wgrProbeOn = false;
WgrProbeStats wgrProbeStats{};
WgrProbeRecord wgrProbeHistory[WGR_PROBE_HISTORY_SIZE]{};
uint8_t wgrProbeHistoryHead = 0;
uint8_t wgrProbeHistoryCount = 0;
uint32_t wgrProbeLastCandidateMs = 0;

struct WgrProbeAccumulator {
    bool active{false};
    uint32_t durationUs{0};
    uint16_t edges{0};
    uint16_t timingValid{0};
    float rssi{NAN};
    uint8_t decodedHeader{0};

    void reset() {
        active = false;
        durationUs = 0;
        edges = 0;
        timingValid = 0;
        rssi = NAN;
        decodedHeader = 0;
    }
};
WgrProbeAccumulator wgrProbeCurrent{};

void resetWgrProbeStatsInternal() {
    const bool enabled = wgrProbeOn;
    wgrProbeStats = WgrProbeStats{};
    wgrProbeStats.enabled = enabled;
    memset(wgrProbeHistory, 0, sizeof(wgrProbeHistory));
    wgrProbeHistoryHead = 0;
    wgrProbeHistoryCount = 0;
    wgrProbeLastCandidateMs = 0;
    wgrProbeCurrent.reset();
}

void noteWgrProbeDecodedHeader(uint8_t header) {
    if (!wgrProbeOn || !wgrProbeCurrent.active) return;
    if (header == 0xAF || header == 0xA1 || header == 0xA2 || header == 0xAD) {
        wgrProbeCurrent.decodedHeader = header;
    }
}


uint8_t lastQueuedBytes[OREGON_MAX_PACKET_BYTES]{};
uint8_t lastQueuedLen = 0;
uint32_t lastQueuedMs = 0;

// La tabella riproduce l'ordinamento nibble/bit del decoder Oregon legacy.
constexpr uint8_t OREGON_BIT_MASK[8] = {16, 32, 64, 128, 1, 2, 4, 8};

bool validateFrameChecksumRaw(const uint8_t *bytes, uint8_t len);
uint16_t rawSensorCode(const uint8_t *bytes);

uint8_t expectedLengthForSensor(uint8_t id) {
    switch (id) {
        case 0xAF: return 9;   // THGN800 Thermo/Hygro
        case 0xA1: return 10;  // WGR800 Wind
        case 0xA2: return 11;  // PCR800 Rain
        case 0xAD: return 8;   // UVN800
        case 0xA3: return 10;  // estensione legacy/experimental
        default: return 0;
    }
}

bool queuePacket(const uint8_t *data, uint8_t len, OregonDecodeSource source) {
    const uint32_t nowMs = millis();
    // Per la sonda WGR etichettiamo il burst soltanto se il frame Oregon
    // supera gia' il checksum. La coda/parser normale resta invariata.
    if (wgrProbeOn && validateFrameChecksumRaw(data, len)) {
        noteWgrProbeDecodedHeader(data[0]);
    }
    if (len == lastQueuedLen && static_cast<uint32_t>(nowMs - lastQueuedMs) < 120U &&
        memcmp(lastQueuedBytes, data, len) == 0) {
        stats.duplicateFrames++;
        return false;
    }

    const uint8_t next = static_cast<uint8_t>((packetHead + 1U) % PACKET_QUEUE_SIZE);
    if (next == packetTail) {
        stats.framesDropped++;
        return false;
    }

    OregonPacket &p = packetQueue[packetHead];
    memset(p.bytes, 0, sizeof(p.bytes));
    memcpy(p.bytes, data, len);
    p.length = len;
    p.receivedAtMs = nowMs;
    // In direct mode leggiamo il valore corrente senza forzare una nuova receive().
    p.rssi = radio.getRSSI(false, true);
    p.decodeSource = static_cast<uint8_t>(source);
    packetHead = next;
    memcpy(lastQueuedBytes, data, len);
    lastQueuedLen = len;
    lastQueuedMs = nowMs;

    stats.framesDetected++;
    if (source == OregonDecodeSource::EdgeTiming) stats.edgeFrames++;
    if (source == OregonDecodeSource::EdgeTimingWeak) stats.weakEdgeFrames++;
    if (source == OregonDecodeSource::EdgeTimingState) stats.stateEdgeFrames++;
    if (source == OregonDecodeSource::BurstAdaptive) stats.burstAdaptiveFrames++;
    if (source == OregonDecodeSource::ClockSync) stats.clockFrames++;
    if (source == OregonDecodeSource::EdgeTimingV21) stats.v21Frames++;

    if (source == OregonDecodeSource::EdgeTimingV21) {
        switch (rawSensorCode(data)) {
            case 0x3D00U: stats.rawWindFrames++; break;
            case 0x2D10U: stats.rawRainFrames++; break;
            case 0xEC70U:
                stats.rawUvFrames++;
                stats.v21UvFrames++;
                break;
            default: stats.rawThermoFrames++; break;
        }
    } else {
        switch (data[0]) {
            case 0xAF: stats.rawThermoFrames++; break;
            case 0xA1: stats.rawWindFrames++; break;
            case 0xA2: stats.rawRainFrames++; break;
            case 0xAD: stats.rawUvFrames++; break;
            default: break;
        }
    }
    return true;
}

void rememberUnknownHeader(uint8_t header, bool weak) {
    if (weak) {
        stats.weakUnknownHeaders++;
        stats.lastWeakUnknownHeader = header;
    } else {
        stats.unknownHeaders++;
        stats.lastUnknownHeader = header;
    }
}

void updateAverage(uint16_t &average, uint16_t value) {
    if (average == 0) {
        average = value;
    } else {
        average = static_cast<uint16_t>((static_cast<uint32_t>(average) * 7U + value) / 8U);
    }
}

#if OREGON_RAW_EDGE_MODE

// -----------------------------------------------------------------------------
// V4.3: decoder OSV3 basato sugli intervalli tra i fronti DIO2.
// RadioLib mette SX1278 in continuous/direct RX e il bit synchronizer viene
// disabilitato. DIO2 espone quindi il dato OOK da cui misuriamo gli intervalli.
// -----------------------------------------------------------------------------

constexpr uint16_t EDGE_RING_SIZE = 4096; // power of two
constexpr uint16_t EDGE_RING_MASK = EDGE_RING_SIZE - 1;
volatile uint16_t edgeDurationRing[EDGE_RING_SIZE];
volatile uint8_t edgeLevelRing[EDGE_RING_SIZE];
volatile uint16_t edgeHead = 0;
volatile uint16_t edgeTail = 0;
volatile uint32_t isrEdgeCount = 0;
volatile uint32_t isrOverflowCount = 0;
volatile uint32_t lastEdgeUs = 0;
volatile bool edgePrimed = false;

struct EdgeDecoder {
    bool decoding{false};
    uint16_t preambleShorts{0};
    bool shortPending{false};
    uint8_t lastBit{1};
    uint8_t bytes[OREGON_MAX_PACKET_BYTES]{};
    uint8_t byteIndex{0};
    uint8_t bitIndex{0};
    uint8_t expectedBytes{0};

    void clearFrame() {
        shortPending = false;
        lastBit = 1;
        byteIndex = 0;
        bitIndex = 0;
        expectedBytes = 0;
        memset(bytes, 0, sizeof(bytes));
    }

    void resetSearch() {
        decoding = false;
        preambleShorts = 0;
        clearFrame();
    }
};

EdgeDecoder strongDecoder;

// WGR800 recovery V4.8: scanner Manchester scorrevole dedicato al solo A1.
// Non modifica la soglia o il framing del decoder strong. Ricostruisce un
// flusso di bit anche quando il preambolo WGR800 e' corto/troncato e cerca
// una finestra completa di 80 bit che inizi con A1 (o con la sua polarita
// invertita). Il frame viene accodato SOLO se supera gia' qui il checksum
// OSV3, quindi il percorso aggressivo non puo' inquinare AF/A2/AD.
constexpr uint8_t WIND_SCAN_BITS = 80;
constexpr uint8_t WIND_SCAN_PHASES = 2;

struct WindSlidingScanner {
    bool phaseShift{false};
    bool shortPending{false};
    bool fresh{true};
    uint8_t lastBit{0};
    uint8_t bits[WIND_SCAN_BITS]{};
    uint8_t head{0};
    uint8_t count{0};

    void reset() {
        shortPending = phaseShift;
        fresh = true;
        lastBit = 0;
        head = 0;
        count = 0;
        memset(bits, 0, sizeof(bits));
    }
};

WindSlidingScanner windScan[WIND_SCAN_PHASES];

enum class IntervalKind : uint8_t { Invalid = 0, Short, Long };

// Decoder parallelo V4.8: usa lo stato RF precedente al fronte e il metodo
// half-time descritto nel documento Oregon Scientific RF Protocols. Il vecchio
// decoder V4.3 resta attivo come fallback, quindi questa logica puo' solo
// aumentare i frame recuperati senza togliere quelli gia' stabili.
struct StateAwareDecoder {
    bool invertLevel{false};
    bool decoding{false};
    bool haveSearchLevel{false};
    uint8_t lastSearchLevel{0};
    uint16_t preambleShorts{0};
    uint16_t halfTime{0};
    uint8_t bytes[OREGON_MAX_PACKET_BYTES]{};
    uint8_t byteIndex{0};
    uint8_t bitIndex{0};
    uint8_t expectedBytes{0};

    void clearFrame() {
        halfTime = 0;
        byteIndex = 0;
        bitIndex = 0;
        expectedBytes = 0;
        memset(bytes, 0, sizeof(bytes));
    }

    void resetSearch() {
        decoding = false;
        haveSearchLevel = false;
        lastSearchLevel = 0;
        preambleShorts = 0;
        clearFrame();
    }
};

StateAwareDecoder stateDecoder[2];

// OS V2.1 usa gli stessi timing di base di V3 ma un framing differente:
// 16 bit logici di preambolo diventano 32 bit fisici alternati e ogni bit
// successivo e' inviato come coppia [inverso, originale]. Il decoder valida
// ogni coppia prima di conservare il secondo bit.
struct Osv21Decoder {
    bool decoding{false};
    uint16_t preambleLongs{0};
    bool shortPending{false};
    uint8_t lastPhysicalBit{1};
    bool havePairFirst{false};
    uint8_t pairFirst{0};
    uint8_t bytes[OREGON_MAX_PACKET_BYTES]{};
    uint16_t decodedBits{0};
    uint16_t expectedBits{0};
    uint8_t expectedBytes{0};

    void clearFrame() {
        shortPending = false;
        lastPhysicalBit = 1;
        havePairFirst = false;
        pairFirst = 0;
        decodedBits = 0;
        expectedBits = 0;
        expectedBytes = 0;
        memset(bytes, 0, sizeof(bytes));
    }

    void resetSearch() {
        decoding = false;
        preambleLongs = 0;
        clearFrame();
    }
};

Osv21Decoder osv21Decoder;

uint16_t diff16(uint16_t a, uint16_t b) {
    return (a > b) ? static_cast<uint16_t>(a - b) : static_cast<uint16_t>(b - a);
}

IntervalKind classifyInterval(uint16_t dtUs) {
    if (dtUs < OREGON_EDGE_MIN_US || dtUs > OREGON_EDGE_MAX_US) return IntervalKind::Invalid;

    // OSV3 reale presenta durate diverse per ON/OFF; teniamo tre centri per
    // short e long invece di una soglia unica. E' la strategia che ha gia'
    // funzionato con i frame AF/A2/AD reali.
    const uint16_t shortExpected[] = {349, 488, 628};
    const uint16_t longExpected[]  = {837, 977, 1116};

    uint16_t shortError = 0xFFFF;
    uint16_t longError = 0xFFFF;
    for (uint16_t expected : shortExpected) {
        const uint16_t e = diff16(dtUs, expected);
        if (e < shortError) shortError = e;
    }
    for (uint16_t expected : longExpected) {
        const uint16_t e = diff16(dtUs, expected);
        if (e < longError) longError = e;
    }

    const uint16_t best = (shortError < longError) ? shortError : longError;
    if (best > OREGON_EDGE_MAX_TIMING_ERROR_US) return IntervalKind::Invalid;
    return (shortError <= longError) ? IntervalKind::Short : IntervalKind::Long;
}

uint8_t checksumPositionForRawHeader(uint8_t header) {
    switch (header) {
        case 0xAF: return 16;
        case 0xA1: return 18;
        case 0xA2: return 19;
        case 0xAD: return 14;
        case 0xA3: return 18;
        default: return 0;
    }
}

uint8_t rawNybble(const uint8_t *bytes, uint8_t index) {
    const uint8_t b = bytes[index / 2U];
    return (index % 2U == 0U) ? static_cast<uint8_t>(b >> 4U)
                               : static_cast<uint8_t>(b & 0x0FU);
}

bool validateFrameChecksumRaw(const uint8_t *bytes, uint8_t len) {
    if (!bytes || len == 0) return false;
    const uint8_t csPos = checksumPositionForRawHeader(bytes[0]);
    if (csPos == 0 || static_cast<uint8_t>(csPos + 2U) > len * 2U) return false;
    uint8_t calculated = 0;
    for (uint8_t i = 1; i < csPos; ++i) calculated = static_cast<uint8_t>(calculated + rawNybble(bytes, i));
    const uint8_t received = static_cast<uint8_t>((rawNybble(bytes, csPos + 1U) << 4U) | rawNybble(bytes, csPos));
    return calculated == received;
}

bool validateFrameChecksumAt(const uint8_t *bytes, uint8_t len, uint8_t csPos) {
    if (!bytes || len == 0 || csPos == 0 || static_cast<uint8_t>(csPos + 2U) > len * 2U) return false;
    uint8_t calculated = 0;
    for (uint8_t i = 1; i < csPos; ++i) calculated = static_cast<uint8_t>(calculated + rawNybble(bytes, i));
    const uint8_t received = static_cast<uint8_t>((rawNybble(bytes, csPos + 1U) << 4U) | rawNybble(bytes, csPos));
    return calculated == received;
}

uint16_t rawSensorCode(const uint8_t *bytes) {
    return static_cast<uint16_t>((rawNybble(bytes, 1) << 12U) |
                                 (rawNybble(bytes, 2) << 8U) |
                                 (rawNybble(bytes, 3) << 4U) |
                                  rawNybble(bytes, 4));
}

uint8_t expectedLengthForV21(uint8_t header) {
    switch (header) {
        case 0xAEU: return 8U;  // EC40 temperatura oppure EC70 UV
        case 0xA1U: return 9U;  // 1D20/1D30 termo-igrometro
        case 0xA2U: return 10U; // 2D10 RGR968 pioggia
        case 0xA3U: return 10U; // 3D00 WGR968 vento
        default: return 0U;
    }
}

uint8_t checksumPositionForV21(uint16_t sensorCode) {
    if (sensorCode == 0xEC40U) return 13U;
    if (sensorCode == 0xEC70U) return 13U;
    if (sensorCode == 0x1D20U) return 16U;
    if (sensorCode == 0x1D30U) return 16U;
    if (sensorCode == 0x2D10U) return 17U;
    if (sensorCode == 0x3D00U) return 18U;
    return 0U;
}

IntervalKind classifyStateInterval(uint16_t dtUs, uint8_t rfLevel) {
    // Soglie medie documentate per OS v2.1/v3.0. In V3 gli ideali sono:
    // ON 349/837 us, OFF 628/1116 us. I range sottostanti sono quelli
    // raccomandati nel documento e tengono conto dell'accorciamento degli impulsi.
    if (rfLevel) {
        if (dtUs >= OREGON_STATE_ON_SHORT_MIN_US && dtUs < OREGON_STATE_ON_SHORT_MAX_US) return IntervalKind::Short;
        if (dtUs >= OREGON_STATE_ON_LONG_MIN_US  && dtUs <= OREGON_STATE_ON_LONG_MAX_US) return IntervalKind::Long;
    } else {
        if (dtUs >= OREGON_STATE_OFF_SHORT_MIN_US && dtUs < OREGON_STATE_OFF_SHORT_MAX_US) return IntervalKind::Short;
        if (dtUs >= OREGON_STATE_OFF_LONG_MIN_US  && dtUs <= OREGON_STATE_OFF_LONG_MAX_US) return IntervalKind::Long;
    }
    return IntervalKind::Invalid;
}


uint16_t avg16(uint32_t sum, uint16_t count) {
    return count ? static_cast<uint16_t>(sum / count) : 0;
}

// -----------------------------------------------------------------------------
// V5.6 - Burst Adaptive Decoder
// -----------------------------------------------------------------------------
// I decoder V4.8 lavorano in streaming e restano invariati. Questo percorso
// viene eseguito SOLO alla fine di un burst RF completo. Prova a ricostruire il
// messaggio usando i timing locali del singolo trasmettitore e cerca una
// finestra AF/A1/A2/AD con checksum valido. Non richiede di agganciare il
// preambolo: e' quindi utile quando il data slicer tronca il preambolo o quando
// il primo fronte viene perso. Un frame entra nella coda solo dopo checksum.

uint16_t adaptiveCenter(uint16_t measured, uint16_t ideal, uint16_t minOk, uint16_t maxOk) {
    return (measured >= minOk && measured <= maxOk) ? measured : ideal;
}

IntervalKind classifyAdaptiveBurstInterval(uint16_t dtUs, uint8_t rawLevel,
                                           const RfBurstRecord &rec,
                                           bool invertLevel) {
    if (dtUs < 120U || dtUs > 1650U) return IntervalKind::Invalid;
    const uint8_t level = static_cast<uint8_t>((rawLevel ^ (invertLevel ? 1U : 0U)) & 1U);

    uint16_t shortC = 0, longC = 0;
    if (level) {
        shortC = adaptiveCenter(rec.onShortUs, 349U, 180U, 680U);
        longC  = adaptiveCenter(rec.onLongUs,  837U, 560U, 1180U);
    } else {
        shortC = adaptiveCenter(rec.offShortUs, 628U, 300U, 900U);
        longC  = adaptiveCenter(rec.offLongUs, 1116U, 760U, 1500U);
    }

    const uint16_t ds = diff16(dtUs, shortC);
    const uint16_t dl = diff16(dtUs, longC);
    const uint16_t best = ds <= dl ? ds : dl;
    // Deliberatamente permissivo: la vera protezione e' il checksum OSV3.
    // Il limite evita soltanto che gap o spurie molto lontane diventino bit.
    if (best > 430U) return IntervalKind::Invalid;
    return ds <= dl ? IntervalKind::Short : IntervalKind::Long;
}

bool decodeAdaptiveFromStart(const BurstAccumulator &burst, const RfBurstRecord &rec,
                             uint16_t startIndex, uint8_t initialBit,
                             bool invertLevel, bool &checksumCandidate) {
    uint8_t frame[OREGON_MAX_PACKET_BYTES]{};
    uint8_t byteIndex = 0;
    uint8_t bitIndex = 0;
    uint8_t expectedBytes = 0;
    uint8_t lastBit = initialBit & 1U;
    uint16_t i = startIndex;

    while (i < burst.storedEdges && byteIndex < OREGON_MAX_PACKET_BYTES) {
        const IntervalKind k = classifyAdaptiveBurstInterval(
            burst.durations[i], burst.levels[i], rec, invertLevel);
        uint8_t bit = lastBit;

        if (k == IntervalKind::Long) {
            lastBit ^= 1U;
            bit = lastBit;
            i++;
        } else if (k == IntervalKind::Short) {
            if (static_cast<uint16_t>(i + 1U) >= burst.storedEdges) return false;
            const IntervalKind k2 = classifyAdaptiveBurstInterval(
                burst.durations[i + 1U], burst.levels[i + 1U], rec, invertLevel);
            if (k2 != IntervalKind::Short) return false;
            bit = lastBit;
            i = static_cast<uint16_t>(i + 2U);
        } else {
            return false;
        }

        if (bit) frame[byteIndex] |= OREGON_BIT_MASK[bitIndex];
        bitIndex++;
        if (bitIndex < 8U) continue;

        bitIndex = 0;
        byteIndex++;
        if (byteIndex == 1U) {
            expectedBytes = expectedLengthForSensor(frame[0]);
            if (expectedBytes == 0U || expectedBytes > OREGON_MAX_PACKET_BYTES) return false;
        }

        if (expectedBytes != 0U && byteIndex >= expectedBytes) {
            burstStats.adaptiveCandidates++;
            checksumCandidate = true;
            if (!validateFrameChecksumRaw(frame, expectedBytes)) {
                burstStats.adaptiveChecksumFail++;
                return false;
            }

            // Se il decoder streaming ha gia' accodato lo stesso frame,
            // queuePacket() lo riconosce come duplicato. In quel caso questa
            // scansione ha comunque validato il burst, ma non viene contato
            // come "recuperato".
            const bool queued = queuePacket(frame, expectedBytes, OregonDecodeSource::BurstAdaptive);
            if (queued) {
                burstStats.adaptiveRecovered++;
                switch (frame[0]) {
                    case 0xAF: stats.burstAdaptiveThermo++; break;
                    case 0xA1: stats.burstAdaptiveWind++; break;
                    case 0xA2: stats.burstAdaptiveRain++; break;
                    case 0xAD: stats.burstAdaptiveUv++; break;
                    default: break;
                }
            }
            return true;
        }
    }
    return false;
}

bool tryAdaptiveBurstDecode(const RfBurstRecord &rec) {
    if (burstCurrent.storedEdges < 60U || burstCurrent.storedEdges > BURST_EDGE_BUFFER_SIZE) return false;
    if (rec.durationMs < 55U || rec.durationMs > 180U) return false;

    burstStats.adaptiveAttempts++;
    // Ogni intervallo puo' essere l'inizio del primo simbolo del payload.
    // Proviamo entrambe le polarita' del livello usato per scegliere i centri
    // ON/OFF e i due possibili valori del bit precedente.
    const uint16_t lastStart = burstCurrent.storedEdges > 12U
        ? static_cast<uint16_t>(burstCurrent.storedEdges - 12U) : 0U;
    for (uint8_t inv = 0; inv < 2U; ++inv) {
        for (uint8_t initial = 0; initial < 2U; ++initial) {
            for (uint16_t start = 0; start < lastStart; ++start) {
                bool checksumCandidate = false;
                const uint32_t before = burstStats.adaptiveRecovered;
                if (decodeAdaptiveFromStart(burstCurrent, rec, start, initial, inv != 0, checksumCandidate)) {
                    return burstStats.adaptiveRecovered != before;
                }
            }
        }
    }
    return false;
}

bool looksLikeTechnolineBurst(const RfBurstRecord &rec) {
    // Impronta osservata sul tuo impianto mentre Oregon e Technoline sono
    // entrambi in aria: burst ~110-120 ms, ~100 fronti, basso match OSV3.
    // Non viene usata per accettare dati: serve solo come diagnostica.
    return rec.durationMs >= 80U && rec.durationMs <= 150U &&
           rec.edges >= 80U && rec.edges <= 150U &&
           rec.timingMatchPct <= 55U;
}

void finalizeRfBurst() {
    if (!burstCurrent.active) return;
    if (burstCurrent.edges < BURST_MIN_EDGES) {
        burstStats.discardedBursts++;
        burstCurrent.reset();
        return;
    }

    RfBurstRecord rec{};
    rec.endedAtMs = millis();
    const uint32_t durationMs32 = (burstCurrent.durationUs + 500UL) / 1000UL;
    rec.durationMs = static_cast<uint16_t>(durationMs32 > 65535UL ? 65535UL : durationMs32);
    rec.edges = burstCurrent.edges;
    rec.rssi = burstCurrent.rssi;
    rec.onShortUs = avg16(burstCurrent.onShortSum, burstCurrent.onShortCount);
    rec.onLongUs = avg16(burstCurrent.onLongSum, burstCurrent.onLongCount);
    rec.offShortUs = avg16(burstCurrent.offShortSum, burstCurrent.offShortCount);
    rec.offLongUs = avg16(burstCurrent.offLongSum, burstCurrent.offLongCount);
    if (burstCurrent.edges) {
        uint32_t pct = (static_cast<uint32_t>(burstCurrent.timingValid) * 100UL) / burstCurrent.edges;
        if (pct > 100UL) pct = 100UL;
        rec.timingMatchPct = static_cast<uint8_t>(pct);
    } else {
        rec.timingMatchPct = 0;
    }
    rec.osv3Like =
        rec.durationMs >= BURST_OSV3_MIN_MS &&
        rec.durationMs <= BURST_OSV3_MAX_MS &&
        rec.timingMatchPct >= BURST_OSV3_MIN_MATCH_PCT;
    rec.likelyTechnoline = looksLikeTechnolineBurst(rec);
    if (rec.likelyTechnoline) burstStats.technolineLikeBursts++;

    // V6.3: Technoline viene gia' decodificata LIVE da ogni fronte con un
    // demodulatore PWM molto leggero (rtl_433-style). Questo recovery offline
    // e' opzionale e serve soltanto a recuperare un bordo iniziale/finale perso.
    if (burstExtraEnabled && rfMode != RfProtocolMode::Oregon && rec.likelyTechnoline &&
        burstCurrent.storedEdges >= 80U) {
        rec.adaptiveRecovered = processLaCrosseBurst(
            burstCurrent.durations, burstCurrent.levels, burstCurrent.storedEdges, rec.rssi);
    } else {
        rec.adaptiveRecovered = false;
    }

    burstHistory[burstHistoryHead] = rec;
    burstHistoryHead = static_cast<uint8_t>((burstHistoryHead + 1U) % BURST_HISTORY_SIZE);
    if (burstHistoryCount < BURST_HISTORY_SIZE) burstHistoryCount++;

    burstStats.burstsTotal++;
    if (rec.osv3Like) burstStats.osv3LikeBursts++;
    if (burstStats.autoActive && burstStats.autoStep < 4U) {
        burstStats.profileBursts[burstStats.autoStep]++;
        if (rec.osv3Like) burstStats.profileOsv3Like[burstStats.autoStep]++;
    }
    burstCurrent.reset();
}

void processRfBurstEdge(uint16_t durationUs, uint8_t level) {
    if (durationUs >= BURST_GAP_US) {
        finalizeRfBurst();
        return;
    }
    if (durationUs < 80U || durationUs > 2500U) return;

    if (!burstCurrent.active) {
        burstCurrent.reset();
        burstCurrent.active = true;
    }
    burstCurrent.durationUs += durationUs;
    if (burstCurrent.edges < 0xFFFFU) burstCurrent.edges++;
    if (burstCurrent.storedEdges < BURST_EDGE_BUFFER_SIZE) {
        burstCurrent.durations[burstCurrent.storedEdges] = durationUs;
        burstCurrent.levels[burstCurrent.storedEdges] = level & 1U;
        burstCurrent.storedEdges++;
    }

    // Una sola lettura RSSI per burst: limita l'impatto sul percorso real-time.
    if (!isfinite(burstCurrent.rssi) && burstCurrent.edges >= 32U) {
        burstCurrent.rssi = radio.getRSSI(false, true);
    }

    const IntervalKind kind = classifyStateInterval(durationUs, level);
    if (kind == IntervalKind::Invalid) return;
    burstCurrent.timingValid++;

    if (level) {
        if (kind == IntervalKind::Short) {
            burstCurrent.onShortSum += durationUs;
            if (burstCurrent.onShortCount < 0xFFFFU) burstCurrent.onShortCount++;
        } else {
            burstCurrent.onLongSum += durationUs;
            if (burstCurrent.onLongCount < 0xFFFFU) burstCurrent.onLongCount++;
        }
    } else {
        if (kind == IntervalKind::Short) {
            burstCurrent.offShortSum += durationUs;
            if (burstCurrent.offShortCount < 0xFFFFU) burstCurrent.offShortCount++;
        } else {
            burstCurrent.offLongSum += durationUs;
            if (burstCurrent.offLongCount < 0xFFFFU) burstCurrent.offLongCount++;
        }
    }
}


void finalizeWgrProbeBurst() {
    if (!wgrProbeCurrent.active) return;

    if (wgrProbeCurrent.edges < WGR_PROBE_MIN_EDGES) {
        wgrProbeCurrent.reset();
        return;
    }

    WgrProbeRecord rec{};
    rec.endedAtMs = millis();
    const uint32_t ms = (wgrProbeCurrent.durationUs + 500UL) / 1000UL;
    rec.durationMs = static_cast<uint16_t>(ms > 65535UL ? 65535UL : ms);
    rec.edges = wgrProbeCurrent.edges;
    rec.rssi = wgrProbeCurrent.rssi;
    rec.decodedHeader = wgrProbeCurrent.decodedHeader;
    if (wgrProbeCurrent.edges) {
        uint32_t pct = (static_cast<uint32_t>(wgrProbeCurrent.timingValid) * 100UL) /
                       wgrProbeCurrent.edges;
        if (pct > 100UL) pct = 100UL;
        rec.timingMatchPct = static_cast<uint8_t>(pct);
    } else {
        rec.timingMatchPct = 0U;
    }
    rec.osv3Like =
        rec.durationMs >= WGR_PROBE_OSV3_MIN_MS &&
        rec.durationMs <= WGR_PROBE_OSV3_MAX_MS &&
        rec.timingMatchPct >= WGR_PROBE_OSV3_MIN_MATCH_PCT;

    wgrProbeStats.burstsTotal++;
    if (rec.osv3Like) wgrProbeStats.osv3LikeBursts++;

    switch (rec.decodedHeader) {
        case 0xAF:
            wgrProbeStats.classifiedThermo++;
            break;
        case 0xA1:
            wgrProbeStats.classifiedWind++;
            // Un A1 valido e' il miglior anchor possibile per la cadenza WGR.
            wgrProbeLastCandidateMs = rec.endedAtMs;
            break;
        case 0xA2:
            wgrProbeStats.classifiedRain++;
            break;
        case 0xAD:
            wgrProbeStats.classifiedUv++;
            break;
        default:
            if (rec.osv3Like) {
                wgrProbeStats.unclassifiedOsv3++;
                if (wgrProbeLastCandidateMs != 0U) {
                    const uint32_t delta = rec.endedAtMs - wgrProbeLastCandidateMs;
                    wgrProbeStats.lastUnclassifiedDeltaMs = delta;
                    // WGR reale osservato ~14 s. Tolleriamo anche un singolo
                    // slot saltato (~28 s), senza estendere la finestra fino
                    // alle cadenze tipiche di THGN/PCR/UVN.
                    const bool oneSlot =
                        delta >= WGR_CADENCE_MIN_MS && delta <= WGR_CADENCE_MAX_MS;
                    const bool twoSlots = delta >= 25000UL && delta <= 31000UL;
                    if (oneSlot || twoSlots) {
                        rec.cadence14 = true;
                        wgrProbeStats.cadence14Matches++;
                        wgrProbeLastCandidateMs = rec.endedAtMs;
                    } else if (delta > 32000UL) {
                        // Anchor troppo vecchio: riparti da questo burst senza
                        // dichiararlo WGR finche' non compare la cadenza.
                        wgrProbeLastCandidateMs = rec.endedAtMs;
                    }
                } else {
                    wgrProbeLastCandidateMs = rec.endedAtMs;
                }
                wgrProbeStats.lastUnclassifiedMs = rec.endedAtMs;
                wgrProbeStats.lastUnclassifiedDurationMs = rec.durationMs;
                wgrProbeStats.lastUnclassifiedEdges = rec.edges;
                wgrProbeStats.lastUnclassifiedMatchPct = rec.timingMatchPct;
                wgrProbeStats.lastUnclassifiedRssi = rec.rssi;
            }
            break;
    }

    wgrProbeHistory[wgrProbeHistoryHead] = rec;
    wgrProbeHistoryHead = static_cast<uint8_t>(
        (wgrProbeHistoryHead + 1U) % WGR_PROBE_HISTORY_SIZE);
    if (wgrProbeHistoryCount < WGR_PROBE_HISTORY_SIZE) wgrProbeHistoryCount++;

    wgrProbeCurrent.reset();
}

void processWgrProbeEdge(uint16_t durationUs, uint8_t level) {
    if (!wgrProbeOn) return;

    if (durationUs >= WGR_PROBE_GAP_US) {
        finalizeWgrProbeBurst();
        return;
    }
    if (durationUs < 80U || durationUs > 2500U) return;

    if (!wgrProbeCurrent.active) {
        wgrProbeCurrent.reset();
        wgrProbeCurrent.active = true;
    }

    wgrProbeCurrent.durationUs += durationUs;
    if (wgrProbeCurrent.edges < 0xFFFFU) wgrProbeCurrent.edges++;

    // Una sola lettura RSSI per burst, solo quando la sonda e' esplicitamente ON.
    if (!isfinite(wgrProbeCurrent.rssi) && wgrProbeCurrent.edges == 32U) {
        wgrProbeCurrent.rssi = radio.getRSSI(false, true);
    }

    const IntervalKind kind = classifyStateInterval(durationUs, level);
    if (kind != IntervalKind::Invalid && wgrProbeCurrent.timingValid < 0xFFFFU) {
        wgrProbeCurrent.timingValid++;
    }
}

void addBitStateAware(StateAwareDecoder &d, uint8_t bit) {
    if (d.byteIndex >= OREGON_MAX_PACKET_BYTES) {
        stats.stateTimingErrors++;
        d.resetSearch();
        return;
    }
    if (bit) d.bytes[d.byteIndex] |= OREGON_BIT_MASK[d.bitIndex];
    d.bitIndex++;

    // Dopo sync A, il primo nibble deve sempre essere A.
    if (d.byteIndex == 0 && d.bitIndex == 4 && (d.bytes[0] & 0xF0U) != 0xA0U) {
        stats.stateManchesterErrors++;
        d.resetSearch();
        return;
    }
    if (d.bitIndex < 8) return;

    d.bitIndex = 0;
    d.byteIndex++;
    if (d.byteIndex == 1) {
        d.expectedBytes = expectedLengthForSensor(d.bytes[0]);
        if (d.expectedBytes == 0 || d.expectedBytes > OREGON_MAX_PACKET_BYTES) {
            stats.stateManchesterErrors++;
            d.resetSearch();
            return;
        }
    }

    if (d.expectedBytes != 0 && d.byteIndex >= d.expectedBytes) {
        stats.stateCandidates++;
        if (validateFrameChecksumRaw(d.bytes, d.expectedBytes)) {
            stats.stateChecksumOk++;
            queuePacket(d.bytes, d.expectedBytes, OregonDecodeSource::EdgeTimingState);
        } else {
            stats.stateChecksumFail++;
        }
        d.resetSearch();
    }
}

void processStateAwareCandidate(StateAwareDecoder &d, uint16_t durationUs, uint8_t rawLevel) {
    const uint8_t rfLevel = static_cast<uint8_t>((rawLevel ^ (d.invertLevel ? 1U : 0U)) & 1U);
    const IntervalKind kind = classifyStateInterval(durationUs, rfLevel);

    if (!d.decoding) {
        if (kind == IntervalKind::Short) {
            // Il preambolo V3 e' una sequenza di 1 Manchester: short OFF, short ON.
            // Richiedere alternanza di stato riduce molto i falsi preamboli.
            if (!d.haveSearchLevel || rfLevel != d.lastSearchLevel) {
                if (d.preambleShorts < 0xFFFFU) d.preambleShorts++;
            } else {
                d.preambleShorts = 1;
            }
            d.haveSearchLevel = true;
            d.lastSearchLevel = rfLevel;
            return;
        }

        if (kind == IntervalKind::Long && d.preambleShorts >= OREGON_STATE_PREAMBLE_MIN_SHORTS) {
            stats.statePreambles++;
            d.decoding = true;
            d.clearFrame();
            // Il primo long dopo il preambolo porta al primo bit del sync (0).
            // Il bit trasmesso e' lo stato RF immediatamente prima della transizione.
            addBitStateAware(d, rfLevel);
            return;
        }

        d.haveSearchLevel = false;
        d.preambleShorts = 0;
        return;
    }

    if (kind == IntervalKind::Invalid) {
        stats.stateTimingErrors++;
        d.resetSearch();
        return;
    }

    d.halfTime = static_cast<uint16_t>(d.halfTime + (kind == IntervalKind::Short ? 1U : 2U));
    if ((d.halfTime & 1U) != 0U) {
        // Una transizione long che termina su una boundary implica che e' mancata
        // la transizione Manchester di mezzo periodo: frame non valido.
        if (kind == IntervalKind::Long) {
            stats.stateManchesterErrors++;
            d.resetSearch();
        }
        return;
    }

    addBitStateAware(d, rfLevel);
}

void addDecodedV21Bit(Osv21Decoder &d, uint8_t bit) {
    // Conserva al massimo il payload utile. UVR128 trasmette due copie senza
    // pausa, ma misura e checksum sono gia' completi nella prima copia: come
    // nella prima implementazione EC70 funzionante, la validiamo subito senza
    // subordinare il dato alla ricezione integra della copia ridondante.
    if (d.decodedBits < OREGON_MAX_PACKET_BYTES * 8U && bit) {
        const uint8_t byteIndex = static_cast<uint8_t>(d.decodedBits / 8U);
        const uint8_t bitIndex = static_cast<uint8_t>(d.decodedBits % 8U);
        d.bytes[byteIndex] |= OREGON_BIT_MASK[bitIndex];
    }
    d.decodedBits++;

    if (d.decodedBits == 4U && (d.bytes[0] & 0xF0U) != 0xA0U) {
        stats.v21PairErrors++;
        d.resetSearch();
        return;
    }
    if (d.decodedBits == 8U) {
        d.expectedBytes = expectedLengthForV21(d.bytes[0]);
        if (d.expectedBytes == 0U || d.expectedBytes > OREGON_MAX_PACKET_BYTES) {
            d.resetSearch();
            return;
        }
        d.expectedBits = static_cast<uint16_t>(d.expectedBytes) * 8U;
    }

    // L'ID EC70 e' completo al ventesimo bit; il contatore distingue il
    // riconoscimento dell'header dall'accettazione finale con checksum valido.
    if (d.decodedBits == 20U && rawSensorCode(d.bytes) == 0xEC70U) {
        stats.v21UvCandidates++;
    }

    if (d.expectedBits != 0U && d.decodedBits >= d.expectedBits) {
        stats.v21Candidates++;
        const uint16_t code = rawSensorCode(d.bytes);
        const uint8_t csPos = checksumPositionForV21(code);
        if (csPos != 0U && validateFrameChecksumAt(d.bytes, d.expectedBytes, csPos)) {
            queuePacket(d.bytes, d.expectedBytes, OregonDecodeSource::EdgeTimingV21);
        } else {
            stats.v21ChecksumFail++;
        }
        d.resetSearch();
    }
}

void addPhysicalV21Bit(Osv21Decoder &d, uint8_t bit) {
    if (!d.havePairFirst) {
        d.pairFirst = bit;
        d.havePairFirst = true;
        return;
    }
    if (d.pairFirst == bit) {
        stats.v21PairErrors++;
        d.resetSearch();
        return;
    }
    d.havePairFirst = false;
    addDecodedV21Bit(d, bit); // secondo bit = dato originale, il primo e' invertito
}

void feedV21Interval(Osv21Decoder &d, IntervalKind kind) {
    if (kind == IntervalKind::Long) {
        if (d.shortPending) {
            stats.v21PairErrors++;
            d.resetSearch();
            return;
        }
        d.lastPhysicalBit ^= 1U;
        addPhysicalV21Bit(d, d.lastPhysicalBit);
        return;
    }
    if (kind == IntervalKind::Short) {
        if (!d.shortPending) {
            d.shortPending = true;
        } else {
            d.shortPending = false;
            addPhysicalV21Bit(d, d.lastPhysicalBit);
        }
        return;
    }
    d.resetSearch();
}

void processV21Candidate(IntervalKind kind) {
    Osv21Decoder &d = osv21Decoder;
    if (!d.decoding) {
        if (kind == IntervalKind::Long) {
            if (d.preambleLongs < 0xFFFFU) d.preambleLongs++;
            return;
        }
        if (kind == IntervalKind::Short && d.preambleLongs >= OREGON_V21_PREAMBLE_MIN_LONGS) {
            stats.v21Preambles++;
            if (d.preambleLongs < 24U) stats.v21ShortPreambles++;
            d.decoding = true;
            d.clearFrame();
            // L'ultimo bit fisico del preambolo V2.1 e' 1. Il primo bit del
            // sync e' ancora 1, quindi il primo intervallo osservato e' short.
            feedV21Interval(d, kind);
            return;
        }
        d.preambleLongs = 0;
        return;
    }
    feedV21Interval(d, kind);
}

void updateStateTimingAverages(uint16_t durationUs, uint8_t level) {
    const IntervalKind k = classifyStateInterval(durationUs, level);
    if (k == IntervalKind::Short) {
        if (level) updateAverage(stats.onShortAverageUs, durationUs);
        else updateAverage(stats.offShortAverageUs, durationUs);
    } else if (k == IntervalKind::Long) {
        if (level) updateAverage(stats.onLongAverageUs, durationUs);
        else updateAverage(stats.offLongAverageUs, durationUs);
    }
}

void IRAM_ATTR onDirectDataEdge() {
    const uint32_t now = micros();
    const uint32_t previous = lastEdgeUs;
    lastEdgeUs = now;

    if (!edgePrimed) {
        edgePrimed = true;
        return;
    }

    uint32_t delta = now - previous;
    if (delta > 0xFFFFU) delta = 0xFFFFU;

    const uint16_t head = edgeHead;
    const uint16_t next = static_cast<uint16_t>((head + 1U) & EDGE_RING_MASK);
    if (next == edgeTail) {
        isrOverflowCount++;
        return;
    }

    edgeDurationRing[head] = static_cast<uint16_t>(delta);
    const uint8_t newLevel = static_cast<uint8_t>(
        gpio_get_level(static_cast<gpio_num_t>(RADIO_DIO2_PIN)));
    edgeLevelRing[head] = static_cast<uint8_t>(newLevel ^ 1U);
    edgeHead = next;
    isrEdgeCount++;
}

bool popEdge(uint16_t &durationUs, uint8_t &level) {
    const uint16_t tail = edgeTail;
    if (tail == edgeHead) return false;
    durationUs = edgeDurationRing[tail];
    level = edgeLevelRing[tail];
    edgeTail = static_cast<uint16_t>((tail + 1U) & EDGE_RING_MASK);
    return true;
}

void resetDecoderWithError(EdgeDecoder &d, bool windRecoveryPath, bool syncError) {
    if (windRecoveryPath) {
        if (syncError) stats.weakSyncErrors++;
        else stats.weakTimingErrors++;
    } else {
        if (syncError) stats.syncErrors++;
        else stats.timingErrors++;
    }
    d.resetSearch();
}

void addBitToDecoder(EdgeDecoder &d, uint8_t bit) {
    if (d.byteIndex >= OREGON_MAX_PACKET_BYTES) {
        resetDecoderWithError(d, false, false);
        return;
    }

    if (bit) d.bytes[d.byteIndex] |= OREGON_BIT_MASK[d.bitIndex];
    d.bitIndex++;

    if (d.byteIndex == 0 && d.bitIndex == 4) {
        if ((d.bytes[0] & 0xF0U) != 0xA0U) {
            resetDecoderWithError(d, false, true);
            return;
        }
    }

    if (d.bitIndex < 8) return;

    d.bitIndex = 0;
    d.byteIndex++;

    if (d.byteIndex == 1) {
        d.expectedBytes = expectedLengthForSensor(d.bytes[0]);
        if (d.expectedBytes == 0 || d.expectedBytes > OREGON_MAX_PACKET_BYTES) {
            rememberUnknownHeader(d.bytes[0], false);
            d.resetSearch();
            return;
        }
    }

    if (d.expectedBytes != 0 && d.byteIndex >= d.expectedBytes) {
        queuePacket(d.bytes, d.expectedBytes, OregonDecodeSource::EdgeTiming);
        d.resetSearch();
    }
}

void classifyPreambleRun(uint16_t run) {
    if (run > stats.maxPreambleShorts) stats.maxPreambleShorts = run;
    if (run >= 28) {
        stats.preRun28Plus++;
    } else if (run >= 18) {
        stats.preRun18_27++;
        stats.weakPreamblesDetected++;
        stats.lastWeakPreambleShorts = run;
    } else if (run >= 12) {
        stats.preRun12_17++;
        stats.weakPreamblesDetected++;
        stats.lastWeakPreambleShorts = run;
    } else if (run >= 8) {
        stats.preRun08_11++;
        stats.weakPreamblesDetected++;
        stats.lastWeakPreambleShorts = run;
    } else if (run >= 4) {
        stats.preRun04_07++;
        stats.weakPreamblesDetected++;
        stats.lastWeakPreambleShorts = run;
    }
}

void processStrongCandidate(IntervalKind kind) {
    EdgeDecoder &d = strongDecoder;
    if (!d.decoding) {
        if (kind == IntervalKind::Short) {
            if (d.preambleShorts < 0xFFFFU) d.preambleShorts++;
            if (d.preambleShorts > stats.maxPreambleShorts) stats.maxPreambleShorts = d.preambleShorts;
            return;
        }

        if (kind == IntervalKind::Long && d.preambleShorts >= OREGON_STRONG_PREAMBLE_MIN_SHORTS) {
            stats.preamblesDetected++;
            stats.lastStrongPreambleShorts = d.preambleShorts;
            d.decoding = true;
            d.clearFrame();
            d.lastBit = 0;
            addBitToDecoder(d, 0);
            return;
        }

        d.preambleShorts = 0;
        return;
    }

    if (kind == IntervalKind::Invalid) {
        resetDecoderWithError(d, false, false);
        return;
    }
    if (kind == IntervalKind::Long) {
        if (d.shortPending) {
            resetDecoderWithError(d, false, false);
            return;
        }
        d.lastBit ^= 1U;
        addBitToDecoder(d, d.lastBit);
        return;
    }

    if (!d.shortPending) d.shortPending = true;
    else {
        d.shortPending = false;
        addBitToDecoder(d, d.lastBit);
    }
}


// V6.3: nessun decoder WGR con preambolo speciale. Il WGR800 1984 viene
// trattato come normale Oregon Protocol 3.0; resta soltanto lo scanner A1
// scorrevole, checksum-gated, come fallback indipendente dal preambolo.

uint8_t nybbleFromBytes(const uint8_t *bytes, uint8_t index) {
    const uint8_t b = bytes[index / 2U];
    return (index % 2U == 0U) ? static_cast<uint8_t>(b >> 4U)
                               : static_cast<uint8_t>(b & 0x0FU);
}

bool validateWindChecksumRaw(const uint8_t *bytes) {
    // Stessa convenzione del parser legacy: WGR800 checksum ai nibble 18/19,
    // somma dei nibble 1..17 (il primo nibble A non partecipa).
    uint8_t calculated = 0;
    for (uint8_t i = 1; i < 18; ++i) {
        calculated = static_cast<uint8_t>(calculated + nybbleFromBytes(bytes, i));
    }
    const uint8_t checkLow = nybbleFromBytes(bytes, 18);
    const uint8_t checkHigh = nybbleFromBytes(bytes, 19);
    const uint8_t received = static_cast<uint8_t>((checkHigh << 4U) | checkLow);
    return calculated == received;
}

uint8_t byteFromWindow(const WindSlidingScanner &s, uint8_t byteOffset, bool invert) {
    uint8_t value = 0;
    const uint8_t oldest = s.head; // quando count==80, head punta al bit piu vecchio
    for (uint8_t bit = 0; bit < 8; ++bit) {
        const uint8_t idx = static_cast<uint8_t>((oldest + byteOffset * 8U + bit) % WIND_SCAN_BITS);
        uint8_t v = s.bits[idx];
        if (invert) v ^= 1U;
        if (v) value |= OREGON_BIT_MASK[bit];
    }
    return value;
}

void tryWindWindow(WindSlidingScanner &s) {
    if (s.count < WIND_SCAN_BITS) return;

    const uint8_t first = byteFromWindow(s, 0, false);
    bool invert = false;
    if (first == 0xA1) {
        invert = false;
    } else if (first == static_cast<uint8_t>(~0xA1U)) {
        invert = true;
    } else {
        return;
    }

    stats.windRecoveryStarts++;
    uint8_t frame[10]{};
    for (uint8_t i = 0; i < 10; ++i) frame[i] = byteFromWindow(s, i, invert);

    // Un falso A1 da rumore non viene mai esposto al resto del firmware.
    if (!validateWindChecksumRaw(frame)) {
        stats.windWindowChecksumFail++;
        return;
    }

    if (queuePacket(frame, 10, OregonDecodeSource::EdgeTimingWeak)) {
        stats.windRecoverySuccess++;
    }
}

void pushWindBit(WindSlidingScanner &s, uint8_t bit) {
    s.bits[s.head] = bit & 1U;
    s.head = static_cast<uint8_t>((s.head + 1U) % WIND_SCAN_BITS);
    if (s.count < WIND_SCAN_BITS) s.count++;
    tryWindWindow(s);
}

void feedWindScanner(WindSlidingScanner &s, IntervalKind kind) {
    if (kind == IntervalKind::Invalid) {
        s.reset();
        return;
    }

    if (kind == IntervalKind::Long) {
        // La seconda fase parte volutamente con mezzo short gia' pendente.
        // Se il primo evento e' un long, scartiamo solo quel mezzo-short fittizio
        // e trattiamo il long normalmente.
        if (s.shortPending) {
            if (s.fresh && s.phaseShift) {
                s.shortPending = false;
            } else {
                s.reset();
                return;
            }
        }
        s.fresh = false;
        s.lastBit ^= 1U;
        pushWindBit(s, s.lastBit);
        return;
    }

    // Due intervalli short consecutivi rappresentano un bit senza toggle.
    if (!s.shortPending) {
        s.shortPending = true;
        s.fresh = false;
    } else {
        s.shortPending = false;
        s.fresh = false;
        pushWindBit(s, s.lastBit);
    }
}

void feedWindScanners(IntervalKind kind) {
    for (auto &s : windScan) feedWindScanner(s, kind);
}

void processEdgeInterval(uint16_t durationUs, uint8_t level) {
    const IntervalKind kind = classifyInterval(durationUs);

    if (kind == IntervalKind::Short) updateAverage(stats.shortAverageUs, durationUs);
    if (kind == IntervalKind::Long) updateAverage(stats.longAverageUs, durationUs);
    updateStateTimingAverages(durationUs, level);

    if (!strongDecoder.decoding && kind != IntervalKind::Short && strongDecoder.preambleShorts > 0) {
        classifyPreambleRun(strongDecoder.preambleShorts);
    }

    // 1) Decoder legacy V4.3: resta intatto come fallback collaudato.
    processStrongCandidate(kind);

    // 2) Decoder V4.8 state-aware, due polarita' in parallelo. Solo i frame con
    // checksum valido vengono accodati, quindi non puo' contaminare il parser.
    processStateAwareCandidate(stateDecoder[0], durationUs, level);
    processStateAwareCandidate(stateDecoder[1], durationUs, level);

    // 3) Decoder Oregon V2.1: cerca il preambolo alternato (long consecutivi),
    // valida ogni coppia inverso/originale e accoda solo EC40/1D20 checksum OK.
    processV21Candidate(kind);

    // 4) Scanner A1 scorrevole: fallback dedicato WGR800 1984. Non richiede
    // un preambolo speciale e accetta soltanto A1 con checksum valido.
    feedWindScanners(kind);
}

#else

// -----------------------------------------------------------------------------
// Fallback V4.2: bit synchronizer SX1278 ON, campionamento DIO2 sul clock DIO1.
// Si abilita mettendo OREGON_RAW_EDGE_MODE=0 in config_private.h.
// -----------------------------------------------------------------------------

constexpr uint16_t CHIP_RING_SIZE = 8192;
constexpr uint16_t CHIP_RING_MASK = CHIP_RING_SIZE - 1;
volatile uint8_t chipRing[CHIP_RING_SIZE];
volatile uint16_t chipHead = 0;
volatile uint16_t chipTail = 0;
volatile uint32_t isrChipCount = 0;
volatile uint32_t isrOverflowCount = 0;
uint32_t streamIndex = 0;

struct ManchesterCandidate {
    uint8_t phase{0};
    bool inverted{false};
    bool haveFirstChip{false};
    uint8_t firstChip{0};
    uint8_t headerOnes{0};
    uint8_t bytes[OREGON_MAX_PACKET_BYTES]{};
    bool frameStarted{false};
    uint8_t byteIndex{0};
    uint8_t bitIndex{0};
    uint8_t expectedBytes{0};

    void resetFrame() {
        headerOnes = 0;
        frameStarted = false;
        byteIndex = 0;
        bitIndex = 0;
        expectedBytes = 0;
        memset(bytes, 0, sizeof(bytes));
    }
};

ManchesterCandidate candidates[4];

void addDecodedBit(ManchesterCandidate &c, uint8_t bit) {
    if (c.byteIndex >= OREGON_MAX_PACKET_BYTES) {
        c.resetFrame();
        return;
    }
    if (bit) c.bytes[c.byteIndex] |= OREGON_BIT_MASK[c.bitIndex];
    c.bitIndex++;
    if (c.bitIndex < 8) return;
    c.bitIndex = 0;
    c.byteIndex++;

    if (c.byteIndex == 1) {
        c.expectedBytes = expectedLengthForSensor(c.bytes[0]);
        if (c.expectedBytes == 0 || c.expectedBytes > OREGON_MAX_PACKET_BYTES) {
            rememberUnknownHeader(c.bytes[0], false);
            c.resetFrame();
            return;
        }
    }
    if (c.expectedBytes != 0 && c.byteIndex >= c.expectedBytes) {
        queuePacket(c.bytes, c.expectedBytes, OregonDecodeSource::ClockSync);
        c.resetFrame();
    }
}

void processDecodedBit(ManchesterCandidate &c, uint8_t bit) {
    if (!c.frameStarted) {
        if (bit == 1) {
            if (c.headerOnes < 255) c.headerOnes++;
            return;
        }
        if (c.headerOnes >= OREGON_HEADER_ONES) {
            c.frameStarted = true;
            c.byteIndex = 0;
            c.bitIndex = 0;
            c.expectedBytes = 0;
            memset(c.bytes, 0, sizeof(c.bytes));
            addDecodedBit(c, 0);
        } else {
            c.headerOnes = 0;
        }
        return;
    }
    addDecodedBit(c, bit);
}

void processChipForCandidate(ManchesterCandidate &c, uint8_t chip, uint32_t index) {
    if (!c.haveFirstChip) {
        if ((index & 1U) != c.phase) return;
        c.firstChip = chip;
        c.haveFirstChip = true;
        return;
    }
    const uint8_t first = c.firstChip;
    c.haveFirstChip = false;
    if (first == chip) {
        stats.manchesterErrors++;
        c.resetFrame();
        return;
    }
    uint8_t bit = (first == 1 && chip == 0) ? 1 : 0;
    if (c.inverted) bit ^= 1U;
    processDecodedBit(c, bit);
}

void IRAM_ATTR onDirectClock() {
    const uint8_t chip = static_cast<uint8_t>(gpio_get_level(static_cast<gpio_num_t>(RADIO_DIO2_PIN)));
    const uint16_t head = chipHead;
    const uint16_t next = static_cast<uint16_t>((head + 1U) & CHIP_RING_MASK);
    if (next == chipTail) {
        isrOverflowCount++;
        return;
    }
    chipRing[head] = chip;
    chipHead = next;
    isrChipCount++;
}

bool popChip(uint8_t &chip) {
    const uint16_t tail = chipTail;
    if (tail == chipHead) return false;
    chip = chipRing[tail];
    chipTail = static_cast<uint16_t>((tail + 1U) & CHIP_RING_MASK);
    return true;
}

#endif

void resetRawReceptionState() {
#if OREGON_RAW_EDGE_MODE
    noInterrupts();
    edgeTail = edgeHead;
    lastEdgeUs = micros();
    edgePrimed = false;
    interrupts();

    strongDecoder.resetSearch();
    stateDecoder[0].resetSearch();
    stateDecoder[1].resetSearch();
    osv21Decoder.resetSearch();
    for (auto &w : windScan) w.reset();
    burstCurrent.reset();
    resetLaCrosseDecoderState();
#endif
}

bool applyRadioFrontendRuntime(float bandwidthKhz, uint8_t gain) {
    if (gain > 3U) return false;
    if (!(bandwidthKhz == 83.3f || bandwidthKhz == 100.0f ||
          bandwidthKhz == 125.0f || bandwidthKhz == 166.7f ||
          bandwidthKhz == 200.0f || bandwidthKhz == 250.0f)) {
        return false;
    }

    currentGain = gain;
    currentBandwidth = bandwidthKhz;
    if (!radioReady) return true;

#if OREGON_RAW_EDGE_MODE
    detachInterrupt(digitalPinToInterrupt(RADIO_DIO2_PIN));
#endif
    int16_t state = radio.setRxBandwidth(bandwidthKhz);
    if (state == RADIOLIB_ERR_NONE) state = radio.setGain(gain);
    if (state == RADIOLIB_ERR_NONE) state = radio.receiveDirect();
#if OREGON_RAW_EDGE_MODE
    if (state == RADIOLIB_ERR_NONE) state = radio.disableBitSync();
    resetRawReceptionState();
    attachInterrupt(digitalPinToInterrupt(RADIO_DIO2_PIN), onDirectDataEdge, CHANGE);
#endif
    if (state != RADIOLIB_ERR_NONE) {
        lastError = String("frontend/restart: ") + state;
        return false;
    }

    Serial.print(F("[RF] frontend applicato: BW="));
    Serial.print(bandwidthKhz, 1);
    Serial.print(F(" kHz gain="));
    Serial.print(gain);
    Serial.print(F(" ("));
    Serial.print(gain == 0 ? "AGC" : (gain == 1 ? "MAX" : (gain == 2 ? "ALTO" : "MEDIO")));
    Serial.println(')');
    return true;
}

bool applyRadioGainRuntime(uint8_t gain) {
    return applyRadioFrontendRuntime(currentBandwidth, gain);
}

void frontendProfileSettings(RfFrontendProfile profile, float &bandwidthKhz, uint8_t &gain) {
    switch (profile) {
        case RfFrontendProfile::WideAgc:
            bandwidthKhz = 166.7f; gain = 0; break;
        case RfFrontendProfile::MaxGain:
            bandwidthKhz = 125.0f; gain = 1; break;
        case RfFrontendProfile::WideMaxGain:
            bandwidthKhz = 166.7f; gain = 1; break;
        case RfFrontendProfile::Stable:
        default:
            bandwidthKhz = 125.0f; gain = 0; break;
    }
}

bool persistOregonFrontend(RfFrontendProfile profile, float bandwidthKhz, uint8_t gain) {
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

void updateAutoScores() {
    for (uint8_t i = 0; i < 4U; ++i) {
        const int32_t validScore = static_cast<int32_t>(burstStats.profileValidFrames[i]) * 200;
        const int32_t osv3Score = static_cast<int32_t>(burstStats.profileOsv3Like[i]) * 8;
        const int32_t total = static_cast<int32_t>(burstStats.profileBursts[i]);
        const int32_t noise = total - static_cast<int32_t>(burstStats.profileOsv3Like[i]);
        burstStats.profileScore[i] = validScore + osv3Score - (noise > 0 ? noise : 0);
    }
}

void serviceAutoCalibrationInternal() {
    if (!burstStats.autoActive || rfMode != RfProtocolMode::Oregon) return;
    const uint32_t now = millis();
    if (static_cast<uint32_t>(now - burstStats.autoStepStartedMs) < AUTO_PROFILE_STEP_MS) return;

    updateAutoScores();
    if (burstStats.autoStep < 3U) {
        burstStats.autoStep++;
        burstStats.autoStepStartedMs = now;
        float bw = 125.0f;
        uint8_t gain = 0;
        frontendProfileSettings(static_cast<RfFrontendProfile>(burstStats.autoStep), bw, gain);
        applyRadioFrontendRuntime(bw, gain);
        Serial.print(F("[RF-AUTO] step "));
        Serial.print(burstStats.autoStep + 1U);
        Serial.print(F("/4 -> "));
        Serial.println(radioFrontendProfileName(static_cast<RfFrontendProfile>(burstStats.autoStep)));
        return;
    }

    uint8_t best = 0;
    for (uint8_t i = 1; i < 4U; ++i) {
        if (burstStats.profileScore[i] > burstStats.profileScore[best]) best = i;
    }
    burstStats.bestProfile = best;
    burstStats.autoActive = false;

    const RfFrontendProfile bestProfile = static_cast<RfFrontendProfile>(best);
    float bw = 125.0f;
    uint8_t gain = 0;
    frontendProfileSettings(bestProfile, bw, gain);
    if (!persistOregonFrontend(bestProfile, bw, gain)) {
        Serial.println(F("[RF-AUTO] ATTENZIONE: profilo migliore non persistito in NVS"));
    }
    applyRadioFrontendRuntime(bw, gain);

    Serial.print(F("[RF-AUTO] completato, profilo migliore: "));
    Serial.print(radioFrontendProfileName(bestProfile));
    Serial.print(F(" score="));
    Serial.println(burstStats.profileScore[best]);
}

} // namespace

const char *rfProtocolModeName(RfProtocolMode mode) {
    switch (mode) {
        case RfProtocolMode::LaCrosse: return "technoline";
        case RfProtocolMode::Dual: return "dual";
        default: return "oregon";
    }
}

const char *radioGainName(uint8_t gain) {
    switch (gain) {
        case 0: return "AGC";
        case 1: return "MAX";
        case 2: return "ALTO";
        case 3: return "MEDIO";
        default: return "N/D";
    }
}

float getRadioBandwidthKhz() { return currentBandwidth; }
float getRadioBandwidthForMode(RfProtocolMode mode) {
    if (mode == RfProtocolMode::LaCrosse) return bandwidthLaCrosse;
    // In DUAL il front-end e' condiviso: usiamo il profilo Oregon stabile.
    return bandwidthOregon;
}

const char *radioFrontendProfileName(RfFrontendProfile profile) {
    switch (profile) {
        case RfFrontendProfile::Stable: return "STABILE";
        case RfFrontendProfile::WideAgc: return "AMPIO-AGC";
        case RfFrontendProfile::MaxGain: return "MAX-125";
        case RfFrontendProfile::WideMaxGain: return "MAX-AMPIO";
        case RfFrontendProfile::AutoScan: return "AUTO-SCAN";
        case RfFrontendProfile::Manual: return "MANUALE";
        default: return "N/D";
    }
}

RfFrontendProfile getRadioFrontendProfile() {
    if (burstStats.autoActive) return RfFrontendProfile::AutoScan;
    return currentFrontendProfile;
}

uint8_t getRadioGain() { return currentGain; }
uint8_t getRadioGainForMode(RfProtocolMode mode) {
    if (mode == RfProtocolMode::LaCrosse) return gainLaCrosse;
    return gainOregon;
}

bool setRadioGainForMode(RfProtocolMode mode, uint8_t gain) {
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

bool setRadioFrontendProfile(RfFrontendProfile profile) {
    if (profile == RfFrontendProfile::AutoScan) return startRadioAutoCalibration();
    if (profile == RfFrontendProfile::Manual) return false;
    if (static_cast<uint8_t>(profile) > static_cast<uint8_t>(RfFrontendProfile::WideMaxGain)) return false;

    burstStats.autoActive = false;
    float bw = 125.0f;
    uint8_t gain = 0;
    frontendProfileSettings(profile, bw, gain);

    if (rfMode == RfProtocolMode::Oregon || rfMode == RfProtocolMode::Dual) {
        if (!persistOregonFrontend(profile, bw, gain)) return false;
        return applyRadioFrontendRuntime(bw, gain);
    }

    // I profili di auto-calibrazione sono pensati per Oregon. In Technoline
    // permettiamo solo l'applicazione temporanea senza modificare il decoder.
    currentFrontendProfile = profile;
    bandwidthLaCrosse = bw;
    gainLaCrosse = gain;
    return applyRadioFrontendRuntime(bw, gain);
}

bool startRadioAutoCalibration() {
    // AUTO SCAN resta una funzione diagnostica Oregon-only: in DUAL il profilo
    // deve rimanere stabile per non interrompere la contemporaneita'.
    if (rfMode != RfProtocolMode::Oregon) return false;
    burstStats.autoActive = true;
    burstStats.autoStep = 0;
    burstStats.autoStepStartedMs = millis();
    burstStats.autoStepDurationMs = AUTO_PROFILE_STEP_MS;
    burstStats.bestProfile = 0;
    for (uint8_t i = 0; i < 4U; ++i) {
        burstStats.profileBursts[i] = 0;
        burstStats.profileOsv3Like[i] = 0;
        burstStats.profileValidFrames[i] = 0;
        burstStats.profileScore[i] = 0;
    }
    currentFrontendProfile = RfFrontendProfile::AutoScan;
    float bw = 125.0f;
    uint8_t gain = 0;
    frontendProfileSettings(RfFrontendProfile::Stable, bw, gain);
    const bool ok = applyRadioFrontendRuntime(bw, gain);
    Serial.println(F("[RF-AUTO] avviato: 4 profili x 45 s"));
    return ok;
}

void stopRadioAutoCalibration() {
    if (!burstStats.autoActive) return;
    burstStats.autoActive = false;
    float bw = bandwidthOregon;
    const uint8_t gain = gainOregon;
    currentFrontendProfile = RfFrontendProfile::Manual;
    applyRadioFrontendRuntime(bw, gain);
}

RfBurstAnalyzerStats getRfBurstAnalyzerStats() {
    updateAutoScores();
    return burstStats;
}

void noteAcceptedOregonFrameForCalibration() {
    if (burstStats.autoActive && burstStats.autoStep < 4U) {
        burstStats.profileValidFrames[burstStats.autoStep]++;
    }
}

uint8_t getRfBurstHistory(RfBurstRecord *out, uint8_t maxRecords) {
    if (!out || maxRecords == 0) return 0;
    const uint8_t count = burstHistoryCount < maxRecords ? burstHistoryCount : maxRecords;
    for (uint8_t n = 0; n < count; ++n) {
        const int idx = (static_cast<int>(burstHistoryHead) - 1 - n + BURST_HISTORY_SIZE) % BURST_HISTORY_SIZE;
        out[n] = burstHistory[idx];
    }
    return count;
}

bool setBurstRecoveryEnabled(bool enabled) {
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

bool burstRecoveryEnabled() { return burstExtraEnabled; }

RfProtocolMode getRfProtocolMode() { return rfMode; }

bool setRfProtocolMode(RfProtocolMode mode) {
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
    osv21Decoder.resetSearch();
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

bool initOregonReceiver() {
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

    if (gainOregon > 3U) gainOregon = 0;
    if (gainLaCrosse > 3U) gainLaCrosse = 0;
    bandwidthOregon = static_cast<float>(bwO10) / 10.0f;
    bandwidthLaCrosse = static_cast<float>(bwL10) / 10.0f;
    if (!(bandwidthOregon == 83.3f || bandwidthOregon == 100.0f || bandwidthOregon == 125.0f ||
          bandwidthOregon == 166.7f || bandwidthOregon == 200.0f || bandwidthOregon == 250.0f)) {
        bandwidthOregon = 125.0f;
    }
    if (!(bandwidthLaCrosse == 83.3f || bandwidthLaCrosse == 100.0f || bandwidthLaCrosse == 125.0f ||
          bandwidthLaCrosse == 166.7f || bandwidthLaCrosse == 200.0f || bandwidthLaCrosse == 250.0f)) {
        bandwidthLaCrosse = 125.0f;
    }
    if (savedProfile > static_cast<uint8_t>(RfFrontendProfile::WideMaxGain)) {
        savedProfile = static_cast<uint8_t>(RfFrontendProfile::Manual);
    }

    // V6.3: baseline RF consolidata a 125 kHz + AGC. Il modo DUAL
    // legge Oregon + Technoline contemporaneamente dallo stesso flusso RAW.
    if (savedRfCfgVer < 59U) {
        gainOregon = 0;
        gainLaCrosse = 0;
        bandwidthOregon = 125.0f;
        bandwidthLaCrosse = 125.0f;
        savedProfile = static_cast<uint8_t>(RfFrontendProfile::Stable);
        rfPrefs.begin("rfrx", false);
        prefPutUCharIfChanged(rfPrefs, "gainO", gainOregon);
        prefPutUCharIfChanged(rfPrefs, "gainL", gainLaCrosse);
        prefPutUShortIfChanged(rfPrefs, "bwO10", 1250U);
        prefPutUShortIfChanged(rfPrefs, "bwL10", 1250U);
        prefPutUCharIfChanged(rfPrefs, "profileO", savedProfile);
        prefPutBoolIfChanged(rfPrefs, "burstX", false);
        prefPutUCharIfChanged(rfPrefs, "cfgVer", 59U);
        rfPrefs.end();
        Serial.println(F("[RF] V6.3 migration: DUAL -> BW125 + AGC, BURST EXTRA OFF, WGR PROBE OFF"));
        rfPrefs.begin("rfmode", false);
        prefPutUCharIfChanged(rfPrefs, "mode", static_cast<uint8_t>(RfProtocolMode::Dual));
        rfPrefs.end();
        rfMode = RfProtocolMode::Dual;
    }

    currentGain = rfMode == RfProtocolMode::LaCrosse ? gainLaCrosse : gainOregon;
    currentBandwidth = rfMode == RfProtocolMode::LaCrosse ? bandwidthLaCrosse : bandwidthOregon;
    currentFrontendProfile = (rfMode == RfProtocolMode::Oregon || rfMode == RfProtocolMode::Dual)
        ? static_cast<RfFrontendProfile>(savedProfile) : RfFrontendProfile::Manual;

    Serial.print(F("[RF] modalita' iniziale: ")); Serial.println(rfProtocolModeName(rfMode));
    pinMode(RADIO_DIO1_PIN, INPUT);
    pinMode(RADIO_DIO2_PIN, INPUT);
    SPI.begin(RADIO_SCLK_PIN, RADIO_MISO_PIN, RADIO_MOSI_PIN, RADIO_CS_PIN);

    int16_t state = radio.beginFSK(
        OREGON_FREQUENCY_MHZ,
        OREGON_CHIP_RATE_KBPS,
        5.0f,
        currentBandwidth,
        10,
        16,
        true
    );
    if (state != RADIOLIB_ERR_NONE) {
        lastError = String("beginFSK/OOK: ") + state;
        return false;
    }

    // Profilo RF configurabile. Il default V4.8 torna al profilo conservativo
    // 125 kHz + AGC che non ha penalizzato i sensori gia' stabili.
    state = radio.setRxBandwidth(currentBandwidth);
    if (state != RADIOLIB_ERR_NONE) {
        lastError = String("setRxBandwidth: ") + state;
        return false;
    }
    state = radio.setGain(currentGain);
    if (state != RADIOLIB_ERR_NONE) {
        lastError = String("setGain: ") + state;
        return false;
    }
    Serial.print(F("[RF] sensitivity: BW="));
    Serial.print(currentBandwidth, 1);
    Serial.print(F(" kHz gain="));
    Serial.println(currentGain);

#if OREGON_RAW_EDGE_MODE
    state = radio.receiveDirect();
    if (state != RADIOLIB_ERR_NONE) {
        lastError = String("receiveDirect: ") + state;
        return false;
    }

    // RadioLib consente di disabilitare il bit synchronizer in continuous mode.
    // In questo modo DIO2 conserva il timing OOK utile al decoder OSV3.
    state = radio.disableBitSync();
    if (state != RADIOLIB_ERR_NONE) {
        lastError = String("disableBitSync: ") + state;
        return false;
    }

    strongDecoder.resetSearch();
    stateDecoder[0].invertLevel = false;
    stateDecoder[1].invertLevel = true;
    stateDecoder[0].resetSearch();
    stateDecoder[1].resetSearch();
    osv21Decoder.resetSearch();
    windScan[0].phaseShift = false;
    windScan[1].phaseShift = true;
    for (auto &s : windScan) s.reset();
    noInterrupts();
    edgeHead = edgeTail = 0;
    isrEdgeCount = 0;
    isrOverflowCount = 0;
    lastEdgeUs = micros();
    edgePrimed = false;
    interrupts();
    attachInterrupt(digitalPinToInterrupt(RADIO_DIO2_PIN), onDirectDataEdge, CHANGE);
#else
    candidates[0].phase = 0; candidates[0].inverted = false;
    candidates[1].phase = 1; candidates[1].inverted = false;
    candidates[2].phase = 0; candidates[2].inverted = true;
    candidates[3].phase = 1; candidates[3].inverted = true;
    for (auto &candidate : candidates) candidate.resetFrame();

    radio.setDirectAction(onDirectClock);
    state = radio.receiveDirect();
    if (state != RADIOLIB_ERR_NONE) {
        lastError = String("receiveDirect: ") + state;
        return false;
    }
#endif

    radioReady = true;
    lastError = "OK";
    return true;
}

void serviceOregonReceiver() {
#if OREGON_RAW_EDGE_MODE
    serviceAutoCalibrationInternal();
    uint16_t durationUs = 0;
    uint8_t level = 0;
    uint16_t processed = 0;
    while (processed < 1536 && popEdge(durationUs, level)) {
        // Oregon ha priorita' nel DUAL. Il decoder Technoline stabile e' pulse-only
        // e costa poche operazioni per edge: puo' quindi lavorare sullo stesso
        // flusso senza dipendere dal Burst Analyzer.
        if (rfMode == RfProtocolMode::Oregon || rfMode == RfProtocolMode::Dual) {
            // La sonda WGR e' puramente passiva e, quando abilitata, vede il
            // burst prima dei decoder cosi' puo' essere etichettata dal frame
            // validato nello stesso intervallo.
            if (wgrProbeOn) processWgrProbeEdge(durationUs, level);
            processEdgeInterval(durationUs, level);
        }
        if (rfMode == RfProtocolMode::LaCrosse || rfMode == RfProtocolMode::Dual) {
            processLaCrosseEdge(durationUs, level);
        }
        // Il Burst Analyzer/recovery e' EXTRA e di default OFF. In AUTO SCAN
        // resta forzato ON perche' serve a calcolare il punteggio dei profili.
        if (burstExtraEnabled || burstStats.autoActive) {
            processRfBurstEdge(durationUs, level);
        }
        processed++;
    }

    // V6.3: finalizza anche la sonda WGR dopo il silenzio del trasmettitore.
    if (wgrProbeOn && wgrProbeCurrent.active) {
        uint32_t lastUsCopy = 0;
        bool ringEmpty = false;
        noInterrupts();
        lastUsCopy = lastEdgeUs;
        ringEmpty = (edgeTail == edgeHead);
        interrupts();
        if (ringEmpty && static_cast<uint32_t>(micros() - lastUsCopy) >= WGR_PROBE_GAP_US) {
            finalizeWgrProbeBurst();
        }
    }

    // Finalizza il burst anche se dopo l'ultimo fronte il trasmettitore resta
    // silenzioso: senza questo controllo il record apparirebbe solo all'inizio
    // della trasmissione successiva.
    if ((burstExtraEnabled || burstStats.autoActive) && burstCurrent.active) {
        uint32_t lastUsCopy = 0;
        bool ringEmpty = false;
        noInterrupts();
        lastUsCopy = lastEdgeUs;
        ringEmpty = (edgeTail == edgeHead);
        interrupts();
        if (ringEmpty && static_cast<uint32_t>(micros() - lastUsCopy) >= BURST_GAP_US) {
            finalizeRfBurst();
        }
    }

    noInterrupts();
    stats.edgesCaptured = isrEdgeCount;
    stats.ringOverflows = isrOverflowCount;
    interrupts();
#else
    uint8_t chip = 0;
    uint16_t processed = 0;
    while (processed < 512 && popChip(chip)) {
        for (auto &candidate : candidates) processChipForCandidate(candidate, chip, streamIndex);
        streamIndex++;
        processed++;
    }
    noInterrupts();
    stats.chipsSampled = isrChipCount;
    stats.ringOverflows = isrOverflowCount;
    interrupts();
#endif
}

bool getOregonPacket(OregonPacket &packet) {
    if (packetTail == packetHead) return false;
    packet = packetQueue[packetTail];
    packetTail = static_cast<uint8_t>((packetTail + 1U) % PACKET_QUEUE_SIZE);
    return true;
}


bool setWgrProbeEnabled(bool enabled) {
    if (wgrProbeOn == enabled) return true;
    wgrProbeOn = enabled;
    resetWgrProbeStatsInternal();
    Serial.print(F("[WGR-PROBE] "));
    Serial.println(enabled ? F("ON (RAM-only)") : F("OFF"));
    return true;
}

bool prepareRadioForDeepSleep() {
    burstStats.autoActive = false;
    finalizeRfBurst();
    if (wgrProbeOn) resetWgrProbeStatsInternal();
#if OREGON_RAW_EDGE_MODE
    detachInterrupt(digitalPinToInterrupt(RADIO_DIO2_PIN));
    noInterrupts();
    edgeTail = edgeHead;
    interrupts();
#endif
    packetHead = packetTail = 0;
    resetLaCrosseDecoderState();

    if (!radioReady) return true;
    const int16_t state = radio.sleep();
    if (state != RADIOLIB_ERR_NONE) {
        lastError = String("sleep: ") + state;
        return false;
    }
    radioReady = false;
    lastError = "SLEEP";
    Serial.println(F("[RF] SX1278 -> sleep"));
    return true;
}

bool wgrProbeEnabled() {
    return wgrProbeOn;
}

WgrProbeStats getWgrProbeStats() {
    WgrProbeStats out = wgrProbeStats;
    out.enabled = wgrProbeOn;
    return out;
}

uint8_t getWgrProbeHistory(WgrProbeRecord *out, uint8_t maxRecords) {
    if (!out || maxRecords == 0U) return 0U;
    const uint8_t n = (wgrProbeHistoryCount < maxRecords) ? wgrProbeHistoryCount : maxRecords;
    for (uint8_t i = 0; i < n; ++i) {
        const int idx = (static_cast<int>(wgrProbeHistoryHead) - 1 - i +
                         WGR_PROBE_HISTORY_SIZE) % WGR_PROBE_HISTORY_SIZE;
        out[i] = wgrProbeHistory[idx];
    }
    return n;
}

OregonRxStats getOregonRxStats() {
    return stats;
}

const char *oregonRadioError() {
    return lastError.c_str();
}

const char *oregonDecodeSourceName(OregonDecodeSource source) {
    switch (source) {
        case OregonDecodeSource::ClockSync: return "clock";
        case OregonDecodeSource::EdgeTiming: return "edge";
        case OregonDecodeSource::EdgeTimingWeak: return "edge-weak";
        case OregonDecodeSource::EdgeTimingState: return "edge-state";
        case OregonDecodeSource::BurstAdaptive: return "burst-adapt";
        case OregonDecodeSource::EdgeTimingV21: return "edge-v2.1";
        default: return "unknown";
    }
}

float currentRadioRssi() {
    return radio.getRSSI(false, true);
}
