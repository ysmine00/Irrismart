from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from dotenv import load_dotenv
import os

load_dotenv()
db = SQLAlchemy()

def create_app(config=None):
    app = Flask(__name__, static_folder="../static", static_url_path="/static")
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///irrismart.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    if config:
        app.config.update(config)
    db.init_app(app)
    CORS(app)
    from app.routes.api import api
    from app.routes.pages import pages
    app.register_blueprint(api)
    app.register_blueprint(pages)
    with app.app_context():
        db.create_all()
        _seed_if_empty()
    return app

def _seed_if_empty():
    from app.models import Sensor, Reading, Recommendation, Alert
    from datetime import datetime, timedelta
    import random, math
    if Sensor.query.count() > 0:
        return
    sensors = [
        Sensor(id="ID010001", name="Parcelle Oliviers Nord",  crop_type="olive",  flow_rate=5.0, battery_level=81.0, latitude=32.34, longitude=-6.35, area_ha=2.4),
        Sensor(id="ID010002", name="Parcelle Agrumes Centre", crop_type="citrus", flow_rate=5.0, battery_level=78.0, latitude=32.35, longitude=-6.34, area_ha=1.9),
        Sensor(id="ID010003", name="Parcelle Blé Sud",        crop_type="wheat",  flow_rate=5.0, battery_level=85.0, latitude=32.33, longitude=-6.36, area_ha=3.2),
    ]
    db.session.add_all(sensors)
    db.session.commit()
    base = datetime.utcnow() - timedelta(days=14)
    for sensor in sensors:
        moisture = 41.0
        battery  = sensor.battery_level + 1.7
        for d in range(15):
            ts = base + timedelta(days=d, hours=1)
            moisture += random.uniform(-1.8, 0.9)
            moisture  = max(28, min(52, moisture))
            battery  -= random.uniform(0.1, 0.15)
            rain = round(random.uniform(0, 5.0), 1) if 4 <= d <= 10 else 0.0
            temp = round(22 + 8 * math.sin(d / 14 * math.pi) + random.uniform(-1, 1), 1)
            db.session.add(Reading(
                sensor_id=sensor.id, timestamp=ts,
                soil_moisture=round(moisture, 1),
                air_temperature=temp,
                air_humidity=round(55 + random.uniform(-5, 5), 1),
                battery_voltage=round(battery, 1),
                rain_mm=rain))
            action = "WAIT" if moisture > 35 else "IRRIGATE"
            db.session.add(Recommendation(
                sensor_id=sensor.id, created_at=ts, action=action,
                duration_minutes=0 if action == "WAIT" else 45,
                reason="Humidité actuelle suffisante pour aujourd'hui." if action == "WAIT" else "Humidité insuffisante.",
                acknowledged=True))
    db.session.add(Alert(
        sensor_id="ID010001", type="TREND_CHANGE",
        message="Les tendances capteurs changent, surveiller la cohérence des mesures.",
        sent_sms=False, acknowledged=False))
    db.session.commit()
