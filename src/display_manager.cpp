#include "display_manager.h"
#include <Wire.h>
#include <U8g2lib.h>
#include <Preferences.h>
#include "board_config.h"
#include "config.h"
#include "network_manager.h"
#include "weather_parser.h"
#include "barometer_manager.h"
#include "lacrosse_ws23xx.h"
#include "oregon_receiver.h"
#include "lightning_manager.h"

namespace {
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
uint32_t lastRefreshMs = 0;
uint32_t pageEpochMs = 0;
uint8_t page = 0;
bool displayOn = true;
bool displayPrefsReady = false;
Preferences displayPrefs;
DisplayRuntimeConfig displayCfg{};
uint32_t webSecurityBootstrapUntilMs = 0;
String webSecurityBootstrapUser;
String webSecurityBootstrapPasswordText;

// Compact live registry for OLED only. It stores no history: ten slots mirror
// the maximum Web session registry and cost only a few bytes per transmitter.
struct OledOregonSlot {
    uint32_t updatedMs{0};
    uint16_t code{0};
    uint8_t channel{0};
    uint8_t rollingCode{0};
    uint8_t type{0};
    uint8_t batteryState{0}; // 0=N/D, 1=OK, 2=LOW
    int8_t uvIndex{-1};
    int8_t rssiDbm{-127};
};
OledOregonSlot oledOregonSlots[10]{};
uint8_t oledSensorWindow{0};
uint32_t oledSensorWindowEpoch{0};

char oledRssiGrade(int8_t dbm) {
    if (dbm <= -127) return '-';
    if (dbm >= -100) return 'G';
    if (dbm >= -115) return 'Y';
    return 'R';
}

char oledBatteryGrade(uint8_t state) {
    if (state == 1U) return '+';
    if (state == 2U) return '!';
    return '-';
}

char oledSensorTypeChar(uint8_t type) {
    switch (static_cast<SensorType>(type)) {
        case SensorType::ThermoHygro: return 'T';
        case SensorType::Wind: return 'W';
        case SensorType::Rain: return 'R';
        case SensorType::UV: return 'U';
        default: return '?';
    }
}

#if OLED_BUTTON_ENABLE
bool buttonRawPressed = false;
bool buttonStablePressed = false;
uint32_t buttonLastChangeMs = 0;
uint32_t buttonPressedAtMs = 0;
#endif

DisplayRuntimeConfig defaults() { return DisplayRuntimeConfig{}; }

void normalize(DisplayRuntimeConfig &c) {
    c.pageMask &= DISPLAY_PAGE_ALL;
    if (!c.pageMask) c.pageMask = DISPLAY_PAGE_ALL;
    c.environmentFields &= DISPLAY_ENV_ALL;
    c.windRainFields &= DISPLAY_WIND_ALL;
    c.technolineFields &= DISPLAY_TECH_ALL;
    c.pressureFields &= DISPLAY_PRESS_ALL;
    c.statusFields &= DISPLAY_STATUS_ALL;
    c.lightningFields &= DISPLAY_AS_ALL;
    if (c.pageIntervalSec < 2U) c.pageIntervalSec = 2U;
    if (c.pageIntervalSec > 60U) c.pageIntervalSec = 60U;
    if (c.contrast < 8U) c.contrast = 8U;
}

bool sameConfig(const DisplayRuntimeConfig &a, const DisplayRuntimeConfig &b) {
    return a.pageMask == b.pageMask &&
           a.environmentFields == b.environmentFields &&
           a.windRainFields == b.windRainFields &&
           a.technolineFields == b.technolineFields &&
           a.pressureFields == b.pressureFields &&
           a.statusFields == b.statusFields &&
           a.lightningFields == b.lightningFields &&
           a.pageIntervalSec == b.pageIntervalSec &&
           a.contrast == b.contrast;
}

bool verifyStoredConfig(Preferences &p, const DisplayRuntimeConfig &c) {
    DisplayRuntimeConfig d = defaults();
    normalize(d);
    return p.getUChar("pages", d.pageMask) == c.pageMask &&
           p.getUChar("env", d.environmentFields) == c.environmentFields &&
           p.getUChar("wind", d.windRainFields) == c.windRainFields &&
           p.getUChar("tech", d.technolineFields) == c.technolineFields &&
           p.getUChar("press", d.pressureFields) == c.pressureFields &&
           p.getUChar("status", d.statusFields) == c.statusFields &&
           p.getUChar("as3935", d.lightningFields) == c.lightningFields &&
           p.getUShort("page_s", d.pageIntervalSec) == c.pageIntervalSec &&
           p.getUChar("contrast", d.contrast) == c.contrast;
}

bool pageEnabled(uint8_t p) {
    return p < 7U && (displayCfg.pageMask & static_cast<uint8_t>(1U << p)) != 0U;
}

uint8_t firstEnabledPage() {
    for (uint8_t p = 0; p < 7U; ++p) if (pageEnabled(p)) return p;
    return 0U;
}

uint8_t nextEnabledPage(uint8_t current) {
    for (uint8_t step = 1; step <= 7U; ++step) {
        const uint8_t p = static_cast<uint8_t>((current + step) % 7U);
        if (pageEnabled(p)) return p;
    }
    return firstEnabledPage();
}

void header(const char *title, bool wifiOk, bool mqttOk) {
    oled.setFont(u8g2_font_6x10_tf);
    oled.drawStr(0, 9, title);
    oled.drawStr(100, 9, wifiOk ? "W" : "-");
    oled.drawStr(118, 9, mqttOk ? "M" : "-");
    oled.drawHLine(0, 12, 128);
}

void drawLine(const char *text, uint8_t &y, uint8_t step = 10U) {
    if (y > 63U) return;
    oled.drawStr(0, y, text);
    y = static_cast<uint8_t>(y + step);
}

void renderEnvironment(const StationState &s, bool wifiOk, bool mqttOk) {
    header("ESTERNO", wifiOk, mqttOk);
    char line[48];
    oled.setFont(u8g2_font_5x8_tf);
    uint8_t y = 23;
    const uint32_t now = millis();

    if (displayCfg.environmentFields & DISPLAY_ENV_TEMP_HUM) {
        if (s.thermoValid && sensorFresh(s.thermoUpdatedMs, now))
            snprintf(line, sizeof(line), "T %.1fC  H %.0f%%", s.temperatureC, s.humidityPct);
        else snprintf(line, sizeof(line), "T --.-C  H --%%");
        drawLine(line, y);
    }
    const bool showHeatUv = (displayCfg.environmentFields & DISPLAY_ENV_HEAT_UV) != 0U;
    if (displayCfg.environmentFields & DISPLAY_ENV_DEW) {
        if (s.dewPointValid && showHeatUv && s.heatIndexValid)
            snprintf(line, sizeof(line), "Dew %.1f Heat %.1f", s.dewPointC, s.heatIndexC);
        else if (s.dewPointValid) snprintf(line, sizeof(line), "Dew %.1fC", s.dewPointC);
        else snprintf(line, sizeof(line), "Dew --.-C");
        drawLine(line, y);
    }
    if (showHeatUv) {
        if (!(displayCfg.environmentFields & DISPLAY_ENV_DEW)) {
            if (s.heatIndexValid) snprintf(line, sizeof(line), "Heat %.1fC", s.heatIndexC);
            else snprintf(line, sizeof(line), "Heat N/A");
            drawLine(line, y);
        }
        int uvA = -1, uvB = -1;
        uint16_t codeA = 0, codeB = 0;
        for (uint8_t i = 0; i < 10U; ++i) {
            const OledOregonSlot &u = oledOregonSlots[i];
            if (static_cast<SensorType>(u.type) != SensorType::UV || u.uvIndex < 0 || !u.updatedMs ||
                static_cast<uint32_t>(now - u.updatedMs) > 300000UL) continue;
            if (uvA < 0) { uvA = u.uvIndex; codeA = u.code; }
            else if (uvB < 0) { uvB = u.uvIndex; codeB = u.code; break; }
        }
        if (uvA >= 0 && uvB >= 0) snprintf(line, sizeof(line), "UV %04X:%d %04X:%d", codeA, uvA, codeB, uvB);
        else if (uvA >= 0) snprintf(line, sizeof(line), "UV %04X:%d", codeA, uvA);
        else snprintf(line, sizeof(line), "UV --");
        drawLine(line, y);
    }
    if (displayCfg.environmentFields & DISPLAY_ENV_BATTERY) {
        snprintf(line, sizeof(line), "BAT T:%s U:%s", sensorBatteryName(s.thermoSensor), sensorBatteryName(s.uvSensor));
        drawLine(line, y);
    }
    if (y == 23) drawLine("Nessun campo selezionato", y);
}

void renderWindRain(const StationState &s, bool wifiOk, bool mqttOk) {
    header("VENTO / PIOGGIA", wifiOk, mqttOk);
    char line[48];
    oled.setFont(u8g2_font_5x8_tf);
    uint8_t y = 23;
    const uint32_t now = millis();
    const bool windFresh = s.windValid && sensorFresh(s.windUpdatedMs, now);

    if (displayCfg.windRainFields & DISPLAY_WIND_SPEED_GUST) {
        if (windFresh) snprintf(line, sizeof(line), "V %.1f  G %.1f km/h", s.windAverageKmh, s.windGustKmh);
        else snprintf(line, sizeof(line), "V --  G -- km/h");
        drawLine(line, y);
    }
    if (displayCfg.windRainFields & DISPLAY_WIND_DIRECTION) {
        if (windFresh) snprintf(line, sizeof(line), "%s %.0f deg", windDirectionName(s.windDirectionIndex), s.windDirectionDeg);
        else snprintf(line, sizeof(line), "Direzione --");
        drawLine(line, y);
    }
    if (displayCfg.windRainFields & DISPLAY_WIND_RAIN) {
        if (s.rainValid && sensorFresh(s.rainUpdatedMs, now))
            snprintf(line, sizeof(line), "Rain %.2f  rate %.2f", s.rainTotalMm, s.rainRateMmH);
        else snprintf(line, sizeof(line), "Pioggia --");
        drawLine(line, y);
    }
    if (displayCfg.windRainFields & DISPLAY_WIND_BATTERY) {
        snprintf(line, sizeof(line), "BAT W:%s R:%s", sensorBatteryName(s.windSensor), sensorBatteryName(s.rainSensor));
        drawLine(line, y);
    }
    if (y == 23) drawLine("Nessun campo selezionato", y);
}

void renderLaCrosse(const StationState &s, bool wifiOk, bool mqttOk) {
    header("TECHNOLINE", wifiOk, mqttOk);
    char line[52];
    oled.setFont(u8g2_font_5x8_tf);
    uint8_t y = 23;
    const auto &lc = s.lacrosse;

    if (displayCfg.technolineFields & DISPLAY_TECH_TEMP_HUM) {
        if (lc.temperatureValid || lc.humidityValid) {
            char t[12], h[10];
            if (lc.temperatureValid) snprintf(t, sizeof(t), "%.1fC", lc.temperatureC); else snprintf(t, sizeof(t), "--.-C");
            if (lc.humidityValid) snprintf(h, sizeof(h), "%.0f%%", lc.humidityPct); else snprintf(h, sizeof(h), "--%%");
            snprintf(line, sizeof(line), "T %s  H %s", t, h);
        } else snprintf(line, sizeof(line), "T --.-C  H --%%");
        drawLine(line, y);
    }
    if (displayCfg.technolineFields & DISPLAY_TECH_WIND_GUST) {
        char w[12], g[12];
        if (lc.windValid) snprintf(w, sizeof(w), "%.1f", lc.windKmh); else snprintf(w, sizeof(w), "--");
        if (lc.gustValid) snprintf(g, sizeof(g), "%.1f", lc.gustKmh); else snprintf(g, sizeof(g), "--");
        snprintf(line, sizeof(line), "W %s  G %s km/h", w, g);
        drawLine(line, y);
    }
    if (displayCfg.technolineFields & DISPLAY_TECH_DIRECTION) {
        if (lc.directionValid) snprintf(line, sizeof(line), "%s %.0f deg", laCrosseWindDirectionName(lc.windDirectionIndex), lc.windDirectionDeg);
        else snprintf(line, sizeof(line), "Direzione --");
        drawLine(line, y);
    }
    if (displayCfg.technolineFields & DISPLAY_TECH_RAIN) {
        if (lc.rainValid) snprintf(line, sizeof(line), "Rain %.2f mm", lc.rainTotalMm);
        else snprintf(line, sizeof(line), "Rain --");
        drawLine(line, y);
    }
    if (displayCfg.technolineFields & DISPLAY_TECH_META) {
        if (isfinite(lc.lastRssi)) {
            int rssi = static_cast<int>(lroundf(lc.lastRssi));
            if (rssi < -126) rssi = -126;
            if (rssi > 0) rssi = 0;
            snprintf(line, sizeof(line), "ID%02X %ddBm %c B-", lc.sensorId, rssi,
                     oledRssiGrade(static_cast<int8_t>(rssi)));
        } else {
            snprintf(line, sizeof(line), "ID%02X RSSI-- B-", lc.sensorId);
        }
        drawLine(line, y);
    }
    if (y == 23) drawLine("Nessun campo selezionato", y);
}

void renderPressure(const StationState &s, bool wifiOk, bool mqttOk) {
    header("BAROMETRO", wifiOk, mqttOk);
    char line[48];
    oled.setFont(u8g2_font_5x8_tf);
    uint8_t y = 23;

    if (!s.pressureValid) {
        drawLine("BME280 non rilevato", y);
        drawLine("I2C 0x76 / 0x77", y);
        return;
    }
    if (displayCfg.pressureFields & DISPLAY_PRESS_STATION) {
        snprintf(line, sizeof(line), "Psta %.1f hPa", s.pressureAbsoluteHpa);
        drawLine(line, y);
    }
    if (displayCfg.pressureFields & DISPLAY_PRESS_ALTIMETER) {
        snprintf(line, sizeof(line), "Alt %.1f hPa", s.pressureSeaLevelHpa);
        drawLine(line, y);
    }
    if (displayCfg.pressureFields & DISPLAY_PRESS_TREND) {
        if (s.pressureTrendValid) snprintf(line, sizeof(line), "Trend %+.1f/3h", s.pressureTrendHpa3h);
        else snprintf(line, sizeof(line), "Trend acquisizione");
        drawLine(line, y);
    }
    if (displayCfg.pressureFields & DISPLAY_PRESS_FORECAST) {
        snprintf(line, sizeof(line), "%s", barometerForecastName(s));
        drawLine(line, y);
    }
    if (y == 23) drawLine("Nessun campo selezionato", y);
}


void renderLightning(bool wifiOk, bool mqttOk) {
    header("AS3935 FULMINI", wifiOk, mqttOk);
    char line[56];
    oled.setFont(u8g2_font_5x8_tf);
    uint8_t y = 23;
    const LightningState s = getLightningState();
    const LightningConfig c = getLightningConfig();

    if (displayCfg.lightningFields & DISPLAY_AS_STATUS) {
        if (!s.enabled) snprintf(line, sizeof(line), "Sensore DISABILITATO");
        else snprintf(line, sizeof(line), "Sens %s IRQ %s CAL %s",
                      s.detected ? "OK" : "KO", s.irqOk ? "OK" : "KO", s.calibrationOk ? "OK" : "KO");
        drawLine(line, y);
    }
    if (displayCfg.lightningFields & DISPLAY_AS_LAST_STRIKE) {
        if (!s.lastLightningMs) snprintf(line, sizeof(line), "Ultimo fulmine --");
        else if (s.distanceOutOfRange) snprintf(line, sizeof(line), "Ult >40km E%lu", static_cast<unsigned long>(s.lastEnergy));
        else snprintf(line, sizeof(line), "Ult %ukm E%lu", s.lastDistanceKm, static_cast<unsigned long>(s.lastEnergy));
        drawLine(line, y);
    }
    if (displayCfg.lightningFields & DISPLAY_AS_COUNTERS) {
        snprintf(line, sizeof(line), "L%lu N%lu D%lu IRQ%lu",
                 static_cast<unsigned long>(s.lightningTotal), static_cast<unsigned long>(s.noiseTotal),
                 static_cast<unsigned long>(s.disturberTotal), static_cast<unsigned long>(s.irqTotal));
        drawLine(line, y);
    }
    if (displayCfg.lightningFields & DISPLAY_AS_FILTERS) {
        snprintf(line, sizeof(line), "%s NF%u WD%u SP%u M%u",
                 c.indoor ? "IN" : "OUT", c.noiseFloor, c.watchdogThreshold, c.spikeRejection, c.minStrikes);
        drawLine(line, y);
    }
    if (displayCfg.lightningFields & DISPLAY_AS_BUS_TUNING) {
        snprintf(line, sizeof(line), "I2C%02X GPIO%d %ldkHz",
                 c.i2cAddress, static_cast<int>(c.irqPin), static_cast<long>(s.resonanceHz / 1000L));
        drawLine(line, y);
    }
    if (y == 23) drawLine("Nessun campo selezionato", y);
}

void renderStatus(const StationState &, const OregonRxStats &rx, const LaCrosseRxStats &lc, bool wifiOk, bool mqttOk) {
    const RfProtocolMode mode = getRfProtocolMode();
    header(mode==RfProtocolMode::Dual ? "RF DUAL" : (mode==RfProtocolMode::Oregon ? "RF OREGON" : "RF TECHNOLINE"), wifiOk, mqttOk);
    char line[52];
    oled.setFont(u8g2_font_5x8_tf);
    uint8_t y = 23;

    if (displayCfg.statusFields & DISPLAY_STATUS_OREGON) {
        snprintf(line, sizeof(line), "AF%lu A1%lu A2%lu AD%lu",
                 static_cast<unsigned long>(rx.rawThermoFrames), static_cast<unsigned long>(rx.rawWindFrames),
                 static_cast<unsigned long>(rx.rawRainFrames), static_cast<unsigned long>(rx.rawUvFrames));
        drawLine(line, y);
    }
    if (displayCfg.statusFields & DISPLAY_STATUS_DECODER) {
        snprintf(line, sizeof(line), "State %lu Wscan %lu/%lu",
                 static_cast<unsigned long>(rx.stateEdgeFrames), static_cast<unsigned long>(rx.windRecoverySuccess),
                 static_cast<unsigned long>(rx.windRecoveryStarts));
        drawLine(line, y);
    }
    if (displayCfg.statusFields & DISPLAY_STATUS_TIMING) {
        snprintf(line, sizeof(line), "run4:%lu 8:%lu 12:%lu 18:%lu",
                 static_cast<unsigned long>(rx.preRun04_07), static_cast<unsigned long>(rx.preRun08_11),
                 static_cast<unsigned long>(rx.preRun12_17), static_cast<unsigned long>(rx.preRun18_27));
        drawLine(line, y);
    }
    if (displayCfg.statusFields & DISPLAY_STATUS_TECH) {
        snprintf(line, sizeof(line), "LC %lu T%lu W%lu R%lu",
                 static_cast<unsigned long>(lc.validFrames), static_cast<unsigned long>(lc.temperatureFrames),
                 static_cast<unsigned long>(lc.windFrames + lc.gustFrames), static_cast<unsigned long>(lc.rainFrames));
        drawLine(line, y);
    }
    if (displayCfg.statusFields & DISPLAY_STATUS_NETWORK) {
        if (wifiConnected()) snprintf(line, sizeof(line), "WEB %s", wifiIpAddress().c_str());
        else snprintf(line, sizeof(line), "WEB non connesso");
        drawLine(line, y);
    }
    if (y == 23) drawLine("Nessun campo selezionato", y);
}

void renderSensorHealth(bool wifiOk, bool mqttOk) {
    const uint32_t now = millis();
    uint8_t active[10];
    uint8_t count = 0;
    for (uint8_t i = 0; i < 10U; ++i) {
        if (!oledOregonSlots[i].updatedMs) continue;
        if (static_cast<uint32_t>(now - oledOregonSlots[i].updatedMs) > 600000UL) continue;
        active[count++] = i;
    }

    if (oledSensorWindowEpoch != pageEpochMs) {
        oledSensorWindowEpoch = pageEpochMs;
        if (count > 5U) oledSensorWindow = static_cast<uint8_t>((oledSensorWindow + 5U) % count);
        else oledSensorWindow = 0;
    }

    char title[20];
    if (count > 5U) snprintf(title, sizeof(title), "SENSORI RF %u/%u", oledSensorWindow / 5U + 1U, (count + 4U) / 5U);
    else snprintf(title, sizeof(title), "SENSORI RF");
    header(title, wifiOk, mqttOk);
    oled.setFont(u8g2_font_5x8_tf);
    uint8_t y = 23;
    if (!count) {
        drawLine("Nessun Oregon recente", y);
        return;
    }

    const uint8_t rows = count < 5U ? count : 5U;
    for (uint8_t n = 0; n < rows && y <= 63U; ++n) {
        const uint8_t pos = static_cast<uint8_t>((oledSensorWindow + n) % count);
        const OledOregonSlot &s = oledOregonSlots[active[pos]];
        char line[30];
        if (static_cast<SensorType>(s.type) == SensorType::UV && s.uvIndex >= 0) {
            snprintf(line, sizeof(line), "%c%u %04X U%d %d%c B%c", oledSensorTypeChar(s.type), s.channel,
                     s.code, static_cast<int>(s.uvIndex), static_cast<int>(s.rssiDbm),
                     oledRssiGrade(s.rssiDbm), oledBatteryGrade(s.batteryState));
        } else {
            snprintf(line, sizeof(line), "%c%u %04X %d%c B%c", oledSensorTypeChar(s.type), s.channel,
                     s.code, static_cast<int>(s.rssiDbm), oledRssiGrade(s.rssiDbm),
                     oledBatteryGrade(s.batteryState));
        }
        drawLine(line, y);
    }
}

void applyDisplayPower() {
    if (displayOn) {
        oled.setPowerSave(0);
        oled.setContrast(displayCfg.contrast);
        lastRefreshMs = 0;
        pageEpochMs = millis();
        if (!pageEnabled(page)) page = firstEnabledPage();
    } else {
        oled.clearBuffer();
        oled.sendBuffer();
        oled.setPowerSave(1);
    }
}
} // namespace

