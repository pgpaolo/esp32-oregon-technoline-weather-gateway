# Architecture

Current consolidated development branch:

```text
codex/sdfat-write-status
```

## Data flow

```text
Oregon / Technoline 433.92 MHz sensors
                 │
                 ▼
             SX1278 OOK
                 │ raw edges / burst intervals
                 ▼
        ┌──────────────────────┐
        │ RF acquisition       │
        │ oregon_receiver.*    │
        └──────────┬───────────┘
                   │
        ┌──────────┴──────────────┐
        ▼                         ▼
 Oregon OSV3 / V2.1          Technoline WS23xx
 weather_parser.*            lacrosse_ws23xx.*
        │                         │
        │                         └──────────┐
        ▼                                    │
 thermo_channel_manager.*                   │
        │                                    │
        └──────────────┬─────────────────────┘
                       ▼
                station_state.*
                       │
           ┌───────────┼────────────┬──────────────┬─────────────┐
           ▼           ▼            ▼              ▼             ▼
        Web/API      MQTT          OLED          Serial       RAM queue
        web_mgr      publisher     display_mgr    diagnostics     │
                                                                  ▼
                                                             SdFat / CSV

BME280 ───────► barometer_manager ───────────────► station_state

AS3935 ───────► lightning_manager ──► Web / MQTT / OLED

Wi-Fi ────────► network_manager ────► Web + MQTT
```

## RF separation

The radio acquisition layer is kept separate from data presentation and network output.

- OSV3 and normal V2.1 parsing have bounded validation paths.
- UVR128/EC70 recovery is a narrow fallback using stored burst intervals, gated by EC70 identity + Manchester-pair validation + checksum.
- Technoline/WS23xx decoding remains separate from Oregon parsing.
- Presentation changes must not be used to relax RF validity checks.

## Oregon transmitter identity

A physical Oregon transmitter is represented by the combination of:

- sensor family/type;
- sensor code;
- channel;
- rolling code.

This identity is reused by session-quality diagnostics and the generic MQTT transmitter namespace.

## Thermo-channel routing

`thermo_channel_manager.*` stores CH1-CH3 state independently from the legacy station-wide temperature/humidity fields.

Only the configured **primary channel** feeds legacy temperature/humidity and derived values. Secondary channels remain available to Web/MQTT without overwriting the primary station state.

The manager also owns persistent enabled-channel and auto-discovery policy.

## Station state

`station_state.*` remains the compatibility aggregation point for legacy weather fields, derived values and Technoline state.

Per-transmitter diagnostic/presentation registries are intentionally small live structures rather than long-lived telemetry history.

## Web UI

The human-readable Dashboard source lives in `web/dashboard.html`.

During PlatformIO build it is transformed/compressed into the generated embedded asset used by `web_manager.cpp`. This keeps the source maintainable while reducing flash usage.

`web_manager.cpp` also provides the REST-style configuration/state endpoints and the live Oregon session registry used by the Dashboard.

## MQTT

`mqtt_publisher.cpp` maintains two compatibility layers:

1. legacy station/topic aliases;
2. per-transmitter Oregon namespace `oregon/sensor/<CODE>/ch<CHANNEL>/id<ROLLING>/...`.

The existing 32-bit field mask remains the persistent selection mechanism. The namespace separates individual sensors without adding a new enable bit for every rolling ID.

## OLED

`display_manager.*` owns persistent page/field/contrast/interval configuration.

The **Sensori RF / RSSI / batterie** page uses a compact live registry rather than duplicating the full Web state. Up to ten recent Oregon transmitters are tracked, five rows shown at once.

AS3935 has its own selectable page. Technoline remains a station page with common RSSI notation.

## Local sensors

### BME280

`barometer_manager.*` reads local temperature/humidity/pressure and feeds the station/local-output path.

### AS3935

`lightning_manager.*` isolates lightning detection/configuration from RF reception. The interrupt handler is minimal; I2C work is deferred outside the ISR.

AS3935 data feeds Web, MQTT and OLED but does not enter the 433 MHz receive pipeline.

## Persistence design

ESP32 Preferences/NVS is reserved for user configuration rather than continuous telemetry.

Persistent areas include network, MQTT/TLS, display, Oregon thermo-channel policy, AS3935 and persistent RF settings. Runtime reception counters/history are not continuously written to flash.

## microSD output path

`sd_logger.*` receives only already validated measurements. It copies CSV rows into a fixed 16-slot RAM queue; deferred service writes bounded batches through SdFat on the board's dedicated HSPI bus. The RF decoder never performs filesystem I/O.

The storage backend tries 4 MHz and one clean 400 kHz fallback. An explicit format operation is permitted when the card transport initialized but no supported FAT volume exists. The Web header polls the existing SD status API every four seconds and derives `SD SCRIVE` from the cumulative written-record counter; this adds no flash writes and no RF-path coupling.

## Power management

The controlled Web power-off path coordinates MQTT/offline state, OLED, BME280, AS3935, SX1278 and Wi-Fi before entering deep sleep.

Deep sleep is a controller state, not a physical power disconnect.

## Design goals

- Keep RF acquisition/validation independent from presentation/network layers.
- Never convert a weak/unknown signal into a valid measurement only to improve UI statistics.
- Keep multiple physical transmitters independent.
- Preserve legacy topics/fields while adding non-colliding per-transmitter outputs.
- Minimize RAM/flash growth by reusing compact live registries and build-time Web compression.
- Avoid flash wear by writing NVS only for user configuration changes.
- Keep removable-media failure isolated from RF, MQTT, OLED and Web operation.
- Keep raw/burst diagnostic polling off the normal Dashboard path whenever possible.
