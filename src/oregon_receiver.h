#pragma once
#include <Arduino.h>
#include "oregon_types.h"


enum class RfProtocolMode : uint8_t {
    Oregon = 0,
    LaCrosse = 1,
    Dual = 2
};

bool setRfProtocolMode(RfProtocolMode mode);
RfProtocolMode getRfProtocolMode();
const char *rfProtocolModeName(RfProtocolMode mode);

// Guadagno LNA SX1278. RadioLib accetta 0=AGC, 1..6=fisso; dalla Web UI
// limitiamo volutamente a 0..3 per evitare configurazioni inutilmente estreme.
uint8_t getRadioGain();
uint8_t getRadioGainForMode(RfProtocolMode mode);
bool setRadioGainForMode(RfProtocolMode mode, uint8_t gain);
const char *radioGainName(uint8_t gain);


enum class RfFrontendProfile : uint8_t {
    Stable = 0,       // 125 kHz + AGC
    WideAgc = 1,      // 166.7 kHz + AGC
    MaxGain = 2,      // 125 kHz + gain 1
    WideMaxGain = 3,  // 166.7 kHz + gain 1
    AutoScan = 4,
    Manual = 5
};

struct RfBurstRecord {
    uint32_t endedAtMs{0};
    uint16_t durationMs{0};
    uint16_t edges{0};
    float rssi{NAN};
    uint16_t onShortUs{0};
    uint16_t onLongUs{0};
    uint16_t offShortUs{0};
    uint16_t offLongUs{0};
    uint8_t timingMatchPct{0};
    bool osv3Like{false};
    bool adaptiveRecovered{false};
    bool likelyTechnoline{false};
};

struct RfBurstAnalyzerStats {
    uint32_t burstsTotal{0};
    uint32_t osv3LikeBursts{0};
    uint32_t discardedBursts{0};
    bool autoActive{false};
    uint8_t autoStep{0};
    uint32_t autoStepStartedMs{0};
    uint32_t autoStepDurationMs{0};
    uint8_t bestProfile{0};
    uint32_t profileBursts[4]{};
    uint32_t profileOsv3Like[4]{};
    uint32_t profileValidFrames[4]{};
    int32_t profileScore[4]{};
    uint32_t adaptiveAttempts{0};
    uint32_t adaptiveCandidates{0};
    uint32_t adaptiveRecovered{0};
    uint32_t adaptiveChecksumFail{0};
    uint32_t technolineLikeBursts{0};
};

float getRadioBandwidthKhz();
float getRadioBandwidthForMode(RfProtocolMode mode);
RfFrontendProfile getRadioFrontendProfile();
const char *radioFrontendProfileName(RfFrontendProfile profile);
bool setRadioFrontendProfile(RfFrontendProfile profile);
bool startRadioAutoCalibration();
void stopRadioAutoCalibration();
RfBurstAnalyzerStats getRfBurstAnalyzerStats();
uint8_t getRfBurstHistory(RfBurstRecord *out, uint8_t maxRecords);
void noteAcceptedOregonFrameForCalibration();

// V6.3: recovery/diagnostica per-burst opzionale. Il decoder live Technoline
// continua a funzionare anche con questa opzione OFF. Disabilitandola si
// elimina il lavoro extra del Burst Analyzer per massimizzare la regolarita'
// del WGR800 Oregon.
bool setBurstRecoveryEnabled(bool enabled);
bool burstRecoveryEnabled();


enum class OregonDecodeSource : uint8_t {
    Unknown = 0,
    ClockSync,
    EdgeTiming,
    EdgeTimingWeak,
    EdgeTimingState,
    BurstAdaptive,
    EdgeTimingV21
};

struct OregonRxStats {
    uint32_t chipsSampled{0};
    uint32_t ringOverflows{0};
    uint32_t manchesterErrors{0};

    uint32_t edgesCaptured{0};
    uint32_t preamblesDetected{0};
    uint32_t weakPreamblesDetected{0};
    uint32_t timingErrors{0};
    uint32_t syncErrors{0};
    uint32_t weakTimingErrors{0};
    uint32_t weakSyncErrors{0};
    uint32_t unknownHeaders{0};
    uint32_t weakUnknownHeaders{0};