void noteDisplayOregonReading(const WeatherReading &reading) {
    if (reading.type == SensorType::Unknown) return;
    OledOregonSlot *slot = nullptr;
    OledOregonSlot *oldest = &oledOregonSlots[0];
    for (uint8_t i = 0; i < 10U; ++i) {
        OledOregonSlot &candidate = oledOregonSlots[i];
        if (candidate.updatedMs == 0) { slot = &candidate; break; }
        if (candidate.code == reading.sensorCode && candidate.channel == reading.channel &&
            candidate.rollingCode == reading.rollingCode) { slot = &candidate; break; }
        if (static_cast<int32_t>(candidate.updatedMs - oldest->updatedMs) < 0) oldest = &candidate;
    }
    if (!slot) slot = oldest;
    slot->updatedMs = reading.receivedAtMs ? reading.receivedAtMs : millis();
    slot->code = reading.sensorCode;
    slot->channel = reading.channel;
    slot->rollingCode = reading.rollingCode;
    slot->type = static_cast<uint8_t>(reading.type);
    slot->batteryState = reading.batteryStatusValid ? (reading.batteryLow ? 2U : 1U) : 0U;
    slot->uvIndex = (reading.type == SensorType::UV && reading.uvValid) ? static_cast<int8_t>(reading.uvIndex) : -1;
    if (isfinite(reading.rssi)) {
        int rssi = static_cast<int>(lroundf(reading.rssi));
        if (rssi < -126) rssi = -126;
        if (rssi > 0) rssi = 0;
        slot->rssiDbm = static_cast<int8_t>(rssi);
    }
}

