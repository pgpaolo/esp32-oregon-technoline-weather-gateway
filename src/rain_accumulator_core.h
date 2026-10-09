#pragma once
// Rain accumulation arithmetic: no Arduino / heap / radio dependency.
#include <stdint.h>

struct RainBucket {
    uint32_t sensorKey{0};
    uint32_t lastRawMilli{0};
    uint32_t dayKey{0};
    uint32_t monthKey{0};
    uint32_t yearKey{0};
    uint32_t dayMilli{0};
    uint32_t monthMilli{0};
    uint32_t yearMilli{0};
    uint64_t lifetimeMilli{0};
    uint32_t rebaselines{0};
    uint8_t baselineValid{0};
    uint8_t reserved[3]{};
};

struct RainCoreResult { bool changed; bool incremented; bool rebased; };

inline bool rollRainCalendar(RainBucket &b, uint32_t day, uint32_t month, uint32_t year) {
    if (!day || !month || !year) return false;
    bool changed = false;
    if (b.dayKey != day) { b.dayKey = day; b.dayMilli = 0; changed = true; }
    if (b.monthKey != month) { b.monthKey = month; b.monthMilli = 0; changed = true; }
    if (b.yearKey != year) { b.yearKey = year; b.yearMilli = 0; changed = true; }
    return changed;
}

inline RainCoreResult accumulateRain(RainBucket &b, uint32_t key, uint32_t rawMilli,
                                     uint32_t day, uint32_t month, uint32_t year) {
    const bool calendarChanged = rollRainCalendar(b, day, month, year);
    if (!key) return {calendarChanged, false, false};
    if (!b.baselineValid || b.sensorKey != key || rawMilli < b.lastRawMilli ||
        rawMilli - b.lastRawMilli > 500000UL) {
        // Never interpret a sensor reset, replacement, or implausible jump as rainfall.
        const bool rebase = b.baselineValid != 0;
        if (rebase) ++b.rebaselines;
        b.sensorKey = key;
        b.lastRawMilli = rawMilli;
        b.baselineValid = 1;
        return {true, false, rebase};
    }
    const uint32_t delta = rawMilli - b.lastRawMilli;
    if (delta == 0) return {calendarChanged, false, false}; // radio retransmission
    b.lastRawMilli = rawMilli;
    b.lifetimeMilli += delta;
    if (day && month && year) {
        b.dayMilli += delta;
        b.monthMilli += delta;
        b.yearMilli += delta;
    }
    return {true, true, false};
}
