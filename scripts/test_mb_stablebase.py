"""MBFIX2 source/regenerator and restart-risk preflight. Not a hardware endurance test."""
from pathlib import Path
r=Path(__file__).resolve().parent.parent
mb=(r/"src/mb_compatible_publisher.cpp").read_text(encoding="utf-8")
gen=(r/"scripts/apply_mb_single_source.py").read_text(encoding="utf-8")
rain=(r/"src/rain_accumulator.cpp").read_text(encoding="utf-8")
header=(r/"src/rain_accumulator.h").read_text(encoding="utf-8")
ini=(r/"platformio.ini").read_text(encoding="utf-8")
diag=(r/"scripts/apply_mb_measurement_diagnostics.py").read_text(encoding="utf-8")
pattern="v.rainTodayMm = rainAccumulatorTodayMm(!useTechnoline, dayKey);"
assert mb.count(pattern)==1, "MB must read one selected rain accumulator once"
assert gen.count(pattern)==1, "pre-build generator must preserve exact MB fix"
assert "dailyRain(true, dayKey, s.rainTotalMm)" not in gen
assert "dailyRain(false, dayKey, s.lacrosse.rainTotalMm)" not in gen
assert "float rainAccumulatorTodayMm(bool oregon, uint32_t utcDayKey)" in rain
assert "float rainAccumulatorTodayMm(bool oregon, uint32_t utcDayKey);" in header
assert "MBFIX2_STABLEBASE_RAIN_GETTER_V1" in rain
assert "bucket.dayKey != utcDayKey" in rain
assert "bucket.baselineValid" in rain
assert "if (utcDayKey == 0U) return NAN;" in rain
assert "getSdLoggerConfig()" in rain
assert "String(" not in rain.split("// MBFIX2_STABLEBASE_RAIN_GETTER_V1")[1].split("void initRainAccumulator()")[0]
assert "Preferences" not in rain.split("// MBFIX2_STABLEBASE_RAIN_GETTER_V1")[1].split("void initRainAccumulator()")[0]
assert "MB_FIELD_COUNT = 192" in mb or "MB_FIELD_COUNT = 192U" in mb
assert "case 9: return floatField(v.rainTodayMm, 2);" in mb
assert "case 151: return floatField(v.rainTotalMm, 2);" in mb
assert "MB_MEASUREMENT_DIAGNOSTICS_V1" in mb
assert "scheduling empty packet guard" in diag
assert "LILYGO_STABILITY_TLS_GUARD_V1" in mb
assert "MB_TLS_MEMORY_ARBITRATION_V1" in mb
assert "remoteAccessPauseForExternalTls(2000U)" in mb
assert 'pre:scripts/apply_gateway_stability.py' in ini
assert 'pre:scripts/apply_mb_single_source.py' in ini
assert '6.4.0-rc6-stab1-rain1-mbfix2' in ini
print("PASS MBFIX2: strict original rain1 base, daily UTC memory view, regenerator + TLS guard")
