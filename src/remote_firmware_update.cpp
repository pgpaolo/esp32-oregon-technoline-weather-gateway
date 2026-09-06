#include "remote_firmware_update.h"

#include <Update.h>
#include <esp_ota_ops.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <mbedtls/sha256.h>

#include "config.h"
#include "sd_logger.h"

namespace {
enum class UpdateSource : uint8_t { NONE=0, LOCAL=1, REMOTE=2 };

SemaphoreHandle_t otaMutex = nullptr;
UpdateSource source = UpdateSource::NONE;
bool remoteInProgress = false;
bool firstChunk = true;
bool shaStarted = false;
bool restartPending = false;
uint32_t restartAtMs = 0;
uint32_t expectedSequence = 0;
size_t expectedSize = 0;
size_t receivedSize = 0;
String expectedSha256;
String lastSha256;
String lastError;
String lastResult = "Nessun aggiornamento remoto eseguito";
mbedtls_sha256_context shaCtx;

bool lock(uint32_t timeoutMs=1500) {
    if (!otaMutex) otaMutex = xSemaphoreCreateMutex();
    return otaMutex && xSemaphoreTake(otaMutex, pdMS_TO_TICKS(timeoutMs)) == pdTRUE;
}
void unlock() { if (otaMutex) xSemaphoreGive(otaMutex); }

const char *sourceName(UpdateSource s) {
    switch (s) {
        case UpdateSource::LOCAL: return "local";
        case UpdateSource::REMOTE: return "remote";
        default: return "none";
    }
}

bool validSha256(const String &s) {
    if (s.length() != 64U) return false;
    for (char c : s) if (!isxdigit(static_cast<unsigned char>(c))) return false;
    return true;
}

String shaHex(const unsigned char digest[32]) {
    char out[65];
    for (size_t i=0;i<32U;i++) snprintf(out+i*2U,3,"%02x",digest[i]);
    out[64]=0;
    return String(out);
}

String jsonEscape(const String &s) {
    String o;o.reserve(s.length()+8U);
    for (char c : s) {
        if (c=='\\' || c=='\"') { o+='\\'; o+=c; }
        else if (c=='\n') o += "\\n";
        else if (c!='\r') o += c;
    }
    return o;
}

void stopSha() {
    if (shaStarted) {
        mbedtls_sha256_free(&shaCtx);
        shaStarted=false;
    }
}

void clearRemoteSession(bool remountSd) {
    Update.abort();
    stopSha();
    remoteInProgress=false;
    source=UpdateSource::NONE;
    expectedSequence=0;
    expectedSize=0;
    receivedSize=0;
    expectedSha256="";
    firstChunk=true;
    if (remountSd) remountSdLogger();
}

bool failRemoteLocked(const String &message, String &error) {
    error=message;
    lastError=message;
    lastResult="Aggiornamento remoto fallito";
    clearRemoteSession(true);
    return false;
}
} // namespace

bool firmwareLocalBeginGuard(String &error) {
    error="";
    if (!lock()) { error="Updater occupato"; return false; }
    if (source != UpdateSource::NONE || remoteInProgress || restartPending) {
        error="Aggiornamento firmware gia in corso";
        unlock();
        return false;
    }
    source=UpdateSource::LOCAL;
    unlock();
    return true;
}

void firmwareLocalReleaseGuard() {
    if (!lock(500)) return;
    if (source == UpdateSource::LOCAL) source=UpdateSource::NONE;
    unlock();
}

bool firmwareRemoteBegin(size_t imageSize, const String &sha256Hex, String &error) {
    error="";
    if (!lock()) { error="Updater occupato"; return false; }
    if (source != UpdateSource::NONE || remoteInProgress || restartPending) {
        error="Aggiornamento firmware gia in corso";
        unlock();
        return false;
    }
    const esp_partition_t *next=esp_ota_get_next_update_partition(nullptr);
    if (!next) { error="Partizione OTA alternativa non disponibile"; unlock(); return false; }
    if (imageSize==0U || imageSize>next->size || !validSha256(sha256Hex)) {
        error=imageSize==0U ? "Dimensione firmware remota mancante" :
              (imageSize>next->size ? "Firmware troppo grande per lo slot OTA" : "SHA-256 firmware non valido");
        unlock();
        return false;
    }

    // Stop filesystem activity before writing the inactive OTA slot. If begin
    // fails, remount immediately; after success the device will reboot.
    prepareSdLoggerForDeepSleep();
    Update.abort();
    if (!Update.begin(imageSize, U_FLASH)) {
        error="Update.begin fallita, codice "+String((unsigned)Update.getError());
        remountSdLogger();
        unlock();
        return false;
    }

    mbedtls_sha256_init(&shaCtx);
    if (mbedtls_sha256_starts_ret(&shaCtx,0) != 0) {
        Update.abort();
        mbedtls_sha256_free(&shaCtx);
        remountSdLogger();
        error="Inizializzazione SHA-256 fallita";
        unlock();
        return false;
    }
    shaStarted=true;
    source=UpdateSource::REMOTE;
    remoteInProgress=true;
    firstChunk=true;
    expectedSequence=0;
    expectedSize=imageSize;
    receivedSize=0;
    expectedSha256=sha256Hex;
    expectedSha256.toLowerCase();
    lastSha256="";
    lastError="";
    lastResult="Aggiornamento remoto in corso";
    unlock();
    return true;
}

