#!/usr/bin/env python3
"""Source-level invariants: build integration guard; not a substitute for hardware tests."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
web = (root / 'src/web_security.cpp').read_text(encoding='utf-8')
net = (root / 'src/network_manager.cpp').read_text(encoding='utf-8')
assert 'AUTH_SCHEMA_VERSION = 3U' in web
assert 'generateBootstrapPassword()' in web
assert 'password = generateBootstrapPassword();' in web
assert 'password = DEFAULT_PASSWORD;' not in web
assert 'password == DEFAULT_PASSWORD' in web
assert 'persistConfig(cfg, password)' in web
assert 'Serial.println(bootstrapPassword)' in web
assert 'esp_fill_random(randomBytes' in web
assert 'recoveryPassword = String("Oregon-") + suffix;' not in net
assert 'esp_fill_random(bytes, sizeof(bytes))' in net
assert 'p.getString("apsecret", "")' in net
assert 'p.putString("apsecret", recoveryPassword)' in net
assert 'WiFi.mode(WIFI_AP_STA);' in net
assert net.index('WiFi.mode(WIFI_AP_STA);',net.index('void startRecoveryAp()')) < net.index('buildRecoveryCredentials();',net.index('void startRecoveryAp()'))
print('Security provisioning source checks: PASS')
