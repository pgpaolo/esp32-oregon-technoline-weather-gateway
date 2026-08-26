# Gateway meteo ESP32 Oregon Scientific + Technoline 433 MHz

Firmware standalone per **ESP32 / LILYGO T3 + SX1278 433.92 MHz** capace di ricevere sensori **Oregon Scientific OSV2.1/OSV3** e **Technoline / La Crosse WS23xx**, mostrare i dati tramite interfaccia Web e pubblicarli via MQTT con TLS opzionale.

Branch release candidate attuale:

```text
release/6.4.0-rc3
```

Il macro firmware è **6.4.0-rc3**. Questa release deriva direttamente dal ramo Web provisioning/auth/OTA validato in CI e conserva l'architettura RF già collaudata.

## Funzioni principali

- ricezione RF Oregon + Technoline sullo stesso SX1278 a 433.92 MHz;
- Oregon OSV3 e supporto Oregon V2.1 delimitato/validato;
- recovery dedicato **UVR128 / EC70** per preambolo tagliato o fase iniziale incerta;
- termoigrometri Oregon **CH1-CH2-CH3** con canale principale configurabile e auto-rilevamento;
- più trasmettitori UV contemporanei, inclusi UVN800 (`D874`) e UVR128 (`EC70`);
- stato RSSI uniforme sui sensori Oregon e Technoline;
- stato batteria uniforme dove previsto dal protocollo: `BAT OK`, `BAT LOW`, `BAT N/D`;
- namespace MQTT indipendente per ogni trasmettitore Oregon, basato su codice sensore + canale + rolling ID;
- configurazione MQTT per famiglia/stazione e funzione;
- MQTT TLS: disabilitato, verificato con CA oppure insecure solo per diagnostica;
- display OLED configurabile da Web, con pagina **SENSORI RF / RSSI / BATTERIE**;
- BME280 locale opzionale;
- AS3935 opzionale con Web, MQTT e OLED;
- hostname configurabile e mDNS;
- backup/ripristino JSON della configurazione;
- riavvio e spegnimento software/deep sleep;
- datalogger microSD con backend SdFat, formattazione FAT, retry automatici e badge di stato;
- provisioning Wi-Fi da Web con credenziali in NVS, prova delle nuove credenziali e rollback automatico;
- Access Point di recovery dopo perdita prolungata della rete principale;
- **scansione manuale asincrona delle reti Wi-Fi** con SSID, RSSI, canale e sicurezza;
- Basic Authentication Web attiva di default;
- credenziali iniziali di questa RC: **`admin / admin`**, da modificare da `SISTEMA`;
- OTA Web autenticato tramite `firmware.bin` PlatformIO/GitHub Actions;
- pioggia Technoline derivata localmente: intensità stimata su 5 minuti, accumulo 1 ora e 24 ore;
- correzione del rain-rate Oregon PCR800 con test di regressione sul caso circa **172,0 mm/h**;
- asset Web gzip generato durante la build.

Documentazione provisioning/sicurezza: [docs/WEB_PROVISIONING_OTA_AUTH.md](docs/WEB_PROVISIONING_OTA_AUTH.md).
Documentazione recovery RF: [docs/UVR128_RECOVERY.md](docs/UVR128_RECOVERY.md).

## Hardware

### LILYGO T3 / LoRa32 V1.6.1

- ESP32;
- SX1278 433 MHz;
- OLED SSD1306 128x64;
- ambiente PlatformIO `t3-v161-433`.

### LILYGO T3-S3 V1.2/V1.3

Ambiente PlatformIO `t3-s3-433`.

### Sensori locali opzionali

- BME280 su I2C (`0x76` / `0x77`);
- AS3935; sul T3 V1.6.1 i default sono I2C `0x03` e IRQ GPIO34.

Pinout e note: [docs/HARDWARE.md](docs/HARDWARE.md).

## Oregon Scientific

A seconda del modello vengono gestiti:

- temperatura e umidità;
- punto di rugiada e heat index;
- vento medio, current/gust, direzione e wind chill;
- pioggia totale, intensità/rate, valori locali 1h/24h e incremento frame;
- indice UV;
- canale, rolling code, modello e protocollo;
- RSSI RF e batteria quando disponibili.

Dettagli Oregon V2.1: [docs/OREGON_V21.md](docs/OREGON_V21.md).

## Technoline / La Crosse WS23xx

Vengono gestiti:

