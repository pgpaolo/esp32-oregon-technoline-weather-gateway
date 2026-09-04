# Meteobridge Adapter / Weather Realtime API v1

Questo componente mantiene compatibile il flusso Meteobridge/Weather34 esistente e aggiunge un livello normalizzato per ESP32 e stazioni secondarie.

## Obiettivo

Il ricevitore `mb.php` continua ad accettare il formato Meteobridge/Aurora-compatible. Il pacchetto validato viene inoltre normalizzato nello schema JSON `weather-realtime-v1`, separato per `station_id`.

I valori mancanti nello standard JSON sono `null`, mai `--` o entità HTML.

> Gli URL e gli identificativi riportati sotto sono esclusivamente esempi. Hostname, percorso di pubblicazione e `station_id` devono essere configurati in base all'installazione reale e non sono codificati nel progetto.

## Struttura

- `lib/weather_realtime.php`: normalizzatore e storage multi-stazione.
- `mbridge/mb.php`: ricevitore Meteobridge-compatible con supporto `station=`.
- `mbridge/weather.php`: endpoint JSON read-only per Belchertown o altri client.

## Meteobridge principale / Weather34

Il Meteobridge principale può rimanere configurato senza parametro `station`:

```text
https://weather.example.net/mbridge/mb.php
```

In questo modo continua ad alimentare il backend realtime storico usato da Weather34/Aurora e produce anche `legacy-primary.json` nello storage normalizzato.

## ESP32 secondario

Nel campo URL di COMPATIBLE MB usare, ad esempio:

```text
https://weather.example.net/mbridge/mb.php?station=station-2&source=esp32
```

Il firmware aggiunge automaticamente `&d=<packet>`.

Quando `station=` è presente, il flusso viene salvato nello storage normalizzato senza sovrascrivere il realtime legacy Weather34, salvo `legacy=1` esplicito.

## Endpoint JSON

Esempio:

```text
/mbridge/weather.php?station=station-2
```

Risposta:

```json
{
  "ok": true,
  "schema": "weather-realtime-v1",
  "station_id": "station-2",
  "source": "esp32",
  "age_seconds": 4,
  "stale": false,
  "data": {
    "temperature_c": 22.4,
    "humidity_pct": 81,
    "wind_speed_kmh": 3.2,
    "pressure_hpa": 1019.5,
    "rain_today_mm": 0.0
  }
}
```

## Storage

Default:

```text
/var/tmp/weather-realtime/
```

Esempio:

```text
legacy-primary.json
station-2.json
station-2.daily.json
```

Creazione directory consigliata:

```bash
sudo install -d -o www-data -g www-data -m 0770 /var/tmp/weather-realtime
```

La directory può essere cambiata con la variabile ambiente `WEATHER_REALTIME_DIR`.

## Belchertown

Per una stazione secondaria usare preferibilmente un URL relativo:

```ini
secondary_station_source = /mbridge/weather.php?station=station-2
secondary_station_refresh_seconds = 60
```

Questo evita mixed-content quando Belchertown viene servito via HTTPS.

## Multi-stazione

| URL ricezione | JSON normalizzato | Realtime legacy W34 |
|---|---|---|
| `mb.php` | `legacy-primary.json` | sì |
| `mb.php?station=station-2` | `station-2.json` | no |
| `mb.php?station=x&legacy=1` | `x.json` | sì |

Usare `legacy=1` per una sola sorgente, così il backend Weather34 non viene sovrascritto da stazioni diverse.

## Stato

Development / hardware test. Questo componente è destinato a essere validato sul server reale prima della promozione a una release candidate successiva.
