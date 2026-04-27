from datetime import datetime
from app import db

class Sensor(db.Model):
    __tablename__ = "sensors"
    id           = db.Column(db.String,  primary_key=True)
    name         = db.Column(db.String,  nullable=False)
    crop_type    = db.Column(db.String,  nullable=False)   # olive|citrus|wheat|alfalfa|beet
    latitude     = db.Column(db.Float)
    longitude    = db.Column(db.Float)
    installed_at = db.Column(db.DateTime, default=datetime.utcnow)
    battery_level= db.Column(db.Float,   default=100.0)
    is_active    = db.Column(db.Boolean, default=True)
    flow_rate    = db.Column(db.Float,   default=5.0)
    area_ha      = db.Column(db.Float,   default=1.0)
    soil_type    = db.Column(db.String,  default="limoneux")

    readings        = db.relationship("Reading",        backref="sensor", lazy=True, order_by="Reading.timestamp")
    recommendations = db.relationship("Recommendation", backref="sensor", lazy=True, order_by="Recommendation.created_at")
    alerts          = db.relationship("Alert",          backref="sensor", lazy=True)

    def to_dict(self):
        latest = Reading.query.filter_by(sensor_id=self.id).order_by(Reading.timestamp.desc()).first()
        return {
            "id": self.id, "name": self.name, "crop_type": self.crop_type,
            "latitude": self.latitude, "longitude": self.longitude,
            "battery_level": self.battery_level, "is_active": self.is_active,
            "flow_rate": self.flow_rate, "area_ha": self.area_ha, "soil_type": self.soil_type,
            "installed_at": self.installed_at.isoformat(),
            "latest_reading": latest.to_dict() if latest else None,
        }


class Reading(db.Model):
    __tablename__ = "readings"
    id              = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sensor_id       = db.Column(db.String,  db.ForeignKey("sensors.id"), nullable=False, index=True)
    timestamp       = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    soil_moisture    = db.Column(db.Float,   nullable=False)
    air_temperature  = db.Column(db.Float)
    air_humidity     = db.Column(db.Float)
    battery_voltage  = db.Column(db.Float)
    rain_mm          = db.Column(db.Float,   default=0.0)
    soil_temperature = db.Column(db.Float)
    ph_level         = db.Column(db.Float)

    def to_dict(self):
        return {
            "id": self.id, "sensor_id": self.sensor_id,
            "timestamp": self.timestamp.isoformat(),
            "soil_moisture": self.soil_moisture,
            "air_temperature": self.air_temperature,
            "air_humidity": self.air_humidity,
            "battery_voltage": self.battery_voltage,
            "rain_mm": self.rain_mm,
            "soil_temperature": self.soil_temperature,
            "ph_level": self.ph_level,
        }


class WeatherCache(db.Model):
    __tablename__ = "weather_cache"
    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fetched_at       = db.Column(db.DateTime, default=datetime.utcnow)
    forecast_date    = db.Column(db.Date,    nullable=False, unique=True)
    temp_max         = db.Column(db.Float)
    temp_min         = db.Column(db.Float)
    precipitation_mm = db.Column(db.Float,   default=0)
    precipitation_prob = db.Column(db.Float, default=0)   # 0-100 %
    wind_speed_kmh   = db.Column(db.Float)
    humidity_percent = db.Column(db.Float)

    def to_dict(self):
        return {
            "forecast_date": self.forecast_date.isoformat(),
            "temp_max": self.temp_max, "temp_min": self.temp_min,
            "precipitation_mm": self.precipitation_mm,
            "precipitation_prob": self.precipitation_prob,
            "wind_speed_kmh": self.wind_speed_kmh,
            "humidity_percent": self.humidity_percent,
            "fetched_at": self.fetched_at.isoformat(),
        }


class Recommendation(db.Model):
    __tablename__ = "recommendations"
    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sensor_id        = db.Column(db.String,  db.ForeignKey("sensors.id"), nullable=False)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    action           = db.Column(db.String,  nullable=False)   # IRRIGATE|WAIT|NO_ACTION|MONITOR
    duration_minutes = db.Column(db.Integer, default=0)
    reason           = db.Column(db.String)
    confidence       = db.Column(db.Float,   default=80.0)     # percent
    acknowledged     = db.Column(db.Boolean, default=False)
    moisture_at_time = db.Column(db.Float)
    health_impact    = db.Column(db.Integer, default=0)        # +/- on soil health

    def to_dict(self):
        return {
            "id": self.id, "sensor_id": self.sensor_id,
            "created_at": self.created_at.isoformat(),
            "action": self.action, "duration_minutes": self.duration_minutes,
            "reason": self.reason, "confidence": self.confidence,
            "acknowledged": self.acknowledged,
            "moisture_at_time": self.moisture_at_time,
            "health_impact": self.health_impact,
        }


