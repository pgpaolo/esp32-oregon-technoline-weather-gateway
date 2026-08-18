# Architecture

```text
433.92 MHz sensors
       │
       ▼
   SX1278 OOK
       │ raw edges / pulse timing
       ▼
┌──────────────────────────────┐
│ RF receiver                  │
│ oregon_receiver.*            │
└──────────────┬───────────────┘
               │
       ┌───────┴──────────┐
       ▼                  ▼
 Oregon OSV3         WS23xx decoder
 weather_parser.*    lacrosse_ws23xx.*
       │                  │
       └────────┬─────────┘
                ▼
         station_state.*
                │
      ┌─────────┼───────────┬──────────────┐
      ▼         ▼           ▼              ▼
 Web/API      MQTT        OLED          Serial diag
 web_manager  publisher   display_mgr
                ▲
                │
             Wi-Fi

BME280 ───────────────► barometer_manager ─► station_state
```

## Design goals

- Keep RF receive/decoder work independent from presentation/network layers.
- Treat transient RF conditions as diagnostics, not fatal errors.
- Avoid flash wear from telemetry: NVS is written only for user configuration.
- Keep the embedded Web UI self-contained with no runtime external assets.
- Keep raw/burst diagnostic polling off the normal dashboard path.