void initDisplay() {
    // I2C_SHARED_BUS_COMPAT_V2
    // OLED + BME280 + AS3935 share one conservative bus. Hardware testing
    // confirmed that cable capacitance, not the BME280 driver, was the source
    // of intermittent/missing ACKs with long leads.
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    Wire.setTimeOut(80);
    Wire.setClock(100000);
    oled.setBusClock(100000);
    oled.begin();
    Wire.setClock(100000);

    const DisplayRuntimeConfig d = defaults();
    displayCfg = d;
    displayOn = true;
    displayPrefsReady = displayPrefs.begin("display", false);
    if (displayPrefsReady) {
        displayOn = displayPrefs.getBool("on", true);
        displayCfg.pageMask = displayPrefs.getUChar("pages", d.pageMask);
        displayCfg.environmentFields = displayPrefs.getUChar("env", d.environmentFields);
        displayCfg.windRainFields = displayPrefs.getUChar("wind", d.windRainFields);
        displayCfg.technolineFields = displayPrefs.getUChar("tech", d.technolineFields);
        displayCfg.pressureFields = displayPrefs.getUChar("press", d.pressureFields);
        displayCfg.statusFields = displayPrefs.getUChar("status", d.statusFields);
        displayCfg.lightningFields = displayPrefs.getUChar("as3935", d.lightningFields);
        displayCfg.pageIntervalSec = displayPrefs.getUShort("page_s", d.pageIntervalSec);
        displayCfg.contrast = displayPrefs.getUChar("contrast", d.contrast);
    } else {
        Serial.println(F("[OLED] ATTENZIONE: NVS display non disponibile; uso default runtime"));
    }
    normalize(displayCfg);
    oled.setContrast(displayCfg.contrast);
    page = firstEnabledPage();

    if (!displayOn) {
        oled.clearBuffer();
        oled.sendBuffer();
        oled.setPowerSave(1);
        Serial.println(F("[OLED] power save attivo da configurazione persistente"));
    } else {
        oled.setPowerSave(0);
        oled.clearBuffer();
        oled.setFont(u8g2_font_6x10_tf);
        oled.drawStr(0, 12, "Oregon+Tech " FIRMWARE_VERSION);
        oled.drawStr(0, 27, BOARD_NAME);
        oled.drawStr(0, 42, "SX1278 OOK 433.92");
        oled.drawStr(0, 57, "Avvio...");
        oled.sendBuffer();
    }
    pageEpochMs = millis();
#if OLED_BUTTON_ENABLE
    pinMode(OLED_BUTTON_PIN, INPUT_PULLUP);
    buttonRawPressed = digitalRead(OLED_BUTTON_PIN) == LOW;
    buttonStablePressed = buttonRawPressed;
    buttonLastChangeMs = millis();
    buttonPressedAtMs = buttonStablePressed ? millis() : 0;
    Serial.print(F("[OLED] pulsante fisico GPIO"));
    Serial.println(OLED_BUTTON_PIN);
#endif
}

