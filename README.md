# IrriSmart

Système de conseil en irrigation intelligent pour les agriculteurs de Béni Mellal-Khénifra, Maroc.

**Démo live :** https://irrismart.up.railway.app

---

## Description

IrriSmart est un système IoT et IA de précision pour petits exploitants agricoles de la région de Béni Mellal-Khénifra (plaine du Tadla). Il combine capteurs capacitifs de sol en temps réel, moteur RandomForest (94.4–95.0% accuracy), détection d'anomalies IsolationForest, analyse statistique saisonnière (z-score vs baselines INRA Tadla), intégration météo Open-Meteo, et tableau de bord bilingue FR/AR avec assistant conversationnel en darija marocaine.

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend | Python 3.11, Flask 3.0.0 |
| Base de données | PostgreSQL (Railway) |
| ML / IA | scikit-learn 1.3.2 (RandomForest, IsolationForest) |
| Frontend | HTML5, CSS3, Vanilla JS, Chart.js, Leaflet.js |
| IoT Gateway | Heltec WiFi LoRa 32 V3 |
| Capteurs | Capacitive Soil Moisture v1.2 |
| Déploiement | Railway.app |
| Météo | Open-Meteo API (32.34°N, -6.35°E) |
| SMS / WhatsApp | Twilio |
| Assistant IA | Claude Haiku (claude-haiku-4-5-20251001) |

---

## Cultures et seuils (INRA Tadla + FAO-56)

| Culture | ID Capteur | Parcelle | Seuil critique | Optimal | Surface |
|---------|-----------|----------|----------------|---------|---------|
| Olivier | ID010001 | Parcelle Oliviers Nord | 15% | 35–50% | 2.4 ha |
| Agrumes | ID010002 | Parcelle Agrumes Centre | 20% | 45–60% | 1.9 ha |
| Blé dur | ID010003 | Parcelle Blé Sud | 10% | 30–45% | 3.2 ha |

---

## Performances ML (test set 2 400 échantillons/culture)

| Culture | Accuracy | F1 | Recall | CV F1 | ROC AUC |
|---------|----------|----|--------|-------|---------|
| Olivier | 94.71% | 0.9423 | 93.51% | 0.9418 | 0.9503 |
| Agrumes | 94.42% | 0.9462 | 94.62% | 0.9494 | 0.9482 |
| Blé dur | 95.00% | 0.9390 | 92.76% | 0.9346 | 0.9514 |

---

## Installation locale

```bash
git clone https://github.com/ysmine00/Irrismart.git
cd Irrismart
pip install -r requirements.txt
cp .env.example .env   # remplir DATABASE_URL, ANTHROPIC_API_KEY, TWILIO_*
python run.py
```

---

## Principaux endpoints API

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | /api/sensors/latest | Dernières lectures par culture |
| GET | /api/sensors/\<id\>/history | Historique capteur (paginé) |
| POST | /api/data | Ingestion lecture (JSON ou paquet Makerfabs) |
| POST | /api/predict | Inférence RF explicite |
| GET | /api/recommendation | Recommandation temps réel toutes cultures |
| GET | /api/forecast/\<id\> | Prévision humidité 72 h |
| GET | /api/anomalies | Anomalies z-score saisonnières |
| POST | /api/anomaly/detect | Inférence IsolationForest |
| GET | /api/water-savings | Économies eau cumulées |
| POST | /api/chat | Assistant bilingue (Claude Haiku) |
| GET | /api/weather | Prévisions Open-Meteo 6 jours |
| GET | /api/health | Health check |

**Format paquet Makerfabs (LoRa) :**
```
ID010003 REPLY: SOIL INDEX:0 H:48.85 T:30.50 ADC:896 BAT:1016
```

---

## Architecture IoT

```
[Capteurs capacitifs] → GPIO32/33/34
        ↓ (ADC 12-bit, 3.3V)
[Heltec WiFi LoRa 32 V3]  ← gateway.ino (191 lignes)
        ↓ HTTP POST
[Flask API / Railway]
        ↓
[PostgreSQL] + [RF Models] + [IsolationForest] + [Open-Meteo]
        ↓
[PWA Dashboard] + [Twilio SMS/WhatsApp] + [Claude Haiku]
```

**Mode production :** noeuds LoRa autonomes → 433 MHz, SF10, BW=125 kHz → gateway → cloud

---

## Références scientifiques

- Allen et al. (1998). FAO Irrigation and Drainage Paper No. 56
- Breiman, L. (2001). Random Forests. Machine Learning, 45(1), 5–32
- Liu et al. (2008). Isolation Forest. ICDM 2008
- Augustin et al. (2016). A study of LoRa. Sensors, 16(9), 1466
- Et-taibi et al. (2024). Smart irrigation IoT. Results in Engineering, 22, 102283
- INRA Tadla — Seuils hydriques Béni Mellal-Khénifra

---

## Auteure

**Yasmine Kouch** — Al Akhawayn University in Ifrane  
Capstone Design, Spring 2026  
Superviseur : Dr. Amine Abouaomar
