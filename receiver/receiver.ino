#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>
#include <math.h>

/* ================== TOGGLE MODE ================== */
#define USE_BACKEND  1   // 1 = kirim ke Pi, 0 = tidak kirim HTTP
#define ONLY_PI_4    1   // 1 = rangkaian mati: HANYA WiFi + data random ke Pi (no LoRa/LCD/I2C/SPI)
                         // 0 = mode normal (LoRa + LCD)
/* ================================================= */

#if !ONLY_PI_4
#include <SPI.h>
#include <LoRa.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#endif

// Forward declare — Arduino menyisipkan prototype fungsi di sini (sebelum struct penuh)
struct DataPacket;

/* ------------------- WiFi ------------------- */
const char* ssid = "madong-smart-aquaculture";
const char* password = "12345678";

/* --------------- Raspberry Pi API --------------- */
const char* PI_URL = "http://192.168.50.1:8777/api/sensor/ingest";
const char* BEARER_TOKEN =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImE3ZDJkMWY2LTliNTgtNDYyZC05MGZkLTA1YmViOTRlNWVjMSIsInJvbGUiOiJhZG1pbiIsImlhdCI6MTc1Njg5OTIxOH0.siu-ITBJxhl5Jhap0ohHRdmd70kFY6oI0CevIgGgLnI";

#if !ONLY_PI_4
/* ------------------- LCD ------------------- */
LiquidCrystal_I2C lcd(0x27, 20, 4);

/* ------------------- LoRa ------------------- */
#define LORA_SCK   18
#define LORA_MISO  19
#define LORA_MOSI  23
#define LORA_CS     5
#define LORA_RST   33
#define LORA_DIO0  34
#define LORA_FREQ  951E6   // samakan dgn TX (transmitter.ino)
#endif

/* ------------------- Node Map (NODE → kja_id) ------------------- */
struct NodeMap { const char* id; int kjaId; };
const NodeMap NODE_MAP[] = {
  {"NODE1", 1},  // KJA-01
  {"NODE2", 2},  // KJA-02
  {"NODE3", 3},  // KJA-03
  {"NODE4", 4},  // KJA-04
};
const int NODE_COUNT = sizeof(NODE_MAP) / sizeof(NODE_MAP[0]);

int findNodeIndex(const String &id) {
  for (int i = 0; i < NODE_COUNT; i++) if (id == NODE_MAP[i].id) return i;
  return -1;
}

#if !ONLY_PI_4
/* -------------- State per Node -------------- */
struct NodeState {
  bool   has = false;
  float  pH = NAN, sal = NAN, suhu = NAN, ntu = NAN;
  String status = "";
  unsigned long lastMs = 0;
  int    rssi = 0;
  float  snr  = 0;
  unsigned long pktCount = 0;
};
NodeState nodeStates[NODE_COUNT];
#endif

/* ====== Definisi struct & Ring Buffer ====== */
struct DataPacket {
  String nodeId;
  int    kjaId;
  float  pH, sal, suhu, ntu;
  String status;
  String timestamp;   // YYYY-MM-DD HH:MM:SS atau "now" (fallback)
  int rssi; float snr;
};

#define BUFFER_SIZE 40
static DataPacket rbBuf[BUFFER_SIZE];
static int rbHead = 0, rbTail = 0;

inline bool rbEmpty() { return rbHead == rbTail; }

void rbPush(const DataPacket &pkt) {
  int next = (rbHead + 1) % BUFFER_SIZE;
  if (next == rbTail) rbTail = (rbTail + 1) % BUFFER_SIZE;
  rbBuf[rbHead] = pkt;
  rbHead = next;
}

bool rbPop(DataPacket &pkt) {
  if (rbEmpty()) return false;
  pkt = rbBuf[rbTail];
  rbTail = (rbTail + 1) % BUFFER_SIZE;
  return true;
}

/* ------------------- Waktu Lokal ------------------- */
bool timeValid() {
  struct tm t;
  if (!getLocalTime(&t, 0)) return false;
  return (t.tm_year > (2016 - 1900));
}

