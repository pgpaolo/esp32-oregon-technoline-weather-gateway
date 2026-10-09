# Audit di provenienza e licenza — ESP32 Oregon/Technoline

**Data di riferimento:** 2026-10-09. **Stato:** PRELIMINARE — revisione tecnica documentale, non parere legale né autorizzazione a cambiare la licenza. **Ramo:** `legal/noncommercial-license-audit` dalla candidata `release/6.4.0-rc6-stab1-rain1-mbfix2-stablebase` (baseline `69fac6d0a6d94fde32bf64e36141a3b1965a5a45`).

> **Attenzione: LICENZA ATTUALE INVARIATA.** `LICENSE`, README pubblici, metadata e sorgenti restano sotto GNU GPL-3.0-or-later come attualmente dichiarato. I documenti di questa cartella NON introducono condizioni obbligatorie né eliminano diritti già concessi. Non usare bozze PolyForm come intestazioni dei file esistenti.

## Scopo e limiti

L'obiettivo del titolare è riservare l'utilizzo commerciale a una licenza separata, ammettendo usi non commerciali. Il repository corrente però dichiara codice derivato/riferito a materiale GPL di altri autori. Una diversa licenza del complesso richiede una prova verificabile di titolarità e compatibilità: **non basta cambiare il testo di `LICENSE` o aggiungere una frase al copyright**.

Questa valutazione esamina dichiarazioni di provenienza nel repository, file upstream pubblicamente consultabili e licenze delle dipendenze dirette. Non costituisce un confronto forense integrale di tutte le funzioni, di tutti gli artifact compilati e di ogni versione transitiva delle librerie. La classificazione `da verificare` non significa `libero da copyright altrui`.

## Risultato prioritario — decodifica WS23xx

| Componente | Evidenza nel codice / upstream | Implicazione prudenziale | Azione |
|---|---|---|---|
| `src/lacrosse_ws23xx.cpp` | Intestazione del file: riferimento a `rtl_433` (GPL-2.0-or-later), copyright Marc Alexander / Jonathan Oxer e dichiarazione di state-machine **derivata** da PracticalArduino. | **BLOCCANTE** fino a revisione delle parti effettivamente adattate; non rilicenziare unilateralmente sotto PolyForm. | Eseguire comparazione espressiva funzione-per-funzione e ottenere permessi aggiuntivi **oppure** realizzare una implementazione indipendente con specifiche di protocollo verificabili. |
| `rtl_433/src/devices/lacrossews.c` | File upstream GPL-2.0-or-later; collegamento: https://github.com/merbanan/rtl_433/blob/master/src/devices/lacrossews.c | Parametri di protocollo e fatti tecnici, isolati, non equivalgono automaticamente a copia protetta; **eventuale espressione di codice adattata** resta vincolata al diritto del titolare. | Registrare similitudini, provenienza, date e materiale effettivamente riprodotto. |
| `PracticalArduino WeatherStationReceiver` | `DISTRIBUTION` indica GPL-3.0-or-later e copyright 2009 Marc Alexander e Jonathan Oxer: https://github.com/practicalarduino/WeatherStationReceiver/blob/master/DISTRIBUTION ; codice: https://github.com/practicalarduino/WeatherStationReceiver/blob/master/WeatherStationReceiver.pde | La dichiarazione interna `derivato` richiede indagine prioritaria e/o permesso degli aventi diritto. | Nessuna modifica GPL/PolyForm prima di chiudere questa voce. |

**Non confondere idea e implementazione:** il fatto che un algoritmo descriva un protocollo radio non dimostra di per sé che il codice dell'applicazione sia un'opera derivata. Tuttavia il repository stesso afferma l'esistenza di una derivazione: fino a prova contraria è scorretto dichiarare l'intero progetto totalmente originale e a uso commerciale vietato.

## Inventario dipendenze PlatformIO (dichiarate direttamente)

| Dipendenza | Evidenza disponibile | Valutazione preliminare |
|---|---|---|
| RadioLib — jgromes/RadioLib | MIT dichiarata dal repository upstream | Generalmente permissiva, preservare avvisi e verificare versione / dipendenze. |
| U8g2 — olikraus/u8g2 | Libreria core BSD-2-Clause; font e alcuni esempi hanno condizioni specifiche, come indicato nel `LICENSE` upstream | Verificare quali font siano inclusi nella build ed eventuali condizioni ulteriori. |
| PubSubClient — knolleary/pubsubclient | MIT | Preservare avvisi. |
| Adafruit BME280 Library | BSD 3-Clause secondo `LICENSE` upstream | Preservare disclaimer e nomi, verificare anche dipendenze Adafruit. |
| SdFat — greiman/SdFat | MIT per repository | Verificare versione `^2.3.1` effettivamente risolta e notices. |
| ArduinoJson — bblanchon/ArduinoJson | MIT | Versione dichiarata `7.4.2`: verificare insieme all'artifact. |
| WebSockets — Links2004/arduinoWebSockets | LGPL-2.1 dichiarata dal repository upstream | Esaminare obblighi di distribuzione in caso di linking incorporato/statico, codice oggetto e modalità di sostituzione/relinking, oltre alle modifiche alla libreria. |
| AS3935MI — christandlg/AS3935MI | In `src/AS3935MI.cpp` è presente esplicita LGPL-2.1-or-later, non rilevata automaticamente come repository license | Preservare copyright Gregor Christandl e condizioni LGPL, verificando il commit fissato nell'URL PlatformIO. |
| Arduino-ESP32 / ESP-IDF / toolchain | Framework e dipendenze transitive non inventariate da questo controllo | Inventario per lockfile e pacchetto effettivamente distribuito; la sola licenza del repository non esaurisce gli obblighi di un binario. |

