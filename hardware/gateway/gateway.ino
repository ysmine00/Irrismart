/*
 * IrriSmart Gateway Firmware — Direct ADC Demo Mode
 * Hardware: Heltec WiFi LoRa 32 (V2 or V3)
 *
 * 3× Capacitive Soil Moisture Sensor v1.2 wired DIRECTLY to ADC GPIO pins.
 * No LoRa radio used in this demo — sensors connect via jumper wires.
 *
 * Wiring:
 *   Sensor 1 → GPIO32  crop: olive   sensor_id: ID010001
 *   Sensor 2 → GPIO33  crop: citrus  sensor_id: ID010002
 *   Sensor 3 → GPIO34  crop: wheat   sensor_id: ID010003
 *   All sensors: VCC → 3.3V, GND → GND
 *
 * Libraries required (install via Arduino Library Manager):
 *   - WiFi.h         (bundled with ESP32 board package)
 *   - HTTPClient.h   (bundled with ESP32 board package)
 *   - ArduinoJson    (by Benoit Blanchon, v6.x)
 *
 * If your board is V2 (SX1276 chip): LoRa.h is available but NOT initialised
 * here — only WiFi is used in this demo sketch.
 * If your board is V3 (SX1262 chip): same approach, LoRa not initialised.
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ── Configuration ─────────────────────────────────────────────────────────────
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASS "YOUR_WIFI_PASSWORD"
#define API_URL   "https://irrismart.up.railway.app/api/data"

// ADC calibration — field-calibrate these for your specific sensors
#define ADC_DRY 3200   // raw ADC reading when sensor is in dry air
#define ADC_WET 1200   // raw ADC reading when sensor is submerged in water

// Sensor pin mapping
const int   PINS[]       = {32, 33, 34};
const char* SENSOR_IDS[] = {"ID010001", "ID010002", "ID010003"};
const char* CROPS[]      = {"olive",    "citrus",   "wheat"};
const int   NUM_SENSORS  = 3;

// Post every 60 seconds
#define POST_INTERVAL_MS 60000UL

// ── ADC → moisture conversion ─────────────────────────────────────────────────
float adcToMoisture(int raw) {
  float pct = 100.0f * (ADC_DRY - raw) / (float)(ADC_DRY - ADC_WET);
  if (pct < 0.0f)   pct = 0.0f;
  if (pct > 100.0f) pct = 100.0f;
  return pct;
}

// ── WiFi helpers ─────────────────────────────────────────────────────────────
bool connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[WiFi] Connecting");
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 20) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("[WiFi] Connected: " + WiFi.localIP().toString());
    return true;
  }
  Serial.println("[WiFi] Failed — will retry next cycle");
  return false;
}

void ensureWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Reconnecting...");
    connectWiFi();
  }
}

// ── POST one sensor reading ───────────────────────────────────────────────────
bool postReading(const char* sensor_id, const char* crop_type, float moisture_pct) {
  ensureWiFi();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] Skipping POST — no WiFi");
    return false;
  }

  // Build JSON payload
  StaticJsonDocument<256> doc;
  doc["sensor_id"]        = sensor_id;
  doc["crop_type"]        = crop_type;   // informational; server uses sensor's registered crop
  doc["soil_moisture"]    = moisture_pct;
  doc["air_temperature_c"] = 0;          // no DHT22 in direct-wired demo
  doc["air_humidity_pct"]  = 0;
  char body[256];
  serializeJson(doc, body);

  HTTPClient http;
  http.begin(API_URL);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(8000);

  int code = http.POST(body);
  String resp = http.getString();
  http.end();

  Serial.printf("[HTTP] %s %s → %d %s\n", sensor_id, crop_type, code, resp.c_str());
  return (code == 200 || code == 201);
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n[IrriSmart] Gateway booting...");

  // Configure ADC pins as inputs
  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(PINS[i], INPUT);
  }

  connectWiFi();
  Serial.println("[IrriSmart] Ready — posting every 60s");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  static unsigned long lastPost = 0;

  if (millis() - lastPost >= POST_INTERVAL_MS) {
    lastPost = millis();
    Serial.println("\n[IrriSmart] Reading sensors...");

    for (int i = 0; i < NUM_SENSORS; i++) {
      int raw = analogRead(PINS[i]);
      float pct = adcToMoisture(raw);
      Serial.printf("  [%s] GPIO%d raw=%d moisture=%.1f%%\n",
                    SENSOR_IDS[i], PINS[i], raw, pct);
      postReading(SENSOR_IDS[i], CROPS[i], pct);
      delay(200);   // brief pause between posts
    }
  }
}
