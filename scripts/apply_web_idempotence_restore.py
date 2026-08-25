Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src/web_manager.cpp"
text = path.read_text(encoding="utf-8")

# A few older SD pre-scripts use the literal route declarations as idempotence
# anchors on the second PlatformIO build in the same workspace.  The generic
# Web-auth patch wraps routes in lambdas, which is functionally correct but
# hides those anchors.  Keep these selected declarations in their historical
# shape and enforce authentication inside their handlers instead.
routes = [
    ("/api/network/reset", "HTTP_POST", "handleNetworkConfigReset"),
    ("/api/sd", "HTTP_GET", "handleSdConfigGet"),
    ("/api/sd", "HTTP_POST", "handleSdConfigPost"),
    ("/api/sd/reset", "HTTP_POST", "handleSdConfigReset"),
    ("/api/sd/remount", "HTTP_POST", "handleSdRemount"),
    ("/api/sd/format", "HTTP_POST", "handleSdFormat"),
]

changed = False
for url, method, handler in routes:
    wrapped = (
        f'    server.on("{url}", {method}, [](){{ if (!requireWebAuth()) return; '
        f'{handler}(); }});\n'
    )
    direct = f'    server.on("{url}", {method}, {handler});\n'
    if wrapped in text:
        text = text.replace(wrapped, direct, 1)
        changed = True

    signature = f"void {handler}() {{\n"
    guarded = signature + "    if (!requireWebAuth()) return;\n"
    if signature in text and guarded not in text:
        text = text.replace(signature, guarded, 1)
        changed = True

path.write_text(text, encoding="utf-8")
print("Web auth idempotence: selected SD/network routes restored" + (" with changes" if changed else " (already stable)"))
