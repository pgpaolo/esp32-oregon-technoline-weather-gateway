# Troubleshooting

This guide refers to the hardware-validated storage branch `codex/sdfat-write-status`.

## No Wi-Fi connection

- Verify the 2.4 GHz SSID/password in `src/config_private.h`.
- Check static IP, gateway and DNS values.
- Use the serial monitor at 115200 baud.
- If a restored backup changed hostname/IP, verify the new values after reboot.

## Web UI not reachable

- Read the assigned IP from serial output.
- Confirm the client and ESP32 are on the same routed LAN/VLAN.
- Check firewall/client-isolation settings on the access point.
- Try the numeric IP before diagnosing mDNS.

## Oregon sensor not received

Start from conservative normal settings:

- RF mode `DUAL` or `OREGON`;
- profile `STABILE`;
- gain `AGC`;
- `BURST EXTRA` OFF for normal use;
- `WGR PROBE` OFF unless specifically diagnosing wind recovery.

Then inspect Dashboard session quality, Diagnostics and RAW frames before changing receiver thresholds.

Check antenna, 433.92 MHz radio variant, sensor batteries and physical distance/orientation.

## CH2 / CH3 thermo sensor not shown

- Confirm the sensor itself is set to the intended channel.
- Enable auto-discovery or manually enable the channel in the Oregon configuration tab.
- Wait for at least one valid transmission after changing sensor/channel configuration.
- Check whether the sensor appears in the per-transmitter session-quality table even if the main temperature card is showing another channel.
- Remember that only the selected **primary** channel feeds legacy station temperature/humidity.

## Wrong legacy temperature after adding another thermo sensor

Check the configured primary thermo channel.

Secondary CH2/CH3 values are intentionally kept independent and should not overwrite `oregon/temperature` / `oregon/humidity` or derived station values unless selected as primary.

## UVN800 works but UVR128 does not

- Confirm the firmware is built from `codex/sdfat-write-status`, not an older intermediate branch.
- Keep Oregon reception active (`OREGON` or `DUAL`).
- The EC70 recovery does **not** require optional Burst Extra to be ON.
- Check V2.1 candidate/checksum/pair/recovery counters in Diagnostics/API state.
- Confirm the sensor code is `EC70` when a valid frame appears.
- Test with the UVR128 close to the receiver before changing timing parameters.
- Avoid broad decoder relaxations: the dedicated recovery is intentionally checksum- and EC70-gated.

## Two UV sensors overwrite each other

On the consolidated branch they should not.

Check the per-transmitter namespaces:

```text
oregon/sensor/D874/ch.../id.../uv
oregon/sensor/EC70/ch.../id.../uv
```

The legacy `oregon/uv` topic is only a compatibility aggregate and can change as different valid UV transmitters are received.

## RSSI shows red

The common UI thresholds are:

- green: >= -100 dBm;
- yellow: -115..-101 dBm;
- red: < -115 dBm.

A red RSSI is not automatically an invalid packet: checksum/protocol validation determines validity. Improve antenna position, transmitter orientation or distance before modifying decoder timing.

## Battery shows N/D

This is normal when the protocol/packet does not provide a battery flag.

In particular **Technoline WS23xx does not transmit battery state**, so Web/OLED intentionally show `BAT N/D` / `B-`.

## Technoline / WS23xx not received

- Confirm the transmitter is a compatible WS23xx-family device.
- Inspect the Technoline acquisition badges and RAW diagnostics.
- Keep Burst Extra disabled during normal operation unless diagnosing reception.
- Check `next update` metadata and allow enough time for the next announced transmission.
- In DUAL mode verify Oregon traffic still works; a failure isolated to Technoline is easier to diagnose than a total RF failure.

## Gust is shown as not announced

WS23xx indicates which data types are announced in the current update cycle. `GUST non annunciata` means the current protocol cycle did not announce a gust frame; it should not be converted to a fake zero value.

## MQTT does not connect

- Verify broker IP/hostname and port.
- Test plain MQTT first on a trusted LAN.
- For CA-verified TLS, ensure the CA PEM is complete and matches the broker chain.
- `TLS insecure` can isolate certificate-validation problems but should not be permanent.
- Check username/password and client ID.
- Remember that an empty password field in the Web form preserves the stored password unless the explicit clear option is used.

