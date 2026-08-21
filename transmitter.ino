#include <SPI.h>
#include <LoRa.h>
#include <EEPROM.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <math.h>

/* =============== KONFIGURASI NODE =============== */
#define NODE_ID            "NODE1"   // "NODE1"/"NODE2"/"NODE3"/"NODE4"
#define BASE_INTERVAL_MS   3000      // beda tiap node: 3000/3600/4200/4800
#define LORA_FREQ          951E6     // 915E6 atau 923E6 (harus sama dgn RX)
/* ================================================= */

// ==================== LCD ====================
LiquidCrystal_I2C lcd(0x27, 20, 4);

// ==================== pH ====================
#define PH_PIN 25
#define VREF 3.3
float voltagePH = 0.0, pH = 0.0;
float slope = -5.7, intercept = 21.34; // ganti sesuai hasil kalibrasi
#define FILTER_SIZE 10
float voltageBuffer[FILTER_SIZE]; int bufferIndex = 0; bool bufferFull = false;

float filterVoltage(float x){
  voltageBuffer[bufferIndex] = x;
  bufferIndex = (bufferIndex + 1) % FILTER_SIZE;
  if (bufferIndex == 0) bufferFull = true;
  int n = bufferFull ? FILTER_SIZE : bufferIndex;
  float s = 0; for (int i=0;i<n;i++) s += voltageBuffer[i];
  return s / n;
}
float readPH(){
  const int N = 20; float acc = 0;
  for (int i=0;i<N;i++){ acc += analogRead(PH_PIN) * (VREF/4095.0f); delayMicroseconds(1500); }
  float raw = acc / N;
  voltagePH = filterVoltage(raw);
  pH = constrain(slope * voltagePH + intercept, 0, 14);
  return pH;
}
void calibratePH(){
  Serial.println("=== Kalibrasi pH ===");
  Serial.println("Celupkan sensor ke pH 4.01"); delay(15000);
  float v4=0; for(int i=0;i<20;i++){ v4+=analogRead(PH_PIN)*(VREF/4095.0); delay(200);} v4/=20.0;
  Serial.println("Pindah ke pH 6.86"); delay(15000);
  float v6=0; for(int i=0;i<20;i++){ v6+=analogRead(PH_PIN)*(VREF/4095.0); delay(200);} v6/=20.0;
  slope=(6.86-4.01)/(v6-v4); intercept=4.01 - slope*v4;
  EEPROM.put(8, slope); EEPROM.put(12, intercept); EEPROM.commit();
  Serial.printf("Done. slope=%.4f intercept=%.4f\n", slope, intercept);
}

// ================== Salinitas =================
#define SALINITY_PIN 32
float V0 = 0.0, V1 = 1.0;  // kalibrasi 0 & 30 ppt
float readSalinitas(){
  float v = analogRead(SALINITY_PIN) * (3.3 / 4095.0);  
  if (fabs(V1 - V0) < 0.001) return 0.0;
  float m = 30.0 / (V1 - V0), b = -m * V0;
  float sal = m * v + b;
  Serial.printf("Nilai salinitas = %.2f, var sal = %.2f", v, sal);
  return constrain(sal, 0.0, 40.0);
}

// ==================== Suhu ====================
#define ONE_WIRE_BUS 13
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
float readSuhu(){ sensors.requestTemperatures(); return sensors.getTempCByIndex(0); }

// ============== Turbidity (DFRobot SEN0189) ==============
#define TURBIDITY_PIN 35            // ADC: gunakan AO sensor via divider
const int jumlahPembacaan = 50;
const int bufferSizeMA = 10; float bufferMA[bufferSizeMA]; int indexMA = 0;
const int bufferSizeMedian = 5; float bufferMedian[bufferSizeMedian]; int indexMedian = 0;

// warm-up agar filter terisi dulu
int warmupCount = 0;
const int warmupNeeded = 2 * ((bufferSizeMA > bufferSizeMedian) ? bufferSizeMA : bufferSizeMedian);

