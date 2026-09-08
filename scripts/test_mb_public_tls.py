from pathlib import Path

root = Path(__file__).resolve().parent.parent
cpp = (root / "src/mb_compatible_publisher.cpp").read_text(encoding="utf-8")
hdr = (root / "src/mb_compatible_publisher.h").read_text(encoding="utf-8")
dash = (root / "web/dashboard.html").read_text(encoding="utf-8")
ini = (root / "platformio.ini").read_text(encoding="utf-8")

required_cpp = [
    '// MB_PUBLIC_TLS_V2',
    '#include "remote_trust.h"',
    '#include <esp_heap_caps.h>',
    'client.setCACert(REMOTE_TRUST_CA);',
    'MbCompatibleTlsMode::CustomCa',
    'http.setConnectTimeout(connectTimeoutMs);',
    'http.setTimeout(requestTimeoutMs);',
    'http.setReuse(false);',
    'connectTimeoutMs = cfg.timeoutMs < 5000U ? 5000U : cfg.timeoutMs',
    'requestTimeoutMs = cfg.timeoutMs < 7000U ? 7000U : cfg.timeoutMs',
    'client.setHandshakeTimeout',
    'client.lastError(sslText, sizeof(sslText))',
    'heap_caps_get_largest_free_block(MALLOC_CAP_8BIT)',
    'WiFi.hostByName(host.c_str(), resolved)',
    'probe.connect(resolved, port, 2000)',
    'HTTPS fail http=%d ssl=%d',
    'client.stop();',
    'return "PUBLIC_CA";',
    'return "CUSTOM_CA";',
]
for needle in required_cpp:
    assert needle in cpp, f"missing MB public TLS integration: {needle}"

assert 'CustomCa = 2' in hdr
assert 'Insecure = 1' in hdr
assert 'CaVerified = 0' in hdr
assert 'CA certificate required for verified HTTPS' not in cpp
assert 'static_cast<uint8_t>(MbCompatibleTlsMode::CustomCa)' in cpp
assert 'MbCompatibleTlsMode::CustomCa && cfg.caCertificate.length() == 0U' in cpp

assert 'CA pubblica (ISRG X1/X2)' in dash
assert '<option value="2">CA personalizzata</option>' in dash
assert '<option value="1">Senza verifica (solo test)</option>' in dash
assert 'ISRG Root X1/X2 gia presenti nel firmware' in dash
assert 'pre:scripts/apply_mb_public_tls_fix.py' in ini

print('MB public TLS integration + failure diagnostics: OK')
