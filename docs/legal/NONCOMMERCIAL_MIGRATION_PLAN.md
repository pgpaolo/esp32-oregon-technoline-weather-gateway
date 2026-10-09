# Piano di migrazione verso una licenza non commerciale

**Destinazione desiderata:** una eventuale **nuova edizione**, tecnicamente e giuridicamente verificata, del firmware ESP32 Oregon/Technoline con **PolyForm Noncommercial 1.0.0** per il codice di cui il titolare detiene diritti sufficienti e licenze commerciali separate per gli impieghi non permessi.

**Richiesta operativa chiarita:** i decoder e le librerie di terzi conservano le rispettive licenze, mentre si desidera PolyForm Noncommercial per la parte originale e, se compatibile, l'edizione completa. Poiché il decoder Technoline è integrato nella stessa immagine eseguibile, l'attuale compilato resta GPL e l'etichetta PolyForm sull'insieme è subordinata a permessi aggiuntivi o sostituzione della parte derivata. Vedere [schema di licenza differenziata](MIXED_LICENSE_ARCHITECTURE.md).

**Stato:** PIANO NON ATTUATO / NO-GO AL CAMBIO GLOBALE. Gli attuali file `LICENSE`, `NOTICE`, `AUTHORS.md` e le release rimangono GPL-3.0-or-later. Nessun contenuto di questa cartella costituisce una nuova offerta di licenza del firmware distribuito.

## Criteri di uscita (gate obbligatori)

| Gate | Attività | Accettazione | Stato |
|---|---|---|---|
| G0 — Snapshot | Conservare SHA, tag, licenze e notices delle edizioni GPL esistenti | Branch e tag storici identificati e conservati | Fatto per baseline verificata |
| G1 — Provenance | Comparare il decoder `lacrosse_ws23xx.cpp` con `rtl_433` e PracticalArduino; esaminare sorgenti RF ulteriori, UI, asset e collaborazioni | Report con parti originali, parti copiate/adattate, riferimenti ai commit e autori | DA FARE |
| G2 — Titolarità | Verificare diritti su contributi, eventuali vincoli lavorativi/committenti, permessi dei titolari GPL | Documentazione firmata o prove legalmente attendibili | DA FARE |
| G3 — Sostituzione o permessi | Ottenere un consenso esplicito alla sublicenza non commerciale dalle persone/enti legittimati **oppure** sviluppare componenti indipendenti senza espressione protetta ripresa | Decoder verificato non derivato o autorizzazioni valide in ambito PolyForm | DA FARE |
| G4 — Dipendenze | Analizzare SBOM/lock file effettivi, transitive e gli obblighi LGPL, in particolare WebSockets e AS3935MI, inclusa la distribuzione binaria | Inventario versionato e modalità di conformità per firmware ESP32 | DA FARE |
| G5 — Nuovo prodotto | Separare la futura edizione legalmente distribuibile dalle pubblicazioni GPL precedenti, senza pretendere retroattività | Nuovo contenuto e package tracciato, review legale completata | DA FARE |
| G6 — Validazione | Eseguire build PlatformIO T3/T3-S3, test regressione Oregon/Technoline/MB/SD/TLS/WSS e 24 ore di stabilità sul dispositivo | CI verde e registrazione test senza riavvii inattesi | DA FARE |
| G7 — Pubblicazione | Solo dopo G1–G6: dichiarare licenza coerente, testi ufficiali, SPDX per file di esclusiva titolarità, notices upstream, schema di autorizzazione commerciale | Nuova edizione pubblicata con policy accurata, revisione legale e senza claim ingannevoli | DA FARE |

## Soluzione A — permessi degli aventi diritto

Individuare gli aventi diritto delle parti realmente adattate. Chiedere un'autorizzazione supplementare espressa **per la specifica porzione di codice**, che consenta distribuzione sotto PolyForm Noncommercial e opzioni commerciali separate, oltre a verificare le altre dipendenze e i loro obblighi. Una semplice approvazione informale, il silenzio o una licenza GPL preesistente non valgono come permesso di cambiare condizioni.