void serviceDisplayButton() {
#if OLED_BUTTON_ENABLE
    const uint32_t now = millis();
    const bool rawPressed = digitalRead(OLED_BUTTON_PIN) == LOW;
    if (rawPressed != buttonRawPressed) {
        buttonRawPressed = rawPressed;
        buttonLastChangeMs = now;
    }
    if (rawPressed == buttonStablePressed) return;
    if (static_cast<uint32_t>(now - buttonLastChangeMs) < OLED_BUTTON_DEBOUNCE_MS) return;

    buttonStablePressed = rawPressed;
    if (buttonStablePressed) {
        buttonPressedAtMs = now;
        return;
    }

    const uint32_t heldMs = buttonPressedAtMs ? static_cast<uint32_t>(now - buttonPressedAtMs) : 0;
    buttonPressedAtMs = 0;
    if (heldMs >= OLED_BUTTON_MIN_PRESS_MS && heldMs <= OLED_BUTTON_MAX_PRESS_MS) {
        const bool persisted = setDisplayEnabled(!displayEnabled());
        Serial.print(F("[OLED] toggle da pulsante fisico, pressione ms="));
        Serial.print(heldMs);
        Serial.print(F(" NVS="));
        Serial.println(persisted ? F("OK") : F("KO"));
    }
#endif
}

