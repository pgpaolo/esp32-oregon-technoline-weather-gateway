# V6.4 development line - consolidated hardware validation checklist

Questa checklist valida il branch corrente:

```text
codex/sdfat-write-status
```

Il macro firmware è `6.4.0-rc2`; il branch contiene ulteriori funzioni non ancora integrate in `main`.

## Build / CI

- [x] Host test Oregon V2.1 / UVR128 recovery
- [x] GitHub Actions Validate
- [x] AS3935 Integration Guard
- [x] PlatformIO `t3-v161-433`
- [x] PlatformIO `t3-s3-433`
- [x] Controllo dimensione reale `firmware.bin`
- [ ] Build locale pulita prima del merge finale: `pio run -t clean -e t3-v161-433 && pio run -e t3-v161-433`

Riferimento storage corrente: T3 64,9% Flash / 30,7% RAM; T3-S3 62,1% Flash / 30,4% RAM.

## microSD / SdFat

- [x] T3 V1.6.1: mount reale confermato
- [x] T3 V1.6.1: formattazione reale confermata
- [x] Backend SdFat 2.3.1 compilato su entrambi i target
- [x] Primo tentativo 4 MHz + fallback pulito 400 kHz
- [x] Badge superiore presente una sola volta dopo build consecutive
- [x] `SD ON` e `SD SCRIVE` derivati dallo stato/contatore reale
- [ ] Scrittura CSV Oregon e Technoline continuativa >= 2 ore
- [ ] `queue_depth=0`, `dropped=0`, `write_errors=0` durante RF intensa
- [ ] Scheda piena/read-only: gateway RF/MQTT/Web resta operativo
- [ ] Deep sleep con coda pendente: drain e chiusura verificati

## Boot / system

- [ ] Avvio senza reset inattesi
- [ ] Hardware tab mostra firmware, build, Git commit e reset reason
- [ ] Heap libero/minimo stabile dopo almeno 30 minuti
- [ ] Riavvio Web funzionante
- [ ] `SPEGNI` porta il controller in deep sleep in modo controllato
- [ ] T3 V1.6.1: wake tramite RESET/EN
- [ ] T3-S3: wake tramite RESET/EN e, se abilitato, BOOT/User GPIO0

## Wi-Fi / hostname / mDNS

- [ ] IP raggiungibile
- [ ] Cambio hostname con salvataggio e reboot
- [ ] Hostname persistente dopo power cycle
- [ ] `http://hostname.local/` raggiungibile da un client con mDNS
- [ ] DHCP e IP statico verificati

## RF Oregon OSV3

- [ ] THGN/THGR temperatura/umidità
- [ ] WGR800 vento/direzione/gust/current
- [ ] PCR800 pioggia
- [ ] UVN800 (`D874`) UV
- [ ] Nessun incremento anomalo degli overflow RF

## Oregon CH1-CH3

- [ ] CH1 indipendente
- [ ] CH2 indipendente
- [ ] CH3 indipendente
- [ ] Auto-discovery mostra un canale dopo il primo frame valido
- [ ] Canale manualmente abilitato resta visibile anche temporaneamente offline
- [ ] Cambio canale principale aggiorna solo i valori legacy/derivati previsti
- [ ] CH secondario non sovrascrive temperatura/umidità legacy
- [ ] Batteria/RSSI coerenti per ogni canale

## Oregon V2.1

- [ ] EC40 / temperatura-only se disponibile
- [ ] 1D20 / termoigrometro se disponibile
- [ ] Altri sensori V2.1 disponibili non degradano OSV3
- [ ] Contatori V2.1 checksum/pair error coerenti

## UVR128 / EC70

- [x] Ricezione hardware reale UVR128 confermata
- [ ] Verifica continuativa >= 2 ore insieme a UVN800
- [ ] UVN800 e UVR128 restano due righe/riquadri distinti
- [ ] RSSI dei due UV indipendente
- [ ] Batteria dei due UV indipendente quando trasmessa
- [ ] Nessun falso EC70 da burst Technoline/OSV3
- [ ] Recovery continua a funzionare con `BURST EXTRA` OFF

## Qualità sessione / Dashboard

- [ ] Ogni trasmettitore Oregon ha riga indipendente per code/channel/rolling ID
- [ ] RSSI verde >= -100 dBm
- [ ] RSSI giallo -115..-101 dBm
- [ ] RSSI rosso < -115 dBm
- [ ] `BAT OK` verde
- [ ] `BAT LOW` rosso
- [ ] `BAT N/D` grigio
- [ ] Vento, pioggia, termo e UV usano la stessa grammatica grafica

## RF Technoline / WS23xx

