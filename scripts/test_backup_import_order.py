#!/usr/bin/env python3
"""Check the generated backup handler cannot commit thermo settings before validating the whole request."""
from pathlib import Path
s = (Path(__file__).resolve().parents[1] / 'src/web_manager.cpp').read_text(encoding='utf-8')
start = s.index('void handleConfigImport()')
end = s.index('void handleBurstExtra()', start)
body = s[start:end]
assert body.index('validateDisplayConfig(displayCfg)') < body.index('saveThermoChannelConfig(thermoCfg)')
assert body.index('validateLightningConfig(lightningCfg)') < body.index('saveThermoChannelConfig(thermoCfg)')
assert body.index('invalid RF backup values') < body.index('saveThermoChannelConfig(thermoCfg)')
assert body.index('validateMbCompatibleConfig(mbImport, replaceMbCa)') < body.index('saveThermoChannelConfig(thermoCfg)')
assert body.index('saveThermoChannelConfig(thermoCfg)') < body.index('saveMqttConfig(m, replacePassword, replaceCa)')
print('Backup import preflight-before-commit invariant: PASS')