String getLocalTimestamp() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) return "Invalid Time";
  char b[25];
  strftime(b, sizeof(b), "%Y-%m-%d %H:%M:%S", &timeinfo);
  return String(b);
}

String getNowTimestamp() {
  if (!timeValid()) return "now";
  return getLocalTimestamp();
}

/* ------------------- Kirim ke Raspberry Pi ------------------- */
bool sendToPi(const DataPacket &pkt) {
#if USE_BACKEND
  if (WiFi.status() != WL_CONNECTED) return false;
  if (pkt.kjaId < 1 || pkt.kjaId > 4) {
    Serial.printf("[SKIP] kja_id invalid utk %s: %d\n", pkt.nodeId.c_str(), pkt.kjaId);
    return false;
  }
  String body = "{";
  body += "\"kja_id\":"       + String(pkt.kjaId) + ",";
  body += "\"ph\":"           + String(isnan(pkt.pH)   ? 0.0 : pkt.pH,   2) + ",";
  body += "\"temperature\":"  + String(isnan(pkt.suhu) ? 0.0 : pkt.suhu, 2) + ",";
  body += "\"salinity\":"     + String(isnan(pkt.sal)  ? 0.0 : pkt.sal,  2) + ",";
  body += "\"turbidity\":"    + String(isnan(pkt.ntu)  ? 0.0 : pkt.ntu,  2) + ",";
  body += "\"status\":\""     + pkt.status + "\",";
  body += "\"timestamp\":\""  + pkt.timestamp + "\"";
  body += "}";
  WiFiClient client; HTTPClient http;
  http.begin(client, PI_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + BEARER_TOKEN);
  int code = http.POST(body);
  Serial.print("[HTTP] code: "); Serial.println(code);
  if (code > 0) Serial.println(http.getString());
  else          Serial.println("HTTP Error: " + http.errorToString(code));
  http.end();
  return (code >= 200 && code < 300);
#else
  (void)pkt; return true;
#endif
}

#if !ONLY_PI_4
/* ------------------- LCD helpers ------------------- */
void showOnLCD(const String& id, float pH, float sal, float suhu, float ntu,
               int rssi = 0, float snr = 0, unsigned long pktCount = 0, int age = -1) {
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("ID:"); lcd.print(id); lcd.print("  #"); lcd.print(pktCount);
  lcd.setCursor(0, 1); lcd.print("PH: ");  if (isnan(pH)) lcd.print("--"); else lcd.print(pH, 2);
  lcd.setCursor(0, 2); lcd.print("SAL: "); if (isnan(sal)) lcd.print("--"); else lcd.print(sal, 2);
  lcd.setCursor(0, 3); lcd.print("SH: ");
  if (isnan(suhu)) lcd.print("--"); else { lcd.print(suhu, 1); lcd.print((char)223); lcd.print("C "); }
  lcd.setCursor(11, 3); lcd.print("TUR: "); if (isnan(ntu)) lcd.print("--"); else lcd.print(ntu, 1);
  if (age >= 0) { lcd.setCursor(11, 1); lcd.print("RSI:"); lcd.print(rssi);
                  lcd.setCursor(11, 2); lcd.print("SNR:"); lcd.print(snr, 1); }
}
#endif

