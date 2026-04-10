# IrriSmart

Irrigation advisory system for small farms in Morocco. Sensors in the field send soil and weather data wirelessly to a central gateway, which forwards it to a backend that decides whether to irrigate or wait — and why.

The dashboard runs in French and Arabic and is accessible from any device.

---

## How it works

Capacitive soil moisture sensors (Makerfabs) sit in the ground across different farm parcels. They communicate over LoRa (433 MHz) to a gateway (Heltec WiFi LoRa 32 V3) which relays readings to the backend over WiFi. The backend processes the data, runs a recommendation engine, and updates the dashboard in real time.

If moisture drops critically, the farmer gets an SMS.

---

## Stack

- Flask + SQLAlchemy + PostgreSQL
- Open-Meteo API for weather forecasts
- Twilio for SMS alerts
- Chart.js + Leaflet.js for the frontend
- Arduino (Heltec ESP32 LoRa) for the gateway
- Deployed on Railway

---

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in .env with your database URL and API credentials
python run.py
```

The database is created and seeded automatically on first run.

---

## Gateway

Flash `gateway.ino` to a Heltec WiFi LoRa 32 V3. Set your WiFi credentials in the sketch. It will listen for Makerfabs packets on 433 MHz and POST them to the backend.

Libraries needed: Heltec ESP32 Dev-Boards, ArduinoJson

---

## API

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/sensors` | List sensors |
| POST | `/api/sensors` | Register a sensor |
| POST | `/api/data` | Ingest a reading |
| GET | `/api/recommendation` | Get irrigation decision |
| GET | `/api/alerts` | List active alerts |
| GET | `/api/weather` | Weather forecast |
| GET | `/api/reports/weekly` | Weekly report |

---

## Live

https://irrismart.up.railway.app
