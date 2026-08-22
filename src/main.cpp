#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include "board_config.h"
#include "config.h"
#include "oregon_receiver.h"
#include "weather_parser.h"
#include "station_state.h"
#include "network_manager.h"
#include "mqtt_publisher.h"
#include "display_manager.h"
#include "barometer_manager.h"
#include "web_manager.h"
#include "lacrosse_ws23xx.h"
#include "lightning_manager.h"
#include "thermo_channel_manager.h"

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
StationState station;

namespace {
uint32_t lastStatePublishMs = 0;
uint32_t lastRfDiagnosticMs = 0;
uint32_t lastUnknownCount = 0;
uint32_t lastWeakUnknownCount = 0;

void printReading(const WeatherReading &r) {
    switch (r.type) {
        case SensorType::ThermoHygro:
            Serial.print(F(" T=")); Serial.print(r.temperatureC, 1);
            Serial.print(F("C H=")); Serial.print(r.humidityPct, 0); Serial.print('%');
            break;
        case SensorType::Wind:
            Serial.print(F(" avg=")); Serial.print(r.windAverageKmh, 1);
            Serial.print(F("km/h current=")); Serial.print(r.windGustKmh, 1);
            Serial.print(F("km/h dir=")); Serial.print(windDirectionName(r.windDirectionIndex));
            Serial.print('('); Serial.print(r.windDirectionDeg, 1); Serial.print(')');
            break;
        case SensorType::Rain:
            Serial.print(F(" total=")); Serial.print(r.rainTotalMm, 2);
            Serial.print(F("mm rate=")); Serial.print(r.rainRateMmH, 2); Serial.print(F("mm/h"));
            break;
        case SensorType::UV:
            Serial.print(F(" UV=")); Serial.print(r.uvIndex);
            break;
        default:
            break;
    }
    Serial.print(F(" model=")); Serial.print(sensorModelName(r.sensorCode));
    Serial.print(F(" code="));
    if (r.sensorCode < 0x1000) Serial.print('0');
    if (r.sensorCode < 0x0100) Serial.print('0');
    if (r.sensorCode < 0x0010) Serial.print('0');
    Serial.print(r.sensorCode, HEX);
    if (r.channel) { Serial.print(F(" ch=")); Serial.print(r.channel); }
    Serial.print(F(" batt=")); Serial.print(batteryStatusName(r));
}

void printPacket(const OregonPacket &packet, const WeatherReading *reading, bool accepted) {
#if SERIAL_PACKET_DUMP
    Serial.print(accepted ? F("[RF] OK  ") : F("[RF] DROP "));
    Serial.print(F("src="));
    Serial.print(oregonDecodeSourceName(static_cast<OregonDecodeSource>(packet.decodeSource)));
    Serial.print(F(" len=")); Serial.print(packet.length);
    Serial.print(F(" rssi=")); Serial.print(packet.rssi, 1);
    Serial.print(F(" data="));
    for (uint8_t i = 0; i < packet.length; ++i) {
        if (packet.bytes[i] < 0x10) Serial.print('0');
        Serial.print(packet.bytes[i], HEX);
        if (i + 1 < packet.length) Serial.print(' ');
    }
    if (reading) {
        Serial.print(F(" type="));
        Serial.print(sensorTypeName(reading->type));
        printReading(*reading);
    }
    Serial.println();
#else
    (void)packet; (void)reading; (void)accepted;
#endif
}

void printLaCrosseReading(const LaCrossePacket &p, const LaCrosseReading &r) {
    Serial.print(F("[LC] OK model=")); Serial.print(laCrosseModelName(r.wsId));
    Serial.print(F(" id=0x")); if (r.sensorId < 0x10) Serial.print('0'); Serial.print(r.sensorId, HEX);
    Serial.print(F(" type=")); Serial.print(laCrosseTypeName(r.type));
    Serial.print(F(" rssi=")); Serial.print(r.rssi, 1);
    Serial.print(F(" src=")); Serial.print(p.decoder == 1U ? F("leader") : (p.decoder == 2U ? F("burst") : F("window")));
    Serial.print(F(" hyp=")); Serial.print(p.hypothesis);
    switch (r.type) {
        case LaCrosseType::Temperature:
            Serial.print(F(" T=")); Serial.print(r.temperatureC, 1); Serial.print(F("C")); break;
        case LaCrosseType::Humidity:
            Serial.print(F(" H=")); Serial.print(r.humidityPct, 0); Serial.print('%'); break;
        case LaCrosseType::Rain:
            Serial.print(F(" rain=")); Serial.print(r.rainTotalMm, 2); Serial.print(F("mm")); break;
        case LaCrosseType::Wind:
            Serial.print(F(" wind=")); Serial.print(r.windKmh, 1); Serial.print(F("km/h dir="));
            Serial.print(r.directionDeg, 1); Serial.print(' '); Serial.print(laCrosseWindDirectionName(r.directionIndex)); break;
        case LaCrosseType::Gust:
            Serial.print(F(" gust=")); Serial.print(r.gustKmh, 1); Serial.print(F("km/h dir="));
            Serial.print(r.directionDeg, 1); Serial.print(' '); Serial.print(laCrosseWindDirectionName(r.directionIndex)); break;
        default: break;
    }
    Serial.print(F(" next=")); Serial.print(laCrosseNextUpdateName(r.nextUpdateCode));
    Serial.print(F(" raw="));
    for (uint8_t i=0;i<LACROSSE_WS23XX_NIBBLES;i++) Serial.print(p.nibbles[i], HEX);
    Serial.println();
}

void printRfDiagnostics(const OregonRxStats &rx) {
    Serial.print(F("[RF-DIAG] proto=")); Serial.print(rfProtocolModeName(getRfProtocolMode())); Serial.print(F(" mode=edge/raw"));
    Serial.print(F(" edges=")); Serial.print(rx.edgesCaptured);
    Serial.print(F(" preS=")); Serial.print(rx.preamblesDetected);
    Serial.print(F(" preW=")); Serial.print(rx.weakPreamblesDetected);
    Serial.print(F(" frames=")); Serial.print(rx.framesDetected);
    Serial.print(F(" strongOK=")); Serial.print(rx.edgeFrames);
    Serial.print(F(" weakOK=")); Serial.print(rx.weakEdgeFrames);
    Serial.print(F(" raw[AF/A1/A2/AD]="));
    Serial.print(rx.rawThermoFrames); Serial.print('/');
    Serial.print(rx.rawWindFrames); Serial.print('/');
    Serial.print(rx.rawRainFrames); Serial.print('/');
    Serial.print(rx.rawUvFrames);
    Serial.print(F(" errS[t/s]=")); Serial.print(rx.timingErrors); Serial.print('/'); Serial.print(rx.syncErrors);
    Serial.print(F(" errW[t/s]=")); Serial.print(rx.weakTimingErrors); Serial.print('/'); Serial.print(rx.weakSyncErrors);
    Serial.print(F(" ovf=")); Serial.print(rx.ringOverflows);
    Serial.print(F(" Wscan[ok/head/csKO]=")); Serial.print(rx.windRecoverySuccess); Serial.print('/'); Serial.print(rx.windRecoveryStarts); Serial.print('/'); Serial.print(rx.windWindowChecksumFail);
    const WgrProbeStats wp = getWgrProbeStats();
    if (wp.enabled) {
        Serial.print(F(" Wprobe[osv3/uncl/14s]=")); Serial.print(wp.osv3LikeBursts); Serial.print('/'); Serial.print(wp.unclassifiedOsv3); Serial.print('/'); Serial.print(wp.cadence14Matches);
    }
    Serial.print(F(" State[pre/cand/ok/fail/t/m]="));
    Serial.print(rx.statePreambles); Serial.print('/');
    Serial.print(rx.stateCandidates); Serial.print('/');
    Serial.print(rx.stateChecksumOk); Serial.print('/');
    Serial.print(rx.stateChecksumFail); Serial.print('/');
    Serial.print(rx.stateTimingErrors); Serial.print('/');
    Serial.print(rx.stateManchesterErrors);
    Serial.print(F(" runs[4/8/12/18/28+]="));
    Serial.print(rx.preRun04_07); Serial.print('/');
    Serial.print(rx.preRun08_11); Serial.print('/');
    Serial.print(rx.preRun12_17); Serial.print('/');
    Serial.print(rx.preRun18_27); Serial.print('/');
    Serial.print(rx.preRun28Plus);
    if (rx.shortAverageUs) {
        Serial.print(F(" short~")); Serial.print(rx.shortAverageUs); Serial.print(F("us"));
    }
    if (rx.longAverageUs) {
        Serial.print(F(" long~")); Serial.print(rx.longAverageUs); Serial.print(F("us"));
    }
    if (rx.onShortAverageUs || rx.offShortAverageUs) {
        Serial.print(F(" ON[S/L]=")); Serial.print(rx.onShortAverageUs); Serial.print('/'); Serial.print(rx.onLongAverageUs);
        Serial.print(F(" OFF[S/L]=")); Serial.print(rx.offShortAverageUs); Serial.print('/'); Serial.print(rx.offLongAverageUs);
    }
    Serial.println();

    if (rx.unknownHeaders != lastUnknownCount) {
        lastUnknownCount = rx.unknownHeaders;
        Serial.print(F("[RF-DIAG] strong unknown header=0x"));
        if (rx.lastUnknownHeader < 0x10) Serial.print('0');
        Serial.println(rx.lastUnknownHeader, HEX);
    }
    if (rx.weakUnknownHeaders != lastWeakUnknownCount) {
        lastWeakUnknownCount = rx.weakUnknownHeaders;
        Serial.print(F("[RF-DIAG] weak unknown header=0x"));
        if (rx.lastWeakUnknownHeader < 0x10) Serial.print('0');
        Serial.println(rx.lastWeakUnknownHeader, HEX);
    }
}
}

