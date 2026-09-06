#pragma once

#include <Arduino.h>

// Shared guard between the existing authenticated local OTA upload and the
// AdminSensor Remote OTA stream. Arduino Update is global and must never be
// driven by two sources at the same time.
bool firmwareLocalBeginGuard(String &error);
void firmwareLocalReleaseGuard();

bool firmwareRemoteBegin(size_t imageSize, const String &sha256Hex, String &error);
bool firmwareRemoteWrite(uint32_t sequence, uint8_t *data, size_t len, String &error);
bool firmwareRemoteEnd(String &error);
void firmwareRemoteAbort(const String &reason = String());

bool firmwareUpdateInProgress();
String firmwareUpdateStatusJson();
void serviceRemoteFirmwareUpdate();