- [ ] Temperatura
- [ ] Umidità
- [ ] Vento
- [ ] Direzione
- [ ] Pioggia
- [ ] Gust se annunciata dal trasmettitore
- [ ] Decoder stabile in modalità DUAL
- [ ] RSSI mostrato con le stesse soglie Oregon
- [ ] Batteria mostrata come `N/D` / `B-`, senza inventare uno stato non trasmesso

## MQTT plain / TLS

- [ ] Connessione MQTT plain
- [ ] TLS con CA verificata
- [ ] TLS insecure solo per prova diagnostica
- [ ] Credenziali/client ID/base topic persistenti dopo reboot
- [ ] Campi deselezionati non vengono pubblicati

## MQTT Oregon legacy

- [ ] `oregon/temperature` segue solo il canale termo principale
- [ ] `oregon/humidity` segue solo il canale termo principale
- [ ] Topic vento/pioggia legacy invariati
- [ ] `oregon/uv` resta disponibile come compatibilità

## MQTT Oregon CH1-CH3

- [ ] `oregon/thermo/ch1/...`
- [ ] `oregon/thermo/ch2/...`
- [ ] `oregon/thermo/ch3/...`
- [ ] Nessuna umidità stale su sensori temperature-only

## MQTT per trasmettitore

Avviare durante il test:

```bash
mosquitto_sub -h <broker> -t 'weatherstation/#' -v
```

Verificare:

- [ ] `oregon/sensor/F824/ch.../id.../temperature`
- [ ] termoigrometri diversi non si sovrascrivono
- [ ] UVN800 `D874` e UVR128 `EC70` hanno namespace diversi
- [ ] vento Oregon ha namespace indipendente
- [ ] pioggia Oregon ha namespace indipendente
- [ ] `type/model/protocol/rssi/battery` compaiono solo con RF metadata attivi
- [ ] nessun rolling ID viene usato come falsa selezione persistente: la selezione resta per funzione/famiglia

## AS3935

- [ ] Sensore rilevato
- [ ] IRQ OK
- [ ] Calibrazione/risonanza plausibile
- [ ] Modalità Indoor/Outdoor salvata
- [ ] Filtri salvati e riletti
- [ ] Auto-tuning/fixed capacitor verificati
- [ ] Noise/Disturber/Lightning counters aggiornano correttamente
- [ ] Ultimo fulmine: distanza + energia
- [ ] MQTT state/event/last_strike/diagnostics rispettano le checkbox
- [ ] OLED AS3935 leggibile
- [ ] Reinit Web funzionante

## OLED generale

- [ ] OLED ON/OFF dalla Web UI
- [ ] Stato OLED persistente dopo reboot e power cycle
- [ ] Pagine abilitate/disabilitate rispettate
- [ ] Intervallo pagina rispettato
- [ ] Contrasto rispettato
- [ ] T3 V1.6.1: toggle fisico non attivo per default
- [ ] T3-S3: GPIO0 toggle fisico verificato

## OLED Sensori RF

- [ ] Pagina `Sensori RF / RSSI / batterie` selezionabile
- [ ] Fino a 5 righe leggibili contemporaneamente
- [ ] Con >5 trasmettitori la pagina ruota correttamente
- [ ] `G/Y/R` coerente con RSSI Dashboard
- [ ] `B+ / B! / B-` coerente con batteria Dashboard
- [ ] UV mostra codice e indice senza sovrapporre testo
- [ ] Technoline page usa la stessa classe RSSI e `B-`

## Backup / restore

- [ ] Export JSON riuscito
- [ ] JSON non contiene SSID/password Wi-Fi
- [ ] Password MQTT assente per default
- [ ] Export con password MQTT solo su scelta esplicita
- [ ] Import backup valido
- [ ] Import schema/JSON non valido rifiutato
- [ ] Configurazione rete ripristinata
- [ ] Mask MQTT ripristinata
- [ ] CH1-CH3 primary/enabled/auto-discovery ripristinati
- [ ] Pagine/campi OLED ripristinati
- [ ] AS3935 ripristinato
- [ ] RF persistente ripristinato

## Stabilità finale

- [ ] Test continuo >= 24 ore
- [ ] Nessun WDT/PANIC/BROWNOUT inatteso
- [ ] Web UI responsiva durante ricezione RF intensa
- [ ] MQTT continua a pubblicare durante uso Web
- [ ] Nessuna crescita anomala heap/fragmentazione osservabile
- [ ] Nessun peggioramento evidente nella ricezione Oregon/Technoline rispetto alla build precedente

## Criterio di merge

Il branch `codex/sdfat-write-status` può essere considerato pronto per merge solo dopo le verifiche hardware di lunga durata ancora aperte. Mount e formattazione sono confermati; non vengono presentati come prova automatica dei casi scheda piena, read-only o deep sleep con coda pendente.
