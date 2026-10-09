Import("env")
from pathlib import Path
import re

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "web_manager.cpp"
text = path.read_text(encoding="utf-8")

# A source archive may have been produced from a workspace after some of the
# PlatformIO pre-scripts had already run.  In that state the SD handlers can be
# present while their initWeb() routes were later normalized/removed by another
# pass.  apply_sd_datalogger.py historically expected the original
# /api/network/reset route block and therefore stopped before it could recover.
#
# This small pre-pass only acts on that inconsistent state.  A clean checkout
# has no SD handlers yet and is deliberately left untouched.
handlers_present = all(token in text for token in (
    "void handleSdConfigGet()",
    "void handleSdConfigPost()",
    "void handleSdConfigReset()",
    "void handleSdRemount()",
))

if not handlers_present:
    print("SD route repair: clean/pre-SD source, nothing to do")
else:
    route_specs = (
        ("/api/sd", "HTTP_GET", "handleSdConfigGet"),
        ("/api/sd", "HTTP_POST", "handleSdConfigPost"),
        ("/api/sd/reset", "HTTP_POST", "handleSdConfigReset"),
        ("/api/sd/remount", "HTTP_POST", "handleSdRemount"),
    )

    def route_present(url, method):
        # Accept direct handlers and auth-wrapped lambdas, with arbitrary
        # whitespace/newlines introduced by older build passes.
        pattern = re.compile(
            r'server\.on\s*\(\s*"' + re.escape(url) + r'"\s*,\s*' + re.escape(method) + r'\s*,',
            re.S,
        )
        return pattern.search(text) is not None

    missing = [(url, method, handler) for url, method, handler in route_specs if not route_present(url, method)]

    if not missing:
        print("SD route repair: routes already present")
    else:
        lines = "".join(
            f'    server.on("{url}", {method}, {handler});\n'
            for url, method, handler in missing
        )

        # Prefer a route that is stable in both fresh and previously-auth-patched
        # workspaces.  Insert after the complete statement, regardless of
        # whether its callback is direct or a lambda.
        anchors = (
            r'(?m)^[ \t]*server\.on\s*\(\s*"/api/network/reset".*?\);[ \t]*\n',
            r'(?m)^[ \t]*server\.on\s*\(\s*"/api/config/export".*?\);[ \t]*\n',
        )
        match = None
        for expression in anchors:
            match = re.search(expression, text)
            if match:
                break

        if match:
            text = text[:match.end()] + lines + text[match.end():]
        else:
            # Last-resort semantic anchor inside initWeb().  server.onNotFound
            # occurs after all normal routes and is safe for route insertion.
            nf = re.search(r'(?m)^[ \t]*server\.onNotFound\s*\(', text)
            if not nf:
                raise RuntimeError("SD route repair: no safe initWeb route anchor found")
            text = text[:nf.start()] + lines + text[nf.start():]

        path.write_text(text, encoding="utf-8")
        repaired = ", ".join(f"{method} {url}" for url, method, _ in missing)
        print(f"SD route repair: restored {repaired}")

# The late SD browser pass intentionally upgrades the configuration loader from
# loadSd() to loadSdPanel().  On a second PlatformIO build the older SD generator
# runs first and used to interpret that upgrade as a missing patch anchor.
# Normalize only this one loader back to the generator form here; the late
# browser pass will upgrade it again before gzip generation.  This keeps clean
# builds, source archives and same-workspace rebuilds equivalent.
dash_path = root / "web" / "dashboard.html"
dash = dash_path.read_text(encoding="utf-8")
if "t==='sd')loadSdPanel()" in dash and "t==='sd')loadSd()" not in dash:
    dash = dash.replace("t==='sd')loadSdPanel()", "t==='sd')loadSd()", 1)
    dash_path.write_text(dash, encoding="utf-8")
    print("SD route repair: restored base MICROSD loader for repeat build")
elif 'id="tabSd"' in dash:
    print("SD route repair: MICROSD loader already compatible")