bool firmwareRemoteWrite(uint32_t sequence, uint8_t *data, size_t len, String &error) {
    error="";
    if (!data || len==0U || len>8192U) {
        error=len>8192U ? "Blocco remoto oltre 8192 byte" : "Blocco firmware vuoto";
        return false;
    }
    if (!lock()) { error="Updater occupato"; return false; }
    if (!remoteInProgress || source!=UpdateSource::REMOTE) {
        error="Sessione firmware remota non valida";
        unlock();
        return false;
    }
    if (sequence!=expectedSequence) {
        const String msg="Sequenza blocco non valida: atteso "+String(expectedSequence);
        const bool r=failRemoteLocked(msg,error);unlock();return r;
    }
    if (receivedSize+len>expectedSize) {
        const bool r=failRemoteLocked("Dimensione firmware oltre il valore dichiarato",error);unlock();return r;
    }
    if (firstChunk) {
        firstChunk=false;
        if (data[0]!=0xE9U) {
            const bool r=failRemoteLocked("File non riconosciuto come immagine firmware ESP32",error);unlock();return r;
        }
    }
    const size_t written=Update.write(data,len);
    if (written!=len) {
        const String msg="Scrittura OTA incompleta, codice "+String((unsigned)Update.getError());
        const bool r=failRemoteLocked(msg,error);unlock();return r;
    }
    if (mbedtls_sha256_update_ret(&shaCtx,data,len)!=0) {
        const bool r=failRemoteLocked("Calcolo SHA-256 fallito",error);unlock();return r;
    }
    receivedSize+=len;
    expectedSequence++;
    unlock();
    return true;
}

bool firmwareRemoteEnd(String &error) {
    error="";
    if (!lock()) { error="Updater occupato"; return false; }
    if (!remoteInProgress || source!=UpdateSource::REMOTE) {
        error="Sessione firmware remota non valida";
        unlock();
        return false;
    }
    if (receivedSize==0U || receivedSize!=expectedSize) {
        const bool r=failRemoteLocked("Dimensione firmware incompleta",error);unlock();return r;
    }

    unsigned char digest[32]={0};
    if (!shaStarted || mbedtls_sha256_finish_ret(&shaCtx,digest)!=0) {
        const bool r=failRemoteLocked("Chiusura SHA-256 fallita",error);unlock();return r;
    }
    lastSha256=shaHex(digest);
    stopSha();
    if (lastSha256!=expectedSha256) {
        const bool r=failRemoteLocked("SHA-256 firmware non corrispondente",error);unlock();return r;
    }
    if (!Update.end(false) || !Update.isFinished()) {
        const String msg="Finalizzazione OTA fallita, codice "+String((unsigned)Update.getError());
        const bool r=failRemoteLocked(msg,error);unlock();return r;
    }

    remoteInProgress=false;
    source=UpdateSource::NONE;
    lastError="";
    lastResult="Firmware remoto verificato; riavvio programmato";
    restartPending=true;
    restartAtMs=millis()+1800UL;
    unlock();
    return true;
}

void firmwareRemoteAbort(const String &reason) {
    if (!lock(500)) return;
    if (remoteInProgress && source==UpdateSource::REMOTE) {
        lastError=reason.isEmpty()?"Aggiornamento remoto interrotto":reason;
        lastResult="Aggiornamento remoto annullato";
        clearRemoteSession(true);
    }
    unlock();
}

bool firmwareUpdateInProgress() {
    bool value=true;
    if (lock(100)) {
        value=(source!=UpdateSource::NONE) || remoteInProgress || restartPending;
        unlock();
    }
    return value;
}

String firmwareUpdateStatusJson() {
    const esp_partition_t *running=esp_ota_get_running_partition();
    const esp_partition_t *next=esp_ota_get_next_update_partition(nullptr);
    String j;j.reserve(720);
    if (!lock(250)) return "{\"firmware_version\":\""+String(FIRMWARE_VERSION)+"\",\"status\":\"busy\"}";
    const float pct=expectedSize?100.0f*(float)receivedSize/(float)expectedSize:0.0f;
    j="{\"firmware_version\":\""+String(FIRMWARE_VERSION)+"\",\"ota_supported\":"+String(next?"true":"false")+
      ",\"running_slot\":\""+String(running?running->label:"--")+"\",\"running_size\":"+String(running?running->size:0)+
      ",\"next_slot\":\""+String(next?next->label:"--")+"\",\"next_size\":"+String(next?next->size:0)+
      ",\"in_progress\":"+String((source!=UpdateSource::NONE||remoteInProgress)?"true":"false")+
      ",\"source\":\""+String(sourceName(source))+"\",\"received\":"+String(receivedSize)+
      ",\"expected\":"+String(expectedSize)+",\"percent\":"+String(pct,1)+
      ",\"restart_pending\":"+String(restartPending?"true":"false")+
      ",\"last_sha256\":\""+jsonEscape(lastSha256)+"\",\"last_result\":\""+jsonEscape(lastResult)+
      "\",\"last_error\":\""+jsonEscape(lastError)+"\"}";
    unlock();
    return j;
}

void serviceRemoteFirmwareUpdate() {
    bool restart=false;
    if (lock(50)) {
        restart=restartPending && static_cast<int32_t>(millis()-restartAtMs)>=0;
        if (restart) restartPending=false;
        unlock();
    }
    if (restart) ESP.restart();
}
