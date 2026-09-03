Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime: COMPATIBLE MB must never merge Oregon and Technoline measurements
# into the same packet. sourcePriority is retained in NVS/API for backward
# compatibility, but now means an exclusive source selector:
#   0 = Oregon Scientific
#   1 = Technoline / La Crosse
# Local BME280 pressure/indoor data remains gateway-local and may accompany
# either source. Oregon UV is exported only when Oregon is selected.
# ---------------------------------------------------------------------------
cpp = read("src/mb_compatible_publisher.cpp")
start = cpp.find("LiveSelection selectLive(")
end = cpp.find("\nString floatField(", start)
if start < 0 or end < 0:
    raise RuntimeError("MB single-source: selectLive anchors missing")

strict_select = r'''LiveSelection selectLive(const StationState &s, const MbCompatibleConfig &cfg, uint32_t now, uint32_t dayKey) {
    LiveSelection v;
    const bool useTechnoline = cfg.sourcePriority == 1U;

    if (!useTechnoline) {
        // Oregon source: no Technoline fallback is allowed.
        if (oregonThermoFresh(s, now)) {
            v.tempC = s.temperatureC;
            v.humPct = s.humidityPct;
            v.tempFromOregon = true;
            if (s.dewPointValid) v.dewC = s.dewPointC;
            if (s.heatIndexValid) v.heatIndexC = s.heatIndexC;
        }
        if (oregonWindFresh(s, now)) {
            v.windKmh = s.windAverageKmh;
            if (finiteValue(s.windGustKmh)) v.gustKmh = s.windGustKmh;
            if (finiteValue(s.windDirectionDeg)) v.dirDeg = s.windDirectionDeg;
            if (s.windChillValid) v.windChillC = s.windChillC;
            v.windFromOregon = true;
        }
        if (oregonRainFresh(s, now)) {
            v.rainTotalMm = s.rainTotalMm;
            if (finiteValue(s.rainRateMmH)) v.rainRateMmH = s.rainRateMmH;
            if (s.rainLastHourValid) v.rain1hMm = s.rainLastHourMm;
            if (s.rainLast24hValid) v.rain24hMm = s.rainLast24hMm;
            v.rainTodayMm = dailyRain(true, dayKey, s.rainTotalMm);
            v.rainFromOregon = true;
        }
        if (s.uvValid && sensorFresh(s.uvUpdatedMs, now) && s.uvIndex >= 0)
            v.uv = static_cast<float>(s.uvIndex);
    } else {
        // Technoline source: no Oregon fallback is allowed.
        if (lcThermoFresh(s, now)) {
            v.tempC = s.lacrosse.temperatureC;
            v.humPct = s.lacrosse.humidityPct;
            v.dewC = dewPoint(v.tempC, v.humPct);
        }
        if (lcWindFresh(s, now)) {
            v.windKmh = s.lacrosse.windKmh;
            if (s.lacrosse.gustValid && sensorFresh(s.lacrosse.gustUpdatedMs, now))
                v.gustKmh = s.lacrosse.gustKmh;
            if (s.lacrosse.directionValid) v.dirDeg = s.lacrosse.windDirectionDeg;
        }
        if (lcRainFresh(s, now)) {
            v.rainTotalMm = s.lacrosse.rainTotalMm;
            if (s.lacrosse.rainRate5mValid) v.rainRateMmH = s.lacrosse.rainRate5mMmH;
            if (s.lacrosse.rainLastHourValid) v.rain1hMm = s.lacrosse.rainLastHourMm;
            if (s.lacrosse.rainLast24hValid) v.rain24hMm = s.lacrosse.rainLast24hMm;
            v.rainTodayMm = dailyRain(false, dayKey, s.lacrosse.rainTotalMm);
        }
        // UV belongs to the Oregon station and must remain unavailable here.
    }

    // BME280 is local gateway hardware, not a fallback weather station.
    if (s.pressureValid && sensorFresh(s.pressureUpdatedMs, now)) {
        if (finiteValue(s.pressureSeaLevelHpa)) v.pressureHpa = s.pressureSeaLevelHpa;
        if (s.pressureTrendValid && finiteValue(v.pressureHpa) && finiteValue(s.pressureTrendHpa3h))
            v.pressure3hAgoHpa = v.pressureHpa - s.pressureTrendHpa3h;
        if (s.indoorTemperatureValid) v.indoorTempC = s.indoorTemperatureC;
        if (s.indoorHumidityValid) v.indoorHumPct = s.indoorHumidityPct;
    }
    return v;
}
'''
cpp = cpp[:start] + strict_select + cpp[end:]

# Add a human-readable source name to the status JSON while preserving the
# historical source_priority numeric field for config/backup compatibility.
status_anchor = '    out += ",\\\"source_priority\\\":" + String(cfg.sourcePriority);\n'
if '"source_station"' not in cpp:
    if status_anchor not in cpp:
        raise RuntimeError("MB single-source: status source anchor missing")
    cpp = cpp.replace(
        status_anchor,
        status_anchor + '    out += ",\\\"source_station\\\":\\\"" + String(cfg.sourcePriority == 1U ? "TECHNOLINE" : "OREGON") + "\\\"";\n',
        1,
    )
write("src/mb_compatible_publisher.cpp", cpp)

header = read("src/mb_compatible_publisher.h")
header = header.replace(
    "uint8_t sourcePriority{0}; // 0 Oregon->Technoline, 1 Technoline->Oregon",
    "uint8_t sourcePriority{0}; // exclusive source: 0 Oregon, 1 Technoline/La Crosse",
)
write("src/mb_compatible_publisher.h", header)

# ---------------------------------------------------------------------------
# Web UI: replace the old priority/fallback wording with an exclusive station
# selector. The element id remains mbPriority to keep the existing API stable.
# ---------------------------------------------------------------------------
dash = read("web/dashboard.html")
old_select = '<label><span>Sorgente primaria</span><select id="mbPriority"><option value="0">Oregon, fallback Technoline</option><option value="1">Technoline, fallback Oregon</option></select></label>'
new_select = '<label><span>Stazione sorgente</span><select id="mbPriority"><option value="0">Oregon Scientific</option><option value="1">Technoline / La Crosse</option></select></label>'
if old_select in dash:
    dash = dash.replace(old_select, new_select, 1)
elif new_select not in dash:
    raise RuntimeError("MB single-source: dashboard source selector missing")

old_note = "Pacchetto Meteobridge/Aurora-compatible a 192 campi: i valori realmente disponibili vengono inviati, gli altri restano <code>--</code>. HTTPS verificato richiede una CA PEM; la modalita senza verifica e solo diagnostica."
new_note = "Pacchetto Meteobridge/Aurora-compatible a 192 campi. Tutti i dati esterni provengono esclusivamente dalla stazione sorgente selezionata: nessun fallback o mescolamento Oregon/Technoline. I valori non disponibili restano <code>--</code>. Il BME280 locale resta indipendente dalla scelta. HTTPS verificato richiede una CA PEM; la modalita senza verifica e solo diagnostica."
if old_note in dash:
    dash = dash.replace(old_note, new_note, 1)
elif new_note not in dash:
    raise RuntimeError("MB single-source: dashboard note anchor missing")
write("web/dashboard.html", dash)

print("MB-compatible single-source: Oregon/Technoline mixing disabled")
