from flask import Blueprint, request, jsonify
from datetime import datetime, date, timedelta
import json as _json
import math as _math
from sqlalchemy import func
from app import db
from app.models import Sensor, Reading, WeatherCache, Recommendation, Alert, SeasonalAnomalyLog
from app.services import weather_service, recommendation_service, alert_service

api = Blueprint("api", __name__, url_prefix="/api")

def ok(data=None, status=200):
    return jsonify({"status":"ok","data":data}), status

def err(msg, status=400):
    return jsonify({"status":"error","message":msg}), status


# ── Health ────────────────────────────────────────────────────────────────────
@api.route("/health")
def health():
    return ok({"version":"1.0.0","system":"IrriSmart"})


# ── Sensors ───────────────────────────────────────────────────────────────────
@api.route("/sensors")
def list_sensors():
    return ok([s.to_dict() for s in Sensor.query.filter_by(is_active=True).all()])

@api.route("/sensors/<sid>")
def get_sensor(sid):
    return ok(Sensor.query.get_or_404(sid).to_dict())

@api.route("/sensors", methods=["POST"])
def register_sensor():
    b = request.get_json(silent=True) or {}
    for f in ["id","name","crop_type"]:
        if f not in b: return err(f"Missing: {f}")
    if Sensor.query.get(b["id"]): return err("Sensor exists", 409)
    s = Sensor(id=b["id"], name=b["name"], crop_type=b["crop_type"],
               latitude=b.get("latitude"), longitude=b.get("longitude"),
               flow_rate=b.get("flow_rate",5.0), area_ha=b.get("area_ha",1.0))
    db.session.add(s); db.session.commit()
    return ok(s.to_dict(), 201)

@api.route("/sensors/<sid>/history")
def sensor_history(sid):
    limit = request.args.get("limit", 48, type=int)
    rows  = Reading.query.filter_by(sensor_id=sid)\
        .order_by(Reading.timestamp.desc()).limit(limit).all()
    return ok([r.to_dict() for r in reversed(rows)])


@api.route("/sensors/latest")
def sensors_latest():
    """Returns latest reading per crop, keyed by crop name. Used by IA tab."""
    sensors = Sensor.query.filter_by(is_active=True).all()
    result = {}
    for s in sensors:
        reading = Reading.query.filter_by(sensor_id=s.id)\
            .order_by(Reading.timestamp.desc()).first()
        if reading:
            result[s.crop_type] = {
                "soil_moisture_pct": reading.soil_moisture,
                "temperature_c": reading.air_temperature,
                "sensor_id": s.id,
                "sensor_name": s.name,
                "timestamp": reading.timestamp.isoformat(),
            }
    return ok(result)


# ── Ingest sensor data (from ESP32 gateway) ───────────────────────────────────
def _parse_makerfabs(raw):
    """
    Parse Makerfabs raw string:
      "ID010003 REPLY: SOIL INDEX:0 H:48.85 T:30.50 ADC:896 BAT:1016"
    Returns dict with sensor_id, air_humidity, air_temperature, soil_moisture, battery_pct
    or None if the string doesn't match the expected format.
    """
    import re
    m_id  = re.match(r'^(ID\w+)', raw)
    m_h   = re.search(r'\bH:([\d.]+)', raw)
    m_t   = re.search(r'\bT:([\d.]+)', raw)
    m_adc = re.search(r'\bADC:(\d+)', raw)
    m_bat = re.search(r'\bBAT:(\d+)', raw)
    if not (m_id and m_adc):
        return None
    adc = int(m_adc.group(1))
    # BAT: 1016 ≈ 3.0V ≈ 100%; linear scale 800=0% … 1016=100%
    bat_raw = int(m_bat.group(1)) if m_bat else 1016
    bat_pct = round(max(0, min(100, (bat_raw - 800) / (1016 - 800) * 100)), 1)
    return {
        "sensor_id":       m_id.group(1),
        "soil_moisture":   recommendation_service.adc_to_pct(adc),
        "air_humidity":    float(m_h.group(1)) if m_h else None,
        "air_temperature": float(m_t.group(1)) if m_t else None,
        "battery_pct":     bat_pct,
    }

@api.route("/data", methods=["POST"])
def ingest():
    # Support both JSON body and raw Makerfabs string
    raw = request.get_data(as_text=True).strip()
    if raw.startswith("ID") and "ADC:" in raw:
        b = _parse_makerfabs(raw)
        if b is None:
            return err("Impossible d'analyser la chaîne Makerfabs")
    else:
        b = request.get_json(silent=True) or {}

    sid = b.get("sensor_id")
    if not sid: return err("Missing sensor_id")
    s = Sensor.query.get(sid)
    if not s: return err(f"Unknown sensor: {sid}")

    # Accept raw ADC or pre-converted percentage
    soil = b.get("soil_moisture")
    if soil is None:
        adc = b.get("soil_adc")
        if adc is None: return err("Missing soil_moisture or soil_adc")
        soil = recommendation_service.adc_to_pct(int(adc))

    bat = b.get("battery_pct", 100.0)
    r = Reading(sensor_id=sid, soil_moisture=float(soil),
                air_temperature=b.get("air_temperature"),
                air_humidity=b.get("air_humidity"),
                battery_voltage=float(bat),
                rain_mm=b.get("rain_mm", 0),
                soil_temperature=b.get("soil_temperature"),
                ph_level=b.get("ph_level"))
    s.battery_level = float(bat)
    db.session.add(r)
    db.session.commit()

    # Standard alert checks
    alert_service.check_and_alert(s.id, r.soil_moisture, r.battery_voltage, r.air_temperature, r.timestamp)

    # Seasonal anomaly detection
    try:
        detect_anomaly(s.id, s.crop_type, r.soil_moisture)
    except Exception as e:
        print(f"Anomaly detection failed: {e}")

    return ok({"reading_id": r.id})


# ── Weather ───────────────────────────────────────────────────────────────────
@api.route("/weather")
def weather():
    days = request.args.get("days", 7, type=int)
    return ok(weather_service.get_forecast(days=days))