## A specific MQTT measurement is missing

Check the relevant checkbox in the MQTT configuration group.

The 32-bit mask selects **functions/families**. Individual Oregon rolling IDs are not separately enabled/disabled. If the measurement function is enabled, each accepted transmitter uses its own namespace.

Use:

```bash
mosquitto_sub -h <broker> -t 'weatherstation/#' -v
```

and verify both legacy and `oregon/sensor/...` topics.

## Per-transmitter MQTT topic changes after sensor reset

Oregon rolling code can change when a transmitter is reset/re-batteried. The generic namespace intentionally includes rolling ID, so a new transmitter identity can create a new path.

Sensor code and channel remain part of the namespace for disambiguation.

## AS3935 not detected

On classic T3 V1.6.1 defaults are:

- I2C address `0x03`;
- IRQ GPIO34;
- I2C SDA 21 / SCL 22.

Check wiring and the AS3935 configuration tab. Use **Reinit** after changing address/IRQ settings.

If OLED/BME280 work but AS3935 does not, focus on address, module wiring and IRQ rather than the entire I2C bus.

## AS3935 detects too much noise/disturbers

Start with a correctly detected/calibrated sensor, then tune filters gradually:

- noise floor;
- watchdog threshold;
- spike rejection;
- minimum strikes;
- disturber mask.

Do not aggressively raise every filter before verifying IRQ/calibration/resonance.

## OLED page missing

Open the Display configuration and verify the corresponding page checkbox.

For the consolidated branch, **Sensori RF / RSSI / batterie** is an independent selectable page. AS3935 is also an independent page.

## OLED sensor page is crowded

The page is designed to show five recent Oregon transmitters at once. With more than five, it rotates automatically. It intentionally uses compact codes such as `F824`, `EC70`, G/Y/R and B+/B!/B- instead of long model names.

## OLED stays off after reboot

OLED power state is persistent. Use the Web UI display control to switch it on.

On T3 V1.6.1 the physical toggle is disabled by default unless explicitly enabled for a verified board revision.

## Controller does not wake from a button after SPEGNI

On T3 V1.6.1 the default wake path is RESET/EN. The firmware does not assume a guaranteed runtime user button on all V1.6.1 revisions.

T3-S3 can use BOOT/User GPIO0 when enabled.

## Build problems

Clean and rebuild the target environment:

```bash
pio run -t clean -e t3-v161-433
pio run -e t3-v161-433
```

Optional S3:

```bash
pio run -t clean -e t3-s3-433
pio run -e t3-s3-433
```

The build runs several idempotent pre-build scripts that generate/patch the final Web, MQTT/OLED and UVR128 recovery sources. Their status lines should appear before compilation.

## microSD does not mount

Read the top badge and the microSD Configuration tab before changing pins or RF code:

- `SD OFF`: enable the datalogger if storage is wanted;
- `SD PRONTA`: card mounted, logger disabled;
- `SD ON`: logger enabled and mounted;
- `SD SCRIVE`: new CSV records were written since the previous four-second status poll;
- `SD KO`: logger enabled but the card did not mount;
- `SD ERR`: the browser could not read `/api/sd`.

The tooltip reports written rows, queue, errors and current file. In the microSD tab, `init=FAT INVALID` with SdFat error `0x00/0x00` means the card transport initialized but the filesystem is absent/invalid; use the explicit two-confirmation `FORMATTA SD` action. A non-zero SdFat error indicates card/SPI initialization failure and formatting cannot begin yet.

The T3 V1.6.1 wiring is CS13, SCK14, MOSI15 and MISO2. The firmware tries 4 MHz and then 400 kHz after full cleanup. Do not reintroduce repeated Arduino `SD.begin()` retries: the hardware-confirmed fix uses SdFat.

Formatting erases the entire card. Copy any needed data first.

## Firmware size

Current `codex/sdfat-write-status` reference for T3 V1.6.1:

- real firmware.bin: 1,283,584 B;
- app partition: 1,966,080 B;
- application ELF: 1,276,881 B;
- margin: 689,199 B.

Both targets intentionally use `min_spiffs.csv`: the project embeds its Web UI and does not use SPIFFS, while NVS and two OTA slots remain. Do not change the layout again merely to hide a size regression; first inspect generated Web assets and linked code.