## Soluzione B — sostituzione indipendente del decoder

Produrre **una nuova implementazione senza copiare espressioni creative del codice esistente**, utilizzando specifiche di protocollo, dati tecnici pubblici e propri tracciati RF. Documentare divisione dei compiti, provenienza dei requisiti, test e revisione incrociata. Evitare il copia/incolla di funzioni, macro o stati; non basta rinominare funzioni. I fatti di protocollo non sono di per sé equivalenti al codice sorgente protetto, ma la valutazione della derivazione resta da documentare.

Per verificare equivalenza funzionale con la base GPL: test di checksum/parità, pacchetti WS23xx, tempi PWM, RF live, rain, vento, termo/igro e casi di errore. Compilare T3 V1.6.1 / T3-S3. Effettuare test di stabilità reali prima di sostituire qualsiasi componente in produzione.

## Librerie LGPL e distribuzione firmware

Valutare gli obblighi LGPL delle biblioteche effettivamente collegate. Nei dispositivi embedded con linking statico potrebbero servire forme di distribuzione di codice oggetto o altri accorgimenti per permettere la modifica/sostituzione della libreria, oltre a codice, avvisi e copyright upstream. Non affermare che PolyForm sull'applicazione elimini questi obblighi; la procedura finale deve essere verificata in relazione alle versioni esatte delle librerie/framework usate.

## Testo di intestazione — SOLO ESEMPIO FUTURO PER CODICE CON DIRITTI ACCERTATI

```cpp
/*
 * ESP32 Oregon/Technoline Weather Gateway - New Independent Edition
 * Copyright (c) 2026 Gianpaolo P.
 *
 * SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
 *
 * This original file is licensed for noncommercial purposes under
 * the PolyForm Noncommercial License 1.0.0.
 * Commercial uses require a separately negotiated written license.
 * Third-party components and existing GPL editions retain their
 * own licenses and pre-existing grants.
 *
 * See the edition-specific LICENSE and NOTICE.
 */
```

**Questo esempio non deve essere inserito nei file del firmware GPL attuale.** Non utilizzare `SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0` finché non sia documentata la titolarità e validata l'edizione di destinazione.

## Condizioni commerciali da predisporre separatamente

Se e solo se il nuovo prodotto sarà legalmente distribuibile in edizione non commerciale, un contratto commerciale separato dovrebbe definire: (a) licenziatario e prodotto/versione; (b) usi concessi, per numero di dispositivi, copie o sedi; (c) durata, territorio e possibilità di distribuzione/integrazione OEM; (d) attribuzione e marchi; (e) corrispettivo, supporto e aggiornamenti; (f) responsabilità/garanzie; (g) esclusioni rispetto al software di terzi e alla GPL storica; (h) conformità a LGPL e altre licenze upstream. Non inserire una tariffa o diritti esclusivi retroattivi non concordati.

## Cosa possiamo già fare senza cambiare licenza

- Applicare correttamente gli obblighi GPL alle versioni pubblicate, mantenendo attribution/copyright e offrendo eventualmente **supporto, collaudi, consulenza o personalizzazioni a pagamento**. Questo non vieta ad altri il commercio consentito dalla GPL.
- Proteggere identificazione di origine, marchio e identità del progetto nei limiti dei diritti applicabili; la licenza del copyright non crea automaticamente un marchio registrato.
- Lavorare privatamente a una futura edizione indipendente. Una volta distribuita, si applicheranno le condizioni valide per quella precisa edizione, senza revocare la GPL delle release passate.

**Prossima decisione tecnica richiesta:** scegliere fra richiesta di permessi agli autori upstream e implementazione indipendente del decoder WS23xx. L'opzione indipendente consente maggiore controllo sui diritti del codice, ma richiede nuovo sviluppo e collaudo, e non risolve automaticamente eventuali vincoli delle altre dipendenze.

Fonti autorevoli: https://www.gnu.org/licenses/gpl-faq.en.html ; https://polyformproject.org/licenses/noncommercial/1.0.0 ; https://github.com/practicalarduino/WeatherStationReceiver/blob/master/DISTRIBUTION .
