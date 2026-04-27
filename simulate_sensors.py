"""
IrriSmart - Sensor Simulator
Simulates 3 LoRa soil sensors sending data to the IrriSmart API.
Run this during your presentation to show live sensor data.

Usage: python3 simulate_sensors.py
"""
import requests
import time
import random
import math

# Your live Railway URL
API = "https://web-production-0cb7c.up.railway.app"

SENSORS = [
    {"id": "ID010001", "name": "Parcelle Oliviers Nord",  "crop": "olive",  "base_moisture": 41.0, "battery": 85.0},
    {"id": "ID010002", "name": "Parcelle Agrumes Centre", "crop": "citrus", "base_moisture": 48.0, "battery": 82.0},
    {"id": "ID010003", "name": "Parcelle Blé Sud",        "crop": "wheat",  "base_moisture": 35.0, "battery": 88.0},
]

CROP_ROTATION = ["olive", "citrus", "wheat"]

print("🌱 IrriSmart Sensor Simulator Started")
print(f"📡 Sending data to: {API}")
print("🔄 Crop rotation enabled for AI testing")
print("Press Ctrl+C to stop\n")

day = 0
while True:
    print(f"--- Reading #{day+1} ---")
    for i, s in enumerate(SENSORS):
        # Rotate crop type every reading for each sensor
        current_crop = CROP_ROTATION[(day + i) % len(CROP_ROTATION)]
        # Realistic moisture variation
        moisture = s["base_moisture"] + math.sin(day / 7) * 5 + random.uniform(-2, 2)
        moisture = max(20, min(70, round(moisture, 1)))

        temp      = round(25 + math.sin(day / 14) * 8 + random.uniform(-1, 1), 1)
        humidity  = round(55 + random.uniform(-5, 5), 1)
        rain      = round(random.uniform(0, 4), 1) if random.random() > 0.75 else 0.0
        battery   = round(s["battery"] - day * 0.05, 1)
        soil_temp = round(temp - 2.0 + random.uniform(-0.5, 0.5), 1)  # soil ~2°C cooler than air
        ph        = round(6.8 + random.uniform(-0.3, 0.3), 2)          # typical agricultural pH

        try:
            r = requests.post(f"{API}/api/data", json={
                "sensor_id":       s["id"],
                "soil_moisture":   moisture,
                "air_temperature": temp,
                "air_humidity":    humidity,
                "battery_pct":     battery,
                "rain_mm":         rain,
                "soil_temperature": soil_temp,
                "ph_level":        ph,
            }, timeout=10)
            status = "✅" if r.status_code == 200 else f"❌ {r.status_code}"
            print(f"  [{current_crop.upper()}] {s['name']}: moisture={moisture}% airTemp={temp}°C soilTemp={soil_temp}°C pH={ph} rain={rain}mm battery={battery}% {status}")
        except Exception as e:
            print(f"  {s['name']}: ❌ Error - {e}")

    day += 1
    print(f"\nNext reading in 60 seconds...\n")
    time.sleep(60)