void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.println();
    Serial.println(F("========================================"));
    Serial.print(F(" Oregon + Technoline 433 Gateway ")); Serial.println(FIRMWARE_VERSION);
    Serial.print(F(" Board: ")); Serial.println(BOARD_NAME);
    Serial.println(F(" RF: SX1278 OOK direct RAW EDGE"));
    Serial.println(F(" Oregon: OSV3 V4.8 multi-decoder"));
    Serial.println(F(" Technoline: WS230x / WS-2310 rtl_433-compatible OOK/PWM 52-bit"));
    Serial.println(F(" RF mode: DUAL simultaneo + modalita singole diagnostiche"));
    Serial.println(F(" Web: HTTP + hostname/mDNS configurabile"));
    Serial.println(F("========================================"));

    pinMode(BOARD_LED_PIN, OUTPUT);
    digitalWrite(BOARD_LED_PIN, BOARD_LED_OFF);

    initThermoChannels();
    initDisplay();
    initBarometer();
    initLightning();
    initNetwork();
    initMQTT(mqttClient, wifiClient);
    initWeb(station);
    initLaCrosseWs23xx();

    if (!initOregonReceiver()) {
        Serial.print(F("[RF] inizializzazione fallita: "));
        Serial.println(oregonRadioError());
    } else {
        Serial.println(F("[RF] SX1278 pronto: OOK raw edge RX, BitSync OFF"));
    }
}

