"""
Recommendation engine — matches every metric shown in the IrriSmart demo:
  • IRRIGATE / WAIT / NO_ACTION / MONITOR decision
  • Irrigation duration
  • Confidence %
  • Soil health score (0-100) with sub-scores
  • 5-day forecast cards (besoin, pluie %, stress thermique)
  • Simulation rapide (irrigate vs wait outcome)
  • Data confidence & sensor reliability meta-indicators
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from app import db
from app.models import Sensor, Reading, Recommendation

CROP_THRESHOLDS = {
    "olive":   {"critical":15, "low":25, "opt_low":35, "opt_high":50, "opt_mid":42, "high":60},
    "citrus":  {"critical":20, "low":30, "opt_low":45, "opt_high":60, "opt_mid":52, "high":70},
    "wheat":   {"critical":10, "low":20, "opt_low":30, "opt_high":45, "opt_mid":37, "high":55},
    "alfalfa": {"critical":25, "low":35, "opt_low":50, "opt_high":65, "opt_mid":57, "high":75},
    "beet":    {"critical":20, "low":30, "opt_low":45, "opt_high":60, "opt_mid":52, "high":70},
}

@dataclass
class DayForecastCard:
    date: str
    besoin: str        # Faible | Moyen | Élevé
    pluie_pct: float
    stress_thermique: str

@dataclass
class SimulationResult:
    scenario: str            # "irrigate" | "wait"
    estimated_moisture: float
    estimated_health: int
    moisture_impact: float
    health_impact: int
    description: str

@dataclass
class RecommendationResult:
    action: str
    duration_minutes: int
    reason: str
    confidence: float
    moisture_pct: float
    is_critical: bool
    factors: list
    forecast_cards: list
    sim_irrigate: SimulationResult = None
    sim_wait: SimulationResult     = None
    soil_health: int               = 83
    health_sub: dict               = field(default_factory=dict)
    data_confidence: float         = 76.0
    sensor_reliability: str        = "À surveiller"
    trend_coherence: str           = "Stable"
    freshness_min: int             = 14


def adc_to_pct(adc):
    return round(max(0, min(100, 100 * (800 - adc) / 500)), 1)


def _duration(deficit, flow_rate):
    mm = deficit * 2
    mins = (mm / flow_rate) * 60
    return int(max(15, min(120, round(mins / 5) * 5)))


def _besoin(moisture, thresholds):
    if moisture < thresholds["low"]:   return "Élevé"
    if moisture < thresholds["opt_low"]: return "Moyen"
    return "Faible"

def _stress(temp_max):
    if temp_max > 38: return "Élevé"
    if temp_max > 32: return "Moyen"
    return "Faible"


def _soil_health(sensor_id, moisture, thresholds):
    readings = Reading.query.filter_by(sensor_id=sensor_id)\
        .order_by(Reading.timestamp.desc()).limit(14).all()
    if not readings:
        return 70, {"stabilite_humidite":70,"equilibre_irrigation":70,"stress_thermique":99,"coherence_decisions":70}

    moistures = [r.soil_moisture for r in readings]
    temps     = [r.air_temperature for r in readings if r.air_temperature]

    # Stability: how far readings stray from optimal mid
    opt_mid = thresholds["opt_mid"]
    avg_dev = sum(abs(m - opt_mid) for m in moistures) / len(moistures)
    stabilite = max(0, min(100, int(100 - avg_dev * 2)))

    # Irrigation balance: how often in optimal range
    in_range  = sum(1 for m in moistures if thresholds["opt_low"] <= m <= thresholds["opt_high"])
    equilibre = int(100 * in_range / len(moistures))

    # Thermal stress: avg max below 38°C target
    avg_temp    = sum(temps) / len(temps) if temps else 25
    stress_th   = max(0, min(100, int(100 - max(0, avg_temp - 28) * 3)))

    # Decision coherence (past recs)
    recs = Recommendation.query.filter_by(sensor_id=sensor_id)\
        .order_by(Recommendation.created_at.desc()).limit(14).all()
    coherence = 75 if recs else 60

    sub = {"stabilite_humidite": stabilite, "equilibre_irrigation": equilibre,
           "stress_thermique": stress_th,   "coherence_decisions": coherence}
    score = int(0.35*stabilite + 0.30*equilibre + 0.20*stress_th + 0.15*coherence)
    return score, sub


def _data_confidence(readings):
    if not readings: return 50.0
    recent  = [r for r in readings if (datetime.utcnow()-r.timestamp).total_seconds() < 3600*3]
    gaps    = 0
    for i in range(1, len(readings)):
        delta = (readings[i].timestamp - readings[i-1].timestamp).total_seconds()
        if delta > 7200: gaps += 1
    freshness = 100 if recent else 60
    gap_penalty = min(40, gaps * 5)
    return round(max(40, freshness - gap_penalty), 1)


def generate(sensor_id, forecasts=None):
    from app.services import weather_service
    sensor = Sensor.query.get(sensor_id)
    if not sensor: return None

    reading = Reading.query.filter_by(sensor_id=sensor_id)\
        .order_by(Reading.timestamp.desc()).first()
    if not reading:
        return RecommendationResult(
            action="MONITOR", duration_minutes=0,
            reason="Aucune donnée capteur disponible.", confidence=0,
            moisture_pct=0, is_critical=False, factors=[], forecast_cards=[])

    t = CROP_THRESHOLDS.get(sensor.crop_type, CROP_THRESHOLDS["olive"])
    moisture = reading.soil_moisture

    if forecasts is None:
        forecasts = weather_service.get_forecast(days=5)
    tomorrow  = forecasts[1] if len(forecasts) > 1 else (forecasts[0] if forecasts else {})

    rain_exp  = tomorrow.get("precipitation_mm", 0) >= 5
    rain_prob = tomorrow.get("precipitation_prob", 0)
    high_temp = tomorrow.get("temp_max", 0) > 35
    temp_max  = tomorrow.get("temp_max", 30)
    precip    = tomorrow.get("precipitation_mm", 0)
    is_crit   = moisture < t["critical"]

    # ── Decision ──
    factors = []
    if moisture < t["low"]:
        if rain_exp:
            action, duration = "WAIT", 0
            reason = "Humidité actuelle suffisante pour aujourd'hui."
        else:
            deficit  = t["opt_mid"] - moisture
            duration = _duration(deficit, sensor.flow_rate)
            if high_temp: duration = min(120, int(duration * 1.2))
            action = "IRRIGATE"
            reason = f"Humidité insuffisante ({moisture}% < {t['low']}%). Irriguer {duration} min."
        factors.append({"label": f"Humidité actuelle: {moisture}%", "type": "moisture"})
        if rain_prob: factors.append({"label": f"Probabilité de pluie: {int(rain_prob)}%", "type": "rain"})
    elif moisture > t["high"]:
        action, duration = "NO_ACTION", 0
        reason = f"Sol suffisamment humide ({moisture}%)."
        factors.append({"label": f"Humidité actuelle: {moisture}%", "type": "moisture"})
    else:
        if high_temp:
            action, duration = "MONITOR", 0
            reason = f"Température élevée prévue ({temp_max}°C). Surveiller demain."
        else:
            action, duration = "WAIT", 0
            reason = "Humidité actuelle suffisante pour aujourd'hui."
        factors.append({"label": f"Humidité actuelle: {moisture}%", "type": "moisture"})
        if rain_prob: factors.append({"label": f"Probabilité de pluie: {int(rain_prob)}%", "type": "rain"})

    # hot days coming
    hot_days = sum(1 for f in forecasts if f.get("temp_max", 0) > 32)
    if hot_days: factors.append({"label": f"Jours chauds à venir: {hot_days}d", "type": "heat"})

    confidence = 80.0
    if len(factors) >= 2: confidence = 85.0
    if is_crit: confidence = 95.0
    if rain_prob > 60: confidence -= 10

    # ── Forecast cards ──
    cards = []
    for f in forecasts[1:6]:
        fdate = f.get("forecast_date","")
        cards.append(DayForecastCard(
            date=fdate,
            besoin=_besoin(moisture, t),
            pluie_pct=f.get("precipitation_prob", 0),
            stress_thermique=_stress(f.get("temp_max", 25))))

    # ── Soil health ──
    all_readings = Reading.query.filter_by(sensor_id=sensor_id)\
        .order_by(Reading.timestamp.desc()).limit(30).all()
    soil_score, sub = _soil_health(sensor_id, moisture, t)
    data_conf = _data_confidence(all_readings)

    mins_ago = abs(int((datetime.utcnow() - reading.timestamp).total_seconds() / 60))

    # ── Simulation ──
    irr_moisture = min(t["opt_high"], moisture + _duration(t["opt_mid"]-moisture, sensor.flow_rate) * sensor.flow_rate / 60 / 2)
    irr_health   = min(100, soil_score + 3)
    wait_moisture= max(t["critical"], moisture - 1.5)
    wait_health  = soil_score

    sim_irrigate = SimulationResult("irrigate", round(irr_moisture,1), irr_health,
                                    round(irr_moisture-moisture,1), irr_health-soil_score,
                                    "L'irrigation immédiate stabilise l'humidité pour les prochaines 24h.")
    sim_wait     = SimulationResult("wait", round(wait_moisture,1), wait_health,
                                    round(wait_moisture-moisture,1), 0,
                                    "Attendre préserve les ressources si la pluie est confirmée.")

    # ── Persist ──
    rec = Recommendation(sensor_id=sensor_id, action=action, duration_minutes=duration,
                         reason=reason, confidence=confidence,
                         moisture_at_time=moisture, health_impact=irr_health-soil_score)
    db.session.add(rec)
    db.session.commit()

    return RecommendationResult(
        action=action, duration_minutes=duration, reason=reason, confidence=confidence,
        moisture_pct=moisture, is_critical=is_crit, factors=factors,
        forecast_cards=cards, sim_irrigate=sim_irrigate, sim_wait=sim_wait,
        soil_health=soil_score, health_sub=sub, data_confidence=data_conf,
        sensor_reliability="À surveiller" if data_conf < 80 else "Fiable",
        trend_coherence="Stable", freshness_min=mins_ago)
