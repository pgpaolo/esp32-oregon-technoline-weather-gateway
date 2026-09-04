# Gateway meteo ESP32 Oregon Scientific + Technoline 433 MHz

Firmware standalone per **ESP32 / LILYGO T3 + SX1278 433.92 MHz** capace di ricevere sensori **Oregon Scientific OSV2.1/OSV3** e **Technoline / La Crosse WS23xx**, mostrare i dati tramite interfaccia Web autenticata, pubblicarli via MQTT/TLS e integrare sensori locali BME280 e AS3935.

Autore e maintainer del progetto: **Gianpaolo P.** (`pgpaolo`) · Copyright © 2026 Gianpaolo P.

## Release candidate attuale

```text
main                 stabile / produzione + backport selettivo BME280/I2C (PR #23)
release/6.4.0-rc3    RC storico congelato
release/6.4.0-rc4    release candidate completa attuale (firmware 6.4.0-rc4)
develop               sviluppo successivo (6.4.0-dev2)
```

`release/6.4.0-rc4` è stata aggiornata integralmente con la soluzione revisionata su `develop` al commit `68c1adc7df3e4e7a56b24b13bc6bdfc80bd247f3`. RC3 resta congelata. `main` contiene ora il backport selettivo BME280/I2C mergiato tramite PR #23, mentre l'insieme completo delle funzioni RC4 resta isolato in questo branch fino a una decisione esplicita di promozione.

## Funzioni principali

- ricezione RF Oregon + Technoline sullo stesso SX1278 a **433.92 MHz**;
- Oregon OSV3 e supporto Oregon V2.1 delimitato/validato;
- recovery dedicato UVR128 / EC70;
- termoigrometri Oregon CH1-CH3 con canale principale configurabile e auto-rilevamento;
- più trasmettitori UV indipendenti, inclusi UVN800 (`D874`) e UVR128 (`EC70`);
- Technoline WS23xx: temperatura, umidità, pioggia, vento e gust;
- stato RSSI/batteria uniforme dove il protocollo lo consente;
- MQTT con gruppi selezionabili e TLS opzionale verificato con CA;
- **COMPATIBLE MB** a 192 campi con sorgente Oregon/Technoline esclusiva;
- display OLED configurabile;
- BME280 locale opzionale;
- AS3935 opzionale con Web, MQTT e OLED;
- monitor hardware CPU, heap, flash, uptime, reset/build e temperatura interna MCU quando disponibile;
- nuova pagina **CONFIGURAZIONE > I2C / HW** con scanner manuale e verifica chip-ID BME280;
- datalogger microSD SdFat con retry, formattazione FAT e diagnostica;
- provisioning Wi-Fi, scansione asincrona SSID, trial/rollback credenziali e recovery AP;
- Basic Authentication Web, backup/ripristino configurazione e OTA autenticato;
- riavvio e spegnimento software/deep sleep;
- attribuzione Web discreta con copyright, identificativo GPL e **versione firmware realmente installata**, senza polling aggiuntivo.

## Hardware supportato

### LILYGO T3 / LoRa32 V1.6.1

- ESP32;
- SX1278 433 MHz;
- OLED SSD1306 128x64;
- ambiente PlatformIO `t3-v161-433`.

### LILYGO T3-S3 V1.2/V1.3

Ambiente PlatformIO `t3-s3-433`.

Pinout e note: [docs/HARDWARE.md](docs/HARDWARE.md).

## BME280 e bus I2C

Il BME280 viene rilevato automaticamente a `0x76` o `0x77`. Sul T3 V1.6.1:

```text
SDA = GPIO21
SCL = GPIO22
```

OLED, BME280 e AS3935 condividono lo stesso controller I2C. Il collaudo hardware ha dimostrato che il problema di mancato rilevamento del BME280 era dovuto a **cavi I2C troppo lunghi / capacità del bus**, non al driver BME280.

Per aumentare il margine, il bus condiviso normale resta quindi a:

```text
100 kHz
Wire timeout 80 ms
```

Anche con SDA/SCL entrambe alte a riposo, fronti degradati da cavi troppo lunghi possono impedire gli ACK. È quindi preferibile mantenere SDA/SCL corti.