bool displayButtonEnabled() {
#if OLED_BUTTON_ENABLE
    return true;
#else
    return false;
#endif
}

int displayButtonPin() {
#if OLED_BUTTON_ENABLE
    return OLED_BUTTON_PIN;
#else
    return -1;
#endif
}

bool displayEnabled() { return displayOn; }
bool displayPersistenceAvailable() { return displayPrefsReady; }

void showWebSecurityBootstrap(const String &username, const String &password, uint32_t durationMs) {
    if (!displayOn || password.length() == 0U) return;
    webSecurityBootstrapUser = username;
    webSecurityBootstrapPasswordText = password;
    webSecurityBootstrapUntilMs = millis() + (durationMs < 5000UL ? 5000UL : durationMs);

    oled.setPowerSave(0);
    oled.clearBuffer();
    oled.setFont(u8g2_font_6x10_tf);
    oled.drawStr(0, 9, "WEB ADMIN - PRIMO AVVIO");
    oled.drawHLine(0, 12, 128);
    oled.setFont(u8g2_font_5x8_tf);
    String u = String("USER: ") + webSecurityBootstrapUser;
    String p = String("PASS: ") + webSecurityBootstrapPasswordText;
    oled.drawStr(0, 27, u.c_str());
    oled.drawStr(0, 40, p.c_str());
    oled.drawStr(0, 53, "Salvala e cambiala da");
    oled.drawStr(0, 63, "CONFIG > SISTEMA");
    oled.sendBuffer();
    Serial.println(F("[OLED] credenziali Web iniziali mostrate temporaneamente"));
}

