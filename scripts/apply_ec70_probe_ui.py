#!/usr/bin/env python3
"""Expose passive EC70/UVR128 probe telemetry in the API and Web diagnostics.

This is diagnostic only. It does not change RF timings, decoder acceptance,
checksums, MQTT, SD or OLED. The companion recovery patch records how far the
existing EC70/1D20 phase scan gets on each captured Oregon burst.
"""
from pathlib import Path

Import("env")
ROOT = Path(env.subst("$PROJECT_DIR"))
HDR = ROOT / "src" / "oregon_receiver.h"
WEB = ROOT / "src" / "web_manager.cpp"
DASH = ROOT / "web" / "dashboard.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def patch_header() -> None:
    text = HDR.read_text(encoding="utf-8")
    if "ec70ProbeBursts" in text:
        print("EC70 probe API: oregon_receiver.h already patched")
        return
    marker = "    uint32_t v21ChecksumFail{0};\n    uint32_t v21PairErrors{0};\n"
    extra = marker + "\n    // Passive EC70/UVR128 probe. Counts progress of the existing targeted\n    // phase scan without changing acceptance or timing. 'Near' means the best\n    // reconstructed 16-bit sensor code is at most 2 bits away from EC70.\n    uint32_t ec70ProbeBursts{0};\n    uint32_t ec70ProbeHeaderA{0};\n    uint32_t ec70Probe20Bit{0};\n    uint32_t ec70ProbeNear{0};\n    uint32_t ec70ProbeExact{0};\n    uint32_t ec70ProbeChecksumOk{0};\n    uint32_t ec70ProbeLastNearMs{0};\n    uint32_t ec70ProbeLastNearDeltaMs{0};\n    uint16_t ec70ProbeLastDurationMs{0};\n    uint16_t ec70ProbeLastEdges{0};\n    uint16_t ec70ProbeLastBestCode{0};\n    int16_t ec70ProbeLastRssi10{0};\n    uint8_t ec70ProbeLastDistance{0xFFU};\n"
    text = replace_once(text, marker, extra, "EC70 probe stats")
    HDR.write_text(text, encoding="utf-8")
    print("EC70 probe API: patched oregon_receiver.h")


def patch_web() -> None:
    text = WEB.read_text(encoding="utf-8")
    if '"ec70_probe_bursts"' in text:
        print("EC70 probe API: web_manager.cpp already patched")
        return
    marker = '    out += ",\\\"v21_pair_errors\\\":" + String(rx.v21PairErrors);\n'
    extra = marker + '''    out += ",\\\"ec70_probe_bursts\\\":" + String(rx.ec70ProbeBursts);\n    out += ",\\\"ec70_probe_header_a\\\":" + String(rx.ec70ProbeHeaderA);\n    out += ",\\\"ec70_probe_20bit\\\":" + String(rx.ec70Probe20Bit);\n    out += ",\\\"ec70_probe_near\\\":" + String(rx.ec70ProbeNear);\n    out += ",\\\"ec70_probe_exact\\\":" + String(rx.ec70ProbeExact);\n    out += ",\\\"ec70_probe_checksum_ok\\\":" + String(rx.ec70ProbeChecksumOk);\n    out += ",\\\"ec70_probe_last_delta_ms\\\":" + String(rx.ec70ProbeLastNearDeltaMs);\n    out += ",\\\"ec70_probe_last_duration_ms\\\":" + String(rx.ec70ProbeLastDurationMs);\n    out += ",\\\"ec70_probe_last_edges\\\":" + String(rx.ec70ProbeLastEdges);\n    out += ",\\\"ec70_probe_best_code\\\":" + String(rx.ec70ProbeLastBestCode);\n    out += ",\\\"ec70_probe_best_distance\\\":" + String(rx.ec70ProbeLastDistance);\n    out += ",\\\"ec70_probe_rssi\\\":";\n    if (rx.ec70ProbeLastRssi10 != 0) out += String(static_cast<float>(rx.ec70ProbeLastRssi10) / 10.0f, 1); else out += "null";\n'''
    text = replace_once(text, marker, extra, "EC70 probe JSON")
    WEB.write_text(text, encoding="utf-8")
    print("EC70 probe API: patched web_manager.cpp")


def patch_dashboard() -> None:
    text = DASH.read_text(encoding="utf-8")
    if "EC70 probe:" in text:
        print("EC70 probe UI: dashboard.html already patched")
        return
    old = "+' · UVR128 cand/OK '+r.v21_uv_candidates+'/'+r.v21_uv_frames+'<br><b>WGR800 1984 V3.0</b>:"
    new = "+' · UVR128 cand/OK '+r.v21_uv_candidates+'/'+r.v21_uv_frames+'<br><b>EC70 probe:</b> scan '+(r.ec70_probe_bursts||0)+' · A '+(r.ec70_probe_header_a||0)+' · 20b '+(r.ec70_probe_20bit||0)+' · near≤2 '+(r.ec70_probe_near||0)+' · EC70 '+(r.ec70_probe_exact||0)+' · csOK '+(r.ec70_probe_checksum_ok||0)+' · best '+((r.ec70_probe_best_distance??255)<255?('0x'+Number(r.ec70_probe_best_code||0).toString(16).padStart(4,'0').toUpperCase()+' / '+r.ec70_probe_best_distance+' bit'):'-')+' · Δ '+(r.ec70_probe_last_delta_ms?(r.ec70_probe_last_delta_ms/1000).toFixed(1)+' s':'-')+' · '+(r.ec70_probe_last_duration_ms||0)+' ms/'+(r.ec70_probe_last_edges||0)+'e · '+(r.ec70_probe_rssi==null?'RSSI N/D':Number(r.ec70_probe_rssi).toFixed(1)+' dBm')+'<br><b>WGR800 1984 V3.0</b>:"
    text = replace_once(text, old, new, "EC70 probe diagnostic line")
    DASH.write_text(text, encoding="utf-8")
    print("EC70 probe UI: patched dashboard.html")


patch_header()
patch_web()
patch_dashboard()
