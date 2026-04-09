from flask import Blueprint, request, jsonify
from datetime import datetime, date, timedelta
from sqlalchemy import func
from app import db
from app.models import Sensor, Reading, WeatherCache, Recommendation, Alert
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
                rain_mm=b.get("rain_mm", 0))
    s.battery_level = float(bat)
    db.session.add(r)
    db.session.commit()

    # Check for alert conditions after every new reading
    alert_service.check_and_alert(s.id, r.soil_moisture, r.battery_voltage, r.air_temperature, r.timestamp)

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
