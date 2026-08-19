#pragma once
#include <Arduino.h>

const char *firmwareVersion();
const char *firmwareGitCommit();
String firmwareBuildTimestamp();
const char *firmwareResetReason();