    uint32_t framesDetected{0};
    uint32_t framesDropped{0};
    uint32_t edgeFrames{0};
    uint32_t weakEdgeFrames{0};
    uint32_t stateEdgeFrames{0};
    uint32_t clockFrames{0};
    uint32_t duplicateFrames{0};
    // WGR800 V3.0: scanner A1 indipendente dal preambolo.
    // "starts" conta le finestre che ricostruiscono un header A1; il frame
    // viene accettato soltanto dopo checksum valido.
    uint32_t windRecoveryStarts{0};
    uint32_t windRecoverySuccess{0};
    uint32_t windWindowChecksumFail{0};

    // Decoder state-aware basato sull'algoritmo half-time del documento OSV3.
    uint32_t statePreambles{0};
    uint32_t stateCandidates{0};
    uint32_t stateChecksumOk{0};
    uint32_t stateChecksumFail{0};
    uint32_t stateTimingErrors{0};
    uint32_t stateManchesterErrors{0};

    // Oregon Protocol 2.1: preambolo alternato, coppie invertito/originale
    // validate e checksum del payload prima dell'accodamento.
    uint32_t v21Preambles{0};
    uint32_t v21Candidates{0};
    uint32_t v21Frames{0};
    uint32_t v21UvCandidates{0};
    uint32_t v21UvFrames{0};
    uint32_t v21ChecksumFail{0};
    uint32_t v21PairErrors{0};

    // V5.6: decoder offline per-burst, adattivo sui timing reali del singolo
    // trasmettitore. Non sostituisce i decoder V4.8; aggiunge solo frame con
    // header noto e checksum valido.
    uint32_t burstAdaptiveFrames{0};
    uint32_t burstAdaptiveThermo{0};
    uint32_t burstAdaptiveWind{0};
    uint32_t burstAdaptiveRain{0};
    uint32_t burstAdaptiveUv{0};

    // Frame completi prima del parser/checksum.
    uint32_t rawThermoFrames{0};
    uint32_t rawWindFrames{0};
    uint32_t rawRainFrames{0};
    uint32_t rawUvFrames{0};

    // Distribuzione dei run di short prima di un long: utile per il WGR800.
    uint32_t preRun04_07{0};
    uint32_t preRun08_11{0};
    uint32_t preRun12_17{0};
    uint32_t preRun18_27{0};
    uint32_t preRun28Plus{0};
    uint16_t maxPreambleShorts{0};
    uint16_t lastStrongPreambleShorts{0};
    uint16_t lastWeakPreambleShorts{0};

    uint16_t shortAverageUs{0};
    uint16_t longAverageUs{0};
    uint16_t onShortAverageUs{0};
    uint16_t onLongAverageUs{0};
    uint16_t offShortAverageUs{0};
    uint16_t offLongAverageUs{0};
    uint8_t lastUnknownHeader{0};
    uint8_t lastWeakUnknownHeader{0};
};


struct WgrProbeRecord {
    uint32_t endedAtMs{0};
    uint16_t durationMs{0};
    uint16_t edges{0};
    float rssi{NAN};
    uint8_t timingMatchPct{0};
    uint8_t decodedHeader{0};   // AF/A1/A2/AD se un decoder live ha validato il burst
    bool osv3Like{false};
    bool cadence14{false};      // burst OSV3 non classificato a ~14 s dal precedente
};

struct WgrProbeStats {
    bool enabled{false};
    uint32_t burstsTotal{0};
    uint32_t osv3LikeBursts{0};
    uint32_t classifiedThermo{0};
    uint32_t classifiedWind{0};
    uint32_t classifiedRain{0};
    uint32_t classifiedUv{0};
    uint32_t unclassifiedOsv3{0};
    uint32_t cadence14Matches{0};
    uint32_t lastUnclassifiedMs{0};
    uint32_t lastUnclassifiedDeltaMs{0};
    uint16_t lastUnclassifiedDurationMs{0};
    uint16_t lastUnclassifiedEdges{0};
    uint8_t lastUnclassifiedMatchPct{0};
    float lastUnclassifiedRssi{NAN};
};

// V6.3: sonda RF passiva dedicata alla diagnosi del WGR800 1984 Protocol 3.0.
// E' RAM-only, OFF al boot e non modifica i decoder.
bool setWgrProbeEnabled(bool enabled);
bool wgrProbeEnabled();
WgrProbeStats getWgrProbeStats();
uint8_t getWgrProbeHistory(WgrProbeRecord *out, uint8_t maxRecords);

bool initOregonReceiver();
void serviceOregonReceiver();
bool prepareRadioForDeepSleep();
bool getOregonPacket(OregonPacket &packet);
OregonRxStats getOregonRxStats();
const char *oregonRadioError();
const char *oregonDecodeSourceName(OregonDecodeSource source);

float currentRadioRssi();