class Alert(db.Model):
    __tablename__ = "alerts"
    TYPES = ("LOW_MOISTURE","HIGH_TEMP","FROST_WARNING","LOW_BATTERY","RAIN_EXPECTED","SENSOR_OFFLINE","TREND_CHANGE")
    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sensor_id    = db.Column(db.String,  db.ForeignKey("sensors.id"))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    type         = db.Column(db.String,  nullable=False)
    message      = db.Column(db.String,  nullable=False)
    severity     = db.Column(db.String,  default="info")   # info|warning|critical
    sent_sms     = db.Column(db.Boolean, default=False)
    acknowledged = db.Column(db.Boolean, default=False)
    # impact tags shown in the demo alert card
    decision_impact   = db.Column(db.String, default="Moyen")
    soil_health_impact= db.Column(db.String, default="Moyen")
    yield_risk        = db.Column(db.String, default="Faible")

    def to_dict(self):
        return {
            "id": self.id, "sensor_id": self.sensor_id,
            "created_at": self.created_at.isoformat(),
            "type": self.type, "message": self.message, "severity": self.severity,
            "sent_sms": self.sent_sms, "acknowledged": self.acknowledged,
            "decision_impact": self.decision_impact,
            "soil_health_impact": self.soil_health_impact,
            "yield_risk": self.yield_risk,
        }


class AnomalyLog(db.Model):
    __tablename__ = "anomaly_log"
    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sensor_id     = db.Column(db.String,  db.ForeignKey("sensors.id"))
    crop          = db.Column(db.String)
    anomaly_score = db.Column(db.Float,   nullable=False)   # negative = more anomalous
    severity      = db.Column(db.String,  default="normal") # normal|warning|critical
    message       = db.Column(db.Text)
    timestamp     = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id, "sensor_id": self.sensor_id, "crop": self.crop,
            "anomaly_score": self.anomaly_score, "severity": self.severity,
            "message": self.message, "timestamp": self.timestamp.isoformat(),
        }


class AIDecisionLog(db.Model):
    __tablename__ = "ai_decision_log"
    id              = db.Column(db.Integer, primary_key=True, autoincrement=True)
    crop            = db.Column(db.String,  nullable=False)
    decision        = db.Column(db.String,  nullable=False)   # irrigate|wait
    confidence      = db.Column(db.Float,   nullable=False)   # 0.0-1.0
    soil_moisture   = db.Column(db.Float)
    temperature     = db.Column(db.Float)
    reasoning       = db.Column(db.Text)      # JSON array of French reasoning strings
    timestamp       = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "crop": self.crop,
            "decision": self.decision,
            "confidence": self.confidence,
            "soil_moisture": self.soil_moisture,
            "temperature": self.temperature,
            "reasoning": json.loads(self.reasoning) if self.reasoning else [],
            "timestamp": self.timestamp.isoformat(),
        }


class SeasonalBaseline(db.Model):
    """Monthly soil moisture baselines derived from INRA Tadla data."""
    __tablename__ = "seasonal_baselines"
    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    crop_type     = db.Column(db.String, nullable=False)
    month         = db.Column(db.Integer, nullable=False)   # 1-12
    moisture_min  = db.Column(db.Float)
    moisture_max  = db.Column(db.Float)
    moisture_mean = db.Column(db.Float)
    moisture_std  = db.Column(db.Float)
    __table_args__ = (db.UniqueConstraint("crop_type", "month", name="uq_baseline_crop_month"),)

    def to_dict(self):
        return {
            "crop_type": self.crop_type, "month": self.month,
            "moisture_min": self.moisture_min, "moisture_max": self.moisture_max,
            "moisture_mean": self.moisture_mean, "moisture_std": self.moisture_std,
        }


class SeasonalAnomalyLog(db.Model):
    """Records statistical seasonal anomaly detections."""
    __tablename__ = "seasonal_anomaly_log"
    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sensor_id        = db.Column(db.String, db.ForeignKey("sensors.id"))
    crop_type        = db.Column(db.String, nullable=False)
    timestamp        = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    moisture_pct     = db.Column(db.Float)
    z_score          = db.Column(db.Float)
    deviation_type   = db.Column(db.String)   # "above" | "below"
    rolling_mean     = db.Column(db.Float)
    seasonal_mean    = db.Column(db.Float)
    seasonal_min     = db.Column(db.Float)
    seasonal_max     = db.Column(db.Float)
    severity         = db.Column(db.String)   # "moderate" | "high"
    possible_causes  = db.Column(db.Text)     # JSON list
    recommended_action = db.Column(db.String)

    def to_dict(self):
        import json
        return {
            "id": self.id, "sensor_id": self.sensor_id, "crop_type": self.crop_type,
            "timestamp": self.timestamp.isoformat(),
            "moisture_pct": self.moisture_pct, "z_score": self.z_score,
            "deviation_type": self.deviation_type, "rolling_mean": self.rolling_mean,
            "seasonal_mean": self.seasonal_mean,
            "seasonal_range": [self.seasonal_min, self.seasonal_max],
            "severity": self.severity,
            "possible_causes": json.loads(self.possible_causes) if self.possible_causes else [],
            "recommended_action": self.recommended_action,
        }