// Rasio pembagi tegangan (Vadc/Vsensor) — UNTUK 10k ATAS (AO) & 4.7k BAWAH (GND) ≈ 0.32
float faktorPembagi = 0.32f;

// Kalibrasi 2 titik
float turb_V_clear = 1.20f;   // Vsensor saat 0 NTU
float turb_V_ref   = 1.60f;   // Vsensor saat larutan referensi
float turb_ref_ntu = 100.0f;  // nilai NTU larutan referensi

// EEPROM map
#define EE_V0               0
#define EE_V1               4
#define EE_PH_SLOPE         8
#define EE_PH_INTERCEPT     12
#define EE_TURB_V_CLEAR     24
#define EE_TURB_V_REF       28
#define EE_TURB_REF_NTU     32
#define EE_FAKTOR_PEMBAGI   36

float movingAverage(float x){
  bufferMA[indexMA] = x; indexMA = (indexMA + 1) % bufferSizeMA;
  float s = 0; for (int i=0;i<bufferSizeMA;i++) s += bufferMA[i];
  return s / bufferSizeMA;
}
float medianFilter(float x){
  bufferMedian[indexMedian] = x; indexMedian = (indexMedian + 1) % bufferSizeMedian;
  float t[bufferSizeMedian]; for (int i=0;i<bufferSizeMedian;i++) t[i] = bufferMedian[i];
  for (int i=0;i<bufferSizeMedian-1;i++) for (int j=0;j<bufferSizeMedian-1-i;j++) if (t[j] > t[j+1]) { float u=t[j]; t[j]=t[j+1]; t[j+1]=u; }
  return t[bufferSizeMedian/2];
}

float readTurbidity(){
  long totalADC = 0; for (int i=0;i<jumlahPembacaan;i++){ totalADC += analogRead(TURBIDITY_PIN); delay(2); }
  int adcAvg = totalADC / jumlahPembacaan;

  // Tolak pembacaan tidak valid (wiring salah)
  if (adcAvg <= 5)  { lcd.setCursor(16,3); lcd.print("LOW"); return 0.0f; }
  if (adcAvg >= 4090){ lcd.setCursor(16,3); lcd.print("SAT"); return 0.0f; }

  float vADC  = (adcAvg * 3.3f) / 4095.0f;   // tegangan di ADC (0..3.3V)
  float vSens = vADC / faktorPembagi;        // tegangan asli di AO sensor
  float vFilt = medianFilter(movingAverage(vSens));

  // indikator warm-up
  if (warmupCount < warmupNeeded) {
    warmupCount++;
    lcd.setCursor(16, 3); lcd.print("WUP");
    return 0.0f;
  }

  float gap = fabs(turb_V_ref - turb_V_clear);
  if (gap < 0.02f) return 0.0f;              // kalibrasi belum layak

  float m = turb_ref_ntu / (turb_V_ref - turb_V_clear);
  float b = -m * turb_V_clear;
  float ntu = m * vFilt + b;
  if (ntu < 0) ntu = 0;
  return ntu;
}

// ==================== LoRa (ESP32 VSPI) ====================
#define LORA_SCK   18
#define LORA_MISO  19
#define LORA_MOSI  23
#define LORA_CS     5
#define LORA_RST   33
#define LORA_DIO0  34

unsigned long lastSend = 0;

