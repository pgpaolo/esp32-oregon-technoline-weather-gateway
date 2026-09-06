Import("env")

from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "remote_access.cpp"
text = path.read_text(encoding="utf-8")

marker = "ADMIN_SENSOR_DYNAMIC_HEAP_V3"
if marker in text:
    print("AdminSensor Remote dynamic heap: already optimized")
else:
    # apply_remote_access_ota.py installs a conservative 8 KiB contiguous
    # headroom check before buffering dynamic loopback replies. On the classic
    # T3 V1.6.1 the Oregon /api/state response is materially larger than the
    # Davis response and the 8 KiB rule can reject a perfectly safe request
    # even with >50 KiB total heap still free. The response is subsequently
    # emitted in 2 KiB raw chunks, so reserve only the contiguous space needed
    # for one Base64/WebSocket chunk plus allocator/TLS slack, while retaining
    # a much larger total-heap safety floor.
    guard = re.compile(
        r"const size_t reserveLen=haveLen\?len:2048U;\s*"
        r"const size_t largestBlock=heap_caps_get_largest_free_block\(MALLOC_CAP_8BIT\);\s*"
        r"if\(reserveLen>largestBlock\|\|largestBlock-reserveLen<8192U\)\{\s*"
        r"c\.stop\(\);err=\"Heap contiguo insufficiente per risposta locale\";return false;\s*"
        r"\}\s*"
        r"r\.body\.reserve\(reserveLen\);start=millis\(\);",
        re.S,
    )

    replacement = r'''// ADMIN_SENSOR_DYNAMIC_HEAP_V3
    const size_t reserveLen=haveLen?len:2048U;
    const size_t largestBlock=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
    const size_t freeHeap=ESP.getFreeHeap();
    constexpr size_t HTTP_CONTIGUOUS_HEADROOM=4096U;
    constexpr size_t HTTP_TOTAL_HEADROOM=16384U;
    if(reserveLen>largestBlock || freeHeap<=reserveLen ||
       largestBlock-reserveLen<HTTP_CONTIGUOUS_HEADROOM ||
       freeHeap-reserveLen<HTTP_TOTAL_HEADROOM){
        c.stop();
        err="Heap insufficiente risposta locale: need="+String(reserveLen)+
            " block="+String(largestBlock)+" free="+String(freeHeap);
        return false;
    }
    r.body.reserve(reserveLen);start=millis();'''

    text, n = guard.subn(replacement, text, count=1)
    if n != 1:
        # A workspace may already contain a previous variant of the generated
        # guard. Match semantically between reserveLen and body.reserve rather
        # than requiring the exact 8 KiB text.
        semantic = re.compile(
            r"const size_t reserveLen=haveLen\?len:2048U;\s*"
            r"const size_t largestBlock=heap_caps_get_largest_free_block\(MALLOC_CAP_8BIT\);\s*"
            r"if\([^{}]*Heap contiguo insufficiente per risposta locale[^{}]*\}\s*"
            r"r\.body\.reserve\(reserveLen\);start=millis\(\);",
            re.S,
        )
        text, n = semantic.subn(replacement, text, count=1)

    if n != 1:
        raise RuntimeError("Remote dynamic heap: generated localHttp guard anchor missing")

    path.write_text(text, encoding="utf-8")
    print(
        "AdminSensor Remote dynamic heap: /api/state compatible guard enabled "
        "(4 KiB contiguous + 16 KiB total headroom)"
    )