void prepareDisplayForDeepSleep() {
    oled.clearBuffer();
    oled.sendBuffer();
    oled.setPowerSave(1);
    Serial.println(F("[OLED] deep-sleep power save"));
}

bool setDisplayEnabled(bool enabled) {
    if (displayOn == enabled) return displayPrefsReady;

    bool persisted = false;
    if (displayPrefsReady) {
        displayPrefs.putBool("on", enabled);
        persisted = displayPrefs.getBool("on", !enabled) == enabled;
    }

    displayOn = enabled;
    applyDisplayPower();
    Serial.print(enabled ? F("[OLED] acceso") : F("[OLED] power save"));
    Serial.print(F(" · NVS "));
    Serial.println(persisted ? F("verificata") : F("NON verificata"));
    return persisted;
}

DisplayRuntimeConfig getDisplayConfig() { return displayCfg; }

bool validateDisplayConfig(const DisplayRuntimeConfig &cfg) {
    if ((cfg.pageMask & DISPLAY_PAGE_ALL) == 0U) return false;
    if ((cfg.pageMask & ~DISPLAY_PAGE_ALL) != 0U) return false;
    if ((cfg.environmentFields & ~DISPLAY_ENV_ALL) != 0U) return false;
    if ((cfg.windRainFields & ~DISPLAY_WIND_ALL) != 0U) return false;
    if ((cfg.technolineFields & ~DISPLAY_TECH_ALL) != 0U) return false;
    if ((cfg.pressureFields & ~DISPLAY_PRESS_ALL) != 0U) return false;
    if ((cfg.statusFields & ~DISPLAY_STATUS_ALL) != 0U) return false;
    if ((cfg.lightningFields & ~DISPLAY_AS_ALL) != 0U) return false;
    if (cfg.pageIntervalSec < 2U || cfg.pageIntervalSec > 60U) return false;
    if (cfg.contrast < 8U) return false;
    return true;
}

