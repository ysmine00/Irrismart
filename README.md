# IrriSmart

Irrigation advisory system for smallholder farms in the Beni Mellal-Khénifra region of Morocco. Built as a CS capstone project.

Live: https://irrismart.up.railway.app

---

## What it does

Farmers in the Tadla region mostly irrigate on fixed schedules, same day every week, regardless of actual soil conditions or weather. This wastes a significant amount of water and stresses crops. IrriSmart puts a soil moisture sensor in each plot and tells the farmer daily whether to irrigate, wait, or just keep an eye on things.

The system handles three crop types: olive, citrus, and wheat. Each has different moisture thresholds based on INRA Tadla and FAO guidelines.

---

## How it works

Capacitive soil sensors (Makerfabs LoRa Soil Sensor V3) sit in the ground and wake up every hour to take a reading. They send it over LoRa (433 MHz) to a gateway (Heltec WiFi LoRa 32 V3) sitting in the farm building. The gateway forwards it to the backend over WiFi. The backend checks the moisture against crop thresholds, pulls a weather forecast from Open-Meteo, and decides what to recommend. If moisture is critical, the farmer gets an SMS.

The dashboard is in French and Arabic with RTL support: most farmers in the region are more comfortable in one of those two.

---

## Stack

- Backend: Flask + SQLAlchemy, PostgreSQL, deployed on Railway
- Weather: Open-Meteo (free, no API key)
- Alerts: Twilio SMS
- Frontend: Vanilla HTML/CSS/JS, Chart.js for charts, Leaflet for the map
- Hardware: Makerfabs LoRa Soil Sensor V3 (×3), Heltec WiFi LoRa 32 V3 (×1)

---

## Sensor format

The Makerfabs sensor sends ASCII over LoRa:

```
ID010001 REPLY: SOIL INDEX:0 H:48.85 T:30.50 ADC:896 BAT:1016
```

ADC value is inversely proportional to moisture, higher ADC means drier soil. The backend converts it to a percentage using wet/dry calibration values.

---

## Moisture thresholds

| Crop | Irrigate below | Optimal range | Critical |
|------|---------------|---------------|---------|
| Olive | 25% | 35–50% | < 15% |
| Citrus | 30% | 45–60% | < 20% |
| Wheat | 20% | 30–45% | < 10% |

---

## API

| Method | Endpoint | What it does |
|--------|----------|-------------|
| POST | `/api/data` | Receive reading from gateway |
| GET | `/api/sensors` | List sensors |
| GET | `/api/recommendation` | Get today's irrigation decision |
| GET | `/api/weather` | Cached weather forecast |
| GET | `/api/alerts` | Active alerts |
| GET | `/api/reports/weekly` | Weekly summary |

---

## Running locally

Needs Python 3.11+ and PostgreSQL.

```bash
git clone https://github.com/ysmine00/Irrismart.git
cd Irrismart
pip install -r requirements.txt
cp .env.example .env
# edit .env with your database URL and Twilio credentials
python run.py
```

Database initializes and seeds itself on first run with demo sensor data.
