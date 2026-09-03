from pathlib import Path
import re

CPP = Path("src/mb_compatible_publisher.cpp").read_text(encoding="utf-8")
PATCH = Path("scripts/apply_mb_compatible_publisher.py").read_text(encoding="utf-8")
SINGLE = Path("scripts/apply_mb_single_source.py").read_text(encoding="utf-8")

assert "MB_FIELD_COUNT = 192" in CPP, "MB packet must stay at 192 fields"
assert '"d="' in CPP and '"{data}"' in CPP, "endpoint must support automatic d= and {data} placeholder"
assert "xTaskCreatePinnedToCore" in CPP and "performHttp" in CPP, "HTTP must run outside the RF loop"
assert 'server.on("/api/mbcompatible"' in PATCH, "authenticated MB-compatible API route missing"
assert "COMPATIBLE MB" in PATCH, "Web UI label missing"

expected = {
    2: "v.tempC",
    3: "v.humPct",
    4: "v.dewC",
    5: "v.windKmh",
    6: "v.gustKmh",
    7: "v.dirDeg",
    8: "v.rainRateMmH",
    9: "v.rainTodayMm",
    10: "v.pressureHpa",
    22: "v.indoorTempC",
    23: "v.indoorHumPct",
    24: "v.windChillC",
    42: "v.heatIndexC",
    43: "v.uv",
    44: "v.rain24hMm",
    47: "v.rain1hMm",
    81: "uptimeSec",
    151: "v.rainTotalMm",
}
for index, token in expected.items():
    pattern = rf"case\s+{index}\s*:[^\n]*{re.escape(token)}"
    assert re.search(pattern, CPP), f"MB field {index} no longer maps to {token}"

# Single-station guard: the final pre-build pass replaces the old priority
# fallback model with an exclusive Oregon/Technoline selector. The old UI text
# intentionally remains inside the patch script only as a replacement anchor.
assert "const bool useTechnoline = cfg.sourcePriority == 1U" in SINGLE
assert "Oregon source: no Technoline fallback is allowed" in SINGLE
assert "Technoline source: no Oregon fallback is allowed" in SINGLE
assert "if (!useTechnoline)" in SINGLE and "} else {" in SINGLE
assert "Stazione sorgente" in SINGLE
assert "Oregon Scientific" in SINGLE and "Technoline / La Crosse" in SINGLE
assert "source_station" in SINGLE, "status JSON must expose selected station name"

# The local BME280 is gateway hardware and may accompany either selected
# station, while Oregon UV must not leak into a Technoline packet.
assert "BME280 is local gateway hardware" in SINGLE
assert "UV belongs to the Oregon station" in SINGLE

# A synthetic packet mirrors the firmware's invariant: exactly 192 whitespace
# separated positions. Unknown values are represented by '--', never removed.
fields = ["--"] * 192
fields[0] = "03/09/2026"
fields[1] = "13:45:00"
fields[2] = "21.4"
fields[3] = "67"
fields[5] = "2.50"
fields[8] = "4.20"
fields[9] = "12.40"
fields[10] = "1017.3"
fields[15] = "hPa"
fields[16] = "mm"
fields[43] = "3.0"
packet = " ".join(fields)
assert len(packet.split()) == 192
assert packet.split()[2] == "21.4"
assert packet.split()[8] == "4.20"
assert packet.split()[43] == "3.0"

# User-facing implementation must not use the project-specific receiver name.
# The generic feature is deliberately called COMPATIBLE MB / MB-compatible.
for path in (
    "src/mb_compatible_publisher.h",
    "src/mb_compatible_publisher.cpp",
    "scripts/apply_mb_compatible_publisher.py",
    "scripts/apply_mb_single_source.py",
):
    text = Path(path).read_text(encoding="utf-8").lower()
    assert "diga" not in text, f"project-specific receiver name leaked into {path}"

print("MB-compatible mapping regression OK: 192 fields, exclusive station source, worker HTTP")
