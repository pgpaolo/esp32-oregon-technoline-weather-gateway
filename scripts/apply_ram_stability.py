Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


# RAM_STABILITY_SAFE_V2
#
# Keep the RC6 boot/network/Remote/MB runtime byte-for-byte in behaviour. The
# first RAM experiment changed task creation timing; although CI compiled and
# passed static regression tests, a real T3 V1.6.1 failed to reach normal Wi-Fi
# provisioning. V2 therefore limits itself to passive diagnostics plus a static
# diagnostic-history reduction. No task lifecycle, Wi-Fi, Web provisioning,
# MQTT, TLS, RF or dashboard scheduling path is changed here.

web_path = "src/web_manager.cpp"
web = read(web_path)
marker = "RAM_STABILITY_SAFE_V2"

if marker not in web:
    if "#include <esp_heap_caps.h>" not in web:
        inc = "#include <Arduino.h>\n"
        if inc not in web:
            raise RuntimeError("RAM stability safe V2: Arduino include anchor missing")
        web = web.replace(inc, inc + "#include <esp_heap_caps.h>\n", 1)

    old = "constexpr uint8_t RAW_HISTORY_SIZE = 32;"
    if old not in web:
        raise RuntimeError("RAM stability safe V2: raw history anchor missing")
    web = web.replace(old, "constexpr uint8_t RAW_HISTORY_SIZE = 16; // RAM_STABILITY_SAFE_V2", 1)

    heap_anchor = "    const uint32_t heapMin = ESP.getMinFreeHeap();\n"
    if heap_anchor not in web:
        raise RuntimeError("RAM stability safe V2: heap metrics anchor missing")
    heap_extra = r'''    const uint32_t heapLargest = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
    static uint32_t heapLargestMin = 0xFFFFFFFFUL;
    if (heapLargest < heapLargestMin) heapLargestMin = heapLargest;
    const uint32_t heapFragmentationPct = (heapFree && heapLargest <= heapFree)
        ? 100U - static_cast<uint32_t>((static_cast<uint64_t>(heapLargest) * 100ULL) / heapFree)
        : 0U;
'''
    web = web.replace(heap_anchor, heap_anchor + heap_extra, 1)

    json_anchor = '    out += ",\\\"heap_min_free\\\":" + String(heapMin);\n'
    if json_anchor not in web:
        raise RuntimeError("RAM stability safe V2: heap JSON anchor missing")
    json_extra = (
        json_anchor
        + '    out += ",\\\"heap_largest_free\\\":" + String(heapLargest);\n'
        + '    out += ",\\\"heap_largest_min\\\":" + String(heapLargestMin);\n'
        + '    out += ",\\\"heap_fragmentation_pct\\\":" + String(heapFragmentationPct);\n'
    )
    web = web.replace(json_anchor, json_extra, 1)

    write(web_path, web)
    print("RAM stability SAFE V2: raw history 32->16; passive contiguous-heap telemetry enabled")
else:
    print("RAM stability SAFE V2: already applied")