bool saveDisplayConfig(const DisplayRuntimeConfig &cfg, bool &changed) {
    changed = false;
    if (!validateDisplayConfig(cfg)) return false;
    DisplayRuntimeConfig next = cfg;
    normalize(next);
    if (sameConfig(next, displayCfg)) return displayPrefsReady;
    if (!displayPrefsReady) {
        Serial.println(F("[OLED] ERRORE: configurazione modificata ma NVS display non disponibile"));
        return false;
    }

    if (next.pageMask != displayCfg.pageMask) displayPrefs.putUChar("pages", next.pageMask);
    if (next.environmentFields != displayCfg.environmentFields) displayPrefs.putUChar("env", next.environmentFields);
    if (next.windRainFields != displayCfg.windRainFields) displayPrefs.putUChar("wind", next.windRainFields);
    if (next.technolineFields != displayCfg.technolineFields) displayPrefs.putUChar("tech", next.technolineFields);
    if (next.pressureFields != displayCfg.pressureFields) displayPrefs.putUChar("press", next.pressureFields);
    if (next.statusFields != displayCfg.statusFields) displayPrefs.putUChar("status", next.statusFields);
    if (next.lightningFields != displayCfg.lightningFields) displayPrefs.putUChar("as3935", next.lightningFields);
    if (next.pageIntervalSec != displayCfg.pageIntervalSec) displayPrefs.putUShort("page_s", next.pageIntervalSec);
    if (next.contrast != displayCfg.contrast) displayPrefs.putUChar("contrast", next.contrast);

    if (!verifyStoredConfig(displayPrefs, next)) {
        Serial.println(F("[OLED] ERRORE verifica NVS display: valori non confermati"));
        return false;
    }

    displayCfg = next;
    changed = true;
    if (!pageEnabled(page)) page = firstEnabledPage();
    pageEpochMs = millis();
    lastRefreshMs = 0;
    oled.setContrast(displayCfg.contrast);
    Serial.println(F("[OLED] configurazione Web verificata in NVS"));
    return true;
}

