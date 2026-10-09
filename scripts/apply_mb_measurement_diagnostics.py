"""Final, repeat-build-safe COMPATIBLE MB measurement freshness guard.

Runs after the MB single-source and remote runtime normalizers. Does not affect
RF decoder, 192-position protocol, HTTPS transport or server validation.
"""
Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
p = root / 'src/mb_compatible_publisher.cpp'
s = p.read_text(encoding='utf-8')
before = s


def substitute_once(old, new, name):
    global s
    if new in s:
        return
    if old not in s:
        raise RuntimeError('MB measurement diagnostics: missing ' + name)
    s = s.replace(old, new, 1)


substitute_once(
    'size_t gLastFieldCount = 0;',
    'size_t gLastFieldCount = 0;\nvolatile uint8_t gLastWeatherValues = 0; // excludes metadata/uptime',
    'last values counter',
)
substitute_once(
    'bool lcThermoFresh(const StationState &s, uint32_t now) {',
    '''// WS23xx publishes sensor types in separate messages. Its own configured
// freshness window is 300s, not Oregon's 180s generic window.
bool lcFresh(uint32_t stamp, uint32_t now) {
    return stamp != 0U && static_cast<uint32_t>(now - stamp) <= LACROSSE_SENSOR_STALE_MS;
}
bool lcThermoFresh(const StationState &s, uint32_t now) {''',
    'Technoline-specific age window',
)
for old, new in (
    ('sensorFresh(s.lacrosse.temperatureUpdatedMs, now)', 'lcFresh(s.lacrosse.temperatureUpdatedMs, now)'),
    ('sensorFresh(s.lacrosse.humidityUpdatedMs, now)', 'lcFresh(s.lacrosse.humidityUpdatedMs, now)'),
    ('sensorFresh(s.lacrosse.windUpdatedMs, now)', 'lcFresh(s.lacrosse.windUpdatedMs, now)'),
    ('sensorFresh(s.lacrosse.rainUpdatedMs, now)', 'lcFresh(s.lacrosse.rainUpdatedMs, now)'),
):
    if old in s:
        s = s.replace(old, new)
    elif new not in s:
        raise RuntimeError('MB measurement diagnostics: missing freshness condition '+old)

# Count actual meteorological readings before generating the 192-slot MB frame.
# Never count protocol metadata, date/time, station name, or device uptime.
substitute_once(
    '    const LiveSelection live = selectLive(snapshot, cfg, millis(), dayKey);\n\n    payload = "";',
    '''    const LiveSelection live = selectLive(snapshot, cfg, millis(), dayKey);
    // MB_MEASUREMENT_DIAGNOSTICS_V1
    const uint8_t realValues =
        static_cast<uint8_t>(finiteValue(live.tempC)) +
        static_cast<uint8_t>(finiteValue(live.humPct)) +
        static_cast<uint8_t>(finiteValue(live.windKmh)) +
        static_cast<uint8_t>(finiteValue(live.gustKmh)) +
        static_cast<uint8_t>(finiteValue(live.dirDeg)) +
        static_cast<uint8_t>(finiteValue(live.rainRateMmH)) +
        static_cast<uint8_t>(finiteValue(live.rainTodayMm)) +
        static_cast<uint8_t>(finiteValue(live.rainTotalMm)) +
        static_cast<uint8_t>(finiteValue(live.pressureHpa)) +
        static_cast<uint8_t>(finiteValue(live.indoorTempC)) +
        static_cast<uint8_t>(finiteValue(live.indoorHumPct)) +
        static_cast<uint8_t>(finiteValue(live.uv));
    gLastWeatherValues = realValues;
    if (realValues == 0U) {
        error = cfg.sourcePriority == 1U
            ? "no fresh meteorological measurements (TECHNOLINE + local BME280)"
            : "no fresh meteorological measurements (OREGON + local BME280)";
        payload = "";
        return false;  // Do not send empty frames or initiate unnecessary TLS.
    }

    payload = "";''',
    'missing measurement guard',
)
substitute_once(
    '''    if (!buildPayload(snapshot, cfg, payload, error)) {
        setStatusError(error);
        return; // keep test pending until time synchronization completes
    }''',
    '''    if (!buildPayload(snapshot, cfg, payload, error)) {
        setStatusError(error);
        if (error.startsWith("no fresh meteorological measurements")) {
            // No network attempt occurred: throttle until the next interval.
            gLastScheduleMs = now;
            gForceTest = false;
            if (gMutex && xSemaphoreTake(gMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
                gLastPayloadBytes = 0;
                gLastFieldCount = 0;
                gLastHttpCode = 0;
                gLastResponse = "";
                xSemaphoreGive(gMutex);
            }
        }
        return; // time-sync retries may continue; empty RF reports are throttled
    }''',
    'scheduling empty packet guard',
)
substitute_once(
    '    out += ",\\\"payload_fields\\\":" + String(fieldCount);',
    '    out += ",\\\"payload_fields\\\":" + String(fieldCount);\n    out += ",\\\"weather_measurements\\\":" + String(gLastWeatherValues);',
    'API measurement telemetry',
)
if s != before:
    p.write_text(s, encoding='utf-8')
    print('MB measurement diagnostics: Technoline 300s age, missing-data guard and real-value count applied')
else:
    print('MB measurement diagnostics: already applied')
