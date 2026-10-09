# Accumulo pioggia Oregon + Technoline — 6.4.0-rc6-stab1-rain1

## Scopo

Due accumulatori **indipendenti**: Oregon (ad es. PCR800) e Technoline WS23xx.
Ogni pluviometro trasmette un contatore grezzo cumulativo. Il firmware conserva
il valore grezzo precedente per la singola identita' RF e somma **solamente gli
incrementi positivi plausibili**, in millesimi di millimetro (interi). Il primo
telegramma imposta la baseline a zero; non viene considerato pioggia nuova.

- Periodi: oggi / mese / anno (tutti **UTC**) e totale accumulato dal gateway.
- Telegramma ripetuto: differenza zero, non aggiunge nulla.
- Reset sensore, cambio ID, salto grezzo >500 mm: nuova baseline, **non** genera
  falsa precipitazione. L'evento incrementa `rebases`.
- Se non c'e' NTP: il totale complessivo aumenta, ma gli intervalli calendario
  non vengono popolati fino a sincronizzazione UTC.
- Non viene ricostruita pioggia precedente al primo campione RF o ai periodi in
  cui il pluviometro rimane resettato/cambia ID; senza campioni intermedi non si
  puo' assegnare con certezza a un giorno la pioggia caduta durante un blackout.
- In caso di due pluviometri della stessa famiglia alternativi, il cambio
  identita' crea una nuova baseline; il progetto gestisce **un accumulo per
  famiglia** (non somma piu' pluviometri Oregon in contemporanea).

## Configurazione

Aprire `CONFIGURAZIONE > microSD`. Sono presenti:

- `Accumula pioggia Oregon in RAM` (default ON).
- `Accumula pioggia Technoline in RAM` (default ON).
- `Salva accumulatori su microSD (ogni 60 s)` (default OFF).

Il salvataggio persistente richiede **anche** `Abilita datalogger microSD` e
una microSD montata. Le opzioni sono registrate in NVS (`sdlog/r_oreg`,
`sdlog/r_tech`, `sdlog/r_sd`). I totali RAM sono indipendenti dai flag
`Registra ogni frame ...` (che controllano i CSV grezzi).

Lettura manuale: `GET /api/rain/accumulation`, protetto dalla stessa
sessione autenticata della Web UI. Nessuna nuova richiesta periodica nella
pagina: lettura all'apertura del tab SD e con il pulsante `Aggiorna accumuli`.

## Checkpoint su SD

Due file binari alternati (v1, sequenza, CRC FNV-1a):

- `/weather/rain_a.bin`
- `/weather/rain_b.bin`

Sono circa 112 byte ciascuno e non vengono esposti dal browser dei CSV.
Il firmware cerca entrambi al boot e ripristina l'ultimo valido; una scrittura
interrotta non sovrascrive l'altro slot. Salva solo se lo stato e' cambiato,
al massimo circa una volta al minuto, piu' flush prima dell'unmount/deep sleep.

Gli intervalli di **massimo 60 s** fra due checkpoint possono non essere
salvati alla caduta improvvisa di alimentazione. Con un sensore che conserva il
suo contatore e identita', la lettura successiva recupera naturalmente
l'incremento dal valore grezzo persistito; cio' non e' garantito in presenza
di un simultaneo reset del pluviometro. La formattazione SD cancella i vecchi
checkpoint; il firmware ne scrive di nuovi partendo dallo stato RAM.

Se la SD diventa disponibile soltanto dopo l'arrivo dei primi telegrammi,
non viene caricato tardivamente un vecchio checkpoint (evita di sovrascrivere
misure appena acquisite). In quel caso i totali partono dalla sessione RAM.

## RAM e prestazioni

Ogni `RainBucket` occupa 48 byte su una build C++ standard, per un totale di
96 byte per i dati dei due sensori (esclusi pochi byte di metadati/checkpoint).
Nessuna allocazione dinamica nei callback dei telegrammi e nessuna scrittura
SPI nel percorso RF. Scrittura SdFat differita nel loop principale.

## Test

```sh
g++ -std=c++17 -Wall -Wextra -Werror tests/test_rain_accumulator_core.cpp -o /tmp/test_rain && /tmp/test_rain
pio run -e t3-v161-433
```

**Nota:** e' necessaria una prova fisica sulla LILYGO T3 V1.6.1 per validare
le operazioni SPI/SD, il comportamento dell'alimentazione e l'OTA.