/* ------------------- Setup ------------------- */
void setup() {
  Serial.begin(115200);
  delay(500);

#if ONLY_PI_4
  Serial.println();
  Serial.println("############################################");
  Serial.println("#  ONLY_PI_4=1  (WiFi + dummy HTTP only)  #");
  Serial.println("#  LoRa/LCD/I2C/SPI DISABLED               #");
  Serial.println("############################################");
#else
  Serial.println();
  Serial.println("=== RECEIVER normal (LoRa + LCD) ===");
  lcd.init(); lcd.backlight();
  lcd.setCursor(0, 0); lcd.print("Init WiFi...");
#endif

  WiFi.begin(ssid, password);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - t0) < 15000) {
    delay(400);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi Terhubung");
#if !ONLY_PI_4
    lcd.setCursor(0, 1); lcd.print("WiFi Terhubung   ");
#endif
  } else {
    Serial.println("\nWiFi GAGAL (offline)");
#if !ONLY_PI_4
    lcd.setCursor(0, 1); lcd.print("WiFi Gagal       ");
#endif
  }

  configTime(25200, 0, "pool.ntp.org", "time.nist.gov");
  const unsigned long MAX_NTP_WAIT = 10000;
  unsigned long ts = millis();
  while (!timeValid() && (millis() - ts) < MAX_NTP_WAIT) {
    Serial.println("Menunggu sinkron waktu...");
    delay(500);
  }
  if (timeValid()) {
    Serial.printf("Waktu sinkron: %s\n", getLocalTimestamp().c_str());
  } else {
    Serial.println("NTP belum siap, akan fallback 'now' saat kirim.");
  }

#if ONLY_PI_4
  Serial.println("[ONLY_PI_4] Siap — kirim dummy ke Pi tiap 3s");
#else
  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI);
  LoRa.setPins(LORA_CS, LORA_RST, LORA_DIO0);
  LoRa.setSPIFrequency(1E6);
  if (!LoRa.begin(LORA_FREQ)) {
    lcd.setCursor(0, 2); lcd.print("LoRa GAGAL!");
    while (1) { Serial.println("LoRa init failed"); delay(1000); }
  }
  LoRa.setSpreadingFactor(7);
  LoRa.setSignalBandwidth(125E3);
  LoRa.setCodingRate4(5);
  LoRa.enableCrc();
  lcd.setCursor(0, 2); lcd.print("LoRa RX Aktif    ");
  delay(800); lcd.clear();
  Serial.println("==== RX siap ====");
  Serial.println("Format: NODEX,pH,sal,suhu,NTU");
#endif

  for (int i = 0; i < NODE_COUNT; i++)
    Serial.printf(" - %s -> kja_id=%d\n", NODE_MAP[i].id, NODE_MAP[i].kjaId);
}