Il BME280 usa retry non bloccanti dopo circa 5 s, 15 s, 60 s e poi ogni 5 minuti. Sei letture di pressione consecutive non valide riavviano la discovery.

Documentazione: [docs/BAROMETER_BME280.md](docs/BAROMETER_BME280.md).

## Diagnostica I2C / hardware

Lo scanner completo non è più dentro BAROMETRO. È disponibile in:

```text
CONFIGURAZIONE > I2C / HW
```

La scansione è solo manuale:

1. scansione a **100 kHz**, velocità reale di esercizio;
2. lettura del registro Bosch `0xD0` su `0x76/0x77` (`0x60` identifica un BME280);
3. scansione a **400 kHz** come test di margine/stress;
4. ripristino automatico di 100 kHz / 80 ms.

La pagina mostra anche stato/indirizzo BME280 e AS3935, pin SDA/SCL e **temperatura interna MCU ESP32** quando disponibile. Quest'ultima è una temperatura del chip indicativa, **non una misura dell'ambiente**.

Documentazione: [docs/I2C_HARDWARE_DIAGNOSTICS.md](docs/I2C_HARDWARE_DIAGNOSTICS.md).

## AS3935

Sul T3 V1.6.1 il default è indirizzo I2C `0x03`, IRQ GPIO34. Il firmware usa l'indirizzo configurato in modo deterministico e mostra stato sensore, IRQ, calibrazione/risonanza, ultimo evento, distanza/energia e contatori.

## Barometro e previsione

Il BME280 fornisce pressione di stazione, pressione riportata al livello del mare, temperatura/umidità locale e trend. La quota è configurabile e persistente; il default del progetto è 584 m.

La Web UI può visualizzare hPa, mbar, inHg, mmHg o kPa. I dati interni, MQTT, COMPATIBLE MB e Weather Realtime API restano in hPa.

La testata Web include una previsione grafica in stile WMR200. Il protocollo Oregon disponibile documenta le categorie ma non la formula proprietaria: il gateway usa quindi pressione al livello del mare, trend 3 h e temperatura esterna quando richiesta per una classificazione coerente con le categorie WMR200.

## Interfaccia Web

L'interfaccia è organizzata in:

1. **Dashboard** — Oregon, Technoline e sensori locali;
2. **Hardware** — CPU/SoC, RAM, flash, uptime, temperatura MCU e rete/runtime;
3. **Configurazione** — rete/Wi-Fi, Oregon, MQTT/TLS, display, BAROMETRO, I2C/HW, AS3935, microSD/archivio, backup/ripristino e sistema/sicurezza/OTA;
4. **Diagnostica** — RF mode/gain/profile, qualità sessione, RAW e burst.

I pannelli dettagliati BME280 e AS3935 partono chiusi e si aprono cliccando il titolo.

Sotto la testata compare inoltre una riga volutamente poco invasiva:

```text
© 2026 Gianpaolo P. · firmware <versione installata> · GPL-3.0-or-later
```

La versione viene letta dalla risposta `/api/state` già usata dalla dashboard: **nessuna richiesta HTTP aggiuntiva**.

## MQTT

I topic legacy restano disponibili. Ogni trasmettitore Oregon può anche pubblicare in un namespace indipendente:

```text
<base>/oregon/sensor/<CODE>/ch<CHANNEL>/id<ROLLING>/...
```

La maschera persistente a 32 bit seleziona i gruppi Oregon, Technoline, BME280, AS3935 e gateway/sistema.

Documentazione: [docs/MQTT.md](docs/MQTT.md).

## COMPATIBLE MB

COMPATIBLE MB genera esattamente 192 campi separati da spazi verso un ricevitore configurabile in stile `mb.php`; i campi non disponibili valgono `--`.

La sorgente è esclusiva: scegliendo Oregon non viene usato Technoline come fallback e viceversa. Il BME280 è locale al gateway e può contribuire indipendentemente con pressione/dati interni.

La trasmissione HTTP/HTTPS usa un worker FreeRTOS dedicato, quindi il loop RF non attende il server remoto.

## microSD

