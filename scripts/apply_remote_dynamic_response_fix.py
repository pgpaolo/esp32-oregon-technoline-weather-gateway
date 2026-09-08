Import("env")

from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "remote_access.cpp"
text = path.read_text(encoding="utf-8")

marker = "ADMIN_SENSOR_DYNAMIC_HEAP_V4"
if marker in text:
    print("AdminSensor Remote dynamic heap: already optimized")
else:
    # The previous V3 guard estimated post-reserve fragmentation by requiring
    # reserveLen + 4 KiB to fit inside the *same* largest pre-allocation block.
    # Real T3 V1.6.1 measurements showed /api/state at ~9 KiB with a 10 KiB
    # largest block and ~54 KiB total free heap: the vector allocation itself
    # fits, but V3 rejected it before we could see the actual post-allocation
    # heap layout. Reserve first after proving the response itself fits, then
    # measure the allocator again. This preserves a real 4 KiB contiguous block
    # for the 2 KiB raw -> ~2.8 KiB Base64/WSS frame and 16 KiB total runtime
    # headroom for TLS/RF/MQTT/SD, without assuming both allocations must come
    # from one contiguous pre-reserve region.

    replacement = r'''// ADMIN_SENSOR_DYNAMIC_HEAP_V4
    // Compatibility sentinel for apply_remote_access_ota.py repeat builds:
    // Heap contiguo insufficiente per risposta locale
    const size_t reserveLen=haveLen?len:2048U;
    const size_t largestBlock=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
    const size_t freeHeap=ESP.getFreeHeap();
    constexpr size_t HTTP_POST_RESERVE_CONTIGUOUS=4096U;
    constexpr size_t HTTP_TOTAL_HEADROOM=16384U;

    // Preflight only what is knowable before reserve(): the response vector
    // itself must fit in one block and enough total heap must remain.
    if(reserveLen>largestBlock || freeHeap<=reserveLen ||
       freeHeap-reserveLen<HTTP_TOTAL_HEADROOM){
        c.stop();
        err="Heap insufficiente prima reserve: need="+String(reserveLen)+
            " block="+String(largestBlock)+" free="+String(freeHeap);
        return false;
    }

    r.body.reserve(reserveLen);

    // Now inspect the real post-allocation layout instead of subtracting the
    // response size from the former largest block. If fragmentation leaves no
    // room for a Base64/WSS chunk, release the vector before returning 502.
    const size_t postLargestBlock=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
    const size_t postFreeHeap=ESP.getFreeHeap();
    if(postLargestBlock<HTTP_POST_RESERVE_CONTIGUOUS ||
       postFreeHeap<HTTP_TOTAL_HEADROOM){
        std::vector<uint8_t>().swap(r.body);
        c.stop();
        err="Heap frammentato dopo reserve: need="+String(reserveLen)+
            " block="+String(postLargestBlock)+" free="+String(postFreeHeap);
        return false;
    }
    start=millis();'''

    # Replace any previous generated dynamic-heap block, including V3 source
    # archives that have already been built locally. Keep the match bounded by
    # reserveLen and the first start=millis() that follows body.reserve().
    generated = re.compile(
        r"(?:\/\/ ADMIN_SENSOR_DYNAMIC_HEAP_V\d+\s*)?"
        r"const size_t reserveLen=haveLen\?len:2048U;.*?"
        r"r\.body\.reserve\(reserveLen\);.*?start=millis\(\);",
        re.S,
    )
    text, n = generated.subn(replacement, text, count=1)

    if n != 1:
        # Clean generated source from apply_remote_access_ota.py before any
        # V3/V4 pass. This is intentionally exact so an unrelated reserve is
        # never rewritten by accident.
        base = re.compile(
            r"const size_t reserveLen=haveLen\?len:2048U;\s*"
            r"const size_t largestBlock=heap_caps_get_largest_free_block\(MALLOC_CAP_8BIT\);\s*"
            r"if\(reserveLen>largestBlock\|\|largestBlock-reserveLen<8192U\)\{\s*"
            r"c\.stop\(\);err=\"Heap contiguo insufficiente per risposta locale\";return false;\s*"
            r"\}\s*"
            r"r\.body\.reserve\(reserveLen\);start=millis\(\);",
            re.S,
        )
        text, n = base.subn(replacement, text, count=1)

    if n != 1:
        raise RuntimeError("Remote dynamic heap: generated localHttp guard anchor missing")

    path.write_text(text, encoding="utf-8")
    print(
        "AdminSensor Remote dynamic heap: post-reserve validation enabled "
        "(4 KiB actual contiguous + 16 KiB total headroom)"
    )

# The MB publisher can need a second simultaneous TLS allocation while the
# AdminSensor WSS is connected. Apply the late arbitration pass only after the
# Remote lifecycle and dynamic-response code have reached their final form.
arb = root / "scripts" / "apply_mb_tls_memory_arbitration.py"
arb_scope = {
    "__file__": str(arb),
    "__name__": "__main__",
    "env": env,
    "Import": lambda *args: None,
}
exec(compile(arb.read_text(encoding="utf-8"), str(arb), "exec"), arb_scope, arb_scope)