/* ------------------- Loop ------------------- */
void loop() {
  static unsigned long lastWiFiCheck = 0;
  if (millis() - lastWiFiCheck > 5000) {
    if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
    lastWiFiCheck = millis();
  }

#if ONLY_PI_4
  // --- Hanya uji ke Pi: data random NODE1..NODE4 ---
  static unsigned long lastDummy = 0;
  static int dummyIdx = 0;
  if (millis() - lastDummy > 3000) {
    int idx = dummyIdx % NODE_COUNT;
    dummyIdx++;

    float vPH   = 7.50f + (random(0, 100) / 100.0f);
    float vSal  = 28.0f + (random(0, 60) / 10.0f);
    float vSuhu = 26.0f + (random(0, 40) / 10.0f);
    float vNTU  = 5.0f  + (random(0, 100) / 10.0f);

    DataPacket pkt;
    pkt.nodeId = NODE_MAP[idx].id;
    pkt.kjaId = NODE_MAP[idx].kjaId;
    pkt.pH = vPH; pkt.sal = vSal; pkt.suhu = vSuhu; pkt.ntu = vNTU;
    pkt.status = "ONLY_PI_4";
    pkt.timestamp = getNowTimestamp();
    pkt.rssi = 0; pkt.snr = 0;

    Serial.printf("[ONLY_PI_4] %s kja_id=%d ph=%.2f sal=%.1f suhu=%.1f ntu=%.1f\n",
                  pkt.nodeId.c_str(), pkt.kjaId, vPH, vSal, vSuhu, vNTU);
    rbPush(pkt);
    lastDummy = millis();
  }
#else
  // Terima paket LoRa
  int packetSize = LoRa.parsePacket();
  if (packetSize) {
    String data = ""; while (LoRa.available()) data += (char)LoRa.read(); data.trim();
    int rssi = LoRa.packetRssi(); float snr = LoRa.packetSnr();
    Serial.printf("[LoRa RX] %s | RSSI:%d SNR:%.1f\n", data.c_str(), rssi, snr);

    int p0 = data.indexOf(',');
    if (p0 > 0) {
      String nodeId = data.substring(0, p0);
      nodeId.trim();

      int idx = findNodeIndex(nodeId);
      if (idx < 0) {
        Serial.printf("⚠️  ID '%s' tidak dikenali. Raw='%s'\n", nodeId.c_str(), data.c_str());
      } else {
        int p1 = data.indexOf(',', p0 + 1);
        int p2 = data.indexOf(',', p1 + 1);
        int p3 = data.indexOf(',', p2 + 1);
        if (p1 > 0 && p2 > 0 && p3 > 0) {
          String sPH   = data.substring(p0 + 1, p1);  sPH.trim();
          String sSal  = data.substring(p1 + 1, p2);  sSal.trim();
          String sSuhu = data.substring(p2 + 1, p3);  sSuhu.trim();
          String sNTU  = data.substring(p3 + 1);      sNTU.trim();

          float vPH   = sPH.toFloat();
          float vSal  = sSal.toFloat();
          float vSuhu = sSuhu.toFloat();
          float vNTU  = sNTU.toFloat();

          NodeState &S = nodeStates[idx];
          S.has = true; S.pH = vPH; S.sal = vSal; S.suhu = vSuhu; S.ntu = vNTU;
          S.status = "Data Masuk"; S.lastMs = millis(); S.rssi = rssi; S.snr = snr; S.pktCount++;

          showOnLCD(nodeId, vPH, vSal, vSuhu, vNTU, rssi, snr, S.pktCount, 0);

          DataPacket pkt;
          pkt.nodeId = nodeId;
          pkt.kjaId = NODE_MAP[idx].kjaId;
          pkt.pH = vPH; pkt.sal = vSal; pkt.suhu = vSuhu; pkt.ntu = vNTU;
          pkt.status = "Data Masuk";
          pkt.timestamp = getNowTimestamp();
          pkt.rssi = rssi; pkt.snr = snr;

          Serial.printf("[QUEUE] %s -> kja_id=%d, ts=%s\n",
                        pkt.nodeId.c_str(), pkt.kjaId, pkt.timestamp.c_str());
          rbPush(pkt);
        } else {
          Serial.println("[RX] Gagal parse (delimiter kurang): " + data);
        }
      }
    } else {
      Serial.println("[RX] Payload tidak valid: " + data);
    }
  }

  // Rotasi tampilan LCD antar node (tiap 1.5 s)
  static unsigned long lastRotate = 0; static int showIdx = -1;
  if (millis() - lastRotate > 1500) {
    bool any = false;
    for (int k = 0; k < NODE_COUNT; k++) {
      showIdx = (showIdx + 1) % NODE_COUNT;
      if (nodeStates[showIdx].has) { any = true; break; }
    }
    if (any) {
      const NodeState &S = nodeStates[showIdx];
      int age = (millis() - S.lastMs) / 1000;
      showOnLCD(NODE_MAP[showIdx].id, S.pH, S.sal, S.suhu, S.ntu, S.rssi, S.snr, S.pktCount, age);
    }
    lastRotate = millis();
  }
#endif

  // Kirim antrian ke Pi (tiap 1 s)
  static unsigned long lastSend = 0;
  if (millis() - lastSend > 1000) {
    DataPacket pkt;
    if (rbPop(pkt)) {
      if (sendToPi(pkt)) Serial.printf("✅ Terkirim: %s @ %s\n", pkt.nodeId.c_str(), pkt.timestamp.c_str());
      else               Serial.printf("⚠️  Gagal/skip kirim: %s @ %s\n", pkt.nodeId.c_str(), pkt.timestamp.c_str());
      Serial.println("----------------akhir");
    }
    lastSend = millis();
  }
}
