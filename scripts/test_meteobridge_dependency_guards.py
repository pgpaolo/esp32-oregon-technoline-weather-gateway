from pathlib import Path
base = Path(__file__).resolve().parents[1]
php = (base / 'server/meteobridge/mbridge/mb.php').read_text(encoding='utf-8')
doc = (base / 'server/meteobridge/README.md').read_text(encoding='utf-8')
assert "DIGA_LEGACY_LIB_DIR" in php and "DIGA_LEGACY_LIB_DIR" in doc
assert "http_response_code(503)" in php
assert php.index("if (!is_readable(") < php.index("require_once $securityLibrary;")
assert "diga_require_public_realtime_request();" in php
assert "librerie" in doc.lower()
print("Meteobridge external dependency fail-closed guard: PASS")
