Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))


def function_bounds(text, signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Runtime memory V3 repeat fix: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Runtime memory V3 repeat fix: opening brace missing: {signature}")
    depth = 0
    quote = None
    escape = False
    for i in range(brace, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
    raise RuntimeError(f"Runtime memory V3 repeat fix: unclosed function: {signature}")


# Arduino Print.h defines HEX as the numeric base macro (16). Runtime Memory V3
# originally used HEX as the URL-encoder digit table identifier, which collides
# at preprocessing time. Rename only the generated V3 encoder symbols; runtime
# behavior and allocation sizing remain unchanged.
mb_path = root / "src" / "mb_compatible_publisher.cpp"
text = mb_path.read_text(encoding="utf-8")
old_decl = 'static const char HEX[] = "0123456789ABCDEF";'
new_decl = 'static const char HEX_DIGITS[] = "0123456789ABCDEF";'

if old_decl in text:
    text = text.replace(old_decl, new_decl, 1)
    text = text.replace('out += HEX[(c >> 4) & 0x0FU];', 'out += HEX_DIGITS[(c >> 4) & 0x0FU];', 1)
    text = text.replace('out += HEX[c & 0x0FU];', 'out += HEX_DIGITS[c & 0x0FU];', 1)
elif new_decl not in text:
    raise RuntimeError("Runtime memory V3 compile fix: URL encoder table anchor missing")

mb_path.write_text(text, encoding="utf-8")


# apply_remote_runtime_v2.py intentionally rebuilds remoteAccessStatusJson() on
# every source-generation pass. On a second build in the same workspace the V3
# marker/constants survive, while that rebuilt function returns to the V2-only
# HWM fields. Repair the function independently from the marker so the final
# generated source is idempotent. Proven task sizes remain unchanged.
remote_path = root / "src" / "remote_access.cpp"
remote = remote_path.read_text(encoding="utf-8")

marker = "// RUNTIME_MEMORY_V3_REMOTE\n"
queue_anchor = "constexpr UBaseType_t HTTP_QUEUE_LEN=2;\n"
if marker not in remote:
    if queue_anchor not in remote:
        raise RuntimeError("Runtime memory V3 repeat fix: Remote queue anchor missing")
    remote = remote.replace(queue_anchor, queue_anchor + marker, 1)

http_const = "constexpr uint32_t REMOTE_HTTP_STACK_BYTES=7168U;\n"
admin_const = "constexpr uint32_t REMOTE_ADMIN_STACK_BYTES=12288U;\n"
if http_const not in remote:
    if marker not in remote:
        raise RuntimeError("Runtime memory V3 repeat fix: Remote marker missing for HTTP constant")
    remote = remote.replace(marker, marker + http_const, 1)
if admin_const not in remote:
    insert_after = marker + http_const if marker + http_const in remote else marker
    remote = remote.replace(insert_after, insert_after + admin_const, 1)

old_http = 'xTaskCreate(httpWorker,"remote-http",7168,nullptr,1,&workerHandle)'
new_http = 'xTaskCreate(httpWorker,"remote-http",REMOTE_HTTP_STACK_BYTES,nullptr,1,&workerHandle)'
old_admin = 'xTaskCreate(task,"adminsensor",12288,nullptr,1,&taskHandle)'
new_admin = 'xTaskCreate(task,"adminsensor",REMOTE_ADMIN_STACK_BYTES,nullptr,1,&taskHandle)'
if old_http in remote:
    remote = remote.replace(old_http, new_http, 1)
elif new_http not in remote:
    raise RuntimeError("Runtime memory V3 repeat fix: Remote HTTP task-create anchor missing")
if old_admin in remote:
    remote = remote.replace(old_admin, new_admin, 1)
elif new_admin not in remote:
    raise RuntimeError("Runtime memory V3 repeat fix: Remote Admin task-create anchor missing")

start, end = function_bounds(remote, "String remoteAccessStatusJson()")
seg = remote[start:end]
local_anchor = "    RemoteAccessStatus s=getRemoteAccessStatus();\n"
local_block = (
    "    const uint32_t adminHwm=taskHandle?uxTaskGetStackHighWaterMark(taskHandle):0U;\n"
    "    const uint32_t httpHwm=workerHandle?uxTaskGetStackHighWaterMark(workerHandle):0U;\n"
    "    const uint32_t adminPeak=(adminHwm<=REMOTE_ADMIN_STACK_BYTES)?REMOTE_ADMIN_STACK_BYTES-adminHwm:0U;\n"
    "    const uint32_t httpPeak=(httpHwm<=REMOTE_HTTP_STACK_BYTES)?REMOTE_HTTP_STACK_BYTES-httpHwm:0U;\n"
)
if "const uint32_t adminHwm=" not in seg:
    if local_anchor not in seg:
        raise RuntimeError("Runtime memory V3 repeat fix: Remote status local anchor missing")
    seg = seg.replace(local_anchor, local_anchor + local_block, 1)
else:
    for required in ("const uint32_t httpHwm=", "const uint32_t adminPeak=", "const uint32_t httpPeak="):
        if required not in seg:
            raise RuntimeError(f"Runtime memory V3 repeat fix: incomplete Remote local telemetry: {required}")

old_stack = (
    '    j+=",\\\"stack_admin_hwm\\\":"+String(taskHandle?uxTaskGetStackHighWaterMark(taskHandle):0U);\n'
    '    j+=",\\\"stack_http_hwm\\\":"+String(workerHandle?uxTaskGetStackHighWaterMark(workerHandle):0U);\n'
)
new_stack = (
    '    j+=",\\\"stack_admin_hwm\\\":"+String(adminHwm);\n'
    '    j+=",\\\"stack_admin_size_bytes\\\":"+String(REMOTE_ADMIN_STACK_BYTES);\n'
    '    j+=",\\\"stack_admin_peak_used_bytes\\\":"+String(adminPeak);\n'
    '    j+=",\\\"stack_http_hwm\\\":"+String(httpHwm);\n'
    '    j+=",\\\"stack_http_size_bytes\\\":"+String(REMOTE_HTTP_STACK_BYTES);\n'
    '    j+=",\\\"stack_http_peak_used_bytes\\\":"+String(httpPeak);\n'
)
required_fields = (
    "stack_admin_hwm",
    "stack_admin_size_bytes",
    "stack_admin_peak_used_bytes",
    "stack_http_hwm",
    "stack_http_size_bytes",
    "stack_http_peak_used_bytes",
)
if any(field not in seg for field in required_fields):
    if old_stack not in seg:
        raise RuntimeError("Runtime memory V3 repeat fix: Remote HWM JSON anchor missing")
    seg = seg.replace(old_stack, new_stack, 1)

for field in required_fields:
    if field not in seg:
        raise RuntimeError(f"Runtime memory V3 repeat fix: Remote telemetry missing after repair: {field}")

remote = remote[:start] + seg + remote[end:]
remote_path.write_text(remote, encoding="utf-8")

print("Runtime memory V3 compile/repeat fix: HEX collision removed; Remote telemetry idempotent")
