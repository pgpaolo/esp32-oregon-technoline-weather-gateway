# Gateway meteo ESP32 Oregon Scientific + Technoline 433 MHz

Firmware standalone per **ESP32 / LILYGO T3 + SX1278 433.92 MHz** capace di ricevere sensori **Oregon Scientific OSV2.1/OSV3** e **Technoline / La Crosse WS23xx**, mostrare i dati tramite interfaccia Web e pubblicarli via MQTT con TLS opzionale.

Branch di sviluppo consolidato attuale:

```text
feature/uvr128-v21-recovery
```

Il macro firmware resta **6.4.0-rc2**; questo branch contiene ulteriori funzioni in collaudo hardware non ancora integrate in `main`.

## Funzioni principali attuali

- ricezione RF Oregon + Technoline sullo stesso SX1278 a 433.92 MHz;
- Oregon OSV3 e supporto Oregon V2.1 delimitato/validato;
- recovery dedicato **UVR128 / EC70** per preambolo tagliato o fase iniziale incerta;
- termoigrometri Oregon **CH1-CH2-CH3** con canale principale configurabile e auto-rilevamento;
- più trasmettitori UV contemporanei, inclusi UVN800 (`D874`) e UVR128 (`EC70`);
- stato RSSI uniforme sui sensori Oregon e Technoline:
  - verde >= -100 dBm;
  - giallo da -115 a -101 dBm;
  - rosso < -115 dBm;
  - grigio se non disponibile;
- stato batteria uniforme dove previsto dal protocollo: `BAT OK`, `BAT LOW`, `BAT N/D`;
- Technoline WS23xx mostra correttamente `BAT N/D`, perché il protocollo non trasmette lo stato batteria;
- namespace MQTT indipendente per ogni trasmettitore Oregon, basato su codice sensore + canale + rolling ID;
- configurazione MQTT organizzata per famiglia/stazione e funzione;
- MQTT TLS: disabilitato, verificato con CA oppure insecure solo per diagnostica;
- display OLED configurabile da Web, con pagina dedicata **SENSORI RF / RSSI / BATTERIE**;
- sensore locale BME280 opzionale;
- sensore fulmini AS3935 opzionale con Web, MQTT e OLED;
- hostname configurabile e mDNS;
- backup/ripristino JSON della configurazione;
- riavvio e spegnimento software/deep sleep del controller;
- asset Web gzip generato durante la build per ridurre l'occupazione flash.

Documentazione consolidata del branch: [docs/UVR128_RECOVERY.md](docs/UVR128_RECOVERY.md).

## Hardware principale

### LILYGO T3 / LoRa32 V1.6.1

- ESP32;
- SX1278 433 MHz;
- OLED SSD1306 128x64;
- ambiente PlatformIO `t3-v161-433`.

### Variante opzionale

LILYGO T3-S3 V1.2/V1.3 + SX1278, ambiente PlatformIO `t3-s3-433`.

### Sensori locali opzionali

- BME280 su I2C, indirizzo `0x76` o `0x77`;
- AS3935. Sul T3 V1.6.1 i default sono I2C `0x03` e IRQ GPIO34.

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

## Termoigrometri CH1-CH3

Il firmware mantiene stato separato per CH1, CH2 e CH3.

- Un solo canale configurabile come **principale** alimenta i valori temperatura/umidità legacy e gli indici derivati.
- L'auto-discovery può rendere visibili automaticamente i canali ricevuti.
- I canali abilitati manualmente restano visibili anche se temporaneamente offline.
- Il parser accetta sia la codifica one-hot storica `1/2/4` sia la codifica diretta osservata `1/2/3`.
- I topic legacy seguono il canale principale.
- I topic specifici restano sotto `oregon/thermo/chN/...`.

## Dashboard e stato sensori

La grafica usa lo stesso criterio per tutti i sensori compatibili:

- pallino RSSI verde/giallo/rosso;
- batteria verde `BAT OK`;
- batteria rossa `BAT LOW`;
- grigio `BAT N/D` quando il dato non esiste.

Per Technoline il valore RSSI è reale, mentre la batteria resta `N/D` per limite del protocollo WS23xx.

I trasmettitori Oregon sono distinti per codice sensore, canale e rolling ID anche nella qualità di sessione, evitando che sensori diversi condividano i contatori.

## UV multipli

UVN800 (`D874`), UVR128 (`EC70`) e futuri UV supportati possono essere visualizzati contemporaneamente nella Dashboard. Il valore UV aggregato legacy resta disponibile per compatibilità.

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

La configurazione Web MQTT è divisa in:

- Oregon Termo/igro;
- Oregon Vento;
- Oregon Pioggia;
- Oregon UV;
- Technoline;
- BME280 locale;
- AS3935 fulmini;
- Gateway/sistema.

La maschera MQTT esistente resta a 32 bit. La selezione è per funzione/famiglia, mentre i singoli trasmettitori sono separati dal namespace; non viene aggiunto un ulteriore bit persistente per ogni rolling ID.

