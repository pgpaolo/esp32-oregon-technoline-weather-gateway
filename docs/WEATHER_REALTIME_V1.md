# Weather Realtime API v1 integration

Status: **development / hardware test** (`develop`, firmware `6.4.0-dev2`).

The `COMPATIBLE MB` publisher can be connected to a receiver that normalizes Meteobridge/Aurora-compatible packets into a station-specific JSON model. This lets a real Meteobridge and the ESP32 use the same receiver without mixing their live data.

## Recommended receiver URLs

Keep the primary Meteobridge / Weather34 endpoint unchanged when it must continue feeding the legacy Weather34/Aurora realtime backend:

```text
https://weather.example.net/path/mb.php
```

For a secondary ESP32 station, add a station identifier and optional source label:

```text
http://weather.example.net/path/mb.php?station=castel-giorgio-2&source=esp32
```

Because the URL already contains query parameters, the ESP32 automatically appends the realtime packet as:

```text
&d=<URL-ENCODED-PACKET>
```

No firmware-specific server hostname is hard-coded.

## Single-station separation

The receiver should treat `station=` as a namespace. A packet with an explicit station identifier is stored in that station's normalized realtime object and must not overwrite the legacy Weather34 realtime stream unless the receiver is explicitly configured to do so.

A useful compatibility policy is:

- no `station=` -> legacy primary stream + normalized `legacy-primary`;
- `station=<id>` -> normalized station only;
- `station=<id>&legacy=1` -> normalized station + legacy primary stream.

Only one source should normally be allowed to use `legacy=1`.

## Normalized read API

A consumer such as Belchertown can read a canonical JSON endpoint, for example:

```text
/diga/mbridge/weather.php?station=castel-giorgio-2
```

The canonical model is named `weather-realtime-v1`. Missing measurements are represented by JSON `null`, never by `--` or HTML entities. Display code may render `null` as an em dash.

Typical fields include temperature, humidity, dew point, wind speed/gust/direction, pressure, rain rate/today/1h/24h/total, indoor/BME values and UV where available. Daily min/max values are better maintained by the server rather than fabricated by the ESP32.

## Source selection inside the ESP32

This receiver-side station identifier is independent from the firmware's **Stazione sorgente** selector. `6.4.0-dev2` still sends weather measurements from exactly one selected RF station:

- Oregon Scientific only; or
- Technoline / La Crosse only.

The local BME280 may accompany either selection because it belongs to the gateway hardware; Oregon UV is present only when Oregon is selected.
