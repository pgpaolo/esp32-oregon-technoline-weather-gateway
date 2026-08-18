# Gateway meteo ESP32 Oregon Scientific + Technoline 433 MHz

Firmware standalone per **ESP32 / LILYGO T3 + SX1278 433.92 MHz** capace di ricevere contemporaneamente sensori **Oregon Scientific OSV3** e **Technoline / La Crosse WS23xx**, mostrare i dati tramite interfaccia Web e pubblicarli via MQTT.

Versione firmware: **V6.3**

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
- configurazione rete/MQTT persistente in NVS;
- pulsante di riavvio ESP32;
- **OLED ON/OFF** da Web con power-save persistente.

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
- **Hardware** — risorse ESP32 e stato display;
- **Configurazione** — rete e MQTT/TLS;
- **Diagnostica** — RF, gain, profili, RAW e burst.

Il display OLED può essere spento dalla Web. In questo stato U8g2 usa il power-save e il firmware sospende i refresh del display; RF, MQTT, Wi-Fi e Web continuano a funzionare.

## MQTT

Il firmware supporta pubblicazione selettiva dei campi Oregon, Technoline, BME280, stato JSON, metadati RF e risorse ESP32.

Dettagli: [docs/MQTT.md](docs/MQTT.md).

## Consumo energetico

La scheda dispone di un ingresso ADC per la tensione batteria, ma **non possiede un monitor di corrente integrato** utilizzato dal firmware. Per misurare realmente mA e W è consigliabile un INA219/INA226 su I²C.

## Sicurezza

Non pubblicare mai `src/config_private.h`. La modalità MQTT TLS senza verifica deve essere usata solo per prove. La pagina Web deve restare su rete fidata o essere protetta da VPN/reverse proxy autenticato.

## Licenza e attribuzioni

Il progetto viene distribuito sotto **GNU GPL v3 o successiva**. Il decoder WS23xx utilizza conoscenze e logica derivate da `rtl_433` e `PracticalArduino WeatherStationReceiver`; vedere [NOTICE](NOTICE).