void setup(){
  Serial.begin(115200);
  EEPROM.begin(512);

  // ADC setup
  analogSetWidth(12);
  analogSetAttenuation(ADC_11db);
  analogSetPinAttenuation(PH_PIN,        ADC_11db);
  analogSetPinAttenuation(SALINITY_PIN,  ADC_11db);
  analogSetPinAttenuation(TURBIDITY_PIN, ADC_11db);

  // load kalibrasi
  EEPROM.get(EE_V0, V0);
  EEPROM.get(EE_V1, V1);
  EEPROM.get(EE_PH_SLOPE, slope);
  EEPROM.get(EE_PH_INTERCEPT, intercept);
  EEPROM.get(EE_TURB_V_CLEAR, turb_V_clear);
  EEPROM.get(EE_TURB_V_REF,   turb_V_ref);
  EEPROM.get(EE_TURB_REF_NTU, turb_ref_ntu);
  EEPROM.get(EE_FAKTOR_PEMBAGI, faktorPembagi);

  // PAKSA faktor = 0.32 (divider 10k/4.7k), simpan ke EEPROM
  faktorPembagi = 0.32f;
  EEPROM.put(EE_FAKTOR_PEMBAGI, faktorPembagi);
  EEPROM.commit();
  Serial.printf("[Init] faktorPembagi=%.3f (paksa 0.32)\n", faktorPembagi);

  // init filter buffer
  for (int i=0;i<bufferSizeMA;i++) bufferMA[i] = 0;
  for (int i=0;i<bufferSizeMedian;i++) bufferMedian[i] = 0;

  // LCD
  lcd.init(); lcd.backlight();
  lcd.setCursor(0,0); lcd.print("TX "); lcd.print(NODE_ID); lcd.print(" init..");
  sensors.begin();

  // LoRa
  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI);
  LoRa.setPins(LORA_CS, LORA_RST, LORA_DIO0);
  LoRa.setSPIFrequency(1E6);                // aman untuk kabel/breadboard
  if (!LoRa.begin(LORA_FREQ)){
    lcd.setCursor(0,1); lcd.print("LoRa GAGAL!");
    while(true){ Serial.println("LoRa init failed"); delay(1000); }
  }
  LoRa.setSpreadingFactor(7);
  LoRa.setSignalBandwidth(125E3);
  LoRa.setCodingRate4(5);
  LoRa.setTxPower(17);
  LoRa.enableCrc();

  // pesan awal
  lcd.setCursor(0,1); lcd.print("Sensor Aktif   ");
  lcd.setCursor(0,2); lcd.print("LoRa TX Aktif  ");
  delay(1200);
  lcd.clear();

  // seed jitter
  randomSeed(esp_timer_get_time());
}