void loop() {
    // RF per primo: il ring viene svuotato prima di rete/Web/MQTT.
    serviceOregonReceiver();

    OregonPacket packet;
    while (getOregonPacket(packet)) {
        WeatherReading reading;
        if (parseWeatherPacket(packet, reading)) {
            noteAcceptedOregonFrameForCalibration();
            bool applyThermoPrimary = true;
            if (reading.type == SensorType::ThermoHygro) {
                noteThermoChannelReading(reading);
                applyThermoPrimary = thermoChannelIsPrimary(reading.channel);
            }
            applyWeatherReading(station, reading, applyThermoPrimary);
            printPacket(packet, &reading, true);
            recordWebPacket(packet, &reading, true);
            publishWeatherReading(mqttClient, reading, packet);
            digitalWrite(BOARD_LED_PIN, BOARD_LED_ON);
        } else {
            station.rejectedPacketCount++;
            printPacket(packet, nullptr, false);
            recordWebPacket(packet, nullptr, false);
        }
    }

    LaCrossePacket lcPacket;
    while (getLaCrossePacket(lcPacket)) {
        // RSSI e' letto al momento dell'estrazione; il pacchetto dura solo ~0.15 s.
        lcPacket.rssi = currentRadioRssi();
        LaCrosseReading lcReading;
        if (parseLaCrossePacket(lcPacket, lcReading)) {
            lcReading.rssi = lcPacket.rssi;
            applyLaCrosseReading(station, lcReading);
            printLaCrosseReading(lcPacket, lcReading);
            recordWebLaCrossePacket(lcPacket, &lcReading, true);
            publishLaCrosseReading(mqttClient, lcReading, lcPacket);
            digitalWrite(BOARD_LED_PIN, BOARD_LED_ON);
        } else {
            station.lacrosse.rejectedPacketCount++;
            recordWebLaCrossePacket(lcPacket, nullptr, false);
        }
    }

    serviceDisplayButton();
    serviceWiFi();
    serviceWeb();

    // V6.3: seconda passata RF subito dopo il Web. Non cambia il decoder,
    // ma riduce la latenza con richieste HTTP frequenti e mantiene il ring
    // piu' scarico durante la fase di acquisizione.
    serviceOregonReceiver();

    // AS3935 e' servito solo dopo la seconda passata RF. L'ISR imposta una flag:
    // nessuna lettura I2C e nessun delay bloccante vengono eseguiti nell'interrupt.
    serviceLightning(mqttClient);
    serviceMQTT(mqttClient);
    serviceBarometer(station);

    static uint32_t ledOnMs = 0;
    static bool ledActive = false;
    if (digitalRead(BOARD_LED_PIN) == BOARD_LED_ON && !ledActive) {
        ledOnMs = millis();
        ledActive = true;
    }
    if (ledActive && static_cast<uint32_t>(millis() - ledOnMs) > 60) {
        digitalWrite(BOARD_LED_PIN, BOARD_LED_OFF);
        ledActive = false;
    }

    const OregonRxStats rxStats = getOregonRxStats();
    updateDisplay(station, rxStats, getLaCrosseRxStats(), wifiConnected(), mqttConnected(mqttClient));

    const uint32_t now = millis();
    if (static_cast<uint32_t>(now - lastRfDiagnosticMs) >= RF_DIAGNOSTIC_INTERVAL_MS) {
        lastRfDiagnosticMs = now;
        printRfDiagnostics(rxStats);
        const LaCrosseRxStats lc = getLaCrosseRxStats();
        const RfBurstAnalyzerStats bs = getRfBurstAnalyzerStats();
        Serial.print(F("[BURST] total=")); Serial.print(bs.burstsTotal);
        Serial.print(F(" osv3=")); Serial.print(bs.osv3LikeBursts);
        Serial.print(F(" discard=")); Serial.print(bs.discardedBursts);
        Serial.print(F(" profile=")); Serial.print(radioFrontendProfileName(getRadioFrontendProfile()));
        Serial.print(F(" BW=")); Serial.print(getRadioBandwidthKhz(), 1);
        Serial.print(F(" gain=")); Serial.print(getRadioGain());
        if (bs.autoActive) {
            Serial.print(F(" AUTO step=")); Serial.print(bs.autoStep + 1U); Serial.print(F("/4"));
        }
        Serial.println();

        Serial.print(F("[TECH-DIAG] valid=")); Serial.print(lc.validFrames);
        Serial.print(F(" cand=")); Serial.print(lc.candidates);
        Serial.print(F(" T/H/R/W/G=")); Serial.print(lc.temperatureFrames); Serial.print('/');
        Serial.print(lc.humidityFrames); Serial.print('/'); Serial.print(lc.rainFrames); Serial.print('/');
        Serial.print(lc.windFrames); Serial.print('/'); Serial.print(lc.gustFrames);
        Serial.print(F(" fail[h/c/p/s]=")); Serial.print(lc.headerFails); Serial.print('/');
        Serial.print(lc.complementFails); Serial.print('/'); Serial.print(lc.parityFails); Serial.print('/'); Serial.print(lc.checksumFails);
        Serial.print(F(" seq[pair/win/ok]=")); Serial.print(lc.sequencePairs); Serial.print('/'); Serial.print(lc.sequenceWindows); Serial.print('/'); Serial.print(lc.sequenceValidFrames);
        Serial.print(F(" restart=")); Serial.print(lc.sequenceRestarts);
        Serial.print(F(" reject[P/G]=")); Serial.print(lc.sequencePulseRejects); Serial.print('/'); Serial.print(lc.sequenceGapRejects);
        Serial.print(F(" bits[0/1]=")); Serial.print(lc.lastSequenceBits0); Serial.print('/'); Serial.print(lc.lastSequenceBits1);
        Serial.print(F(" pulse[S/L/G]=")); Serial.print(lc.shortPulseAverageUs); Serial.print('/'); Serial.print(lc.longPulseAverageUs); Serial.print('/'); Serial.print(lc.gapAverageUs);
        Serial.print(F(" bins[<200/200-599/600-1099/1100-1799/1800-3499/>=3500]="));
        for (uint8_t i=0;i<6;i++){ if(i) Serial.print('/'); Serial.print(lc.intervalBins[i]); }
        Serial.print(F(" hyp=")); Serial.print(lc.activeHypothesis); Serial.print(F(" ["));
        for (uint8_t i=0;i<4;i++){ if(i) Serial.print('/'); Serial.print(lc.hypothesisValid[i]); }
        Serial.println(']');
    }

    if (mqttClient.connected() && static_cast<uint32_t>(now - lastStatePublishMs) >= 30000UL) {
        lastStatePublishMs = now;
        publishStationState(mqttClient, station, rxStats, getLaCrosseRxStats());
    }

    delay(1);
}
