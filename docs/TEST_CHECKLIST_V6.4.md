# V6.4.0-rc1 - Test checklist

Questa checklist serve a validare la V6.4.0-rc1 prima di una release stabile.

## Build

- [ ] `pio run -t clean -e t3-v161-433`
- [ ] `pio run -e t3-v161-433`
- [ ] `pio run -e t3-s3-433`
- [ ] GitHub Actions: entrambi i target verdi

## Boot / system

- [ ] Avvio senza reset inattesi
- [ ] Hardware tab mostra firmware, build, Git commit e reset reason
- [ ] Heap libero/minimo stabile dopo almeno 30 minuti
- [ ] Riavvio Web funzionante

## Wi-Fi / hostname / mDNS

- [ ] IP raggiungibile
- [ ] Cambio hostname con salvataggio e reboot
- [ ] Hostname persistente dopo power cycle
- [ ] `http://hostname.local/` raggiungibile da un client con mDNS
- [ ] DHCP e IP statico verificati

## OLED

- [ ] OLED ON/OFF dalla Web UI
- [ ] Stato OLED persistente dopo reboot e power cycle
- [ ] T3 V1.6.1: toggle fisico NON attivo per default
- [ ] Se GPIO0 viene verificato sulla specifica V1.6.1, testare pressione breve dopo abilitazione esplicita
- [ ] T3-S3: GPIO0 toggle fisico verificato

## RF Oregon

- [ ] Temperatura/umidita'
- [ ] WGR800 vento/direzione/gust
- [ ] PCR800 pioggia
- [ ] UVN800 UV
- [ ] Nessun incremento anomalo degli overflow RF

## RF Technoline / WS23xx

- [ ] Temperatura
- [ ] Umidita'
- [ ] Vento
- [ ] Direzione
- [ ] Pioggia
- [ ] Gust RF, se annunciata dal trasmettitore
- [ ] Decoder stabile in modalita' DUAL

## MQTT

- [ ] Connessione MQTT plain
- [ ] Se usato: TLS CA verificato
- [ ] Campi selezionabili pubblicati correttamente
- [ ] Client ID e topic invariati dopo reboot

## Backup / restore

- [ ] Export JSON riuscito
- [ ] Il JSON NON contiene SSID/password Wi-Fi
- [ ] Password MQTT assente per default
- [ ] Export con password MQTT richiede conferma esplicita
- [ ] Import di backup valido
- [ ] Import di JSON/schema non valido rifiutato
- [ ] Configurazione ripristinata dopo reboot

## Stabilita'

- [ ] Test continuo >= 24 ore
- [ ] Nessun WDT/PANIC/BROWNOUT inatteso
- [ ] Web UI responsiva durante ricezione RF intensa
- [ ] MQTT continua a pubblicare durante uso Web

Solo dopo il completamento di questa checklist la versione deve passare da `6.4.0-rc1` a `6.4.0`.
