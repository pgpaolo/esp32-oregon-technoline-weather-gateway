from pathlib import Path

root = Path(__file__).resolve().parent.parent
cpp = (root / "src/mb_compatible_publisher.cpp").read_text(encoding="utf-8")
hdr = (root / "src/mb_compatible_publisher.h").read_text(encoding="utf-8")
remote_cpp = (root / "src/remote_access.cpp").read_text(encoding="utf-8")
remote_hdr = (root / "src/remote_access.h").read_text(encoding="utf-8")
dash = (root / "web/dashboard.html").read_text(encoding="utf-8")
ini = (root / "platformio.ini").read_text(encoding="utf-8")
generator = (root / "scripts/generate_web_ui.py").read_text(encoding="utf-8")

required_cpp = [
    '// MB_PUBLIC_TLS_V2',
    '// MB_TLS_MEMORY_ARBITRATION_V1',
    '#include "remote_trust.h"',
    '#include "remote_access.h"',
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
    'MB_TLS_HEAP_PAUSE_THRESHOLD = 32768U',
    'remoteAccessPauseForExternalTls(2000U)',
    'remoteAccessResumeAfterExternalTls()',
    'remote_pause=%s',
    'client.stop();',
    'return "PUBLIC_CA";',
    'return "CUSTOM_CA";',
    '"worker_stack_hwm"',
]
for needle in required_cpp:
    assert needle in cpp, f"missing MB public TLS/runtime integration: {needle}"

required_remote = [
    '// MB_TLS_REMOTE_PAUSE_V1',
    '// MB_TLS_REMOTE_API_V1',
    'externalTlsPauseRequest',
    'externalTlsPaused',
    'st.state="PAUSED_TLS"',
    'firmwareUpdateInProgress()',
    'vTaskDelay(pdMS_TO_TICKS(40))',
    'ADMIN_SENSOR_RUNTIME_V2',
    'const String resumeUrl=activeWsUrl;',
    'directReconnect=startWs(resumeUrl);',
    'EXTERNAL_TLS_DIRECT_RECONNECT',
    'externalTlsPauseCount',
    'externalTlsDirectReconnectCount',
    '"heap_largest"',
    '"stack_admin_hwm"',
    '"stack_http_hwm"',
    '"tls_pause_count"',
    '"tls_direct_reconnects"',
]
for needle in required_remote:
    assert needle in remote_cpp, f"missing Remote TLS/runtime V2 integration: {needle}"

pause_start = remote_cpp.index('// MB_TLS_REMOTE_PAUSE_V1')
pause_end = remote_cpp.index('RemoteAccessConfig c;if(take()){c=cfg;give();}', pause_start)
pause_segment = remote_cpp[pause_start:pause_end]
assert 'activeWsUrl="";' not in pause_segment, 'runtime V2 must preserve the approved WSS URL during MB pause'

assert 'bool remoteAccessPauseForExternalTls(uint32_t timeoutMs);' in remote_hdr
assert 'void remoteAccessResumeAfterExternalTls();' in remote_hdr

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
assert 'ADMIN_SENSOR_REMOTE_POLL_V3' in dash
assert "if(mainTab==='config')return 15000" in dash
assert "if(mainTab==='diag')return 8000" in dash
assert "if(mainTab==='hardware')return 8000" in dash
assert "if(!remoteUi){refreshSdHeader();setInterval(refreshSdHeader,4000);}" in dash
assert 'remoteUi?15000:4000' not in dash
assert "if(t==='config')loadNetwork();if(t==='config')loadMqtt();" not in dash

assert 'pre:scripts/apply_mb_public_tls_fix.py' in ini
assert 'apply_mb_tls_memory_arbitration.py' in (root / 'scripts/apply_remote_dynamic_response_fix.py').read_text(encoding='utf-8')
assert 'apply_remote_runtime_v2.py' in generator

print('MB public TLS + AdminSensor runtime V2 + adaptive remote UI: OK')