- temperatura;
- umidità;
- totale pluviometrico;
- incremento ultimo frame;
- **intensità stimata su finestra locale di 5 minuti**;
- **pioggia ultima ora** dopo almeno un'ora di storico runtime;
- **pioggia ultime 24 ore** dopo almeno 24 ore di storico runtime;
- velocità vento;
- gust quando annunciato dal protocollo;
- direzione vento;
- ID/modello;
- RSSI e diagnostica RAW.

Lo storico pioggia Technoline è mantenuto in RAM e non viene scritto in NVS/flash. Dopo un riavvio deve quindi ricostruirsi progressivamente.

## Dashboard e stato sensori

La grafica usa lo stesso criterio per tutti i sensori compatibili:

- RSSI verde >= -100 dBm;
- RSSI giallo da -115 a -101 dBm;
- RSSI rosso < -115 dBm;
- grigio se non disponibile;
- batteria verde `BAT OK`;
- batteria rossa `BAT LOW`;
- grigio `BAT N/D` quando il protocollo non fornisce il dato.

Per Technoline il valore RSSI è reale, mentre la batteria resta `N/D` perché WS23xx non trasmette lo stato batteria.

## Termoigrometri CH1-CH3

Il firmware mantiene stato separato per CH1, CH2 e CH3.

- Un canale configurabile come **principale** alimenta temperatura/umidità legacy e gli indici derivati.
- L'auto-discovery può rendere visibili automaticamente i canali ricevuti.
- I canali abilitati manualmente restano visibili anche se temporaneamente offline.
- Sono accettate sia la codifica one-hot storica `1/2/4` sia la codifica diretta osservata `1/2/3`.
- I topic legacy seguono il canale principale.
- I topic specifici restano sotto `oregon/thermo/chN/...`.

## UV multipli

UVN800 (`D874`), UVR128 (`EC70`) e futuri UV supportati possono essere visualizzati contemporaneamente. Trasmettitori dello stesso modello/canale restano distinti tramite rolling ID. Il registro live è condiviso con gli altri sensori Oregon e mantiene fino a 10 trasmettitori recenti.

## MQTT

I topic legacy restano compatibili. In aggiunta, ogni trasmettitore Oregon valido può pubblicare sotto:

```text
<base>/oregon/sensor/<CODE>/ch<CHANNEL>/id<ROLLING>/...
```

Esempi:

```text
weatherstation/oregon/sensor/F824/ch1/id165/temperature
weatherstation/oregon/sensor/1D20/ch3/id114/humidity
weatherstation/oregon/sensor/D874/ch1/id245/uv
weatherstation/oregon/sensor/EC70/ch1/id158/uv
weatherstation/oregon/sensor/1984/ch0/id170/wind_average
weatherstation/oregon/sensor/2914/ch0/id189/rain_total
```

La maschera MQTT persistente resta a 32 bit. La selezione è per funzione/famiglia, mentre i singoli trasmettitori sono separati dal namespace.

Riferimento: [docs/MQTT.md](docs/MQTT.md).

## Wi-Fi: configurazione, scansione e recovery

SSID e password possono essere modificati da **RETE / WI-FI** e vengono salvati in NVS.

Quando viene salvata una nuova coppia SSID/password, il firmware la considera inizialmente una configurazione di prova. Dopo il riavvio tenta l'associazione per 45 secondi; in caso di fallimento ripristina automaticamente le credenziali precedenti disponibili.

Il pulsante **Scansiona reti Wi-Fi** avvia una scansione asincrona soltanto su richiesta. La lista mostra SSID, RSSI, canale e rete aperta/protetta; un clic sull'SSID lo copia nel campo di configurazione. La password Wi-Fi salvata non viene mai restituita dall'API.

Se la modalità STA rimane indisponibile per circa un minuto viene attivato un AP di recovery. L'AP viene spento automaticamente non appena la rete principale torna disponibile.

## Sicurezza Web

Basic Authentication è attiva di default.

Credenziali iniziali della release candidate:

```text
utente: admin
password: admin
```

Sono credenziali di primo accesso/test e vanno cambiate immediatamente da **Configurazione > SISTEMA**. Le nuove password normali devono essere di almeno 8 caratteri. Il firmware esegue una sola migrazione delle vecchie installazioni che avevano una password casuale memorizzata in NVS; dopo la migrazione rispetta la password scelta dall'utente.

Dopo 10 tentativi di autenticazione falliti viene applicato un blocco temporaneo di 30 secondi.