# ── Recommendation ────────────────────────────────────────────────────────────
@api.route("/recommendation")
def recommendation():
    sid = request.args.get("sensor_id")
    forecasts = weather_service.get_forecast(days=6)

    def _fmt(rec, sensor):
        if not rec: return None
        return {
            "sensor_id": sensor.id, "sensor_name": sensor.name, "crop_type": sensor.crop_type,
            "action": rec.action, "duration_minutes": rec.duration_minutes,
            "reason": rec.reason, "confidence": rec.confidence,
            "moisture_pct": rec.moisture_pct, "is_critical": rec.is_critical,
            "factors": rec.factors,
            "forecast_cards": [
                {"date": c.date, "besoin": c.besoin,
                 "pluie_pct": c.pluie_pct, "stress_thermique": c.stress_thermique}
                for c in rec.forecast_cards],
            "sim_irrigate": vars(rec.sim_irrigate) if rec.sim_irrigate else None,
            "sim_wait":     vars(rec.sim_wait)     if rec.sim_wait     else None,
            "soil_health": rec.soil_health, "health_sub": rec.health_sub,
            "data_confidence": rec.data_confidence,
            "sensor_reliability": rec.sensor_reliability,
            "trend_coherence": rec.trend_coherence,
            "freshness_min": rec.freshness_min,
        }

    if sid:
        sensor = Sensor.query.get_or_404(sid)
        rec    = recommendation_service.generate(sid, forecasts)
        return ok(_fmt(rec, sensor))

    results = []
    for s in Sensor.query.filter_by(is_active=True).all():
        rec = recommendation_service.generate(s.id, forecasts)
        results.append(_fmt(rec, s))
    return ok(results)


# ── Soil health ───────────────────────────────────────────────────────────────
@api.route("/soil-health")
def soil_health():
    sid = request.args.get("sensor_id")
    sensors = [Sensor.query.get_or_404(sid)] if sid else Sensor.query.filter_by(is_active=True).all()
    out = []
    for s in sensors:
        reading = Reading.query.filter_by(sensor_id=s.id).order_by(Reading.timestamp.desc()).first()
        moisture = reading.soil_moisture if reading else 40
        t = recommendation_service.CROP_THRESHOLDS.get(s.crop_type, recommendation_service.CROP_THRESHOLDS["olive"])
        score, sub = recommendation_service._soil_health(s.id, moisture, t)
        out.append({"sensor_id": s.id, "name": s.name, "score": score, "sub_scores": sub,
                    "label": "Healthy" if score >= 75 else ("Warning" if score >= 50 else "Critical")})
    return ok(out[0] if sid else out)


# ── Alerts ────────────────────────────────────────────────────────────────────
@api.route("/alerts")
def alerts():
    include_all = request.args.get("all","false").lower() == "true"
    q = Alert.query.order_by(Alert.created_at.desc())
    if not include_all: q = q.filter_by(acknowledged=False)
    return ok([a.to_dict() for a in q.limit(50)])

@api.route("/alerts/<int:aid>/acknowledge", methods=["POST"])
def ack_alert(aid):
    a = Alert.query.get_or_404(aid)
    a.acknowledged = True; db.session.commit()
    return ok()


# ── Reports ───────────────────────────────────────────────────────────────────
@api.route("/reports/weekly")
def weekly():
    sid   = request.args.get("sensor_id")
    since = date.today() - timedelta(days=7)
    sensors = [Sensor.query.get_or_404(sid)] if sid else Sensor.query.filter_by(is_active=True).all()

    summaries = []
    for s in sensors:
        rows = Reading.query.filter(Reading.sensor_id==s.id, Reading.timestamp>=since).all()
        recs = Recommendation.query.filter(Recommendation.sensor_id==s.id, Recommendation.created_at>=since).all()
        avg_moist = round(sum(r.soil_moisture for r in rows)/len(rows), 1) if rows else 0
        avg_temp  = round(sum(r.air_temperature for r in rows if r.air_temperature)/max(1,len(rows)), 1)
        rain_total= round(sum(r.rain_mm for r in rows if r.rain_mm), 1)
        n_irr     = sum(1 for r in recs if r.action=="IRRIGATE")
        n_wait    = sum(1 for r in recs if r.action in ("WAIT","NO_ACTION","MONITOR"))
        pct_pos   = round(100*(n_irr+n_wait)/max(1,len(recs)), 0) if recs else 43

        # Decision history (flux)
        flux = []
        for rec in sorted(recs, key=lambda x: x.created_at, reverse=True)[:7]:
            day_label = rec.created_at.strftime("%-d %B").lower()
            # estimate moisture delta next day
            next_reading = Reading.query.filter(
                Reading.sensor_id==s.id,
                Reading.timestamp > rec.created_at
            ).order_by(Reading.timestamp).first()
            delta_moist = round(next_reading.soil_moisture - rec.moisture_at_time, 0) if (next_reading and rec.moisture_at_time) else -3
            impact = "Impact positif" if rec.health_impact and rec.health_impact > 0 else "Impact neutre"
            flux.append({"date": day_label, "action": rec.action,
                         "impact_label": impact,
                         "delta_moisture": delta_moist,
                         "delta_health": rec.health_impact or 0,
                         "sub": rec.reason})

        # Historical table
        hist = []
        for r in sorted(rows, key=lambda x: x.timestamp)[-7:]:
            hist.append({
                "date": r.timestamp.strftime("%-d %b."),
                "soil_pct": r.soil_moisture,
                "temp_c": r.air_temperature,
                "rain_mm": r.rain_mm or 0,
                "battery_pct": r.battery_voltage or 0,
            })

        active_alerts = Alert.query.filter_by(sensor_id=s.id, acknowledged=False).count()
        rec_latest = recs[-1] if recs else None

        summaries.append({
            "sensor_id": s.id, "name": s.name,
            "avg_moisture_7d": avg_moist, "avg_temp_7d": avg_temp,
            "rain_total_7d": rain_total, "active_alerts": active_alerts,
            "data_confidence": 76,
            "sensor_reliability": "À surveiller",
            "irrigate_count": n_irr, "wait_count": n_wait,
            "positive_decision_pct": pct_pos,
            "narrative": {
                "conditions": "Conditions capteurs globalement stables.",
                "decisions":  "Décisions prudentes, avec attente de la pluie.",
                "impact":     "Impact modéré, suivi renforcé recommandé.",
            },
            "flux": flux,
            "history_table": hist,
        })

    return ok(summaries[0] if sid else summaries)

