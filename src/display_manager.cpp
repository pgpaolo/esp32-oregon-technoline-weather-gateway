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

namespace {
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
uint32_t lastRefreshMs = 0;
uint32_t pageEpochMs = 0;
uint8_t page = 0;
bool displayOn = true;
bool displayPrefsReady = false;
Preferences displayPrefs;

#if OLED_BUTTON_ENABLE
bool buttonRawPressed = false;
bool buttonStablePressed = false;
uint32_t buttonLastChangeMs = 0;
uint32_t buttonPressedAtMs = 0;
#endif

void header(const char *title, bool wifiOk, bool mqttOk) {
    oled.setFont(u8g2_font_6x10_tf);
    oled.drawStr(0, 9, title);
    oled.drawStr(100, 9, wifiOk ? "W" : "-");
    oled.drawStr(118, 9, mqttOk ? "M" : "-");
    oled.drawHLine(0, 12, 128);
}

void renderEnvironment(const StationState &s, bool wifiOk, bool mqttOk) {
    header("ESTERNO", wifiOk, mqttOk);
    char line[42];
    oled.setFont(u8g2_font_6x10_tf);
    const uint32_t now = millis();

    if (s.thermoValid && sensorFresh(s.thermoUpdatedMs, now))
        snprintf(line, sizeof(line), "T %.1fC  H %.0f%%", s.temperatureC, s.humidityPct);
    else snprintf(line, sizeof(line), "T --.-C  H --%%");
    oled.drawStr(0, 25, line);

    if (s.dewPointValid) snprintf(line, sizeof(line), "Dew %.1fC", s.dewPointC);
    else snprintf(line, sizeof(line), "Dew --.-C");
    oled.drawStr(0, 38, line);

    if (s.heatIndexValid) snprintf(line, sizeof(line), "Heat %.1fC  UV %d", s.heatIndexC, s.uvValid ? s.uvIndex : -1);
    else if (s.uvValid) snprintf(line, sizeof(line), "Heat N/A  UV %d", s.uvIndex);
    else snprintf(line, sizeof(line), "Heat N/A  UV --");
    oled.drawStr(0, 51, line);

    snprintf(line, sizeof(line), "BAT T:%s U:%s", sensorBatteryName(s.thermoSensor), sensorBatteryName(s.uvSensor));
    oled.drawStr(0, 63, line);
}

void renderWindRain(const StationState &s, bool wifiOk, bool mqttOk) {
    header("VENTO / PIOGGIA", wifiOk, mqttOk);
    char line[44];
    oled.setFont(u8g2_font_6x10_tf);
    const uint32_t now = millis();

    if (s.windValid && sensorFresh(s.windUpdatedMs, now)) {
        snprintf(line, sizeof(line), "V %.1f G %.1f km/h", s.windAverageKmh, s.windGustKmh);
        oled.drawStr(0, 25, line);
        snprintf(line, sizeof(line), "%s %.0f deg", windDirectionName(s.windDirectionIndex), s.windDirectionDeg);
        oled.drawStr(0, 38, line);
    } else {
        oled.drawStr(0, 25, "Vento --  WGR800");
        oled.drawStr(0, 38, "Attesa frame A1...");
    }

    if (s.rainValid && sensorFresh(s.rainUpdatedMs, now))
        snprintf(line, sizeof(line), "R %.2f  I %.2f", s.rainTotalMm, s.rainRateMmH);
    else snprintf(line, sizeof(line), "Pioggia --");
    oled.drawStr(0, 51, line);

    snprintf(line, sizeof(line), "BAT W:%s R:%s", sensorBatteryName(s.windSensor), sensorBatteryName(s.rainSensor));
    oled.drawStr(0, 63, line);
}

void renderLaCrosse(const StationState &s, bool wifiOk, bool mqttOk) {
    header("TECHNOLINE", wifiOk, mqttOk);
    char line[48];
    oled.setFont(u8g2_font_5x8_tf);
    const auto &lc = s.lacrosse;
    if (lc.temperatureValid || lc.humidityValid)
        snprintf(line, sizeof(line), "T %.1fC H %.0f%%", lc.temperatureValid?lc.temperatureC:NAN, lc.humidityValid?lc.humidityPct:NAN);
    else snprintf(line, sizeof(line), "T --.-C H --%%");
    oled.drawStr(0, 23, line);
    if (lc.windValid || lc.gustValid)
        snprintf(line, sizeof(line), "W %.1f G %.1f km/h", lc.windValid?lc.windKmh:0.0f, lc.gustValid?lc.gustKmh:0.0f);
    else snprintf(line, sizeof(line), "W --  G -- km/h");
    oled.drawStr(0, 33, line);
    if (lc.directionValid) snprintf(line, sizeof(line), "%s %.0f deg", laCrosseWindDirectionName(lc.windDirectionIndex), lc.windDirectionDeg);
    else snprintf(line, sizeof(line), "Direzione --");
    oled.drawStr(0, 43, line);
    if (lc.rainValid) snprintf(line, sizeof(line), "Rain %.2f mm", lc.rainTotalMm);
    else snprintf(line, sizeof(line), "Rain --");
    oled.drawStr(0, 53, line);
    snprintf(line, sizeof(line), "ID %02X pkt %lu", lc.sensorId, static_cast<unsigned long>(lc.validPacketCount));
    oled.drawStr(0, 63, line);
}

void renderPressure(const StationState &s, bool wifiOk, bool mqttOk) {
    header("BAROMETRO", wifiOk, mqttOk);
    char line[44];
    oled.setFont(u8g2_font_6x10_tf);

    if (s.pressureValid) {
        snprintf(line, sizeof(line), "Psta %.1f hPa", s.pressureAbsoluteHpa);
        oled.drawStr(0, 25, line);
        snprintf(line, sizeof(line), "Alt  %.1f hPa", s.pressureSeaLevelHpa);
        oled.drawStr(0, 38, line);
        if (s.pressureTrendValid)
            snprintf(line, sizeof(line), "Trend %+.1f/3h", s.pressureTrendHpa3h);
        else snprintf(line, sizeof(line), "Trend acquisizione");
        oled.drawStr(0, 51, line);
        snprintf(line, sizeof(line), "%s", barometerForecastName(s));
        oled.drawStr(0, 63, line);
    } else {
        oled.drawStr(0, 25, "BME280 non rilevato");
        oled.drawStr(0, 38, "I2C 0x76 / 0x77");
    }
}

void renderStatus(const StationState &, const OregonRxStats &rx, const LaCrosseRxStats &lc, bool wifiOk, bool mqttOk) {
    const RfProtocolMode mode = getRfProtocolMode();
    header(mode==RfProtocolMode::Dual ? "RF DUAL" : (mode==RfProtocolMode::Oregon ? "RF OREGON" : "RF TECHNOLINE"), wifiOk, mqttOk);
    char line[48];
    oled.setFont(u8g2_font_5x8_tf);

    snprintf(line, sizeof(line), "AF%lu A1%lu A2%lu AD%lu",
             static_cast<unsigned long>(rx.rawThermoFrames),
             static_cast<unsigned long>(rx.rawWindFrames),
             static_cast<unsigned long>(rx.rawRainFrames),
             static_cast<unsigned long>(rx.rawUvFrames));
    oled.drawStr(0, 23, line);

    snprintf(line, sizeof(line), "State %lu Wscan %lu/%lu",
             static_cast<unsigned long>(rx.stateEdgeFrames),
             static_cast<unsigned long>(rx.windRecoverySuccess),
             static_cast<unsigned long>(rx.windRecoveryStarts));
    oled.drawStr(0, 33, line);

    snprintf(line, sizeof(line), "run4:%lu 8:%lu 12:%lu 18:%lu",
             static_cast<unsigned long>(rx.preRun04_07),
             static_cast<unsigned long>(rx.preRun08_11),
             static_cast<unsigned long>(rx.preRun12_17),
             static_cast<unsigned long>(rx.preRun18_27));
    oled.drawStr(0, 43, line);

    snprintf(line, sizeof(line), "LC %lu T%lu W%lu R%lu",
             static_cast<unsigned long>(lc.validFrames),
             static_cast<unsigned long>(lc.temperatureFrames),
             static_cast<unsigned long>(lc.windFrames + lc.gustFrames),
             static_cast<unsigned long>(lc.rainFrames));
    oled.drawStr(0, 53, line);

    if (wifiConnected()) snprintf(line, sizeof(line), "WEB %s", wifiIpAddress().c_str());
    else snprintf(line, sizeof(line), "WEB 192.168.1.220 --");
    oled.drawStr(0, 63, line);
}
} // namespace

