# AdminSensor Remote

> Development status: introduced on `develop` after the validated `6.4.0-rc4` baseline. Firmware identity: `6.4.0-dev3`.

AdminSensor Remote provides remote administration without opening an inbound TCP port on the gateway or configuring router port forwarding. The ESP32 establishes the connection itself:

1. HTTPS enrollment to the configured AdminSensor portal;
2. approval returned by the portal;
3. authenticated outbound WSS management tunnel;
4. local Web/API requests proxied through the same protected WebServer used on the LAN.

The implementation is derived from the proven `esp32-davis-weather-gateway/develop-optimized` transport, adapted to this project's Basic-authenticated local Web UI, dual-board build and existing OTA layout.

## Configuration

The Web UI exposes **CONFIGURAZIONE > REMOTE / OTA**. Only the generic HTTPS portal base URL is configurable. The device identity is generated from the ESP32 STA MAC address and the 32-byte random device token is generated once and stored in NVS namespace `remote`.

The token is never returned by the Web API, rendered in HTML or printed to Serial. The UI reports only whether a token exists.

Management endpoints are protected by the existing Web Basic Authentication:

- `GET /api/remote/config`
- `POST /api/remote/config?portal_url=https://...`
- `GET /api/remote/status`
- `POST /api/remote/retry`
- `POST /api/remote/reset`
- `GET /api/firmware/remote-status`

The internal loopback worker authenticates itself to the local WebServer using an in-memory Basic Authorization value. That value is deliberately available only to firmware code and is never exposed through an endpoint or log.

## Transport

Enrollment is sent to:

```text
<portal>/api/device/enroll
```

with the stable device ID, random token, hostname, gateway model and installed firmware version. Public TLS validation uses the CA roots in `src/remote_trust.h`.

After approval, the device connects to the returned `wss://` endpoint using:

```text
Authorization: Bearer <device token>
```

The WebSocket uses a 5-second reconnect interval and heartbeat monitoring. HTTP proxy work is moved to a dedicated low-priority FreeRTOS worker so the WebSocket callback and the RF receive loop do not perform blocking local HTTP transactions.

Maximum proxy request body is 12 KiB, maximum local response body is 24 KiB and maximum WebSocket frame is 38 KiB. Response bodies are Base64-appended directly to the outbound JSON frame to avoid a second large body allocation. A `Content-Encoding: gzip` header is forwarded only when the received body actually starts with the gzip magic bytes.

## Remote OTA

Remote firmware update uses the same authenticated WSS session rather than the HTTP proxy. The protocol is stop-and-wait and accepts these commands:

```json
{"type":"firmware_begin","id":"ota-001","size":1380000,"sha256":"<64 hex chars>"}
{"type":"firmware_chunk","id":"ota-002","sequence":0,"data_b64":"..."}
{"type":"firmware_end","id":"ota-003"}
{"type":"firmware_abort","id":"ota-004","reason":"optional"}
```

Rules:

- exact firmware size is mandatory;
- SHA-256 is mandatory and verified before `Update.end()`;
- sequence starts at `0` and must be strictly consecutive;
- decoded chunks are limited to 8192 bytes; 4096 bytes is recommended;
- first image byte must be ESP32 application magic `0xE9`;
- declared size must fit the inactive OTA partition;
- microSD logging is stopped before remote flash writes and remounted on failure/abort;
- only a fully verified image schedules reboot;
- WSS disconnect/error, network loss, remote configuration change or manual retry aborts an active remote update.

During any firmware update the HTTP tunnel rejects new proxied requests with HTTP 423. Local Web OTA and WSS OTA share an explicit firmware-update guard, so Arduino `Update` can never be driven by both sources at once.

The existing local authenticated OTA remains available in **CONFIGURAZIONE > SISTEMA** and keeps its board-name sanity check, microSD handling and local reboot workflow.

## Partition layout

This project already uses `min_spiffs.csv` with two `0x1E0000` application slots on both supported boards. No one-time partition migration is required to use remote OTA.

Supported build environments:

- `t3-v161-433`
- `t3-s3-433`

## Security notes

AdminSensor Remote is outbound-only, but remote administration still reaches the same powerful management API available on the LAN. Keep the portal under HTTPS/WSS, protect portal accounts appropriately and do not disable the gateway Web authentication unless the device is isolated for testing.

The portal URL may change without recompiling the firmware. No deployment hostname, token or local Web password is committed to the repository.