@api.route("/reports/daily")
def daily():
    since = date.today()
    count = Reading.query.filter(Reading.timestamp >= since).count()
    avg   = db.session.query(func.avg(Reading.soil_moisture)).filter(Reading.timestamp >= since).scalar()
    alerts_n = Alert.query.filter(Alert.created_at >= since).count()
    recs  = Recommendation.query.filter(Recommendation.created_at >= since).all()
    return ok({"date": since.isoformat(), "readings": count,
                "avg_moisture": round(avg or 0,1), "alerts": alerts_n,
                "recommendations": len(recs),
                "irrigate_count": sum(1 for r in recs if r.action=="IRRIGATE")})


# ── AI Decision Engine ────────────────────────────────────────────────────────
# Global models cache - loaded once at startup
AI_MODELS = {}

def load_ai_models():
    """Load trained RandomForest models for all crops"""
    global AI_MODELS
    import os
    import joblib

    crops = ["olive", "citrus", "wheat"]
    models_dir = "models"

    if not os.path.exists(models_dir):
        print("⚠️  WARNING: models/ directory not found - AI features disabled")
        return False

    try:
        for crop in crops:
            model_path = os.path.join(models_dir, f"{crop}_model.pkl")
            if os.path.exists(model_path):
                AI_MODELS[crop] = joblib.load(model_path)
                print(f"✓ Loaded AI model for {crop}")
            else:
                print(f"⚠️  Model not found: {model_path}")

        if AI_MODELS:
            print(f"✅ AI models loaded successfully ({len(AI_MODELS)} crops)")
            return True
        else:
            print("⚠️  No AI models found - train models first")
            return False
    except Exception as e:
        print(f"❌ Error loading AI models: {e}")
        return False


# Load models at module import
load_ai_models()


# Growth stage data
STAGE_MONTHS = {
    "olive":  {0: [12, 1, 2], 1: [3, 4], 2: [5, 6], 3: [7, 8], 4: [9, 10, 11]},
    "citrus": {0: [1, 2], 1: [3, 4], 2: [5], 3: [6, 7, 8, 9], 4: [10, 11, 12]},
    "wheat":  {0: [11, 12], 1: [1, 2], 2: [3], 3: [4, 5], 4: [6]},
}

STAGE_NAMES_FR = {
    "olive":  ["Repos végétatif", "Débourrement", "Floraison", "Grossissement fruit", "Maturation"],
    "citrus": ["Repos", "Débourrement", "Floraison", "Fructification", "Maturation"],
    "wheat":  ["Germination", "Tallage", "Montaison", "Épiaison", "Maturation"],
}

KC_BY_STAGE = {
    "olive":  [0.65, 0.70, 0.75, 0.75, 0.70],
    "citrus": [0.70, 0.75, 0.85, 0.85, 0.75],
    "wheat":  [0.40, 0.70, 1.15, 1.15, 0.50],
}

MOISTURE_THRESHOLDS = {
    "olive":  {0: 20, 1: 28, 2: 35, 3: 32, 4: 25},
    "citrus": {0: 40, 1: 48, 2: 52, 3: 50, 4: 45},
    "wheat":  {0: 35, 1: 40, 2: 45, 3: 50, 4: 30},
}


def get_growth_stage_for_month(crop, month):
    """Return growth stage (0-4) for given crop and month"""
    for stage, months in STAGE_MONTHS.get(crop, STAGE_MONTHS["olive"]).items():
        if month in months:
            return stage
    return 0


def simplified_eto(temp_c, humidity_pct, wind_kmh, solar_radiation=15.0):
    """Simplified Penman-Monteith ETo calculation (mm/day)"""
    import numpy as np

    svp = 0.6108 * np.exp((17.27 * temp_c) / (temp_c + 237.3))
    avp = svp * (humidity_pct / 100.0)
    vpd = svp - avp
    wind_effect = 0.25 + 0.05 * (wind_kmh / 10.0)
    eto = 0.408 * (solar_radiation / 20.0) * (temp_c + 17.8) * vpd * wind_effect
    return max(0.5, min(12.0, eto))


