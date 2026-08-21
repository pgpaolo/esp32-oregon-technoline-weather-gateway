#pragma once
#include <Arduino.h>

// "Soft power-off": mette ESP32 e periferiche supportate in deep sleep.
// Non interrompe fisicamente l'alimentazione della scheda.
bool controllerSoftPowerOffEnabled();
bool controllerWakeButtonEnabled();
int controllerWakeButtonPin();
String controllerWakeHint();

[[noreturn]] void enterControllerDeepSleep();
