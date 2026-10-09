# RC6-stab2 — Physical acceptance / Piano di collaudo hardware

**Firmware:** `6.4.0-rc6-stab2` (`develop` and independent `release/6.4.0-rc6-stab2-hardening`).  
**Status:** **NOT ACCEPTED / NON ANCORA COLLAUDATO**. Hardware tests below are deliberately unchecked.  
**Reference automated baseline:** `b7f4415caa671169f60dd75d37b8947f79cdf6e6`, CI successful 2026-10-09 for T3 V1.6.1, T3-S3 and repo validation. These checks do not prove hardware reliability.

## Record / Scheda prova

| Field / Campo | To record / Da registrare |
|---|---|
| Test date/time, time zone | Pending |
| Tester | Pending |
| Physical board revision and RF frequency | Pending |
| Firmware commit and installed version | Pending |
| PlatformIO environment | `t3-v161-433` or `t3-s3-433` |
| Reset reason, uptime, free/minimum heap | Pending |
| Sensors fitted: Oregon/Technoline, SD, BME280, AS3935 | Pending |
| Sanitized logs, screenshots and evidence | Pending |
| Known-good firmware, backup and rollback method | Pending |
| Decision | **NO-GO / Pending** |

For each case record **PASS / FAIL / NOT APPLICABLE / NOT TESTED** and evidence; exclude secrets and personally identifying data. A historical successful test is *context*, not automatic proof for this binary.

## A. Initial provisioning and security

- [ ] Confirm installed firmware version and board in Serial/Web before and after reboot.
- [ ] Clean/invalid auth NVS: a unique random 24-character Web password is generated and shown on physical OLED/Serial.
- [ ] Upgrade with legacy `admin/admin`: old password fails; generated new password permits authenticated API/Web.
- [ ] Upgrade with a non-default Web password: valid custom credentials survive without reset.
- [ ] Verify authentication lockout/failure behavior and persistence after repeated power cycles.
- [ ] Force authentic Wi-Fi recovery: independent random 20-character AP secret available from physical Serial and retained after reboot; normal STA recovery terminates AP.
- [ ] No direct Internet exposure of cleartext HTTP Basic; use trusted LAN/VPN or HTTPS reverse proxy.

## B. Radio and data mapping

- [ ] Oregon OSV3 + OSV2.1 RF data accepted without checksum relaxation.
- [ ] UVN800 and UVR128 remain independent, including `BURST EXTRA` OFF behavior.
- [ ] Technoline WS23xx temperature, humidity, wind, gust (when present) and rain work in DUAL mode.
- [ ] RF overflow and parser failures remain comparable to known-good baseline under normal and elevated RF traffic.
- [ ] Primary thermo channel and individual MQTT sensor namespaces remain correctly isolated.

## C. Rain, SD and power interruption

- [ ] Verify separate Oregon and Technoline UTC daily/monthly/yearly/total accumulators against known source values.
- [ ] Verify UTC daily/monthly/yearly transitions under controlled test conditions **without changing production clocks blindly**.
- [ ] Confirm rotating/checksummed SdFat rain checkpoints survive repeated reboot and controlled power loss.
- [ ] Run >=2 hours Oregon/Technoline logging; inspect CSV and SD queue/errors/dropped records.
- [ ] Missing/unmounted, full or read-only SD must not block RF, Web or MQTT functions.
- [ ] Confirm explicit SD format requires confirmation; never test destructive format on a card with valuable data.

## D. I2C, Web, backup, MQTT and remote management

- [ ] Validate BME280 (0x76/0x77), shared I2C at 100 kHz, OLED and optional AS3935 on the real board.
- [ ] Exercise Web UI, authenticated API, OLED screens and reboot under active RF.
- [ ] Invalid multi-section configuration import must not modify thermo settings **during validation**; successful import round-trip must survive reboot. Document non-atomic NVS write limitations.
- [ ] MQTT plain and CA-verified TLS reconnect reliably; no insecure TLS mode in sustained operation.
- [ ] Check COMPATIBLE MB publisher and AdminSensor outbound WSS/TLS on configured real services and under sustained load.
- [ ] Meteobridge PHP without private legacy libraries returns expected HTTP 503; with deployed private libraries handles a real secondary station without overwriting primary data.
- [ ] Local Web OTA and remote OTA (when configured) operate using board-correct firmware; interrupted/invalid OTA does not brick the device.

## E. Endurance and rollback

- [ ] >=24-hour continuous run; record reset reason, uptime, free/min heap, RF overflows, MQTT reconnect and rainfall continuity.
- [ ] Multiple safe cold power cycles do not lose Web password, AP passphrase, saved network state or rainfall data.
- [ ] Known-good recovery/rollback procedure validated for exact board; do not assume rolling back firmware reverts NVS schema.
- [ ] T3-S3-specific features tested independently or marked NOT APPLICABLE when that device is absent.

## Decision / Decisione finale

**GO:** all applicable mandatory tests PASS with traceable evidence, regressions resolved, residual risks acknowledged. **NO-GO:** unexplained reset, credential loss, RF failure, corrupt rain/SD state, broken recovery AP or untrusted OTA. Keep [PR #26](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/pull/26) as Draft until hardware acceptance and do not change `main` through documentation work.

**Present decision: NO-GO — pending on-device evaluation.**

Related: [release notes](RELEASE_6.4.0_RC6_STAB2.md) · [security migration](SECURITY_MIGRATION_STAB2.md) · [complete subsystem checklist](TEST_CHECKLIST_V6.4.md) · [troubleshooting](TROUBLESHOOTING.md).
