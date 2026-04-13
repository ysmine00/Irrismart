/*
 * IrriSmart Sensor Node
 *
 * Reads soil moisture, air temperature/humidity, soil temperature, and pH,
 * then transmits over LoRa (SX1278, 433 MHz) to the T-Beam gateway.
 *
 * Hardware:
 *   - Arduino Nano (or compatible)
 *   - Capacitive Soil Moisture Sensor V1.2     → A0
 *   - DHT22 (air temp + humidity)              → D4
 *   - LoRa SX1278 Ra-02                        → SPI (D10=CS, D9=RST, D2=DIO0)
 *   - pH Sensor Module (analog)                → A1  (leave unconnected for simulation)
 *   - DS18B20 waterproof soil temp sensor      → D3  (optional, simulated if absent)
 *
 * Libraries (Arduino Library Manager):
 *   - RadioLib          (by Jan Gromeš)
 *   - DHT sensor library (by Adafruit)
 *
 * Packet format sent over LoRa:
 *   "ID010001,45.2,28.5,62.3,26.1,6.82,87.5"
 *    sensor_id, soil_moisture%, air_temp°C, air_humidity%, soil_temp°C, pH, battery%
 */

#include <RadioLib.h>
#include <DHT.h>
#include <SPI.h>

// ── Pin configuration ──────────────────────────────────────────────────────
#define DHT_PIN         4     // DHT22 data pin
#define SOIL_ADC_PIN    A0    // Capacitive soil sensor
#define PH_ADC_PIN      A1    // pH sensor analog output
#define LORA_CS         10    // SX1278 NSS
#define LORA_RST        9     // SX1278 RST
#define LORA_DIO0       2     // SX1278 DIO0

// ── Node configuration — change per sensor node ────────────────────────────
#define SENSOR_ID          "ID010001"   // ID010001, ID010002, ID010003
#define TRANSMIT_INTERVAL  60000        // ms between transmissions (60 s)

// ── Soil sensor calibration ─────────────────────────────────────────────────
// Measure these values with your actual sensor:
//   SOIL_DRY = ADC reading when sensor is in dry air
//   SOIL_WET = ADC reading when sensor is submerged in water
#define SOIL_DRY    650
#define SOIL_WET    280

// ── pH simulation ───────────────────────────────────────────────────────────
// Set to true until real pH sensor arrives.
// When hardware arrives: set PH_SIMULATE to false — that's the only change needed.
#define PH_SIMULATE    true
#define PH_BASE        6.8   // Typical agricultural soil pH for Tadla region

// ── Soil temperature simulation ─────────────────────────────────────────────
// Set to true until DS18B20 sensor arrives.
#define SOIL_TEMP_SIMULATE  true

// ── Globals ─────────────────────────────────────────────────────────────────
DHT dht(DHT_PIN, DHT22);
SX1278 radio = new Module(LORA_CS, LORA_DIO0, LORA_RST);
unsigned long lastTransmit = 0;
int readingCount = 0;

// ── Setup ───────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("=== IrriSmart Sensor Node ===");
  Serial.print("Sensor ID: ");
  Serial.println(SENSOR_ID);

  dht.begin();
  Serial.println("DHT22 ready");

  int state = radio.begin(433.0);
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("SX1278 LoRa ready on 433 MHz");
  } else {
    Serial.print("LoRa init failed, code: ");
    Serial.println(state);
    while (true) { delay(1000); }
  }

  // Must match gateway settings exactly
  radio.setSpreadingFactor(10);
  radio.setBandwidth(125.0);
  radio.setCodingRate(5);
  radio.setSyncWord(0x12);
  radio.setOutputPower(17);

  Serial.println("Ready. First reading in 5 seconds...");
  delay(5000);
}

// ── Helpers ─────────────────────────────────────────────────────────────────

float readSoilMoisture() {
  int raw = analogRead(SOIL_ADC_PIN);
  float pct = (float)(raw - SOIL_WET) / (SOIL_DRY - SOIL_WET) * 100.0;
  return constrain(pct, 0.0, 100.0);
}

float readPH() {
  if (PH_SIMULATE) {
    // Realistic variation around base pH
    return PH_BASE + ((float)random(-30, 30)) / 100.0;
  }
  // Real pH sensor: voltage output 0–3.3V maps to pH 0–14
  int raw = analogRead(PH_ADC_PIN);
  float voltage = raw * (5.0 / 1023.0);
  return 3.5 * voltage;  // adjust calibration factor for your specific sensor
}

float readSoilTemp(float airTemp) {
  if (SOIL_TEMP_SIMULATE) {
    // Soil temperature is typically 2–4°C cooler than air in daylight
    return airTemp - 2.0 + ((float)random(-50, 50)) / 100.0;
  }
  // DS18B20 reading goes here — add OneWire + DallasTemperature libraries
  return airTemp - 2.0;
}

float readBattery() {
  // Simulated battery — replace with real ADC reading if battery monitoring circuit present
  return 90.0;
}

// ── Loop ────────────────────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  if (now - lastTransmit >= TRANSMIT_INTERVAL) {
    lastTransmit = now;
    readingCount++;

    // Read sensors
    float airTemp    = dht.readTemperature();
    float airHumid   = dht.readHumidity();

    if (isnan(airTemp) || isnan(airHumid)) {
      Serial.println("DHT22 read failed — skipping this cycle");
      return;
    }

    float soilMoist  = readSoilMoisture();
    float soilTemp   = readSoilTemp(airTemp);
    float ph         = readPH();
    float battery    = readBattery();

    // Build packet
    // Format: "ID010001,45.2,28.5,62.3,26.1,6.82,87.5"
    String packet = String(SENSOR_ID) + "," +
                    String(soilMoist,  1) + "," +
                    String(airTemp,    1) + "," +
                    String(airHumid,   1) + "," +
                    String(soilTemp,   1) + "," +
                    String(ph,         2) + "," +
                    String(battery,    1);

    Serial.print("Reading #");
    Serial.print(readingCount);
    Serial.print(" → ");
    Serial.println(packet);

    // Transmit
    int state = radio.transmit(packet);
    if (state == RADIOLIB_ERR_NONE) {
      Serial.println("Transmitted OK");
    } else {
      Serial.print("Transmit failed, code: ");
      Serial.println(state);
    }
  }
}
