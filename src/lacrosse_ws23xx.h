/*
 * Technoline / La Crosse WS23xx decoder interface.
 *
 * See NOTICE for rtl_433 and PracticalArduino protocol/code attribution.
 * This project is distributed under GPL-3.0-or-later.
 */

#pragma once
#include <Arduino.h>
#include <math.h>

static constexpr uint8_t LACROSSE_WS23XX_NIBBLES = 13;

enum class LaCrosseType : uint8_t {
    Unknown = 0,
    Temperature,
    Humidity,
    Rain,
    Wind,
    Gust
};

struct LaCrossePacket {
    uint8_t nibbles[LACROSSE_WS23XX_NIBBLES]{};
    uint32_t receivedAtMs{0};
    float rssi{NAN};
    uint8_t pulseLevel{0};
    uint8_t hypothesis{0};
    // 0=pulse-window rtl_433-style, 1=leader PracticalArduino, 2=burst recovery
    uint8_t decoder{0};
};

struct LaCrosseReading {
    LaCrosseType type{LaCrosseType::Unknown};
    uint8_t wsId{0};
    uint8_t sensorId{0};
    uint8_t dataFlags{0};
    uint8_t updateFlags{0};
    uint8_t nextUpdateCode{0};
    uint32_t receivedAtMs{0};
    float rssi{NAN};

    bool temperatureValid{false};
    float temperatureC{NAN};
    bool humidityValid{false};
    float humidityPct{NAN};
    bool rainValid{false};
    float rainTotalMm{NAN};
    bool windValid{false};
    float windKmh{NAN};
    bool gustValid{false};
    float gustKmh{NAN};
    bool directionValid{false};
    uint8_t directionIndex{0};
    float directionDeg{NAN};
};

struct LaCrosseRxStats {
    uint32_t edgesSeen{0};
    uint32_t resetGaps{0};
    uint32_t candidates{0};
    uint32_t validFrames{0};
    uint32_t duplicateFrames{0};
    uint32_t queueDrops{0};
    uint32_t headerFails{0};
    uint32_t checksumFails{0};
    uint32_t complementFails{0};
    uint32_t parityFails{0};
    uint32_t temperatureFrames{0};
    uint32_t humidityFrames{0};
    uint32_t rainFrames{0};
    uint32_t windFrames{0};
    uint32_t gustFrames{0};

    // V6.3: demodulatore live rtl_433-style. Ogni livello DIO2 viene provato
    // come possibile livello impulso. I gap non devono essere accoppiati:
    // il bit dipende solo dalla larghezza dell'impulso PWM.
    uint32_t streamPulses{0};
    uint32_t streamWindows{0};
    uint32_t streamHeaderMatches{0};
    uint32_t streamValidFrames{0};
    uint32_t streamResets{0};
    uint32_t streamPulseRejects{0};

    // Decoder di riferimento PracticalArduino per WS-2300-25S / WS-2355:
    // il bit e' codificato SOLO dalla durata del periodo HIGH (short=1,
    // long=0), con leader 00001. Eseguiamo due state machine in parallelo
    // perche' DIO2 dell'SX1278 puo' risultare invertito.
    uint32_t leaderStarts{0};
    uint32_t leaderLostZeroStarts{0};
    uint32_t leaderFrames{0};
    uint32_t leaderValidFrames{0};
    uint32_t leaderInvalidFrames{0};
    uint32_t leaderResets{0};
    uint32_t leaderPulseRejects{0};
    uint8_t leaderBits0{0};
    uint8_t leaderBits1{0};

    uint8_t streamBits0{0};
    uint8_t streamBits1{0};
    int8_t activeHypothesis{-1};
    uint32_t hypothesisValid[4]{};

    // Recovery opzionale per-burst. Disabilitabile da Web per confrontare
    // l'impatto sul percorso Oregon/WGR800.
    uint32_t burstAttempts{0};
    uint32_t burstWindows{0};
    uint32_t burstValidFrames{0};
    uint32_t burstRecoveredMissingEdge{0};
    uint32_t burstRejects{0};

    // Alias legacy mantenuti per compatibilita' Web/MQTT.
    uint32_t pulsePairs{0};
    uint32_t pairRejects{0};
    uint32_t frameLengthFails{0};
    uint32_t sequencePairs{0};
    uint32_t sequenceRestarts{0};
    uint32_t sequenceWindows{0};
    uint32_t sequenceHeaderMatches{0};
    uint32_t sequenceValidFrames{0};
    uint32_t sequenceGapRejects{0};
    uint32_t sequencePulseRejects{0};
    uint8_t lastSequenceBits0{0};
    uint8_t lastSequenceBits1{0};
    int8_t sequencePulseLevel{-1};
    uint32_t burstPulseWindows{0};
    uint32_t burstTooShort{0};
    uint16_t lastBurstIntervals{0};
    uint16_t lastBurstPulseCount0{0};
    uint16_t lastBurstPulseCount1{0};
    int8_t burstPulseLevel{-1};

    // Auto-calibrazione SOLO dopo un frame checksum-valid.
    uint16_t shortPulseAverageUs{0};
    uint16_t longPulseAverageUs{0};
    uint16_t gapAverageUs{0};
    uint16_t shortPeriodAverageUs{0};
    uint16_t longPeriodAverageUs{0};

    // Istogramma grezzo intervalli DIO2: <200, 200-599, 600-1099,
    // 1100-1799, 1800-3499, >=3500 us.
    uint32_t intervalBins[6]{};
};

void initLaCrosseWs23xx();
void resetLaCrosseDecoderState();
void processLaCrosseEdge(uint16_t durationUs, uint8_t previousRfLevel);
// Recovery offline opzionale su un burst completo gia' catturato.
bool processLaCrosseBurst(const uint16_t *durations, const uint8_t *levels,
                          uint16_t count, float rssi);
bool getLaCrossePacket(LaCrossePacket &packet);
bool parseLaCrossePacket(const LaCrossePacket &packet, LaCrosseReading &reading);
LaCrosseRxStats getLaCrosseRxStats();
const char *laCrosseTypeName(LaCrosseType type);
const char *laCrosseModelName(uint8_t wsId);
const char *laCrosseWindDirectionName(uint8_t index);
const char *laCrosseNextUpdateName(uint8_t code);
uint32_t laCrosseNextUpdateMs(uint8_t code);