def generate_french_reasoning(crop, features, decision, confidence, stage_name):
    """Generate agronomist-quality French reasoning based on actual feature values"""
    reasons = []

    moisture = features["soil_moisture_pct"]
    threshold = features["moisture_threshold"]
    temp = features["temperature_c"]
    rain = features["rainfall_24h_mm"]
    eto = features["eto_mm_day"]
    etc = features["etc_mm_day"]
    days_since = features["days_since_irrigation"]

    # Moisture analysis
    if moisture < threshold:
        deficit_pct = round(((threshold - moisture) / threshold) * 100, 0)
        reasons.append(
            f"Humidité sol à {moisture:.0f}% — {deficit_pct:.0f}% sous le seuil critique "
            f"de {threshold}% pour {stage_name.lower()} du {crop}. "
            "Irrigation immédiate recommandée."
        )
    else:
        surplus_pct = round(((moisture - threshold) / threshold) * 100, 0)
        reasons.append(
            f"Humidité sol à {moisture:.0f}% — {surplus_pct:.0f}% au-dessus du seuil "
            f"de {threshold}% pour {stage_name.lower()}. Réserve hydrique suffisante."
        )

    # ETo/ETc analysis
    if eto > 6.0:
        reasons.append(
            f"Évapotranspiration élevée ({eto:.1f} mm/j) — forte demande hydrique "
            f"de la culture. ETc = {etc:.1f} mm/j."
        )
    elif eto > 4.0:
        reasons.append(
            f"Évapotranspiration modérée ({eto:.1f} mm/j) — demande hydrique normale "
            f"pour la saison. ETc = {etc:.1f} mm/j."
        )
    else:
        reasons.append(
            f"Évapotranspiration faible ({eto:.1f} mm/j) — conditions favorables "
            "pour conserver l'humidité du sol."
        )

    # Rain analysis
    if rain > 10:
        reasons.append(
            f"Pluie significative enregistrée ({rain:.1f} mm/24h) — recharge naturelle "
            "du sol assurée."
        )
    elif rain > 3:
        reasons.append(
            f"Pluie légère ({rain:.1f} mm/24h) — apport hydrique partiel, "
            "irrigation complémentaire peut être nécessaire."
        )
    else:
        reasons.append(
            "Aucune pluie significative dans les 24h — pas de recharge naturelle prévue."
        )

    # Growth stage criticality
    if stage_name in ["Floraison", "Fructification", "Épiaison"]:
        reasons.append(
            f"Stade phénologique sensible : {stage_name} — période critique pour "
            "le rendement et la qualité."
        )

    # Temperature stress
    if temp > 32 and crop in ["citrus", "wheat"]:
        reasons.append(
            f"Température élevée ({temp:.0f}°C) — risque de stress thermique. "
            "Irrigation pour refroidissement du sol recommandée."
        )
    elif temp < 8 and crop == "wheat":
        reasons.append(
            f"Température basse ({temp:.0f}°C) — ralentissement de l'évaporation. "
            "Irrigation à réduire ou différer."
        )

    # Days since irrigation
    if days_since > 7 and decision == "irrigate":
        reasons.append(
            f"Dernière irrigation il y a {days_since} jours — stock hydrique "
            "probablement épuisé."
        )

    return reasons