Link upstream verificati: https://github.com/jgromes/RadioLib ; https://github.com/olikraus/u8g2/blob/master/LICENSE ; https://github.com/knolleary/pubsubclient ; https://github.com/adafruit/Adafruit_BME280_Library/blob/master/LICENSE ; https://github.com/greiman/SdFat ; https://github.com/bblanchon/ArduinoJson ; https://github.com/Links2004/arduinoWebSockets ; https://github.com/christandlg/AS3935MI/blob/master/src/AS3935MI.cpp .

## Componenti locali ulteriormente da tracciare

| Area | File / gruppo | Esito |
|---|---|---|
| Oregon RF | `src/oregon_receiver.cpp`, `src/weather_parser.cpp`, strutture Oregon | Nessun diritto esclusivo di terzi dimostrato dal solo esame dell'header; servono cronologia, provenance e verifica di eventuali frammenti derivati da altri decoder. |
| Web/UI e interfacce | `src/web_manager.cpp`, `web/dashboard.html`, generatori Python | Apparentemente materiale di progetto; non equiparare la presenza nel repository alla prova completa di titolarità personale. |
| MB / SD / accumulo / MQTT / remote | `src/mb_compatible_publisher.cpp`, `src/rain_accumulator*`, `src/sd_logger*`, `src/remote_access*` e generatori | Verificare codice importato, contributi, commit e contratti del lavoro originale; fare revisione per singolo file. |
| Server PHP | `server/meteobridge/**` | Verificare provenienza e contratti delle librerie private esterne. Materiale non presente nel repository pubblico non va dichiarato automaticamente relicenziabile. |
| Documentazione, asset grafici | README, docs, font, icone, dashboard | Registrare origini e licenze di illustrazioni/font/traduzioni; separare testo originale da materiale di terzi. |

## Vincoli giuridici da conservare

1. **GPL e commercio:** la GPL consente usi e distribuzioni commerciali conformi alla licenza. Aggiungere a un'opera GPL la clausola `no commercial use` creerebbe un'ulteriore restrizione incompatibile: https://www.gnu.org/licenses/gpl-faq.en.html#NoMilitary .
2. **Diritti già accordati:** licenze GPL sulle copie delle release già diffuse restano esercitabili. Una nuova licenza per materiale di propria esclusiva titolarità può disciplinare una nuova concessione, ma non revoca le autorizzazioni sulle precedenti distribuzioni: https://www.gnu.org/licenses/gpl-faq.en.html#CanDeveloperThirdParty .
3. **Contributi / adattamenti:** se un altro titolare ha contribuito sotto GPL, serve il suo permesso per rilasciare quel suo materiale sotto altre condizioni: https://www.gnu.org/licenses/gpl-faq.en.html#Consider .
4. **PolyForm:** la licenza Noncommercial 1.0.0 definisce usi non commerciali inclusi molti soggetti pubblici e no-profit; non è un divieto generico di ogni uso professionale né equivale a `solo hobby privato`: https://polyformproject.org/licenses/noncommercial/1.0.0 .
5. **Codice combinato:** la separazione in file/namespace non garantisce separazione giuridica quando i componenti sono combinati in un unico programma. GPL, LGPL, MIT/BSD, permessi aggiuntivi ed eventuali eccezioni vanno analizzati sul prodotto effettivamente distribuito.
6. **Diritti d'autore sul lavoro personale:** confermare per iscritto la titolarità di tutti i contributi e l'assenza di vincoli con datore di lavoro, committenti o collaboratori; non presumerla dal nome del commit.

## Decisione temporanea

**NO-GO** al cambio della licenza dell'intero repository o all'inserimento di una clausola commerciale nel firmware attuale. **GO** alla preparazione di un ramo documentale separato, agli approfondimenti sulla provenienza, ai permessi upstream e/o a un nuovo decoder non derivato.

Il repository corrente e le release GPL possono continuare a essere mantenuti e corretti nella loro licenza esistente. Qualsiasi futura edizione PolyForm dovrà essere distinta per contenuti e titolarità, con controllo documentato del codice distribuibile.

## Audit trail

- Baseline esaminata: `69fac6d0a6d94fde32bf64e36141a3b1965a5a45`.
- File consultati: `LICENSE`, `NOTICE`, `AUTHORS.md`, `platformio.ini`, `src/lacrosse_ws23xx.cpp`, `src/oregon_receiver.cpp`, `src/weather_parser.cpp`, `src/mb_compatible_publisher.cpp`, documentazione e upstream collegati.
- Risultato della revisione: **provenance e compatibilità non ancora completamente dimostrate**; serviranno analisi di differenze del decoder, verifica delle licenze transitive e consulto giuridico prima della migrazione.