La microSD onboard usa SdFat sul bus HSPI dedicato. I record vengono messi in coda RAM e scritti fuori dal percorso RF critico. In caso di mount fallito i retry sono circa 5 s, 15 s, 60 s e poi ogni 5 minuti. La formattazione è sempre esplicita/manuale.

Documentazione: [docs/SD_DATALOGGER.md](docs/SD_DATALOGGER.md).

## Wi-Fi, autenticazione e OTA

SSID/password Wi-Fi sono configurabili via Web e persistiti in NVS. Le nuove credenziali sono provate come configurazione trial e possono essere ripristinate automaticamente se l'associazione fallisce. Dopo perdita prolungata della STA può partire un recovery AP.

Basic Authentication è attiva di default. Credenziali iniziali:

```text
utente: admin
password: admin
```

Cambiarle subito da **CONFIGURAZIONE > SISTEMA**. Basic Auth su HTTP non cifra il traffico: usare LAN/VPN affidabile o un terminatore HTTPS sicuro.

OTA Web richiede autenticazione e controlla immagine ESP, spazio OTA e mismatch evidente di famiglia T3 prima di riavviare.

Documentazione: [docs/WEB_PROVISIONING_OTA_AUTH.md](docs/WEB_PROVISIONING_OTA_AUTH.md).

## Compilazione da RC4

```bash
git clone https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway.git
cd esp32-oregon-technoline-weather-gateway
git checkout release/6.4.0-rc4
cp src/config_private.example.h src/config_private.h
pio run -e t3-v161-433
pio run -e t3-v161-433 -t upload
pio device monitor -b 115200
```

`src/config_private.h` è ignorato da Git. Non pubblicare credenziali Wi-Fi/MQTT o CA private.

## Profilo RF consigliato

| Impostazione | Valore |
|---|---|
| Modalità RF | `DUAL` |
| Frequenza | `433.92 MHz` |
| Gain | `AGC` |
| Profilo RF | `STABILE` |
| Burst Extra | OFF in uso normale |
| WGR Probe | OFF in uso normale |

## CI / validazione release

La matrice verifica:

- regressione rain-rate PCR800;
- vettori Oregon V2.1;
- mapping COMPATIBLE MB;
- build `t3-v161-433`;
- build `t3-s3-433`;
- seconda build T3 V1.6.1 nello stesso workspace per controllare l'idempotenza dei pre-script;
- guard di integrazione I2C/HW generata;
- guard dell'attribuzione progetto e della versione firmware installata;
- dimensione reale `firmware.bin` rispetto allo slot OTA `0x1E0000`.

La sorgente esatta promossa da `develop` ha superato Validate #192 e PlatformIO Build #268. Anche il branch RC4 deve restare verde dopo i commit di identità, attribuzione e documentazione prima di qualunque merge verso `main`.

Per le dimensioni esatte del firmware usare sempre l'ultima workflow riuscita, perché l'ID Git è incorporato nel binario.

## API, backup e sicurezza

API HTTP: [docs/API.md](docs/API.md)  
Backup configurazione: [docs/CONFIG_BACKUP.md](docs/CONFIG_BACKUP.md)  
Note RC4: [docs/RELEASE_6.4.0_RC4.md](docs/RELEASE_6.4.0_RC4.md)  
Sicurezza: [SECURITY.md](SECURITY.md)

Non esporre direttamente il servizio HTTP dell'ESP32 su Internet e preferire MQTT TLS verificato con CA fuori da una LAN affidabile.

## Autore e citazione

Autore e maintainer del progetto: **Gianpaolo P.** (`pgpaolo`)  
Copyright © 2026 Gianpaolo P.

- attribuzione autore: [AUTHORS.md](AUTHORS.md)
- metadati di citazione: [CITATION.cff](CITATION.cff)
- riconoscimenti e componenti upstream: [NOTICE](NOTICE)

## Licenza

GNU GPL v3 o successiva (`GPL-3.0-or-later`). Vedere [LICENSE](LICENSE). Il testo della GPL resta invariato; attribuzione del progetto e riconoscimenti delle componenti upstream sono mantenuti separatamente in `AUTHORS.md`, `CITATION.cff` e `NOTICE`.
