# Web provisioning, autenticazione e OTA — 6.4.0-rc3

Questo documento descrive il comportamento della release candidate `release/6.4.0-rc3` per configurazione Wi-Fi, recovery di rete, autenticazione Web, OTA e interazione con il datalogger microSD.

## Credenziali Web iniziali

Basic Authentication è abilitata di default.

Credenziali iniziali della release candidate:

```text
utente: admin
password: admin
```

La password `admin` è ammessa esclusivamente come credenziale iniziale/migrazione. Dopo il primo accesso va sostituita da **Configurazione > SISTEMA**; le nuove password normali devono essere lunghe da 8 a 63 caratteri.

Le installazioni che avevano già memorizzato in NVS la precedente password casuale vengono migrate una sola volta allo schema corrente. Una volta completata la migrazione, le password impostate successivamente dall'utente non vengono più sovrascritte dai default firmware.

Dopo 10 autenticazioni fallite viene applicato un lockout temporaneo di 30 secondi.

> Basic Authentication su HTTP fornisce controllo di accesso ma non cifratura del traffico. Usare la Web UI solo su LAN fidata/VPN o dietro una terminazione HTTPS affidabile.

## Configurazione Wi-Fi

La pagina **RETE / WI-FI** permette di configurare:

- SSID;
- nuova password Wi-Fi;
- rete aperta;
- hostname;
- indirizzamento IP previsto dal firmware.

La password Wi-Fi primaria non viene mai restituita dalle API Web e non viene inclusa nei backup JSON.

Se il campo nuova password viene lasciato vuoto, il firmware conserva la password già configurata. Per impostare esplicitamente una rete aperta va usata l'opzione dedicata.

## Prova credenziali e rollback

Quando SSID/password vengono modificati, il firmware salva sia la nuova coppia sia quella precedente e marca la nuova configurazione come **trial**.

Al riavvio:

1. tenta la connessione con le nuove credenziali;
2. se l'associazione riesce, il trial viene confermato e la vecchia coppia viene eliminata;
3. se il collegamento non riesce entro circa 45 secondi, vengono ripristinate automaticamente le credenziali precedenti disponibili.

Questo evita che un errore di digitazione renda permanentemente irraggiungibile il gateway.

## Scansione reti Wi-Fi

La pagina **RETE / WI-FI** dispone del comando **Scansiona reti Wi-Fi**.

La scansione:

- parte solo su richiesta dell'utente;
- è asincrona;
- non viene eseguita in polling continuo;
- richiede autenticazione Web quando Basic Auth è attiva;
- mostra SSID, RSSI, canale e stato aperto/protetto;
- permette di copiare un SSID nel campo di configurazione con un clic;
- non legge e non espone password.

La scansione manuale è volutamente non continua per evitare lavoro radio/network non necessario durante l'acquisizione dei sensori 433 MHz.

## Recovery Access Point

Se la modalità STA resta indisponibile per circa 60 secondi, il firmware avvia un Access Point di recovery mantenendo il servizio Web disponibile localmente.

Le credenziali dell'AP sono derivate dall'identificativo hardware/MAC della scheda e vengono mostrate nello stato rete solo mentre l'AP di recovery è attivo.

Quando la connessione STA principale torna disponibile:

- l'AP viene arrestato automaticamente;
- la scheda ritorna alla normale modalità STA;
- MQTT e servizi Internet considerano connessa soltanto la STA, non il solo AP di recovery.

## OTA Web

La pagina **SISTEMA** consente di caricare un `firmware.bin` generato da PlatformIO o scaricato dagli artifact GitHub Actions.

L'OTA è disponibile soltanto quando l'autenticazione Web è attiva e la richiesta è autenticata.

Prima del flash vengono eseguiti i seguenti controlli:

- spazio libero nello slot OTA;
- header immagine ESP (`0xE9`);
- dimensione cumulativa non superiore allo slot disponibile;
- verifica degli errori di `Update.write()`;
- verifica finale di `Update.end(true)`;
- controllo semplice del nome file per evitare l'uso evidente del firmware della famiglia board opposta (`t3-v161` / `t3-s3`).

Il riavvio avviene solo dopo il completamento corretto dell'immagine.

### Firmware corretto per board

Per LILYGO T3 / LoRa32 V1.6.1:

```text
PlatformIO environment: t3-v161-433
Artifact: firmware-t3-v161-433
```

Per LILYGO T3-S3:

```text
PlatformIO environment: t3-s3-433
Artifact: firmware-t3-s3-433
```

Non installare deliberatamente il `.bin` dell'altra famiglia hardware.

## microSD durante OTA e boot

Se il datalogger è attivo, prima di iniziare il flash OTA il firmware chiude e smonta la microSD in modo controllato.

Se l'OTA fallisce, la SD viene rimontata quando il logger è abilitato.

Al boot, se il datalogger è configurato come attivo, il mount viene tentato automaticamente. In caso di errore vengono pianificati retry non bloccanti:

```text
5 secondi
15 secondi
60 secondi
poi ogni 300 secondi
```

La ricezione RF continua indipendentemente dalla presenza o dallo stato della scheda SD.

Il firmware **non formatta automaticamente** una scheda che non riesce a montare. La formattazione resta un'azione esplicita dell'utente dalla Web UI.

## Stati SD principali

La Dashboard può mostrare:

- `SD OFF` — logger disabilitato;
- `SD PRONTA` — supporto pronto;
- `SD ATTESA` — mount fallito ma retry automatico pianificato;
- `SD ON` — montata;
- `SD SCRIVE` — attività di scrittura;
- `SD KO` / `SD ERR` — errore.

L'API di stato include anche indicazione del retry pendente e del tempo residuo al prossimo tentativo.

## Backup e segreti

Il backup configurazione può includere rete/IP/hostname, MQTT/TLS, selezioni MQTT, configurazione sensori, display, AS3935 e impostazioni RF persistenti.

Non vengono esportati:

- password Wi-Fi;
- password amministratore Web.

La password MQTT segue le regole specifiche del backup e va comunque trattata come segreto.

## Sequenza consigliata per il primo collaudo

1. Installare il `firmware.bin` corretto per la board.
2. Aprire la Web UI.
3. Accedere con `admin / admin`.
4. Cambiare subito la password Web da **SISTEMA**.
5. Verificare la rete corrente.
6. Provare **Scansiona reti Wi-Fi**.
7. Se necessario salvare un nuovo SSID/password e verificare il reboot/ricollegamento.
8. Verificare microSD e stato `SD ON` / `SD SCRIVE` se il logger è abilitato.
9. Scaricare/conservare il `.bin` della stessa build prima di provare l'OTA.
10. Eseguire un OTA di prova solo dopo aver verificato la normale stabilità RF.

## Sicurezza operativa

- non esporre direttamente la porta HTTP dell'ESP32 a Internet;
- preferire LAN/VPN o reverse proxy HTTPS fidato;
- cambiare `admin / admin` al primo accesso;
- non pubblicare `src/config_private.h`;
- usare MQTT TLS con CA verificata quando il broker non è su una LAN fidata;
- usare `TLS insecure` solo per diagnostica temporanea.