Basic Auth su HTTP controlla l'accesso ma **non cifra il traffico**. Usare LAN fidata/VPN o terminazione HTTPS affidabile e non esporre direttamente la porta HTTP a Internet.

## OTA Web

Da **SISTEMA** è possibile installare il `firmware.bin` prodotto dall'ambiente PlatformIO corretto o dagli artifact GitHub Actions.

L'OTA:

- richiede autenticazione Web attiva;
- verifica l'header immagine ESP;
- controlla lo spazio disponibile nello slot OTA;
- respinge nomi file che indicano chiaramente la famiglia board opposta;
- chiude il datalogger microSD prima del flash;
- rimonta la SD se l'upload fallisce e il logger è abilitato;
- riavvia solo dopo la chiusura corretta di `Update.end()`.

## Datalogger microSD

La microSD usa il backend Greiman SdFat e il cablaggio HSPI dedicato. I frame validi e gli snapshot locali vengono accodati in RAM e scritti fuori dal percorso RF critico nei CSV UTC giornalieri sotto `/weather/`.

Se il logger è abilitato, al boot viene tentato automaticamente il mount. In caso di errore i retry non bloccanti avvengono dopo:

```text
5 s -> 15 s -> 60 s -> ogni 5 minuti
```

Non viene mai eseguita una formattazione automatica.

Il badge può mostrare `SD OFF`, `SD PRONTA`, `SD ATTESA`, `SD ON`, `SD SCRIVE`, `SD KO` o `SD ERR`.

Riferimento: [docs/SD_DATALOGGER.md](docs/SD_DATALOGGER.md).

## AS3935

AS3935 è un sensore locale I2C/IRQ opzionale con:

- stato e configurazione Web;
- diagnostica IRQ/calibrazione/risonanza;
- distanza ed energia dell'ultimo fulmine;
- MQTT selezionabile;
- pagina OLED selezionabile;
- configurazione inclusa nel backup/ripristino.

## Compilazione rapida

```bash
git clone https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway.git
cd esp32-oregon-technoline-weather-gateway
git checkout release/6.4.0-rc3
cp src/config_private.example.h src/config_private.h
pio run -e t3-v161-433
pio run -e t3-v161-433 -t upload
pio device monitor -b 115200
```

`src/config_private.h` è escluso da Git. Non pubblicare credenziali Wi-Fi/MQTT o materiale CA privato. Al primo accesso usare `admin / admin`, quindi cambiare la password da **SISTEMA**.

## Profilo RF consigliato

| Impostazione | Valore |
|---|---|
| Modalità RF | `DUAL` |
| Frequenza | `433.92 MHz` |
| Gain | `AGC` |
| Profilo RF | `STABILE` |
| Burst Extra | OFF in uso normale |
| WGR Probe | OFF in uso normale |

Il recovery UVR128 conserva comunque gli intervalli RAW necessari al fallback EC70 anche con Burst Extra disabilitato.

## Build e CI

La `release/6.4.0-rc3` viene verificata automaticamente con:

- vettore di regressione rain-rate PCR800;
- vettori host Oregon V2.1;
- build `t3-v161-433`;
- build `t3-s3-433`;
- seconda build `t3-v161-433` nello stesso workspace per verificare l'idempotenza dei pre-script;
- controllo della dimensione reale di `firmware.bin` rispetto allo slot OTA.

La partizione applicazione `min_spiffs.csv` assegna **1.966.080 byte** a ciascuno slot OTA.

## Backup configurazione

Il backup JSON comprende rete/IP/hostname, MQTT/TLS, maschera campi MQTT, canali Oregon, display, AS3935 e impostazioni RF persistenti. Le credenziali Wi-Fi e quelle dell'amministratore Web non vengono esportate; la password MQTT è esclusa salvo richiesta esplicita.

Dettagli: [docs/CONFIG_BACKUP.md](docs/CONFIG_BACKUP.md).

## Licenza e attribuzioni

GNU GPL v3 o successiva. Il decoder Technoline/WS23xx usa conoscenze e logica compatibile derivate da `rtl_433` e `PracticalArduino WeatherStationReceiver`; vedere [NOTICE](NOTICE).

## Politica branch

Il repository mantiene volutamente soltanto tre linee operative:

- `main` - stabile/produzione;
- `release/6.4.0-rc3` - release candidate corrente in collaudo finale;
- `develop` - sviluppo successivo, inizialmente clonato dalla release candidate.

Le vecchie pull request e i commit restano disponibili come storico anche dopo la rimozione dei branch intermedi.
