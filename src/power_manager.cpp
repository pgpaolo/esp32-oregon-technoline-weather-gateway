#include "power_manager.h"
#include <Arduino.h>
#include <WiFi.h>
#include <esp_sleep.h>
#include <driver/gpio.h>
#include "config.h"
#include "board_config.h"
#include "display_manager.h"
#include "barometer_manager.h"
#include "oregon_receiver.h"
#include "mqtt_publisher.h"

namespace {
void configureWakeSource() {
#if POWER_WAKE_BUTTON_ENABLE
    pinMode(POWER_WAKE_BUTTON_PIN, INPUT_PULLUP);

    // Se lo stesso pulsante e' ancora premuto, attendi il rilascio prima di
    // armare il wake LOW, altrimenti l'ESP32 si risveglierebbe subito.
    const uint32_t started = millis();
    while (digitalRead(POWER_WAKE_BUTTON_PIN) == LOW &&
           static_cast<uint32_t>(millis() - started) < 3000UL) {
        delay(10);
    }

    const esp_err_t err = esp_sleep_enable_ext0_wakeup(
        static_cast<gpio_num_t>(POWER_WAKE_BUTTON_PIN), 0);
    if (err == ESP_OK) {
        Serial.print(F("[POWER] wake deep-sleep su GPIO"));
        Serial.print(POWER_WAKE_BUTTON_PIN);
        Serial.println(F(" LOW"));
    } else {
        Serial.print(F("[POWER] ATTENZIONE: wake GPIO non configurato, err="));
        Serial.println(static_cast<int>(err));
    }
#else
    Serial.println(F("[POWER] wake GPIO non configurato: usare RESET/EN o power-cycle"));
#endif
}
}

bool controllerSoftPowerOffEnabled() {
#if POWER_SOFT_OFF_ENABLE
    return true;
#else
    return false;
#endif
}

bool controllerWakeButtonEnabled() {
#if POWER_WAKE_BUTTON_ENABLE
    return true;
#else
    return false;
#endif
}

int controllerWakeButtonPin() {
#if POWER_WAKE_BUTTON_ENABLE
    return POWER_WAKE_BUTTON_PIN;
#else
    return -1;
#endif
}

String controllerWakeHint() {
#if POWER_WAKE_BUTTON_ENABLE
    return String("premi il pulsante su GPIO") + String(POWER_WAKE_BUTTON_PIN) +
           " oppure RESET/EN";
#else
    return String("premi RESET/EN; in alternativa togli e ridai alimentazione");
#endif
}

[[noreturn]] void enterControllerDeepSleep() {
#if !POWER_SOFT_OFF_ENABLE
    Serial.println(F("[POWER] soft power-off disabilitato: riavvio di sicurezza"));
    delay(100);
    ESP.restart();
    while (true) delay(1000);
#else
    Serial.println(F("[POWER] arresto controllato -> DEEP SLEEP"));

    // Porta prima offline i servizi di rete, poi spegne le periferiche.
    prepareMqttForDeepSleep();
    prepareDisplayForDeepSleep();
    prepareBarometerForDeepSleep();
    const bool radioOk = prepareRadioForDeepSleep();
    if (!radioOk) Serial.println(F("[POWER] ATTENZIONE: SX1278 non ha confermato sleep"));

    digitalWrite(BOARD_LED_PIN, BOARD_LED_OFF);
    WiFi.disconnect(true, false);
    delay(30);
    WiFi.mode(WIFI_OFF);

    configureWakeSource();

    Serial.print(F("[POWER] controller in deep sleep; risveglio: "));
    Serial.println(controllerWakeHint());
    Serial.flush();
    delay(50);

    esp_deep_sleep_start();
    while (true) delay(1000);
#endif
}
