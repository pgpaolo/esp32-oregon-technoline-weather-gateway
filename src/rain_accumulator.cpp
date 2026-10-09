#include "rain_accumulator.h"
#include "rain_accumulator_core.h"
#include "sd_logger.h"
#include <time.h>
#include <stddef.h>
#include <string.h>
#include <math.h>

namespace {
constexpr uint32_t MAGIC = 0x5241494EU; // RAIN
constexpr uint32_t VERSION = 1;
constexpr uint32_t SAVE_INTERVAL_MS = 60000UL;
constexpr time_t VALID_TIME = 1700000000;
struct RainSnapshot {
    uint32_t magic;
    uint32_t version;
    uint32_t sequence;
    RainBucket oregon;
    RainBucket technoline;
    uint32_t crc;
};
static_assert(sizeof(RainSnapshot) < 256, "rain snapshot must be small");
RainSnapshot state{};
bool dirty = false;
bool restoreAttempted = false;
bool restored = false;
bool everObserved = false;
bool lastSdMounted = false;
uint32_t lastSaveMs = 0;
uint32_t saveErrors = 0;
uint32_t lastCheckpointMs = 0;

uint32_t digest(const RainSnapshot &s) {
    const uint8_t *bytes = reinterpret_cast<const uint8_t *>(&s);
    uint32_t v = 2166136261UL;
    for (size_t i = 0; i < offsetof(RainSnapshot, crc); ++i) {
        v = (v ^ bytes[i]) * 16777619UL;
    }
    return v;
}

bool valid(const RainSnapshot &s) {
    return s.magic == MAGIC && s.version == VERSION && s.crc == digest(s);
}

bool utcKeys(uint32_t &day, uint32_t &month, uint32_t &year) {
    const time_t t = time(nullptr);
    if (t < VALID_TIME) { day = month = year = 0; return false; }
    struct tm u{};
    gmtime_r(&t, &u);
    year = static_cast<uint32_t>(u.tm_year + 1900);
    month = year * 100 + static_cast<uint32_t>(u.tm_mon + 1);
    day = month * 100 + static_cast<uint32_t>(u.tm_mday);
    return true;
}

bool persistenceReady() { return sdRainStorageReady(); }

bool latestCheckpoint(RainSnapshot &latest) {
    RainSnapshot a{}, b{};
    const bool va = sdRainReadSlot(0, &a, sizeof(a)) && valid(a);
    const bool vb = sdRainReadSlot(1, &b, sizeof(b)) && valid(b);
    if (!va && !vb) return false;
    latest = !va ? b : (!vb ? a :
        (static_cast<int32_t>(a.sequence - b.sequence) >= 0 ? a : b));
    return true;
}

void syncCheckpointGeneration() {
    // If a card is inserted after RAM acquisition, never adopt old counters,
    // but advance its sequence so the new RAM checkpoint supersedes old slots.
    RainSnapshot last{};
    if (latestCheckpoint(last) &&
        static_cast<int32_t>(last.sequence - state.sequence) > 0) {
        state.sequence = last.sequence;
        dirty = true;
    }
}

void restoreOnce() {
    if (restoreAttempted || !persistenceReady()) return;
    restoreAttempted = true;
    if (everObserved) {
        syncCheckpointGeneration();
        return;
    }
    RainSnapshot best{};
    if (latestCheckpoint(best)) {
        state = best;
        restored = true;
        Serial.println(F("[RAIN] accumulator restored from SD checkpoint"));
    }
}

void observe(RainBucket &bucket, uint32_t key, float raw) {
    if (!isfinite(raw) || raw < 0.0f || raw > 100000.0f) return;
    // First valid reading may occur before the next main-loop service.
    restoreOnce();
    everObserved = true;
    uint32_t day, month, year;
    utcKeys(day, month, year);
    const uint32_t milli = static_cast<uint32_t>(lroundf(raw * 1000.0f));
    const RainCoreResult r = accumulateRain(bucket, key, milli, day, month, year);
    if (r.changed) dirty = true;
}

String bucketJson(const RainBucket &b) {
    String out;
    out.reserve(215);
    out = "{\"initialized\":";
    out += b.baselineValid ? "true" : "false";
    out += ",\"sensor_key\":" + String(b.sensorKey);
    out += ",\"today_mm\":" + String(b.dayMilli / 1000.0, 3);
    out += ",\"month_mm\":" + String(b.monthMilli / 1000.0, 3);
    out += ",\"year_mm\":" + String(b.yearMilli / 1000.0, 3);
    out += ",\"lifetime_mm\":" + String(static_cast<double>(b.lifetimeMilli) / 1000.0, 3);
    out += ",\"sensor_total_mm\":" + String(b.lastRawMilli / 1000.0, 3);
    out += ",\"rebases\":" + String(b.rebaselines);
    out += "}";
    return out;
}
} // namespace

