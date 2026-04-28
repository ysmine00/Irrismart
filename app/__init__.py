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
    db_url = os.getenv("DATABASE_URL", "sqlite:///irrismart.db")
    # Railway sets postgres:// but SQLAlchemy requires postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
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
        _migrate_db()
        _seed_if_empty()
        _seed_seasonal_baselines()
        _backfill_history()
    return app

def _migrate_db():
    """Add columns introduced after initial deploy. Safe to run on every startup."""
    from sqlalchemy import text
    new_columns = [
        ("readings",        "soil_temperature", "FLOAT"),
        ("readings",        "ph_level",         "FLOAT"),
        ("recommendations", "moisture_at_time",  "FLOAT"),
        ("recommendations", "health_impact",     "INTEGER"),
    ]
    # Step 1: add missing columns (separate connection per statement so a failed
    # ALTER TABLE does not leave the transaction in an aborted state)
    for table, col, col_type in new_columns:
        with db.engine.connect() as conn:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
                print(f"[Migration] Added {table}.{col}")
            except Exception:
                conn.rollback()  # column already exists — reset and continue

    # Step 2: fix/backfill soil_temperature and ph_level (fresh connection)
    with db.engine.begin() as conn:
        try:
            conn.execute(text("""
                UPDATE readings
                SET soil_temperature = air_temperature - 2.0 + (MOD(id, 10) - 5.0) * 0.1
                WHERE (soil_temperature IS NULL OR soil_temperature > 60 OR soil_temperature < -10)
                AND air_temperature IS NOT NULL
            """))
            conn.execute(text("""
                UPDATE readings
                SET ph_level = 6.8 + (MOD(id, 7) - 3.0) * 0.1
                WHERE ph_level IS NULL OR ph_level > 14 OR ph_level < 0
            """))
            print("[Migration] Backfilled soil_temperature and ph_level")
        except Exception as e:
            print(f"[Migration] Backfill skipped: {e}")

def _seed_seasonal_baselines():
    """Seed INRA Tadla monthly soil moisture baselines. Runs only if table is empty."""
    from app.models import SeasonalBaseline
    if SeasonalBaseline.query.count() > 0:
        return

    # Source: INRA Tadla field data for Beni Mellal-Khénifra region
    BASELINES = {
        "olive": [
            (1,40,60,50,5),(2,38,58,48,5),(3,35,55,45,5),(4,32,52,42,5),
            (5,28,50,39,6),(6,22,45,34,6),(7,18,40,29,6),(8,20,42,31,6),
            (9,28,50,39,5),(10,35,55,45,5),(11,38,58,48,5),(12,40,62,51,5),
        ],
        "citrus": [
            (1,50,70,60,5),(2,48,68,58,5),(3,45,65,55,5),(4,42,62,52,5),
            (5,38,60,49,6),(6,32,55,44,6),(7,28,50,39,6),(8,30,52,41,6),
            (9,38,60,49,5),(10,42,62,52,5),(11,48,68,58,5),(12,50,72,61,5),
        ],
        "wheat": [
            (1,45,65,55,5),(2,43,63,53,5),(3,40,60,50,5),(4,38,58,48,5),
            (5,32,55,44,6),(6,25,48,37,6),(7,20,42,31,6),(8,22,45,34,6),
            (9,32,55,44,5),(10,38,60,49,5),(11,43,63,53,5),(12,45,65,55,5),
        ],
    }
    for crop, rows in BASELINES.items():
        for month, mn, mx, mean, std in rows:
            db.session.add(SeasonalBaseline(
                crop_type=crop, month=month,
                moisture_min=mn, moisture_max=mx,
                moisture_mean=mean, moisture_std=std,
            ))
    db.session.commit()
    print("[Seed] Seasonal baselines inserted (INRA Tadla)")


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
    _insert_history_hours(sensors, hours=168)  # 7 days
    db.session.add(Alert(
        sensor_id="ID010001", type="TREND_CHANGE",
        message="Les tendances capteurs changent, surveiller la cohérence des mesures.",
        sent_sms=False, acknowledged=False))
    db.session.commit()
    print("[Seed] 7 days of hourly history seeded")

def _backfill_history():
    """On an existing DB with few readings, insert 7 days of backdated history."""
    from app.models import Sensor, Reading
    if Reading.query.count() >= 200:
        return
    sensors = Sensor.query.all()
    if not sensors:
        return
    _insert_history_hours(sensors, hours=168)
    db.session.commit()
    print("[Backfill] 7-day history inserted for existing DB")

def _insert_history_hours(sensors, hours=168):
    from app.models import Reading, Recommendation
    from datetime import datetime, timedelta
    import random, math
    base = datetime.utcnow() - timedelta(hours=hours - 1)
    for sensor in sensors:
        moisture = {"olive": 42.0, "citrus": 48.0, "wheat": 37.0}.get(sensor.crop_type, 40.0)
        battery  = sensor.battery_level + 0.5
        for h in range(hours):
            ts = base + timedelta(hours=h)
            moisture += random.uniform(-1.2, 0.6)
            moisture  = max(28, min(62, moisture))
            battery  -= random.uniform(0.005, 0.015)
            rain = round(random.uniform(0, 2.0), 1) if random.random() > 0.85 else 0.0
            temp = round(22 + 5 * math.sin((h % 24) / 24 * math.pi) + random.uniform(-1, 1), 1)
            soil_temp = round(temp - 2.0 + random.uniform(-0.5, 0.5), 1)
            ph        = round(6.8 + random.uniform(-0.3, 0.3), 2)
            db.session.add(Reading(
                sensor_id=sensor.id, timestamp=ts,
                soil_moisture=round(moisture, 1),
                air_temperature=temp,
                air_humidity=round(55 + random.uniform(-5, 5), 1),
                battery_voltage=round(battery, 1),
                rain_mm=rain,
                soil_temperature=soil_temp,
                ph_level=ph))
            action = "WAIT" if moisture > 35 else "IRRIGATE"
            db.session.add(Recommendation(
                sensor_id=sensor.id, created_at=ts, action=action,
                duration_minutes=0 if action == "WAIT" else 45,
                reason="Humidité actuelle suffisante pour aujourd'hui." if action == "WAIT" else "Humidité insuffisante.",
                moisture_at_time=round(moisture, 1),
                acknowledged=True))