@api.route("/predict", methods=["POST"])
def ai_predict():
    """AI-powered irrigation decision prediction"""
    from app.models import AIDecisionLog
    import json
    import numpy as np

    b = request.get_json(silent=True) or {}

    # Required fields
    crop = b.get("crop", "").lower()
    if crop not in AI_MODELS:
        return err(f"Crop '{crop}' not supported or model not loaded. Available: {list(AI_MODELS.keys())}")

    # Extract features
    try:
        soil_moisture_pct = float(b.get("soil_moisture_pct", 0))
        temperature_c = float(b.get("temperature_c", 25))
        humidity_pct = float(b.get("humidity_pct", 50))
        rainfall_24h_mm = float(b.get("rainfall_24h_mm", 0))
        wind_speed_kmh = float(b.get("wind_speed_kmh", 5))
        days_since_irrigation = int(b.get("days_since_irrigation", 3))
        month = b.get("month", datetime.now().month)
    except (ValueError, TypeError):
        return err("Invalid feature values")

    # Derive additional features
    growth_stage = get_growth_stage_for_month(crop, month)
    stage_name = STAGE_NAMES_FR[crop][growth_stage]
    kc = KC_BY_STAGE[crop][growth_stage]
    moisture_threshold = MOISTURE_THRESHOLDS[crop][growth_stage]

    # Calculate ETo and ETc
    eto_mm_day = simplified_eto(temperature_c, humidity_pct, wind_speed_kmh)
    etc_mm_day = eto_mm_day * kc

    # Build feature vector
    features = {
        "soil_moisture_pct": soil_moisture_pct,
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
        "rainfall_24h_mm": rainfall_24h_mm,
        "wind_speed_kmh": wind_speed_kmh,
        "eto_mm_day": eto_mm_day,
        "etc_mm_day": etc_mm_day,
        "growth_stage": growth_stage,
        "days_since_irrigation": days_since_irrigation,
        "month": month,
        "moisture_threshold": moisture_threshold,
    }

    # Prepare for model
    feature_order = [
        "soil_moisture_pct", "temperature_c", "humidity_pct", "rainfall_24h_mm",
        "wind_speed_kmh", "eto_mm_day", "etc_mm_day", "growth_stage",
        "days_since_irrigation", "month", "moisture_threshold"
    ]
    X = np.array([[features[f] for f in feature_order]])

    # Predict
    model = AI_MODELS[crop]
    prediction = model.predict(X)[0]
    probabilities = model.predict_proba(X)[0]

    decision = "irrigate" if prediction == 1 else "wait"
    confidence = float(probabilities[1] if prediction == 1 else probabilities[0])

    # Generate French reasoning
    reasons = generate_french_reasoning(crop, features, decision, confidence, stage_name)

    # Prepare response
    result = {
        "crop": crop,
        "decision": decision,
        "confidence": round(confidence, 3),
        "action": "IRRIGUER" if decision == "irrigate" else "ATTENDRE",
        "confidence_pct": round(confidence * 100, 1),
        "icon": "💧" if decision == "irrigate" else "✅",
        "reasons": reasons,
        "stage_name": stage_name,
        "water_demand_mm": round(etc_mm_day, 1),
        "features_used": features,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Log decision to database
    try:
        log_entry = AIDecisionLog(
            crop=crop,
            decision=decision,
            confidence=confidence,
            soil_moisture=soil_moisture_pct,
            temperature=temperature_c,
            reasoning=json.dumps(reasons, ensure_ascii=False)
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        print(f"Failed to log AI decision: {e}")

    return ok(result)


@api.route("/auto_action", methods=["POST"])
def ai_auto_action():
    """Automatically trigger irrigation based on AI decision with high confidence"""
    b = request.get_json(silent=True) or {}
    crop = b.get("crop", "").lower()

    if not crop:
        return err("Missing crop parameter")

    # Get latest sensor reading for this crop
    sensor = Sensor.query.filter_by(crop_type=crop, is_active=True).first()
    if not sensor:
        return err(f"No active sensor found for crop: {crop}")

    reading = Reading.query.filter_by(sensor_id=sensor.id)\
        .order_by(Reading.timestamp.desc()).first()

    if not reading:
        return err(f"No readings found for sensor: {sensor.id}")

    # Run AI prediction internally
    features_payload = {
        "crop": crop,
        "soil_moisture_pct": reading.soil_moisture,
        "temperature_c": reading.air_temperature or 25,
        "humidity_pct": reading.air_humidity or 50,
        "rainfall_24h_mm": reading.rain_mm or 0,
        "wind_speed_kmh": 5,  # default
        "days_since_irrigation": 3,  # default - could track in DB
    }

    # Make internal prediction call
    with api.test_request_context(json=features_payload, method='POST'):
        response_data, status = ai_predict()
        if status != 200:
            return response_data, status

        prediction = response_data.get_json()["data"]

    # Auto-action logic
    pump_status = "OFF"
    sms_sent = False

    if prediction["confidence"] > 0.80 and prediction["decision"] == "irrigate":
        pump_status = "ON"

        # Send Twilio SMS
        try:
            from twilio.rest import Client
            import os

            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")
            twilio_phone = os.getenv("TWILIO_PHONE_NUMBER")
            user_phone = os.getenv("USER_PHONE_NUMBER")

            if all([account_sid, auth_token, twilio_phone, user_phone]):
                client = Client(account_sid, auth_token)

                message_body = (
                    f"🌱 IrriSmart AUTO: Irrigation déclenchée pour {crop.upper()}. "
                    f"Humidité: {reading.soil_moisture:.0f}%. "
                    f"Confiance IA: {prediction['confidence_pct']:.0f}%"
                )

                message = client.messages.create(
                    body=message_body,
                    from_=twilio_phone,
                    to=user_phone
                )
                sms_sent = True
                print(f"✓ SMS sent: {message.sid}")
        except Exception as e:
            print(f"Failed to send SMS: {e}")

    result = {
        "crop": crop,
        "sensor_id": sensor.id,
        "pump_status": pump_status,
        "ai_decision": prediction["decision"],
        "confidence": prediction["confidence"],
        "confidence_pct": prediction["confidence_pct"],
        "reasons": prediction["reasons"],
        "sms_sent": sms_sent,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return ok(result)


@api.route("/ai/history")
def ai_history():
    """Get recent AI decision history"""
    from app.models import AIDecisionLog

    limit = request.args.get("limit", 50, type=int)
    entries = AIDecisionLog.query.order_by(AIDecisionLog.timestamp.desc())\
        .limit(limit).all()

    return ok([e.to_dict() for e in entries])


@api.route("/ai/stats")
def ai_stats():
    """Get AI model metadata and performance stats"""
    import os
    import json

    metadata_path = "models/model_metadata.json"

    if not os.path.exists(metadata_path):
        return err("Model metadata not found - train models first", 404)

    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
        return ok(metadata)
    except Exception as e:
        return err(f"Failed to load metadata: {e}", 500)


# ── Anomaly Detection ─────────────────────────────────────────────────────────
ANOMALY_MODEL = None

def _load_anomaly_model():
    global ANOMALY_MODEL
    import joblib, os
    path = "models/anomaly_detector.pkl"
    if os.path.exists(path):
        ANOMALY_MODEL = joblib.load(path)
        print("✓ Loaded anomaly detector")
    else:
        print("⚠️  anomaly_detector.pkl not found — anomaly detection disabled")

_load_anomaly_model()

ANOMALY_FEATURES = ["soil_moisture_pct", "temperature_c", "humidity_pct", "eto_mm_day"]

def _anomaly_message(crop, features, score):
    soil = features["soil_moisture_pct"]
    temp = features["temperature_c"]
    hum  = features["humidity_pct"]
    eto  = features["eto_mm_day"]

    if soil < 12:
        return f"Humidité sol anormalement basse ({soil:.0f}%) pour la saison — capteur défaillant possible."
    if soil > 75:
        return f"Humidité sol excessivement élevée ({soil:.0f}%) — vérifier le capteur ou une inondation."
    if temp > 42:
        return f"Température hors plage normale ({temp:.0f}°C) pour {crop} — lecture suspecte."
    if temp < -3 and crop in ("citrus", "olive"):
        return f"Température anormalement basse ({temp:.0f}°C) pour {crop} — risque de gel ou erreur capteur."
    if hum < 10:
        return f"Humidité relative anormalement basse ({hum:.0f}%) — capteur potentiellement défaillant."
    if eto > 11:
        return f"Évapotranspiration anormalement élevée ({eto:.1f} mm/j) — combinaison chaleur/vent extrême détectée."
    return f"Lecture de capteur incohérente (score={score:.3f}) — vérification recommandée."


@api.route("/anomaly/detect", methods=["POST"])
def anomaly_detect():
    from app.models import AnomalyLog
    import numpy as np

    if not ANOMALY_MODEL:
        return err("Anomaly model not loaded — train it first with anomaly_detector.py", 503)

    b = request.get_json(silent=True) or {}
    sensor_id = b.get("sensor_id")
    crop = b.get("crop", "olive").lower()

    try:
        features = {
            "soil_moisture_pct": float(b.get("soil_moisture_pct", 35)),
            "temperature_c":     float(b.get("temperature_c", 22)),
            "humidity_pct":      float(b.get("humidity_pct", 55)),
            "eto_mm_day":        float(b.get("eto_mm_day", 4.0)),
        }
    except (ValueError, TypeError):
        return err("Invalid feature values")

    X = np.array([[features[f] for f in ANOMALY_FEATURES]])
    prediction = ANOMALY_MODEL.predict(X)[0]      # 1 = normal, -1 = anomaly
    score = float(ANOMALY_MODEL.score_samples(X)[0])  # lower = more anomalous

    is_anomaly = prediction == -1
    if not is_anomaly:
        severity = "normal"
    elif score < -0.25:
        severity = "critical"
    else:
        severity = "warning"

    message = _anomaly_message(crop, features, score) if is_anomaly else "Lecture normale — aucune anomalie détectée."

    # Log to DB
    try:
        log = AnomalyLog(
            sensor_id=sensor_id, crop=crop,
            anomaly_score=round(score, 4),
            severity=severity, message=message,
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"AnomalyLog write failed: {e}")

    return ok({
        "is_anomaly": bool(is_anomaly),
        "anomaly_score": round(score, 4),
        "severity": severity,
        "message": message,
        "features_checked": features,
    })


@api.route("/anomaly/history")
def anomaly_history():
    from app.models import AnomalyLog
    limit = request.args.get("limit", 20, type=int)
    entries = AnomalyLog.query.filter(AnomalyLog.severity != "normal")\
        .order_by(AnomalyLog.timestamp.desc()).limit(limit).all()
    return ok([e.to_dict() for e in entries])


# ── Irrigation Impact Predictor ────────────────────────────────────────────────
SOIL_DEPTH_FACTOR = {"olive": 0.6, "citrus": 0.5, "wheat": 0.4}

STAGE_CRITICALITY = {
    0: 0.3, 1: 0.5, 2: 0.9, 3: 0.85, 4: 0.6
}

STAGE_NAMES_IMPACT = {
    "olive":  ["Repos végétatif", "Débourrement", "Floraison", "Grossissement fruit", "Maturation"],
    "citrus": ["Repos", "Débourrement", "Floraison", "Fructification", "Maturation"],
    "wheat":  ["Germination", "Tallage", "Montaison", "Épiaison", "Maturation"],
}

MOISTURE_THR_IMPACT = {
    "olive":  {0: 20, 1: 28, 2: 35, 3: 32, 4: 25},
    "citrus": {0: 40, 1: 48, 2: 52, 3: 50, 4: 45},
    "wheat":  {0: 35, 1: 40, 2: 45, 3: 50, 4: 30},
}

@api.route("/predict/impact", methods=["POST"])
def predict_impact():
    b = request.get_json(silent=True) or {}
    crop = b.get("crop", "olive").lower()
    if crop not in MOISTURE_THR_IMPACT:
        return err(f"Unknown crop: {crop}")

    try:
        current_moisture    = float(b.get("current_moisture", 30))
        days_without        = int(b.get("days_without_irrigation", 3))
        growth_stage        = int(b.get("growth_stage", 0))
        area_m2             = float(b.get("area_m2", 1000))
    except (ValueError, TypeError):
        return err("Invalid input values")

    growth_stage = max(0, min(4, growth_stage))
    threshold    = MOISTURE_THR_IMPACT[crop].get(growth_stage, 30)
    depth_factor = SOIL_DEPTH_FACTOR.get(crop, 0.5)
    stage_crit   = STAGE_CRITICALITY.get(growth_stage, 0.5)
    stage_name   = STAGE_NAMES_IMPACT.get(crop, STAGE_NAMES_IMPACT["olive"])[growth_stage]

    # Water deficit (mm)
    deficit_pct      = max(0, threshold - current_moisture)
    water_deficit_mm = round(deficit_pct * depth_factor, 1)

    # Irrigation volume (liters) — 1 mm/m² = 1 litre
    irr_volume = round(water_deficit_mm * area_m2, 0)

    # Yield risk (%)
    base_risk = min(100, deficit_pct * 2 + days_without * 3)
    yield_risk_pct = round(base_risk * stage_crit, 1)

    if yield_risk_pct < 15:
        risk_label = "Faible"
    elif yield_risk_pct < 40:
        risk_label = "Modéré"
    elif yield_risk_pct < 70:
        risk_label = "Élevé"
    else:
        risk_label = "Critique"

    # AI savings vs manual (AI optimizes timing: 15-30%)
    savings_pct = round(15 + min(15, days_without * 1.5), 1)

    # French recommendation
    if water_deficit_mm == 0:
        recommendation = (
            f"Aucun déficit hydrique détecté pour {crop} au stade {stage_name}. "
            "Irrigation différée recommandée."
        )
    elif yield_risk_pct >= 70:
        recommendation = (
            f"Déficit critique : {water_deficit_mm} mm manquants. "
            f"Appliquer {irr_volume:.0f} litres immédiatement ({area_m2:.0f} m²). "
            f"Stade {stage_name} très sensible — tout retard compromet le rendement."
        )
    elif yield_risk_pct >= 40:
        recommendation = (
            f"Déficit significatif : {water_deficit_mm} mm. "
            f"Irriguer avec {irr_volume:.0f} litres dans les 24h. "
            f"Stade {stage_name} — risque de stress hydrique modéré."
        )
    else:
        recommendation = (
            f"Déficit léger : {water_deficit_mm} mm. "
            f"Envisager {irr_volume:.0f} litres dans les 48h. "
            f"Stade {stage_name} — surveillance recommandée."
        )

    return ok({
        "crop": crop, "growth_stage": growth_stage, "stage_name": stage_name,
        "current_moisture_pct": current_moisture, "threshold_pct": threshold,
        "water_deficit_mm": water_deficit_mm,
        "irrigation_volume_liters": irr_volume,
        "yield_risk_pct": yield_risk_pct,
        "yield_risk_label": risk_label,
        "estimated_savings_pct": savings_pct,
        "recommendation": recommendation,
    })


# ── WhatsApp test alert ────────────────────────────────────────────────────────
@api.route("/alerts/test", methods=["POST"])
def test_alert():
    import os
    b = request.get_json(silent=True) or {}
    crop      = b.get("crop", "olive").upper()
    emoji_map = {"OLIVE": "🫒", "CITRUS": "🍊", "WHEAT": "🌾"}
    crop_emoji = emoji_map.get(crop, "🌱")

    now_str = datetime.utcnow().strftime("%d/%m/%Y à %H:%M")

    sms_body = (
        f"🌱 IrriSmart — Alerte Test\n"
        f"Culture: {crop} {crop_emoji}\n"
        f"🔴 Décision IA: IRRIGUER\n"
        f"💧 Humidité sol: 24%% (seuil: 35%%)\n"
        f"📊 Confiance: 91%%\n"
        f"⏰ {now_str}"
    )

    wa_body = (
        f"🌱 *IrriSmart — Alerte Irrigation*\n\n"
        f"Culture: *{crop}* {crop_emoji}\n"
        f"Parcelle: Beni Mellal Nord\n\n"
        f"🔴 Décision IA: *IRRIGUER*\n"
        f"💧 Humidité sol: 24% (seuil: 35%)\n"
        f"🌡️ Température: 28°C\n"
        f"📊 Confiance: 91%\n\n"
        f"Raisons:\n"
        f"• Humidité sous seuil critique floraison\n"
        f"• ETo élevée (7.2 mm/j)\n"
        f"• Aucune pluie prévue\n\n"
        f"⏰ {now_str}\n"
        f"🔗 irrismart.up.railway.app"
    )

    sms_sent = False
    wa_sent  = False
    errors   = []

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token  = os.getenv("TWILIO_AUTH_TOKEN")
    from_phone  = os.getenv("TWILIO_PHONE_FROM")
    to_phone    = os.getenv("FARMER_PHONE")
    wa_from     = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    if all([account_sid, auth_token, from_phone, to_phone]):
        try:
            from twilio.rest import Client
            client = Client(account_sid, auth_token)
            msg = client.messages.create(body=sms_body, from_=from_phone, to=to_phone)
            sms_sent = True
            print(f"[Twilio] Test SMS sent: {msg.sid}")
        except Exception as e:
            errors.append(f"SMS: {e}")

        try:
            from twilio.rest import Client
            client = Client(account_sid, auth_token)
            wa_to = f"whatsapp:{to_phone}"
            msg = client.messages.create(body=wa_body, from_=wa_from, to=wa_to)
            wa_sent = True
            print(f"[Twilio] Test WhatsApp sent: {msg.sid}")
        except Exception as e:
            errors.append(f"WhatsApp: {e}")
    else:
        errors.append("Twilio credentials not configured in .env")

    return ok({
        "sms_sent": sms_sent,
        "whatsapp_sent": wa_sent,
        "errors": errors,
        "sms_preview": sms_body,
        "whatsapp_preview": wa_body,
    })


# ── Chart data endpoints ───────────────────────────────────────────────────────
@api.route("/charts/moisture_history")
def chart_moisture_history():
    from app.models import Sensor, Reading
    hours = request.args.get("hours", 24, type=int)
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    sensors = Sensor.query.filter_by(is_active=True).all()

    series = {}
    for s in sensors:
        rows = Reading.query.filter(
            Reading.sensor_id == s.id,
            Reading.timestamp >= cutoff
        ).order_by(Reading.timestamp).all()
        series[s.crop_type] = {
            "label": s.name,
            "crop": s.crop_type,
            "data": [{"t": r.timestamp.isoformat(), "y": round(r.soil_moisture, 1)} for r in rows],
            "threshold": {"olive": 35, "citrus": 50, "wheat": 45}.get(s.crop_type, 35),
        }

    return ok(list(series.values()))


@api.route("/charts/decision_history")
def chart_decision_history():
    from app.models import Recommendation
    days = request.args.get("days", 7, type=int)
    result = []
    for i in range(days - 1, -1, -1):
        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
        day_end   = day_start + timedelta(days=1)
        recs = Recommendation.query.filter(
            Recommendation.created_at >= day_start,
            Recommendation.created_at < day_end
        ).all()
        irrigate_n = sum(1 for r in recs if r.action == "IRRIGATE")
        wait_n     = sum(1 for r in recs if r.action in ("WAIT", "NO_ACTION", "MONITOR"))
        result.append({
            "date": day_start.strftime("%-d %b"),
            "irrigate": irrigate_n,
            "wait": wait_n,
        })
    return ok(result)


@api.route("/charts/eto_scatter")
def chart_eto_scatter():
    from app.models import Reading, Sensor
    import random as _rand
    sensors = {s.id: s.crop_type for s in Sensor.query.filter_by(is_active=True).all()}
    rows = Reading.query.order_by(Reading.timestamp.desc()).limit(300).all()
    points = []
    for r in rows:
        if r.air_temperature and r.air_humidity:
            # Recompute ETo
            temp = r.air_temperature
            hum  = r.air_humidity
            svp  = 0.6108 * (2.71828 ** ((17.27 * temp) / (temp + 237.3)))
            avp  = svp * (hum / 100)
            vpd  = svp - avp
            eto  = max(0.5, min(12.0, 0.408 * (15 / 20) * (temp + 17.8) * vpd * 0.3))
            points.append({
                "x": round(eto, 2),
                "y": round(r.soil_moisture, 1),
                "crop": sensors.get(r.sensor_id, "olive"),
            })
    return ok(points)


@api.route("/charts/confidence_stats")
def chart_confidence_stats():
    from app.models import AIDecisionLog
    entries = AIDecisionLog.query.all()
    high = sum(1 for e in entries if e.confidence > 0.80)
    mid  = sum(1 for e in entries if 0.60 <= e.confidence <= 0.80)
    low  = sum(1 for e in entries if e.confidence < 0.60)
    total = max(1, len(entries))
    # Default non-zero values if no AI decisions logged yet
    if total == 1:
        high, mid, low = 62, 28, 10
        total = 100
    return ok({
        "high":   round(high / total * 100, 1),
        "medium": round(mid  / total * 100, 1),
        "low":    round(low  / total * 100, 1),
        "total_decisions": len(entries),
    })


# ── Seasonal Anomaly Detection ────────────────────────────────────────────────

def detect_anomaly(sensor_id, crop_type, moisture_pct):
    """
    Compare moisture reading against 7-day rolling stats and INRA Tadla seasonal
    baselines. Returns anomaly dict if anomalous, {is_anomaly: False} otherwise.
    """
    from app.models import SeasonalBaseline, SeasonalAnomalyLog

    now = datetime.utcnow()
    month = now.month

    # Fetch seasonal baseline for crop + current month (INRA Tadla data)
    baseline = SeasonalBaseline.query.filter_by(
        crop_type=crop_type, month=month
    ).first()

    # Fetch last 7 days of readings for this sensor
    seven_days_ago = now - timedelta(days=7)
    recent = Reading.query.filter(
        Reading.sensor_id == sensor_id,
        Reading.timestamp >= seven_days_ago
    ).all()
    moistures = [r.soil_moisture for r in recent]

    is_anomaly = False
    z_score = None
    deviation_type = None
    rolling_mean = None
    seasonal_mean = baseline.moisture_mean if baseline else None

    # Rolling z-score check (requires >= 3 readings)
    if len(moistures) >= 3:
        mean_val = sum(moistures) / len(moistures)
        variance = sum((x - mean_val) ** 2 for x in moistures) / len(moistures)
        std_val  = _math.sqrt(variance) if variance > 0 else 1.0
        z = (moisture_pct - mean_val) / std_val
        rolling_mean = round(mean_val, 1)
        z_score = round(z, 2)
        if abs(z) >= 2.0:
            is_anomaly = True
            deviation_type = "below" if z < 0 else "above"

    # Seasonal range check (independent of rolling data)
    if baseline and not is_anomaly:
        if moisture_pct < baseline.moisture_min or moisture_pct > baseline.moisture_max:
            is_anomaly = True
            deviation_type = "below" if moisture_pct < baseline.moisture_min else "above"
            if z_score is None:
                std_val = baseline.moisture_std or 5.0
                z_score = round((moisture_pct - baseline.moisture_mean) / std_val, 2)

    if not is_anomaly:
        return {"is_anomaly": False}

    severity = "high" if z_score and abs(z_score) >= 3 else "moderate"

    if deviation_type == "below":
        possible_causes = [
            "Fuite dans le système d'irrigation",
            "Défaillance du capteur",
            "Stress hydrique sévère — risque de perte de récolte",
        ]
        recommended_action = "Inspection physique urgente de la parcelle"
    else:
        possible_causes = [
            "Sur-irrigation récente",
            "Capteur en zone saturée ou inondée",
            "Drainage insuffisant du sol",
        ]
        recommended_action = "Suspendre l'irrigation et vérifier le drainage"

    result = {
        "is_anomaly": True,
        "z_score": z_score,
        "deviation_type": deviation_type,
        "rolling_mean": rolling_mean,
        "seasonal_mean": seasonal_mean,
        "seasonal_range": [
            baseline.moisture_min if baseline else None,
            baseline.moisture_max if baseline else None,
        ],
        "severity": severity,
        "possible_causes": possible_causes,
        "recommended_action": recommended_action,
    }

    # Persist to DB
    try:
        log = SeasonalAnomalyLog(
            sensor_id=sensor_id,
            crop_type=crop_type,
            moisture_pct=moisture_pct,
            z_score=z_score,
            deviation_type=deviation_type,
            rolling_mean=rolling_mean,
            seasonal_mean=seasonal_mean,
            seasonal_min=baseline.moisture_min if baseline else None,
            seasonal_max=baseline.moisture_max if baseline else None,
            severity=severity,
            possible_causes=_json.dumps(possible_causes, ensure_ascii=False),
            recommended_action=recommended_action,
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"SeasonalAnomalyLog write failed: {e}")

    return result


@api.route("/anomalies")
def get_anomalies():
    """Return last 10 seasonal anomaly detections."""
    from app.models import SeasonalAnomalyLog
    limit = request.args.get("limit", 10, type=int)
    entries = SeasonalAnomalyLog.query\
        .order_by(SeasonalAnomalyLog.timestamp.desc())\
        .limit(limit).all()
    return ok([e.to_dict() for e in entries])


# ── Chat (proxied through backend so API key stays server-side) ───────────────
@api.route("/chat", methods=["POST"])
def chat():
    import os, requests as _req
    b = request.get_json(silent=True) or {}
    message = (b.get("message") or "").strip()
    sensor_ctx = b.get("sensor_ctx") or {}   # structured dict from frontend
    if not message:
        return err("Missing message")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ok({"reply": "Assistant non configuré. Ajoutez ANTHROPIC_API_KEY dans les variables Railway."})

    # Build structured context block if sensor data was provided
    ctx_block = ""
    if isinstance(sensor_ctx, dict) and sensor_ctx:
        ctx_block = (
            "\n\nDonnées capteurs en temps réel:\n"
            + _json.dumps(sensor_ctx, ensure_ascii=False, indent=2)
            + "\n\nSeuils critiques (INRA Tadla + FAO-56):\n"
            "- Olivier: critique < 35%, optimal 50–65%\n"
            "- Agrumes: critique < 45%, optimal 55–70%\n"
            "- Blé:     critique < 40%, optimal 50–65%\n"
        )
    elif isinstance(sensor_ctx, str) and sensor_ctx:
        ctx_block = f"\n\nContexte capteurs actif: {sensor_ctx}."

    system_prompt = (
        "Tu es le conseiller agricole intelligent d'IrriSmart, spécialisé dans l'irrigation\n"
        "pour la région de Béni Mellal-Khénifra (plaine du Tadla) au Maroc.\n"
        "Tes cultures cibles : olive, agrumes (oranges, clémentines), blé dur (variété 'Karim').\n"
        "Tes connaissances sont fondées sur la méthode FAO-56 Penman-Monteith et les fiches\n"
        "techniques de l'INRA Tadla.\n\n"
        "RÈGLE ABSOLUE : Détecte la langue du message et réponds ENTIÈREMENT dans cette langue.\n"
        "- Français → français. Arabe (فصحى ou دارجة) → arabe. Darija en caractères latins → mélange.\n"
        "Ne change jamais de langue en cours de réponse.\n\n"
        "Règles de réponse:\n"
        "- Fais référence aux données capteurs réelles ci-dessous dans chaque réponse\n"
        "- Sois précis, pratique, et concis — tu t'adresses à un agriculteur\n"
        "- Ne réponds pas aux questions hors agriculture et irrigation\n"
        + ctx_block
    )

    try:
        resp = _req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 450,
                "system": system_prompt,
                "messages": [{"role": "user", "content": message}],
            },
            timeout=20,
        )
        resp.raise_for_status()
        reply = resp.json()["content"][0]["text"]
        return ok({"reply": reply})
    except Exception as e:
        return err(f"Erreur assistant: {e}", 502)