void initDisplay() {
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    oled.setBusClock(400000);
    oled.begin();

    displayPrefsReady = displayPrefs.begin("display", false);
    displayOn = displayPrefsReady ? displayPrefs.getBool("on", true) : true;

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
        setDisplayEnabled(!displayEnabled());
        Serial.print(F("[OLED] toggle da pulsante fisico, pressione ms="));
        Serial.println(heldMs);
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

bool displayEnabled() {
    return displayOn;
}

void setDisplayEnabled(bool enabled) {
    if (displayOn == enabled) return;
    displayOn = enabled;

    if (displayPrefsReady && displayPrefs.getBool("on", true) != enabled) {
        displayPrefs.putBool("on", enabled);
    }

    if (enabled) {
        oled.setPowerSave(0);
        lastRefreshMs = 0;
        pageEpochMs = millis();
        Serial.println(F("[OLED] acceso"));
    } else {
        oled.clearBuffer();
        oled.sendBuffer();
        oled.setPowerSave(1);
        Serial.println(F("[OLED] power save"));
    }
}

void updateDisplay(const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats, bool wifiOk, bool mqttOk) {
    if (!displayOn) return;
    const uint32_t now = millis();
    if (static_cast<uint32_t>(now - lastRefreshMs) < DISPLAY_REFRESH_MS) return;
    lastRefreshMs = now;

    if (static_cast<uint32_t>(now - pageEpochMs) >= DISPLAY_PAGE_MS) {
        pageEpochMs = now;
        page = static_cast<uint8_t>((page + 1U) % 5U);
    }

    oled.clearBuffer();
    if (page == 0) renderEnvironment(state, wifiOk, mqttOk);
    else if (page == 1) renderWindRain(state, wifiOk, mqttOk);
    else if (page == 2) renderLaCrosse(state, wifiOk, mqttOk);
    else if (page == 3) renderPressure(state, wifiOk, mqttOk);
    else renderStatus(state, rxStats, lcStats, wifiOk, mqttOk);
    oled.sendBuffer();
}
