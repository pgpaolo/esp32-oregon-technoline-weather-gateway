Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
MARKER = "BOOT_DIAGNOSTICS_V1"


def read(path):
    return (root / path).read_text(encoding="utf-8")


def write(path, text):
    (root / path).write_text(text, encoding="utf-8")


def function_bounds(text, signature):
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Boot diagnostics: function missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Boot diagnostics: opening brace missing: {signature}")

    depth = 0
    quote = None
    escape = False
    line_comment = False
    block_comment = False
    i = brace
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if ch in ('"', "'"):
            quote = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1

    raise RuntimeError(f"Boot diagnostics: unclosed function: {signature}")


def insert_before_call(text, call, checkpoint, required=True):
    marker = f"bootDiagnosticsCheckpoint(BootCheckpoint::{checkpoint});"
    if marker in text:
        return text
    anchor = f"    {call}\n"
    if anchor not in text:
        if required:
            raise RuntimeError(f"Boot diagnostics: init anchor missing: {call.strip()}")
        return text
    return text.replace(anchor, f"    {marker}\n" + anchor, 1)


# This pass deliberately runs after generate_web_ui.py, when all generated
# services (SD, COMPATIBLE MB and AdminSensor Remote) already exist in main.cpp.
# It does not change service order, Wi-Fi behaviour, RF behaviour or task
# lifecycle; it only records the checkpoint immediately before each init.
main_path = "src/main.cpp"
main = read(main_path)
if '#include "boot_diagnostics.h"' not in main:
    anchor = '#include "thermo_channel_manager.h"\n'
    if anchor not in main:
        raise RuntimeError("Boot diagnostics: main include anchor missing")
    main = main.replace(anchor, anchor + f'#include "boot_diagnostics.h" // {MARKER}\n', 1)

if "bootDiagnosticsBegin();" not in main:
    anchor = "void setup() {\n    Serial.begin(115200);\n"
    if anchor not in main:
        raise RuntimeError("Boot diagnostics: setup start anchor missing")
    main = main.replace(
        anchor,
        "void setup() {\n    bootDiagnosticsBegin();\n    Serial.begin(115200);\n",
        1,
    )

if "bootDiagnosticsPrintSummary();" not in main:
    anchor = "    delay(100);\n"
    if anchor not in main:
        raise RuntimeError("Boot diagnostics: Serial settle anchor missing")
    main = main.replace(anchor, anchor + "    bootDiagnosticsPrintSummary();\n", 1)

main = insert_before_call(main, "initDisplay();", "DisplayInit")
main = insert_before_call(main, "initBarometer();", "BarometerInit")
main = insert_before_call(main, "initLightning();", "LightningInit")
main = insert_before_call(main, "initNetwork();", "NetworkInit")
main = insert_before_call(main, "initMQTT(mqttClient, wifiClient);", "MqttInit")
main = insert_before_call(main, "initMbCompatiblePublisher(station);", "MbInit")
main = insert_before_call(main, "initWeb(station);", "WebInit")
main = insert_before_call(main, "initRemoteAccess();", "RemoteInit")
main = insert_before_call(main, "initLaCrosseWs23xx();", "LacrosseInit")

rf_marker = "bootDiagnosticsCheckpoint(BootCheckpoint::RfInit);"
if rf_marker not in main:
    anchor = "    if (!initOregonReceiver()) {\n"
    if anchor not in main:
        raise RuntimeError("Boot diagnostics: RF init anchor missing")
    main = main.replace(anchor, f"    {rf_marker}\n" + anchor, 1)

main = insert_before_call(main, "initThermoChannels();", "ThermoInit")
main = insert_before_call(main, "initSdLogger();", "SdInit")

ready = "    bootDiagnosticsCheckpoint(BootCheckpoint::Ready); // BOOT_DIAGNOSTICS_READY\n"
if "BOOT_DIAGNOSTICS_READY" not in main:
    s, e = function_bounds(main, "void setup() {")
    block = main[s:e]
    close = block.rfind("}")
    if close < 0:
        raise RuntimeError("Boot diagnostics: setup close missing")
    block = block[:close] + ready + block[close:]
    main = main[:s] + block + main[e:]

write(main_path, main)

# Network milestones are separate from setup checkpoints. This distinguishes a
# completed setup that is still associating from an actual boot-time failure.
net_path = "src/network_manager.cpp"
net = read(net_path)
if '#include "boot_diagnostics.h"' not in net:
    anchor = '#include "config.h"\n'
    if anchor not in net:
        raise RuntimeError("Boot diagnostics: network include anchor missing")
    net = net.replace(anchor, anchor + '#include "boot_diagnostics.h"\n', 1)

