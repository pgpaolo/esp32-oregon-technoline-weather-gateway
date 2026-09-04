Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "src" / "web_manager.cpp"
text = path.read_text(encoding="utf-8")


def replace_function(source, signature, replacement):
    start = source.find(signature)
    if start < 0:
        raise RuntimeError(f"BME280 Web diagnostics fix: missing function {signature}")
    brace = source.find("{", start)
    if brace < 0:
        raise RuntimeError(f"BME280 Web diagnostics fix: missing opening brace {signature}")
    depth = 0
    end = brace
    while end < len(source):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if depth == 0:
                end += 1
                while end < len(source) and source[end] in "\r\n":
                    end += 1
                return source[:start] + replacement + source[end:]
        end += 1
    raise RuntimeError(f"BME280 Web diagnostics fix: missing closing brace {signature}")


# Canonicalize the whole handler on every build. This deliberately repairs
# workspaces already modified by earlier pre-script runs, where the diagnostic
# declarations could have been inserted more than once.
handler = r'''void handleBarometerConfigGet() {
    const BarometerRuntimeConfig c = getBarometerConfig();
    const BarometerDetectionDiagnostics d = getBarometerDetectionDiagnostics();
    const uint32_t diagNow = millis();
    const uint32_t retryInMs = (d.nextRetryMs != 0 && static_cast<int32_t>(d.nextRetryMs - diagNow) > 0)
        ? static_cast<uint32_t>(d.nextRetryMs - diagNow) : 0UL;

    String out;
    out.reserve(520);
    out = "{\"altitude_m\":" + String(c.altitudeM, 1);
    out += ",\"pressure_unit\":" + String(static_cast<uint8_t>(c.displayUnit));
    out += ",\"pressure_unit_name\":\"" + String(pressureUnitName(c.displayUnit)) + "\"";
    out += ",\"detected\":"; out += barometerDetected() ? "true" : "false";
    out += ",\"address\":" + String(barometerAddress());
    out += ",\"detection_attempts\":" + String(d.attempts);
    out += ",\"last_attempt_ms\":" + String(d.lastAttemptMs);
    out += ",\"retry_in_ms\":" + String(retryInMs);
    out += ",\"retry_delay_ms\":" + String(d.retryDelayMs);
    out += ",\"i2c_sda\":" + String(I2C_SDA_PIN);
    out += ",\"i2c_scl\":" + String(I2C_SCL_PIN);
    out += ",\"i2c_ack_0x76\":"; out += d.i2cAck76 ? "true" : "false";
    out += ",\"i2c_ack_0x77\":"; out += d.i2cAck77 ? "true" : "false";
    out += ",\"read_failures_total\":" + String(d.readFailuresTotal);
    out += ",\"consecutive_read_failures\":" + String(d.consecutiveReadFailures);
    out += ",\"last_good_read_ms\":" + String(d.lastGoodReadMs);
    out += "}";
    sendNoCache();
    server.send(200, "application/json; charset=utf-8", out);
}

'''

text = replace_function(text, "void handleBarometerConfigGet() {", handler)
path.write_text(text, encoding="utf-8")
print("Canonicalized BME280 Web diagnostics handler (idempotent)")