bool resetDisplayConfigToDefaults(bool &changed) {
    DisplayRuntimeConfig d = defaults();
    normalize(d);
    return saveDisplayConfig(d, changed);
}

uint8_t displayCurrentPage() { return page; }

void updateDisplay(const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats, bool wifiOk, bool mqttOk) {
    if (!displayOn) return;
    const uint32_t now = millis();
    if (webSecurityBootstrapUntilMs) {
        if (static_cast<int32_t>(now - webSecurityBootstrapUntilMs) < 0) return;
        webSecurityBootstrapUntilMs = 0;
        webSecurityBootstrapUser = "";
        webSecurityBootstrapPasswordText = "";
        lastRefreshMs = 0;
        pageEpochMs = now;
    }
    if (static_cast<uint32_t>(now - lastRefreshMs) < DISPLAY_REFRESH_MS) return;
    lastRefreshMs = now;

    if (!pageEnabled(page)) {
        page = firstEnabledPage();
        pageEpochMs = now;
    }
    const uint32_t pageMs = static_cast<uint32_t>(displayCfg.pageIntervalSec) * 1000UL;
    if (static_cast<uint32_t>(now - pageEpochMs) >= pageMs) {
        pageEpochMs = now;
        page = nextEnabledPage(page);
    }

    oled.clearBuffer();
    if (page == 0) renderEnvironment(state, wifiOk, mqttOk);
    else if (page == 1) renderWindRain(state, wifiOk, mqttOk);
    else if (page == 2) renderLaCrosse(state, wifiOk, mqttOk);
    else if (page == 3) renderPressure(state, wifiOk, mqttOk);
    else if (page == 4) renderStatus(state, rxStats, lcStats, wifiOk, mqttOk);
    else if (page == 5) renderLightning(wifiOk, mqttOk);
    else renderSensorHealth(wifiOk, mqttOk);
    oled.sendBuffer();
}