// MBFIX2_STABLEBASE_RAIN_GETTER_V1: no JSON, NVS writes, SD IO or heap allocation.
// Caller: Arduino main loop, which also owns and updates the rain buckets.
float rainAccumulatorTodayMm(bool oregon, uint32_t utcDayKey) {
    if (utcDayKey == 0U) return NAN;
    const SdLoggerConfig cfg = getSdLoggerConfig(); // fixed-size POD only
    if (oregon ? !cfg.rainOregon : !cfg.rainTechnoline) return NAN;
    const RainBucket &bucket = oregon ? state.oregon : state.technoline;
    if (!bucket.baselineValid || bucket.dayKey != utcDayKey) return NAN;
    return static_cast<float>(bucket.dayMilli) / 1000.0f;
}

void initRainAccumulator() {
    state = {};
    state.magic = MAGIC;
    state.version = VERSION;
    dirty = false;
    restoreAttempted = false;
    everObserved = false;
    lastSdMounted = false;
    restoreOnce();
}

void observeOregonRain(const WeatherReading &r) {
    if (!getSdLoggerConfig().rainOregon || !r.rainTotalValid) return;
    const uint32_t key = (static_cast<uint32_t>(r.sensorCode) << 16) |
        (static_cast<uint32_t>(r.channel) << 8) | r.rollingCode;
    observe(state.oregon, key ? key : 1U, r.rainTotalMm);
}

void observeTechnolineRain(const LaCrosseReading &r) {
    if (!getSdLoggerConfig().rainTechnoline || !r.rainValid) return;
    const uint32_t key = (static_cast<uint32_t>(r.wsId) << 8) | r.sensorId;
    observe(state.technoline, key ? key : 1U, r.rainTotalMm);
}

void serviceRainAccumulator() {
    // Keep time conversions and SD status checks outside the hot RF loop.
    static uint32_t previousServiceMs = 0;
    const uint32_t nowMs = millis();
    if (static_cast<uint32_t>(nowMs - previousServiceMs) < 1000UL) return;
    previousServiceMs = nowMs;
    const bool mounted = persistenceReady();
    if (mounted && !lastSdMounted) {
        if (!restoreAttempted) restoreOnce();
        else syncCheckpointGeneration();
    }
    lastSdMounted = mounted;
    uint32_t day, month, year;
    if (utcKeys(day, month, year)) {
        if (rollRainCalendar(state.oregon, day, month, year)) dirty = true;
        if (rollRainCalendar(state.technoline, day, month, year)) dirty = true;
    }
    if (dirty && static_cast<uint32_t>(millis() - lastSaveMs) >= SAVE_INTERVAL_MS)
        flushRainAccumulator();
}

void flushRainAccumulator() {
    if (!dirty || !persistenceReady()) return;
    RainSnapshot next = state;
    next.magic = MAGIC;
    next.version = VERSION;
    next.sequence = state.sequence + 1U;
    next.crc = digest(next);
    const uint8_t slot = static_cast<uint8_t>(next.sequence & 1U);
    lastSaveMs = millis();
    if (sdRainWriteSlot(slot, &next, sizeof(next))) {
        state = next;
        dirty = false;
        lastCheckpointMs = lastSaveMs;
    } else {
        ++saveErrors;
    }
}

void rainAccumulatorSdFormatted() {
    // FORMATTA intentionally erased both checkpoints; repopulate them from RAM.
    dirty = true;
    lastSaveMs = millis() - SAVE_INTERVAL_MS;
}

void rainAccumulatorConfigChanged(bool oregonChanged, bool technolineChanged) {
    // Ignore readings recorded while a source was off; do not count the gap on re-enable.
    if (oregonChanged) state.oregon.baselineValid = 0;
    if (technolineChanged) state.technoline.baselineValid = 0;
    if (oregonChanged || technolineChanged) dirty = true;
    if (!restoreAttempted && persistenceReady()) restoreOnce();
}

String rainAccumulatorJson() {
    const SdLoggerConfig cfg = getSdLoggerConfig();
    uint32_t day, month, year;
    const bool clockValid = utcKeys(day, month, year);
    String out;
    out.reserve(640);
    out = "{\"utc_valid\":";
    out += clockValid ? "true" : "false";
    out += ",\"utc_day\":" + String(day);
    out += ",\"oregon_enabled\":"; out += cfg.rainOregon ? "true" : "false";
    out += ",\"technoline_enabled\":"; out += cfg.rainTechnoline ? "true" : "false";
    out += ",\"sd_requested\":"; out += cfg.rainPersist ? "true" : "false";
    out += ",\"sd_active\":"; out += persistenceReady() ? "true" : "false";
    out += ",\"sd_restored\":"; out += restored ? "true" : "false";
    out += ",\"pending_checkpoint\":"; out += dirty ? "true" : "false";
    out += ",\"last_checkpoint_ms\":" + String(lastCheckpointMs);
    out += ",\"save_errors\":" + String(saveErrors);
    out += ",\"oregon\":" + bucketJson(state.oregon);
    out += ",\"technoline\":" + bucketJson(state.technoline);
    out += "}";
    return out;
}
