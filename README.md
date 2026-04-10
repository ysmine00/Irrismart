# IrriSmart

An intelligent irrigation advisory system for Moroccan farms. IrriSmart collects real-time soil and environmental data from wireless sensors, analyzes it, and gives farmers clear irrigation recommendations — irrigate, wait, or monitor — through a bilingual (French/Arabic) web dashboard.

## What it does

- Receives soil moisture, temperature, humidity, and battery data from LoRa sensors in the field
- Recommends irrigation decisions per crop type (olive, citrus, wheat, alfalfa, beet) with adjustments for soil type, temperature, wind, and rain forecast
- Integrates live weather forecasts from Open-Meteo API
- Sends SMS alerts via Twilio when conditions are critical (low moisture, frost risk, sensor offline, high temperature)
- Displays a responsive dashboard with charts, alerts, reports, and a live map
- Supports French and Arabic

## Architecture

```
[Makerfabs LoRa Sensors] 
        ↓ LoRa 433MHz
[Heltec WiFi LoRa 32 V3 Gateway]
        ↓ HTTP POST
[Flask Backend on Railway]
        ↓
[PostgreSQL Database]
        ↓
[Web Dashboard] + [Twilio SMS]
```

## Tech Stack

- **Backend:** Python / Flask, SQLAlchemy, PostgreSQL
- **Frontend:** HTML/CSS/JavaScript (SPA), Chart.js, Leaflet.js
- **Hardware:** Heltec WiFi LoRa 32 V3 (gateway), Makerfabs capacitive soil sensors
- **APIs:** Open-Meteo (weather), Twilio (SMS alerts)
- **Deployment:** Railway

## Setup

### 1. Clone and install

```bash
git clone https://github.com/ysmine00/Irrismart.git
cd irrismart
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

```
DATABASE_URL=postgresql://user:password@host:5432/irrismart
SECRET_KEY=your-secret-key
FARM_LATITUDE=32.34
FARM_LONGITUDE=-6.35
TWILIO_ACCOUNT_SID=your-sid
TWILIO_AUTH_TOKEN=your-token
TWILIO_PHONE_FROM=+1234567890
FARMER_PHONE=+212600000000
```

### 3. Run

```bash
python run.py
```

The app auto-creates all database tables and seeds sample sensor data on first run.

### 4. Gateway (Arduino)

Open `gateway.ino` in Arduino IDE, set your WiFi credentials, and flash to a Heltec WiFi LoRa 32 V3. The gateway listens for Makerfabs LoRa packets on 433 MHz and forwards them to the backend.

**Required libraries:** Heltec ESP32 Dev-Boards, ArduinoJson

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | System health check |
| GET | `/api/sensors` | List all active sensors |
| POST | `/api/sensors` | Register a new sensor |
| POST | `/api/data` | Ingest sensor reading (raw Makerfabs or JSON) |
| GET | `/api/recommendation` | Get irrigation recommendation |
| GET | `/api/soil-health` | Get soil health score |
| GET | `/api/alerts` | List active alerts |
| POST | `/api/alerts/<id>/acknowledge` | Acknowledge an alert |
| GET | `/api/weather` | Get weather forecast |
| GET | `/api/reports/weekly` | Weekly summary report |
| GET | `/api/reports/daily` | Daily summary |

## Deployment

Deployed on Railway with PostgreSQL. The `Procfile` runs gunicorn with 2 workers:

```
web: gunicorn run:app --bind 0.0.0.0:$PORT --workers 2
```

Live: https://irrismart.up.railway.app