void loop(){
  // ===== Serial Commands (kalibrasi & debug) =====
  if (Serial.available()){
    String cmd = Serial.readStringUntil('\n'); cmd.trim();

    if (cmd == "kalibrasi0"){
      float v = analogRead(SALINITY_PIN) * (3.3 / 4095.0);
      V0 = v; EEPROM.put(EE_V0, V0); EEPROM.commit();
      Serial.printf("Salinity: V0=%.3f V\n", V0);

    } else if (cmd == "kalibrasi30"){
      float v = analogRead(SALINITY_PIN) * (3.3 / 4095.0);
      V1 = v; EEPROM.put(EE_V1, V1); EEPROM.commit();
      Serial.printf("Salinity: V1=%.3f V\n", V1);

    } else if (cmd == "kalibrasiph"){
      calibratePH();

    } else if (cmd == "kalibrasi_turb_bening"){
      long total=0; for(int i=0;i<200;i++){ total+=analogRead(TURBIDITY_PIN); delay(2); }
      int adcAvg = total/200;
      if (adcAvg <= 5 || adcAvg >= 4090){ Serial.println("[Turb] ERROR: ADC tidak valid (0/4095). Cek wiring/divider!"); }
      else{
        float vADC = (adcAvg * 3.3f) / 4095.0f;
        turb_V_clear = vADC / faktorPembagi;
        EEPROM.put(EE_TURB_V_CLEAR, turb_V_clear); EEPROM.commit();
        Serial.printf("[Turb] V_clear=%.4f V (sensor)\n", turb_V_clear);
      }

    } else if (cmd.startsWith("set_turb_ref_ntu ")){
      float val = cmd.substring(17).toFloat();
      if (val >= 5 && val <= 2000){
        turb_ref_ntu = val;
        EEPROM.put(EE_TURB_REF_NTU, turb_ref_ntu); EEPROM.commit();
        Serial.printf("[Turb] refNTU=%.1f\n", turb_ref_ntu);
      } else Serial.println("[Turb] Range 5–2000 NTU");

    } else if (cmd == "kalibrasi_turb_ref"){
      long total=0; for(int i=0;i<200;i++){ total+=analogRead(TURBIDITY_PIN); delay(2); }
      int adcAvg = total/200;
      if (adcAvg <= 5 || adcAvg >= 4090){ Serial.println("[Turb] ERROR: ADC tidak valid (0/4095). Cek wiring/divider!"); }
      else{
        float vADC = (adcAvg * 3.3f) / 4095.0f;
        turb_V_ref = vADC / faktorPembagi;
        EEPROM.put(EE_TURB_V_REF, turb_V_ref); EEPROM.commit();
        Serial.printf("[Turb] V_ref=%.4f V (sensor) utk %.1f NTU\n", turb_V_ref, turb_ref_ntu);
      }

    } else if (cmd.startsWith("set_faktor ")){
      float f = cmd.substring(11).toFloat();
      if (f > 0.05f && f < 1.50f){
        faktorPembagi = f;
        EEPROM.put(EE_FAKTOR_PEMBAGI, faktorPembagi); EEPROM.commit();
        Serial.printf("[Turb] faktorPembagi=%.3f\n", faktorPembagi);
      } else Serial.println("[Turb] Gagal: 0.05–1.50");

    } else if (cmd == "turb_debug"){
      long total=0; for(int i=0;i<200;i++){ total+=analogRead(TURBIDITY_PIN); delay(2); }
      int adcAvg = total/200;
      float vADC  = (adcAvg * 3.3f) / 4095.0f;
      float vSens = (faktorPembagi>0)? vADC / faktorPembagi : 0;
      Serial.printf("[Turb] ADC=%d vADC=%.4fV vSens=%.4fV faktor=%.3f\n", adcAvg, vADC, vSens, faktorPembagi);

    } else if (cmd == "status"){
      Serial.printf("Salinity V0=%.3f | V1=%.3f\n", V0, V1);
      Serial.printf("pH slope=%.4f | intercept=%.4f\n", slope, intercept);
      Serial.printf("Turb V_clear=%.4f | V_ref=%.4f | refNTU=%.1f | faktor=%.3f\n",
                    turb_V_clear, turb_V_ref, turb_ref_ntu, faktorPembagi);
    }
  }

  // ===== Baca sensor =====
  float valPH   = readPH();
  float valSal  = readSalinitas();
  float valSuhu = readSuhu();
  float valNTU  = readTurbidity();

  // fallback jika invalid
  if (isnan(valPH))   valPH = 0.0;
  if (isnan(valSal))  valSal = 0.0;
  if (isnan(valSuhu)) valSuhu = 0.0;
  if (isnan(valNTU))  valNTU = 0.0;

  // ===== LCD (20x4) =====
  lcd.clear();
  lcd.setCursor(0,0);  lcd.print("ID: ");  lcd.print(NODE_ID);
  lcd.setCursor(0,1);  lcd.print("PH: ");  lcd.print(valPH, 2);
  lcd.setCursor(0,2);  lcd.print("SAL: "); lcd.print(valSal, 2);
  lcd.setCursor(0,3);  lcd.print("SH: ");  lcd.print(valSuhu, 1); lcd.print((char)223); lcd.print("C ");
  lcd.setCursor(11,3); lcd.print("TUR: "); lcd.print(valNTU, 1);

  // ===== LoRa TX ===== (format: NODEX,pH,sal,suhu,NTU)
  if (millis() - lastSend > BASE_INTERVAL_MS + (uint32_t)random(0, 500)) {
    String data = String(NODE_ID) + "," + String(valPH, 2) + "," + String(valSal, 2) + "," +
                  String(valSuhu, 1) + "," + String(valNTU, 1);
    LoRa.beginPacket();
    LoRa.print(data);
    LoRa.endPacket(true); // async
    Serial.println(String("[LoRa] Kirim: ") + data);
    lastSend = millis();
  }

  delay(1000);
}
