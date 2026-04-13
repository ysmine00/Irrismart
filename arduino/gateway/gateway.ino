/*
 * IrriSmart Gateway — Heltec WiFi LoRa 32 V3
 *
 * - Listens for Makerfabs LoRa packets on 433 MHz
 * - Forwards raw packet as HTTP POST to the IrriSmart backend
 * - Shows status on the built-in OLED (128x64)
 *
 * Libraries required (install via Arduino Library Manager):
 *   - Heltec ESP32 Dev-Boards  (by Heltec Automation)
 *   - ArduinoJson              (by Benoit Blanchon, v6.x)
 *
 * Board: "Heltec WiFi LoRa 32(V3)"  (Heltec ESP32 Series Dev-boards)
 */

#include "heltec.h"          // Heltec all-in-one: LoRa + OLED
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ── Configuration ─────────────────────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* API_URL       = "https://irrismart.up.railway.app/api/data";

// LoRa — must match Makerfabs sensor settings exactly
const long  LORA_FREQ     = 433E6;   // 433 MHz
const int   LORA_SF       = 10;      // Spreading Factor
const long  LORA_BW       = 125E3;   // Bandwidth 125 kHz
const int   LORA_CR       = 5;       // Coding Rate 4/5
const int   LORA_SYNC     = 0x12;    // Sync word (Makerfabs default)
const int   LORA_TX_PWR   = 14;      // dBm

// ── State ─────────────────────────────────────────────────────────────────────
String lastPacket   = "";
String lastStatus   = "Demarrage...";
int    packetCount  = 0;
bool   wifiOK       = false;

// ── Helpers ───────────────────────────────────────────────────────────────────

void drawDisplay() {
  Heltec.display->clear();
  Heltec.display->setFont(ArialMT_Plain_10);

  // Line 1: WiFi status
  Heltec.display->drawString(0, 0, wifiOK ? "WiFi: OK" : "WiFi: ERREUR");

  // Line 2: packet counter
  Heltec.display->drawString(0, 13, "Paquets: " + String(packetCount));

  // Line 3: last packet (truncated to fit 128px)
  String pktDisplay = lastPacket.length() > 21
                      ? lastPacket.substring(0, 21)
                      : lastPacket;
  Heltec.display->drawString(0, 26, pktDisplay);

  // Line 4: last POST result
  Heltec.display->drawString(0, 39, lastStatus);

  Heltec.display->display();
}

bool connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connexion WiFi");
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 20) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  Serial.println();

  wifiOK = (WiFi.status() == WL_CONNECTED);
  if (wifiOK) {
    Serial.println("WiFi connecte: " + WiFi.localIP().toString());
  } else {
    Serial.println("WiFi echec — mode hors-ligne");
  }
  return wifiOK;
}

// Send the raw Makerfabs string as plain text.
// The backend detects "ID...ADC:..." and parses it server-side.
bool postToBackend(const String& rawPacket) {
  if (WiFi.status() != WL_CONNECTED) {
    // Try to reconnect once
    connectWiFi();
    if (!wifiOK) {
      lastStatus = "POST: pas WiFi";
      return false;
    }
  }

  HTTPClient http;
  http.begin(API_URL);
  http.addHeader("Content-Type", "text/plain");
  http.setTimeout(8000);   // 8 s timeout

  int code = http.POST(rawPacket);

  if (code == 200 || code == 201) {
    lastStatus = "POST: OK (" + String(code) + ")";
    Serial.println("POST OK: " + String(code));
    http.end();
    return true;
  } else if (code > 0) {
    String body = http.getString();
    lastStatus = "POST: err " + String(code);
    Serial.println("POST erreur " + String(code) + ": " + body);
  } else {
    lastStatus = "POST: timeout";
    Serial.println("POST echec: " + http.errorToString(code));
  }

  http.end();
  return false;
}

bool isValidMakerfabsPacket(const String& pkt) {
  // Must start with "ID" and contain "ADC:"
  return pkt.startsWith("ID") && pkt.indexOf("ADC:") != -1;
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // Init Heltec board (OLED on, LoRa on, serial on)
  Heltec.begin(true, true, true, true, LORA_FREQ);

  // LoRa config
  LoRa.setSpreadingFactor(LORA_SF);
  LoRa.setSignalBandwidth(LORA_BW);
  LoRa.setCodingRate4(LORA_CR);
  LoRa.setSyncWord(LORA_SYNC);
  LoRa.setTxPower(LORA_TX_PWR);
  LoRa.receive();   // put radio in continuous RX mode

  Serial.println("LoRa pret sur 433 MHz");

  // WiFi
  connectWiFi();

  drawDisplay();
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  // Check for incoming LoRa packet
  int packetSize = LoRa.parsePacket();

  if (packetSize > 0) {
    String packet = "";
    while (LoRa.available()) {
      packet += (char)LoRa.read();
    }
    packet.trim();

    int rssi = LoRa.packetRssi();
    Serial.println("Paquet recu [RSSI:" + String(rssi) + "]: " + packet);

    if (isValidMakerfabsPacket(packet)) {
      packetCount++;
      lastPacket = packet;
      drawDisplay();

      bool ok = postToBackend(packet);
      Serial.println(ok ? "Transmis OK" : "Transmission echouee");
    } else {
      lastStatus = "Paquet invalide";
      Serial.println("Paquet ignore (format invalide): " + packet);
    }

    drawDisplay();
  }

  // Reconnect WiFi if dropped (check every ~30 s via non-blocking counter)
  static unsigned long lastWiFiCheck = 0;
  if (millis() - lastWiFiCheck > 30000) {
    lastWiFiCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      wifiOK = false;
      Serial.println("WiFi perdu — tentative de reconnexion...");
      connectWiFi();
      drawDisplay();
    }
  }
}