Con `Metadati RF` attivi vengono pubblicati anche tipo, modello, protocollo, RSSI e batteria dei trasmettitori Oregon.

Riferimento completo: [docs/MQTT.md](docs/MQTT.md).

## Display OLED

Le pagine e i campi OLED sono selezionabili dalla Web UI.

È disponibile la pagina opzionale:

```text
SENSORI RF / RSSI / BATTERIE
```

Tiene uno stato live compatto fino a 10 trasmettitori Oregon, senza storico, mostra 5 righe alla volta e ruota automaticamente se i sensori recenti sono più di 5.

Esempio:

```text
T1 F824 -116R B+
T3 1D20  -94G B+
U1 D874  -88G B+
U1 EC70 -122R B+
W0 1984  -92G B+
```

Legenda:

- `G/Y/R`: classe RSSI;
- `B+`: batteria OK;
- `B!`: batteria bassa;
- `B-`: batteria non disponibile.

Anche la pagina Technoline usa la stessa convenzione, ad esempio:

```text
ID79 -113dBm Y B-
```

## AS3935 fulmini

AS3935 è integrato come sensore locale I2C/IRQ opzionale e dispone di:

- stato e configurazione guidata Web;
- diagnostica IRQ, calibrazione e risonanza;
- distanza ed energia dell'ultimo fulmine;
- MQTT selezionabile per stato, evento, ultimo fulmine e diagnostica;
- pagina OLED selezionabile;
- configurazione inclusa nel backup/ripristino.

## Compilazione rapida

```bash
git clone https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway.git
cd esp32-oregon-technoline-weather-gateway
git checkout feature/uvr128-v21-recovery
cp src/config_private.example.h src/config_private.h
pio run -e t3-v161-433
pio run -e t3-v161-433 -t upload
pio device monitor -b 115200
```

`src/config_private.h` è escluso da Git: non pubblicare credenziali Wi-Fi/MQTT o CA private.

## Profilo RF consigliato

| Impostazione | Valore |
|---|---|
| Modalità RF | `DUAL` |
| Frequenza | `433.92 MHz` |
| Gain | `AGC` |
| Profilo RF | `STABILE` |
| Burst Extra | OFF in uso normale |
| WGR Probe | OFF in uso normale |

Il recovery UVR128 conserva comunque il minimo necessario di intervalli RAW quando Oregon è attivo, anche con Burst Extra disabilitato.

## Build e CI

Il codice funzionale è stato validato con **PlatformIO Build #92** prima dei commit finali di sola documentazione:

- Validate: PASS;
- AS3935 Integration Guard: PASS;
- `t3-v161-433`: PASS;
- `t3-s3-433`: PASS;
- vettori host Oregon V2.1: PASS.

T3 V1.6.1, Build #92:

- RAM: `92.560 / 327.680 B` = 28,2%;
- ELF applicazione: `1.226.765 / 1.310.720 B` = 93,6%;
- `firmware.bin` reale: `1.233.472 B`;
- margine reale partizione applicazione: `77.248 B`.

Artifact ID: `9498796327`.

Poiché nel firmware viene incorporato il Git commit, anche un commit di sola documentazione cambia l'identificativo binario generato pur senza modificare la logica applicativa.

## Backup configurazione

Il backup JSON comprende rete, MQTT/TLS, maschera campi MQTT, configurazione canali Oregon, display, AS3935 e impostazioni RF persistenti. Le credenziali Wi-Fi non vengono mai esportate; la password MQTT viene esclusa salvo richiesta esplicita.

Dettagli: [docs/CONFIG_BACKUP.md](docs/CONFIG_BACKUP.md).

## Spegnimento software

Il pulsante Web **SPEGNI** esegue un arresto controllato e porta l'ESP32 in deep sleep. Prima dello sleep vengono arrestati MQTT, OLED, BME280, SX1278 e Wi-Fi.

Sul T3 V1.6.1 il risveglio predefinito resta RESET/EN. Sul T3-S3 è disponibile anche il BOOT/User button GPIO0. Il deep sleep non equivale a un sezionamento elettrico reale.

## Sicurezza

- Non pubblicare `src/config_private.h`.
- Preferire TLS MQTT con verifica CA fuori da una LAN fidata.
- `TLS insecure` è solo diagnostico.
- Non esporre direttamente la Web UI a Internet senza VPN/reverse proxy autenticato/firewall.

Vedere [SECURITY.md](SECURITY.md).

## Licenza e attribuzioni

GNU GPL v3 o successiva. Il decoder Technoline/WS23xx usa conoscenze e logica compatibile derivate da `rtl_433` e `PracticalArduino WeatherStationReceiver`; vedere [NOTICE](NOTICE).

## Politica branch

La struttura prevista dopo la pulizia del repository è volutamente ridotta a:

- `main` - linea integrata/stabile;
- `feature/uvr128-v21-recovery` - linea di sviluppo/collaudo hardware corrente.

Le vecchie PR restano disponibili come storico anche dopo la rimozione dei branch intermedi.
