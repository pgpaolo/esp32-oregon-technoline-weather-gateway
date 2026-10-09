Import("env")
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))

# Show the one-time generated Web administrator password on the OLED for a
# limited interval. Serial output remains the fallback if the display is off.

# Header declaration ---------------------------------------------------------
h = root / "src/display_manager.h"
text = h.read_text(encoding="utf-8")
decl = "void showWebSecurityBootstrap(const String &username, const String &password, uint32_t durationMs = 60000UL);\n"
if decl not in text:
    anchor = "void prepareDisplayForDeepSleep();\n"
    if anchor not in text:
        raise RuntimeError("Web bootstrap OLED: display header anchor missing")
    text = text.replace(anchor, anchor + decl, 1)
    h.write_text(text, encoding="utf-8")

# Display implementation -----------------------------------------------------
p = root / "src/display_manager.cpp"
text = p.read_text(encoding="utf-8")
state_anchor = "DisplayRuntimeConfig displayCfg{};\n"
if "webSecurityBootstrapUntilMs" not in text:
    if state_anchor not in text:
        raise RuntimeError("Web bootstrap OLED: display state anchor missing")
    text = text.replace(
        state_anchor,
        state_anchor
        + "uint32_t webSecurityBootstrapUntilMs = 0;\n"
        + "String webSecurityBootstrapUser;\n"
        + "String webSecurityBootstrapPasswordText;\n",
        1,
    )

if "void showWebSecurityBootstrap(" not in text:
    func_anchor = "void prepareDisplayForDeepSleep() {\n"
    if func_anchor not in text:
        raise RuntimeError("Web bootstrap OLED: display function anchor missing")
    function = r'''void showWebSecurityBootstrap(const String &username, const String &password, uint32_t durationMs) {
    if (!displayOn || password.length() == 0U) return;
    webSecurityBootstrapUser = username;
    webSecurityBootstrapPasswordText = password;
    webSecurityBootstrapUntilMs = millis() + (durationMs < 5000UL ? 5000UL : durationMs);

    oled.setPowerSave(0);
    oled.clearBuffer();
    oled.setFont(u8g2_font_6x10_tf);
    oled.drawStr(0, 9, "WEB ADMIN - PRIMO AVVIO");
    oled.drawHLine(0, 12, 128);
    oled.setFont(u8g2_font_5x8_tf);
    String u = String("USER: ") + webSecurityBootstrapUser;
    String p = String("PASS: ") + webSecurityBootstrapPasswordText;
    oled.drawStr(0, 27, u.c_str());
    oled.drawStr(0, 40, p.c_str());
    oled.drawStr(0, 53, "Salvala e cambiala da");
    oled.drawStr(0, 63, "CONFIG > SISTEMA");
    oled.sendBuffer();
    Serial.println(F("[OLED] credenziali Web iniziali mostrate temporaneamente"));
}

'''
    text = text.replace(func_anchor, function + func_anchor, 1)

update_anchor = "void updateDisplay(const StationState &state, const OregonRxStats &rxStats, const LaCrosseRxStats &lcStats, bool wifiOk, bool mqttOk) {\n    if (!displayOn) return;\n    const uint32_t now = millis();\n"
if "webSecurityBootstrapUntilMs" in text and "webSecurityBootstrapUntilMs = 0;\n        webSecurityBootstrapUser = \"\";" not in text:
    if update_anchor not in text:
        raise RuntimeError("Web bootstrap OLED: updateDisplay anchor missing")
    guarded = update_anchor + r'''    if (webSecurityBootstrapUntilMs) {
        if (static_cast<int32_t>(now - webSecurityBootstrapUntilMs) < 0) return;
        webSecurityBootstrapUntilMs = 0;
        webSecurityBootstrapUser = "";
        webSecurityBootstrapPasswordText = "";
        lastRefreshMs = 0;
        pageEpochMs = now;
    }
'''
    text = text.replace(update_anchor, guarded, 1)

p.write_text(text, encoding="utf-8")

# Web initialization ---------------------------------------------------------
w = root / "src/web_manager.cpp"
text = w.read_text(encoding="utf-8")
call_marker = "showWebSecurityBootstrap(sec.username, bootstrapPassword, 60000UL);"
if call_marker not in text:
    anchor = "    initWebSecurity();\n"
    if anchor not in text:
        raise RuntimeError("Web bootstrap OLED: initWebSecurity anchor missing")
    call = r'''    const String bootstrapPassword = webSecurityBootstrapPassword();
    if (bootstrapPassword.length()) {
        const WebSecurityConfig sec = getWebSecurityConfig();
        showWebSecurityBootstrap(sec.username, bootstrapPassword, 60000UL);
    }
'''
    text = text.replace(anchor, anchor + call, 1)
    w.write_text(text, encoding="utf-8")

print("Web bootstrap OLED: first-boot admin credentials enabled")
