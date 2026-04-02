import os, requests
from datetime import datetime, date, timedelta
from app import db
from app.models import WeatherCache

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
LAT = float(os.getenv("FARM_LATITUDE",  32.34))
LON = float(os.getenv("FARM_LONGITUDE", -6.35))
CACHE_TTL_HOURS = 6

def get_forecast(days=7):
    today = date.today()
    cached = WeatherCache.query.filter(WeatherCache.forecast_date >= today)\
        .order_by(WeatherCache.forecast_date).limit(days).all()
    if cached and _fresh(cached[0]):
        return [c.to_dict() for c in cached]
    try:
        fresh = _fetch(days)
        _save(fresh)
        return fresh
    except Exception as e:
        print(f"[Weather] API error: {e}")
        return [c.to_dict() for c in cached] if cached else []

def get_tomorrow():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    for f in get_forecast(days=2):
        if f["forecast_date"] == tomorrow:
            return f
    r = get_forecast(days=1)
    return r[0] if r else None

def _fresh(entry):
    return (datetime.utcnow() - entry.fetched_at).total_seconds() < CACHE_TTL_HOURS * 3600

def _fetch(days):
    r = requests.get(OPEN_METEO_URL, params={
        "latitude": LAT, "longitude": LON,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,relative_humidity_2m_max",
        "timezone": "Africa/Casablanca",
        "forecast_days": days,
    }, timeout=10)
    r.raise_for_status()
    d = r.json()["daily"]
    return [{
        "forecast_date":     d["time"][i],
        "temp_max":          d["temperature_2m_max"][i],
        "temp_min":          d["temperature_2m_min"][i],
        "precipitation_mm":  d["precipitation_sum"][i] or 0,
        "precipitation_prob":d["precipitation_probability_max"][i] or 0,
        "wind_speed_kmh":    d["wind_speed_10m_max"][i],
        "humidity_percent":  d["relative_humidity_2m_max"][i],
        "fetched_at":        datetime.utcnow().isoformat(),
    } for i in range(len(d["time"]))]

def _save(forecasts):
    for f in forecasts:
        existing = WeatherCache.query.filter_by(forecast_date=date.fromisoformat(f["forecast_date"])).first()
        if existing:
            existing.temp_max=f["temp_max"]; existing.temp_min=f["temp_min"]
            existing.precipitation_mm=f["precipitation_mm"]
            existing.precipitation_prob=f["precipitation_prob"]
            existing.wind_speed_kmh=f["wind_speed_kmh"]
            existing.humidity_percent=f["humidity_percent"]
            existing.fetched_at=datetime.utcnow()
        else:
            db.session.add(WeatherCache(
                forecast_date=date.fromisoformat(f["forecast_date"]),
                temp_max=f["temp_max"], temp_min=f["temp_min"],
                precipitation_mm=f["precipitation_mm"],
                precipitation_prob=f["precipitation_prob"],
                wind_speed_kmh=f["wind_speed_kmh"],
                humidity_percent=f["humidity_percent"]))
    db.session.commit()
