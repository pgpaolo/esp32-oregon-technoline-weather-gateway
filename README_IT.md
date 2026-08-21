# Gateway meteo ESP32 Oregon Scientific + Technoline 433 MHz

Firmware standalone per **ESP32 / LILYGO T3 + SX1278 433.92 MHz** capace di ricevere contemporaneamente sensori **Oregon Scientific OSV3** e **Technoline / La Crosse WS23xx**, mostrare i dati tramite interfaccia Web e pubblicarli via MQTT.

Firmware release candidate: **V6.4.0-rc1** (release stabile: **V6.3.0**)

## Funzioni principali

- ricezione RF simultanea Oregon + Technoline sullo stesso SX1278;
- dashboard Web responsive;
- bussole vento compatte per entrambe le stazioni;
- indicatori di freschezza dei dati;
- tab Hardware con CPU, RAM/heap, flash, spazio OTA, RSSI Wi-Fi e uptime;
- diagnostica RF, RAW frame e burst analyzer;
- BME280 locale opzionale;
- MQTT con selezione dei singoli campi da pubblicare;
- MQTT TLS configurabile da Web;
- hostname configurabile e mDNS (`hostname.local`) persistenti in NVS;
- configurazione rete/MQTT persistente in NVS;
- backup e ripristino JSON della configurazione;
- pulsante di riavvio ESP32;
- **OLED ON/OFF** da Web con power-save persistente;
- pressione breve del pulsante PRG/BOOT configurato per OLED ON/OFF;
- versione firmware, Git commit, data build, board e motivo ultimo reset nel tab Hardware.

## Hardware principale

- LILYGO T3 / LoRa32 V1.6.1
- ESP32
- SX1278 433 MHz
- OLED SSD1306 128×64

È presente anche un ambiente PlatformIO opzionale per LILYGO T3-S3 + SX1278.

## Compilazione rapida

```bash
cp src/config_private.example.h src/config_private.h
pio run -e t3-v161-433
pio run -e t3-v161-433 -t upload
pio device monitor -b 115200
```

`src/config_private.h` contiene le credenziali locali ed è escluso da Git tramite `.gitignore`.

## Interfaccia Web

La UI è divisa in:

- **Dashboard** — Oregon, Technoline e BME280;
- **Hardware** — risorse ESP32, firmware/build/reset e stato display;
- **Configurazione** — hostname/rete, MQTT/TLS e backup/restore;
- **Diagnostica** — RF, gain, profili, RAW e burst.

Il display OLED può essere spento dalla Web oppure commutato con una pressione breve del pulsante PRG/BOOT configurato. In questo stato U8g2 usa il power-save e il firmware sospende i refresh del display; RF, MQTT, Wi-Fi e Web continuano a funzionare. L'hostname è modificabile dalla Web e, se mDNS è disponibile sulla rete client, il gateway è raggiungibile anche come `http://<hostname>.local/`.

## Backup configurazione

La Web UI può esportare e reimportare un file JSON con hostname/IP, MQTT/TLS, maschera campi MQTT, stato OLED e configurazione RF persistente. La password MQTT è esclusa per default e viene inclusa solo su scelta esplicita; SSID e password Wi-Fi non vengono esportati perché restano nel firmware/configurazione privata. L'import valida i valori e riavvia il gateway. Dettagli: [docs/CONFIG_BACKUP.md](docs/CONFIG_BACKUP.md).

## MQTT

Il firmware supporta pubblicazione selettiva dei campi Oregon, Technoline, BME280, stato JSON, metadati RF e risorse ESP32.

Dettagli: [docs/MQTT.md](docs/MQTT.md).

## Consumo energetico

La scheda dispone di un ingresso ADC per la tensione batteria, ma **non possiede un monitor di corrente integrato** utilizzato dal firmware. Per misurare realmente mA e W è consigliabile un INA219/INA226 su I²C.

## Sicurezza

Non pubblicare mai `src/config_private.h`. La modalità MQTT TLS senza verifica deve essere usata solo per prove. La pagina Web deve restare su rete fidata o essere protetta da VPN/reverse proxy autenticato.

## Licenza e attribuzioni

Il progetto viene distribuito sotto **GNU GPL v3 o successiva**. Il decoder WS23xx utilizza conoscenze e logica derivate da `rtl_433` e `PracticalArduino WeatherStationReceiver`; vedere [NOTICE](NOTICE).

### Nota pulsante OLED e board

Il controllo OLED dalla Web UI e' disponibile su entrambe le board. Il toggle fisico e' abilitato di default solo su T3-S3, dove LILYGO dichiara `BUTTON_PIN = 0`. Sul T3 V1.6.1 resta disabilitato per default e puo' essere abilitato esplicitamente in `config_private.h` dopo verifica della revisione hardware.

## Spegnimento software del controller

La Web UI espone il pulsante **SPEGNI**. Il comando esegue un arresto controllato e porta l'ESP32 in **deep sleep** senza scollegare il cavo di alimentazione. Prima dello sleep il firmware pubblica MQTT `offline`, spegne l'OLED, porta il BME280 e l'SX1278 in sleep e disabilita il Wi-Fi.

Sul **T3 V1.6.1** il risveglio predefinito avviene con **RESET/EN**; il progetto non presume l'esistenza di un pulsante utente applicativo su quella revisione. Sul **T3-S3** il BOOT/User button GPIO0 puo' essere usato come sorgente di wake oltre a RESET/EN. Lo stato deep sleep riduce fortemente i consumi ma non equivale a un'interruzione fisica dell'alimentazione; per consumo praticamente nullo serve un load-switch/latch hardware esterno.

