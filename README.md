# IrriSmart
**Smart Irrigation Advisory System — Beni Mellal-Khénifra, Morocco**

Computer Science Capstone Project · December 2025

🔗 **[irrismart.up.railway.app](https://irrismart.up.railway.app)**

---

## Overview

IrriSmart is an IoT-based irrigation advisory system built for smallholder farms in Morocco's Tadla region. The system collects real-time soil moisture data from field sensors, combines it with weather forecasts, and generates daily irrigation recommendations tailored to each crop.

The core question it answers: **should I irrigate today, and for how long?**

---

## Context

The Beni Mellal-Khénifra region has lost 45% of its dam capacity since 1964. Agriculture accounts for 85% of water consumption, and most farmers still irrigate on fixed schedules with no objective measurement. IrriSmart targets a 20–30% reduction in water usage through precision irrigation.

---

## Architecture

Field sensors transmit soil readings over LoRa (433 MHz) to an ESP32 gateway, which forwards data to a Flask backend via HTTP. The backend runs a recommendation engine using crop-specific thresholds and a 7-day weather forecast, then updates the dashboard and sends SMS alerts if needed.

```
Makerfabs Sensors → LoRa 433MHz → Heltec ESP32 Gateway → WiFi → Flask API → PostgreSQL
                                                                          ↓
                                                              Web Dashboard + Twilio SMS
```

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, Flask, SQLAlchemy |
| Database | PostgreSQL |
| Weather | Open-Meteo API |
| Alerts | Twilio SMS |
| Frontend | HTML/CSS/JS, Chart.js, Leaflet.js |
| Hardware | Makerfabs LoRa Soil Sensor V3, Heltec WiFi LoRa 32 V3 |
| Hosting | Railway |

---

## Hardware

Three Makerfabs LoRa Soil Moisture Sensors V3 are deployed across olive, citrus, and wheat parcels. Each sensor transmits every 60 minutes in the following format:

```
ID010001 REPLY: SOIL INDEX:0 H:48.85 T:30.50 ADC:896 BAT:1016
```

A single Heltec WiFi LoRa 32 V3 acts as the gateway, receiving packets and forwarding them to the backend. All hardware is housed in IP65-rated enclosures.

---

## Recommendation Logic

The engine applies crop-specific moisture thresholds (INRA Tadla / FAO) and outputs one of four actions: `IRRIGATE`, `WAIT`, `MONITOR`, or `NO_ACTION`. Rain forecasts, temperature, soil type, and growth stage are factored in as correction variables.

| Crop | Low (%) | Optimal (%) | Critical (%) |
|------|---------|-------------|--------------|
| Olive | 25 | 35–50 | < 15 |
| Citrus | 30 | 45–60 | < 20 |
| Wheat | 20 | 30–45 | < 10 |

---

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/data` | Ingest sensor reading |
| GET | `/api/sensors` | List sensors |
| GET | `/api/recommendation` | Get irrigation decision |
| GET | `/api/weather` | Weather forecast |
| GET | `/api/alerts` | Active alerts |
| GET | `/api/reports/weekly` | Weekly summary |

---

## Running Locally

```bash
git clone https://github.com/ysmine00/Irrismart.git
cd Irrismart
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Fill in `.env` with your database URL, Twilio credentials, and secret key. The database is seeded automatically on first run.

---

## Live Demo

[https://irrismart.up.railway.app](https://irrismart.up.railway.app)

Three parcels are pre-seeded with 14 days of simulated sensor data.
