#include "remote_access.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <esp_mac.h>
#include <esp_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <mbedtls/base64.h>
#include <new>
#include <time.h>
#include <vector>

#include "config.h"
#include "network_manager.h"
#include "remote_firmware_update.h"
#include "remote_trust.h"
#include "web_manager.h"
#include "web_security.h"

namespace {
constexpr const char *NVS_NS="remote", *NVS_URL="url", *NVS_TOKEN="token";
constexpr time_t TLS_EPOCH=1700000000;
constexpr uint32_t RETRY_PENDING=30000UL, RETRY_ERROR=15000UL, RETRY_APPROVED=60000UL;
constexpr size_t MAX_REQ=12288U, MAX_RESP=24576U, MAX_WS=38000U;
constexpr size_t MAX_FW_CHUNK=8192U;
constexpr UBaseType_t HTTP_QUEUE_LEN=4;
constexpr char B64_TABLE[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

struct UrlParts { String host,path; uint16_t port=443; };
struct LocalResp { int code=502; String type="text/plain; charset=utf-8",encoding,location,cache,disposition; std::vector<uint8_t> body; };
struct RemoteReq { uint32_t session=0; String id,method,path,contentType,accept; std::vector<uint8_t> body; };
struct RemoteReply { uint32_t session=0; String id; LocalResp response; };

RemoteAccessConfig cfg;
RemoteAccessStatus st;
String token;
SemaphoreHandle_t mux=nullptr;
TaskHandle_t taskHandle=nullptr,workerHandle=nullptr;
QueueHandle_t requestQueue=nullptr,responseQueue=nullptr;
WebSocketsClient ws;
String wsAuth,activeWsUrl;
bool wsStarted=false;
volatile uint32_t generation=1;
volatile bool forceRetry=false;
volatile bool workerBusy=false;
uint32_t wsSession=0;
uint32_t queueDrops=0;
bool timeRequested=false;

bool take(){return mux&&xSemaphoreTake(mux,pdMS_TO_TICKS(250))==pdTRUE;}
void give(){if(mux)xSemaphoreGive(mux);}
String esc(const String&s){String o;o.reserve(s.length()+8U);for(char c:s){if(c=='\\'||c=='\"'){o+='\\';o+=c;}else if(c=='\n')o+="\\n";else if(c!='\r')o+=c;}return o;}

String makeId(){uint8_t m[6]={0};if(esp_read_mac(m,ESP_MAC_WIFI_STA)!=ESP_OK){uint64_t e=ESP.getEfuseMac();for(uint8_t i=0;i<6;i++)m[5-i]=(e>>(8*i))&0xff;}char b[32];snprintf(b,sizeof(b),"esp32-%02x%02x%02x%02x%02x%02x",m[0],m[1],m[2],m[3],m[4],m[5]);return String(b);}
bool validToken(const String&s){if(s.length()!=64U)return false;for(char c:s)if(!isxdigit((unsigned char)c))return false;return true;}
String newToken(){uint8_t r[32];esp_fill_random(r,sizeof(r));char b[65];for(size_t i=0;i<32U;i++)snprintf(b+i*2U,3,"%02x",r[i]);b[64]=0;return String(b);}

bool parseUrl(const String&u,const char*scheme,UrlParts&o){String p=String(scheme)+"://";if(!u.startsWith(p))return false;String r=u.substring(p.length());if(r.isEmpty()||r.indexOf('@')>=0||r.indexOf('\r')>=0||r.indexOf('\n')>=0)return false;int slash=r.indexOf('/');String a=slash>=0?r.substring(0,slash):r;o.path=slash>=0?r.substring(slash):"/";int colon=a.lastIndexOf(':');if(colon>0){long port=a.substring(colon+1).toInt();if(port<1||port>65535)return false;o.port=(uint16_t)port;o.host=a.substring(0,colon);}else{o.port=443;o.host=a;}return !o.host.isEmpty()&&o.path.startsWith("/");}
bool normalizePortal(String&u){u.trim();while(u.endsWith("/"))u.remove(u.length()-1);if(u.isEmpty())return true;if(u.length()>220U||u.indexOf('?')>=0||u.indexOf('#')>=0)return false;UrlParts p;return parseUrl(u,"https",p);}

void setState(const String&name,const String&err=""){if(!take())return;st.state=name;st.lastError=err;st.configured=!cfg.portalUrl.isEmpty();st.deviceId=remoteDefaultDeviceId();give();}
void load(){Preferences p;if(!p.begin(NVS_NS,false)){cfg={};token=newToken();return;}cfg.portalUrl=p.getString(NVS_URL,"");normalizePortal(cfg.portalUrl);token=p.getString(NVS_TOKEN,"");if(!validToken(token)){token=newToken();p.putString(NVS_TOKEN,token);}p.end();}

size_t b64EncodedLength(size_t n){return ((n+2U)/3U)*4U;}
bool appendB64(String&out,const uint8_t*d,size_t n){if(!n)return true;if(!d)return false;const size_t expected=out.length()+b64EncodedLength(n);char q[4];size_t i=0;while(i+2U<n){const uint32_t v=(uint32_t(d[i])<<16)|(uint32_t(d[i+1])<<8)|uint32_t(d[i+2]);q[0]=B64_TABLE[(v>>18)&0x3f];q[1]=B64_TABLE[(v>>12)&0x3f];q[2]=B64_TABLE[(v>>6)&0x3f];q[3]=B64_TABLE[v&0x3f];if(!out.concat(q,4))return false;i+=3U;}if(i<n){uint32_t v=uint32_t(d[i])<<16;const bool second=i+1U<n;if(second)v|=uint32_t(d[i+1])<<8;q[0]=B64_TABLE[(v>>18)&0x3f];q[1]=B64_TABLE[(v>>12)&0x3f];q[2]=second?B64_TABLE[(v>>6)&0x3f]:'=';q[3]='=';if(!out.concat(q,4))return false;}return out.length()==expected;}
bool b64dec(const String&s,std::vector<uint8_t>&out){out.clear();if(s.isEmpty())return true;size_t cap=s.length()*3U/4U+4U,w=0;if(cap>MAX_REQ+4U)return false;out.resize(cap);if(mbedtls_base64_decode(out.data(),out.size(),&w,(const unsigned char*)s.c_str(),s.length())!=0||w>MAX_REQ){out.clear();return false;}out.resize(w);return true;}
bool b64decFirmware(const char*s,size_t n,std::vector<uint8_t>&out){out.clear();if(!s||!n)return false;const size_t cap=n*3U/4U+4U;if(cap>MAX_FW_CHUNK+4U)return false;size_t w=0;out.resize(cap);if(mbedtls_base64_decode(out.data(),out.size(),&w,(const unsigned char*)s,n)!=0||w==0U||w>MAX_FW_CHUNK){out.clear();return false;}out.resize(w);return true;}

String hdr(const JsonObjectConst&h,const char*wanted){if(h.isNull())return String();String target=wanted;target.toLowerCase();for(JsonPairConst kv:h){String k=kv.key().c_str();k.toLowerCase();if(k==target){String v=kv.value().as<String>();v.replace("\r","");v.replace("\n","");if(v.length()>256U)v.remove(256);return v;}}return String();}
bool safePath(const String&p){return !p.isEmpty()&&p.length()<768U&&p[0]=='/'&&p.indexOf("\r")<0&&p.indexOf("\n")<0&&p.indexOf("://")<0;}

bool localHttp(String method,const String&path,const String&contentType,const String&accept,const std::vector<uint8_t>&req,LocalResp&r,String&err){
    if(!webStarted()){err="Web UI locale non pronta";return false;}
    method.toUpperCase();
    if(!safePath(path)){err="Path non valido";return false;}
    if(method!="GET"&&method!="POST"&&method!="HEAD"){r.code=405;const char*m="Method not allowed";r.body.assign(m,m+strlen(m));return true;}
    WiFiClient c;c.setTimeout(6000);IPAddress ip=WiFi.localIP();
    if(!c.connect(ip,80)){c.stop();if(!c.connect(IPAddress(127,0,0,1),80)){err="Connessione Web UI locale fallita";return false;}}
    c.print(method);c.print(' ');c.print(path);c.print(F(" HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n"));
    const String auth=webSecurityInternalAuthorizationHeader();
    if(!auth.isEmpty()){c.print(F("Authorization: "));c.print(auth);c.print(F("\r\n"));}
    if(!contentType.isEmpty()){c.print(F("Content-Type: "));c.print(contentType);c.print(F("\r\n"));}
    if(!accept.isEmpty()){c.print(F("Accept: "));c.print(accept);c.print(F("\r\n"));}
    if(!req.empty()){c.print(F("Content-Length: "));c.print(req.size());c.print(F("\r\n"));}
    c.print(F("\r\n"));if(!req.empty())c.write(req.data(),req.size());
    uint32_t start=millis();while(!c.available()&&c.connected()&&millis()-start<6000UL)vTaskDelay(pdMS_TO_TICKS(2));
    if(!c.available()){c.stop();err="Timeout Web UI locale";return false;}
    String sl=c.readStringUntil('\n');sl.trim();int a=sl.indexOf(' '),b=sl.indexOf(' ',a+1);
    if(a<0){c.stop();err="Risposta locale non valida";return false;}
    r.code=sl.substring(a+1,b>a?b:sl.length()).toInt();size_t len=0;bool haveLen=false;
    while(c.connected()||c.available()){String l=c.readStringUntil('\n');if(l=="\r"||l.isEmpty())break;l.trim();int x=l.indexOf(':');if(x<1)continue;String k=l.substring(0,x),v=l.substring(x+1);k.toLowerCase();v.trim();if(k=="content-type")r.type=v;else if(k=="content-encoding")r.encoding=v;else if(k=="location")r.location=v;else if(k=="cache-control")r.cache=v;else if(k=="content-disposition")r.disposition=v;else if(k=="content-length"){len=v.toInt();haveLen=true;}}
    if(method=="HEAD"){r.body.clear();r.encoding="";c.stop();return true;}
    if(haveLen&&len>MAX_RESP){c.stop();err="Risposta locale troppo grande";return false;}
    r.body.clear();r.body.reserve(haveLen?len:2048U);start=millis();
    while((c.connected()||c.available())&&millis()-start<6000UL){while(c.available()){int ch=c.read();if(ch<0)break;if(r.body.size()>=MAX_RESP){c.stop();err="Risposta locale oltre limite";return false;}r.body.push_back((uint8_t)ch);if(haveLen&&r.body.size()>=len)break;}if(haveLen&&r.body.size()>=len)break;vTaskDelay(pdMS_TO_TICKS(1));}
    c.stop();if(haveLen&&r.body.size()<len){err="Risposta locale incompleta";return false;}
    if(r.encoding.equalsIgnoreCase("gzip")){const bool valid=r.body.size()>=2U&&r.body[0]==0x1fU&&r.body[1]==0x8bU;if(!valid)r.encoding="";}
    if(r.body.empty())r.encoding="";
    return true;
}

void sendResp(const String&id,const LocalResp&r){
    JsonDocument hd;hd["content-type"]=r.type;if(!r.encoding.isEmpty())hd["content-encoding"]=r.encoding;if(!r.location.isEmpty())hd["location"]=r.location;if(!r.cache.isEmpty())hd["cache-control"]=r.cache;if(!r.disposition.isEmpty())hd["content-disposition"]=r.disposition;
    String headersJson;serializeJson(hd,headersJson);const String escapedId=esc(id);String o;
    if(!o.reserve(headersJson.length()+escapedId.length()+192U)){if(take()){st.lastError="Memoria insufficiente per risposta remota";give();}return;}
    o+=F("{\"type\":\"http_response\",\"id\":\"");o+=escapedId;o+=F("\",\"status\":");o+=String(r.code);o+=F(",\"headers\":");o+=headersJson;o+=F(",\"body_b64\":\"");
    const size_t encodedLen=b64EncodedLength(r.body.size());const size_t finalLen=o.length()+encodedLen+2U;if(finalLen>MAX_WS){if(take()){st.lastError="Risposta remota oltre limite WebSocket";give();}return;}if(!o.reserve(finalLen+1U)){if(take()){st.lastError="Memoria insufficiente per frame WebSocket";give();}return;}const size_t bodyStart=o.length();if(!appendB64(o,r.body.data(),r.body.size())||o.length()!=bodyStart+encodedLen){if(take()){st.lastError="Codifica Base64 risposta remota incompleta";give();}return;}o+=F("\"}");if(o.length()!=finalLen){if(take()){st.lastError="Frame risposta remota incompleto";give();}return;}if(ws.sendTXT(o)&&take()){st.responses++;st.lastActivityMs=millis();st.lastError="";give();}
}
void sendErr(const String&id,int code,const String&msg){LocalResp r;r.code=code;r.body.assign(msg.c_str(),msg.c_str()+msg.length());sendResp(id,r);}

void sendFirmwareReply(const String&id,const char*stage,bool ok,const String&message,uint32_t sequence=UINT32_MAX){const String status=firmwareUpdateStatusJson();String o;o.reserve(message.length()+status.length()+220U);o="{\"type\":\"firmware_response\",\"id\":\""+esc(id)+"\",\"stage\":\""+String(stage)+"\",\"ok\":"+(ok?String("true"):String("false"));if(sequence!=UINT32_MAX)o+=",\"sequence\":"+String(sequence);if(!message.isEmpty())o+=",\"message\":\""+esc(message)+"\"";o+=",\"status\":"+status+"}";if(o.length()<=MAX_WS)ws.sendTXT(o);}

void clearQueuedRequests(){
    if(requestQueue){RemoteReq*q=nullptr;while(xQueueReceive(requestQueue,&q,0)==pdTRUE)delete q;}
    if(responseQueue){RemoteReply*r=nullptr;while(xQueueReceive(responseQueue,&r,0)==pdTRUE)delete r;}
}

void httpWorker(void*){for(;;){RemoteReq*q=nullptr;if(!requestQueue||xQueueReceive(requestQueue,&q,portMAX_DELAY)!=pdTRUE||!q)continue;workerBusy=true;RemoteReply*out=new(std::nothrow)RemoteReply();if(out){out->session=q->session;out->id=q->id;String e;if(!localHttp(q->method,q->path,q->contentType,q->accept,q->body,out->response,e)){out->response.code=502;out->response.type="text/plain; charset=utf-8";out->response.encoding="";out->response.body.assign(e.c_str(),e.c_str()+e.length());}if(!responseQueue||xQueueSend(responseQueue,&out,pdMS_TO_TICKS(250))!=pdTRUE){delete out;if(take()){queueDrops++;give();}}}else if(take()){queueDrops++;give();}delete q;workerBusy=false;}}

void queueHttpRequest(const JsonDocument&d,const String&id,uint32_t session){if(firmwareUpdateInProgress()){sendErr(id,423,"OTA firmware in corso");return;}if(!requestQueue){sendErr(id,503,"Worker HTTP remoto non disponibile");return;}RemoteReq*q=new(std::nothrow)RemoteReq();if(!q){sendErr(id,503,"Memoria insufficiente per richiesta remota");return;}q->session=session;q->id=id;q->method=d["method"]|"GET";q->path=d["path"]|"/";const JsonObjectConst headers=d["headers"].as<JsonObjectConst>();q->contentType=hdr(headers,"content-type");q->accept=hdr(headers,"accept");const String bb=d["body_b64"]|"";if(!b64dec(bb,q->body)){delete q;sendErr(id,413,"Request body non valido");return;}if(xQueueSend(requestQueue,&q,0)!=pdTRUE){delete q;if(take()){queueDrops++;give();}sendErr(id,503,"Coda richieste remote piena");return;}if(take()){st.requests++;give();}}
void drainReplies(){if(!responseQueue)return;for(uint8_t i=0;i<2U;i++){RemoteReply*r=nullptr;if(xQueueReceive(responseQueue,&r,0)!=pdTRUE||!r)break;uint32_t current=0;bool online=false;if(take()){current=wsSession;online=st.transportActive;give();}if(online&&r->session==current)sendResp(r->id,r->response);delete r;}}

void handleFirmwareMessage(const JsonDocument&d,const String&type,const String&id){
    if(id.isEmpty())return;
    if(type=="firmware_begin"){const size_t imageSize=d["size"]|0U;const String sha=d["sha256"]|"";String err;const bool ok=firmwareRemoteBegin(imageSize,sha,err);sendFirmwareReply(id,"begin",ok,ok?String("OTA remota avviata"):err);return;}
    if(type=="firmware_chunk"){const uint32_t sequence=d["sequence"]|UINT32_MAX;const char*dataB64=d["data_b64"].as<const char*>();const size_t dataLen=dataB64?strlen(dataB64):0U;std::vector<uint8_t>chunk;if(sequence==UINT32_MAX||!b64decFirmware(dataB64,dataLen,chunk)){firmwareRemoteAbort("Blocco firmware remoto non valido");sendFirmwareReply(id,"chunk",false,"Blocco firmware remoto non valido",sequence);return;}String err;const bool ok=firmwareRemoteWrite(sequence,chunk.data(),chunk.size(),err);sendFirmwareReply(id,"chunk",ok,ok?String():err,sequence);return;}
    if(type=="firmware_end"){String err;const bool ok=firmwareRemoteEnd(err);sendFirmwareReply(id,"end",ok,ok?String("Firmware verificato; riavvio programmato"):err);return;}
    if(type=="firmware_abort"){String reason=d["reason"]|"Aggiornamento remoto annullato dal portale";firmwareRemoteAbort(reason);sendFirmwareReply(id,"abort",true,reason);}
}

void wsText(uint8_t*p,size_t n){if(!p||!n||n>MAX_WS)return;JsonDocument d;if(deserializeJson(d,p,n))return;String type=d["type"]|"",id=d["id"]|"";uint32_t session=0;if(take()){st.lastActivityMs=millis();session=wsSession;give();}if(type=="ping"){String x="{\"type\":\"pong\"";if(!id.isEmpty())x+=",\"id\":\""+esc(id)+"\"";x+="}";ws.sendTXT(x);return;}if(type=="firmware_begin"||type=="firmware_chunk"||type=="firmware_end"||type=="firmware_abort"){handleFirmwareMessage(d,type,id);return;}if(type!="http_request"||id.isEmpty())return;queueHttpRequest(d,id,session);}

void wsEvent(WStype_t t,uint8_t*p,size_t n){if(t==WStype_CONNECTED){if(take()){wsSession++;st.transportActive=true;st.approved=true;st.state="ONLINE";st.wsConnects++;st.lastActivityMs=millis();st.lastWsEvent="CONNECTED";st.lastError="";give();}Serial.println(F("[REMOTE] AdminSensor ONLINE"));}else if(t==WStype_DISCONNECTED){firmwareRemoteAbort("Connessione AdminSensor interrotta durante OTA");if(take()){bool was=st.transportActive;wsSession++;st.transportActive=false;if(st.configured&&st.approved)st.state="RECONNECT";if(was)st.wsDisconnects++;st.lastWsEvent="DISCONNECTED";give();}}else if(t==WStype_ERROR){firmwareRemoteAbort("Errore WebSocket AdminSensor durante OTA");if(take()){st.lastWsEvent="ERROR";give();}}else if(t==WStype_TEXT)wsText(p,n);else if(t==WStype_PING||t==WStype_PONG){if(take()){st.lastActivityMs=millis();st.lastWsEvent=t==WStype_PING?"WS_PING":"WS_PONG";give();}}}

bool enroll(const String&portal,String&wsUrl,bool&pending){pending=false;wsUrl="";WiFiClientSecure c;c.setCACert(REMOTE_TRUST_CA);c.setTimeout(8000);HTTPClient h;h.setConnectTimeout(7000);h.setTimeout(8000);if(!h.begin(c,portal+"/api/device/enroll")){setState("ERROR","HTTPS enroll init fallita");return false;}h.addHeader("Content-Type","application/json");JsonDocument q;q["device_id"]=remoteDefaultDeviceId();q["device_token"]=token;q["name"]=networkHostname().isEmpty()?"Oregon Gateway":networkHostname();q["model"]="ESP32 Oregon + Technoline Weather Gateway";q["firmware_version"]=FIRMWARE_VERSION;String body;serializeJson(q,body);if(take()){st.enrollAttempts++;st.lastWsEvent="ENROLL";give();}int code=h.POST(body);String resp=code>0?h.getString():String();h.end();if(take()){st.lastEnrollHttpCode=code;st.lastActivityMs=millis();give();}if(code<200||code>=300){setState("ERROR",code>0?String("Enroll HTTP ")+code:"Errore TLS/HTTP enroll");return false;}JsonDocument d;if(deserializeJson(d,resp)){setState("ERROR","Risposta enroll JSON non valida");return false;}String s=d["status"]|"";if(s=="pending"){pending=true;if(take()){st.approved=false;st.transportActive=false;st.lastWsEvent="PENDING";give();}setState("PENDING");return true;}if(s!="approved"){if(take()){st.approved=false;st.transportActive=false;st.lastWsEvent="DENIED";give();}setState("DENIED",s.isEmpty()?"Stato enroll mancante":String("Stato portale: ")+s);return false;}wsUrl=d["websocket_url"]|"";UrlParts u;if(!parseUrl(wsUrl,"wss",u)){setState("ERROR","websocket_url WSS non valido");return false;}if(take()){st.approved=true;st.lastError="";st.wsHost=u.host;st.wsPath=u.path;st.lastWsEvent="APPROVED";give();}setState("APPROVED");return true;}

bool startWs(const String&url){UrlParts u;if(!parseUrl(url,"wss",u))return false;ws.disconnect();ws.beginSslWithCA(u.host.c_str(),u.port,u.path.c_str(),REMOTE_TRUST_CA,"");wsAuth="Authorization: Bearer "+token;ws.setExtraHeaders(wsAuth.c_str());ws.setReconnectInterval(5000);ws.enableHeartbeat(30000,5000,2);activeWsUrl=url;wsStarted=true;if(take()){st.wsAttempts++;st.lastWsAttemptMs=millis();st.wsHost=u.host;st.wsPath=u.path;st.lastWsEvent="CONNECTING";give();}setState("CONNECTING");return true;}

void task(void*){
    uint32_t seen=0,next=0;
    for(;;){
        RemoteAccessConfig c;if(take()){c=cfg;give();}
        const uint32_t g=generation;const bool fr=forceRetry;if(fr)forceRetry=false;
        if(g!=seen||fr){firmwareRemoteAbort(fr?"Retry AdminSensor durante OTA":"Configurazione AdminSensor modificata durante OTA");seen=g;if(wsStarted)ws.disconnect();wsStarted=false;activeWsUrl="";next=0;clearQueuedRequests();if(take()){wsSession++;st.transportActive=false;st.approved=false;st.lastWsEvent=fr?"MANUAL_RETRY":"CONFIG_CHANGED";give();}}
        if(c.portalUrl.isEmpty()){setState("OFF");vTaskDelay(pdMS_TO_TICKS(300));continue;}
        if(!wifiConnected()||networkRecoveryApActive()||networkWifiCredentialTrialPending()){firmwareRemoteAbort("Rete non disponibile durante OTA remota");if(wsStarted){ws.disconnect();wsStarted=false;}setState("WAIT_NETWORK");vTaskDelay(pdMS_TO_TICKS(500));continue;}
        if(time(nullptr)<TLS_EPOCH){if(!timeRequested){configTime(0,0,"pool.ntp.org","time.cloudflare.com");timeRequested=true;}setState("WAIT_TIME");vTaskDelay(pdMS_TO_TICKS(500));continue;}
        const uint32_t now=millis();bool online=false;if(take()){online=st.transportActive;give();}
        if(next==0U||(!online&&(int32_t)(now-next)>=0)){bool pending=false;String u;setState("ENROLLING");const bool ok=enroll(c.portalUrl,u,pending);if(ok&&pending){if(wsStarted){ws.disconnect();wsStarted=false;}next=millis()+RETRY_PENDING;}else if(ok&&!u.isEmpty()){if(!wsStarted||u!=activeWsUrl)startWs(u);next=millis()+RETRY_APPROVED;}else next=millis()+RETRY_ERROR;}
        if(wsStarted){ws.loop();drainReplies();}
        vTaskDelay(pdMS_TO_TICKS(8));
    }
}
} // namespace

String remoteDefaultDeviceId(){static String id=makeId();return id;}
void initRemoteAccess(){if(!mux)mux=xSemaphoreCreateMutex();if(!requestQueue)requestQueue=xQueueCreate(HTTP_QUEUE_LEN,sizeof(RemoteReq*));if(!responseQueue)responseQueue=xQueueCreate(HTTP_QUEUE_LEN,sizeof(RemoteReply*));load();if(take()){st=RemoteAccessStatus{};st.initialized=true;st.configured=!cfg.portalUrl.isEmpty();st.deviceId=remoteDefaultDeviceId();st.state=cfg.portalUrl.isEmpty()?"OFF":"WAIT_NETWORK";st.lastWsEvent="INIT";give();}ws.onEvent(wsEvent);if(!workerHandle&&requestQueue&&responseQueue&&xTaskCreate(httpWorker,"remote-http",7168,nullptr,1,&workerHandle)!=pdPASS){workerHandle=nullptr;setState("ERROR","Worker HTTP remoto non avviato");}if(!taskHandle&&xTaskCreate(task,"adminsensor",12288,nullptr,1,&taskHandle)!=pdPASS){taskHandle=nullptr;setState("ERROR","Task remoto non avviato");}Serial.print(F("[REMOTE] Device ID: "));Serial.println(remoteDefaultDeviceId());Serial.println(F("[REMOTE] Token in NVS (non mostrato)"));}
RemoteAccessConfig getRemoteAccessConfig(){RemoteAccessConfig o;if(take()){o=cfg;give();}return o;}
RemoteAccessStatus getRemoteAccessStatus(){RemoteAccessStatus o;if(take()){o=st;give();}return o;}
bool saveRemoteAccessPortalUrl(const String&in){String u=in;if(!normalizePortal(u))return false;Preferences p;if(!p.begin(NVS_NS,false))return false;p.putString(NVS_URL,u);p.end();if(take()){cfg.portalUrl=u;st.configured=!u.isEmpty();st.approved=false;st.transportActive=false;st.state=u.isEmpty()?"OFF":"WAIT_NETWORK";st.lastError="";st.lastWsEvent="CONFIG_SAVED";give();}generation++;return true;}
bool resetRemoteAccessConfig(){return saveRemoteAccessPortalUrl("");}
void retryRemoteAccessNow(){forceRetry=true;}
String remoteAccessConfigJson(){RemoteAccessConfig c=getRemoteAccessConfig();String j="{\"portal_url\":\""+esc(c.portalUrl)+"\",\"device_id\":\""+esc(remoteDefaultDeviceId())+"\",\"has_token\":";j+=validToken(token)?"true":"false";j+=",\"identity_managed_by_firmware\":true}";return j;}
String remoteAccessStatusJson(){RemoteAccessStatus s=getRemoteAccessStatus();String j="{\"initialized\":";j+=s.initialized?"true":"false";j+=",\"configured\":";j+=s.configured?"true":"false";j+=",\"approved\":";j+=s.approved?"true":"false";j+=",\"transport_active\":";j+=s.transportActive?"true":"false";j+=",\"state\":\""+esc(s.state)+"\",\"device_id\":\""+esc(s.deviceId)+"\",\"enroll_attempts\":"+String(s.enrollAttempts)+",\"last_enroll_http_code\":"+String(s.lastEnrollHttpCode);j+=",\"ws_attempts\":"+String(s.wsAttempts)+",\"ws_connects\":"+String(s.wsConnects)+",\"ws_disconnects\":"+String(s.wsDisconnects);j+=",\"ws_host\":\""+esc(s.wsHost)+"\",\"ws_path\":\""+esc(s.wsPath)+"\",\"last_ws_event\":\""+esc(s.lastWsEvent)+"\"";j+=",\"requests\":"+String(s.requests)+",\"responses\":"+String(s.responses)+",\"http_queue\":"+String(requestQueue?uxQueueMessagesWaiting(requestQueue):0)+",\"http_worker_busy\":"+(workerBusy?String("true"):String("false"))+",\"queue_drops\":"+String(queueDrops);j+=",\"last_activity_age_ms\":"+(s.lastActivityMs?String((uint32_t)(millis()-s.lastActivityMs)):String("null"))+",\"last_error\":\""+esc(s.lastError)+"\",\"firmware_update\":"+firmwareUpdateStatusJson()+"}";return j;}