s, e = function_bounds(net, "void initNetwork() {")
block = net[s:e]
if "BootNetworkState::StaPending" not in block:
    anchor = "    beginSta();\n"
    if anchor not in block:
        raise RuntimeError("Boot diagnostics: initNetwork beginSta anchor missing")
    block = block.replace(anchor, anchor + "    bootDiagnosticsNetwork(BootNetworkState::StaPending);\n", 1)
    net = net[:s] + block + net[e:]

s, e = function_bounds(net, "void startRecoveryAp() {")
block = net[s:e]
if "BootNetworkState::RecoveryAp" not in block:
    anchor = "    recoveryApActive = true;\n"
    if anchor not in block:
        raise RuntimeError("Boot diagnostics: recovery AP anchor missing")
    block = block.replace(anchor, anchor + "    bootDiagnosticsNetwork(BootNetworkState::RecoveryAp);\n", 1)
    net = net[:s] + block + net[e:]

s, e = function_bounds(net, "void serviceWiFi() {")
block = net[s:e]
if "BootNetworkState::StaConnected" not in block:
    anchor = "        if (!wasConnected) {\n"
    if anchor not in block:
        raise RuntimeError("Boot diagnostics: Wi-Fi connected anchor missing")
    block = block.replace(anchor, anchor + "            bootDiagnosticsNetwork(BootNetworkState::StaConnected);\n", 1)
if "BootNetworkState::Lost" not in block:
    anchor = '        Serial.println(F("[WiFi] connessione persa"));\n'
    if anchor not in block:
        raise RuntimeError("Boot diagnostics: Wi-Fi lost anchor missing")
    block = block.replace(anchor, anchor + "        bootDiagnosticsNetwork(BootNetworkState::Lost);\n", 1)
net = net[:s] + block + net[e:]
write(net_path, net)

# Expose the retained checkpoint in /api/state. Fixed enum names are ASCII and
# need no additional JSON escaping.
web_path = "src/web_manager.cpp"
web = read(web_path)
if '#include "boot_diagnostics.h"' not in web:
    anchor = '#include "firmware_info.h"\n'
    if anchor not in web:
        raise RuntimeError("Boot diagnostics: Web include anchor missing")
    web = web.replace(anchor, anchor + '#include "boot_diagnostics.h"\n', 1)

if '\\"previous_checkpoint\\"' not in web:
    anchor = '    out += "\\\"version\\\":\\\"" + String(firmwareVersion()) + "\\\"";\n'
    if anchor not in web:
        raise RuntimeError("Boot diagnostics: /api/state version anchor missing")
    boot_json = r'''    out += ",\"boot\":{\"checkpoint\":\"" + String(bootCheckpointName(bootDiagnosticsCurrentCheckpoint())) + "\"";
    out += ",\"previous_checkpoint\":\"" + String(bootCheckpointName(bootDiagnosticsPreviousCheckpoint())) + "\"";
    out += ",\"previous_complete\":"; out += bootDiagnosticsPreviousComplete() ? "true" : "false";
    out += ",\"network_state\":\"" + String(bootNetworkStateName(bootDiagnosticsCurrentNetworkState())) + "\"";
    out += ",\"previous_network_state\":\"" + String(bootNetworkStateName(bootDiagnosticsPreviousNetworkState())) + "\"";
    out += ",\"reset_reason\":\"" + String(bootDiagnosticsResetReasonName()) + "\"";
    out += ",\"rtc_boot_count\":" + String(bootDiagnosticsRtcBootCount()) + "}";
'''
    web = web.replace(anchor, anchor + boot_json, 1)
write(web_path, web)

# Fail the generation pass if any essential final-source marker is missing.
final_main = read(main_path)
final_net = read(net_path)
final_web = read(web_path)
checks = {
    "main begin": "bootDiagnosticsBegin();" in final_main,
    "main ready": "BOOT_DIAGNOSTICS_READY" in final_main,
    "network pending": "BootNetworkState::StaPending" in final_net,
    "network connected": "BootNetworkState::StaConnected" in final_net,
    "network recovery AP": "BootNetworkState::RecoveryAp" in final_net,
    "state JSON": '\\"previous_checkpoint\\"' in final_web,
}
missing = [name for name, ok in checks.items() if not ok]
if missing:
    raise RuntimeError("Boot diagnostics final validation failed: " + ", ".join(missing))

print("Boot diagnostics V1: RTC checkpoints + Wi-Fi milestones + /api/state enabled")
