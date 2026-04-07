"""
Alert Service — creates Alert records and sends SMS via Twilio.
Triggered by recommendation_service after each reading.
"""
import os
from datetime import datetime, timedelta
from app import db
from app.models import Alert, Sensor, Reading

def _get_twilio():
    sid   = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_  = os.getenv("TWILIO_PHONE_FROM")
    to_    = os.getenv("FARMER_PHONE")
    if not all([sid, token, from_, to_]):
        return None, None, None
    from twilio.rest import Client
    return Client(sid, token), from_, to_

def _already_sent_recently(sensor_id, alert_type, hours=6):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    return Alert.query.filter(
        Alert.sensor_id  == sensor_id,
        Alert.type       == alert_type,
        Alert.sent_sms   == True,
        Alert.created_at >= cutoff
    ).first() is not None

def send_sms(message: str) -> bool:
    client, from_, to_ = _get_twilio()
    if not client:
        print(f"[Twilio] Credentials not set — SMS skipped: {message}")
        return False
    try:
        msg = client.messages.create(body=message, from_=from_, to=to_)
        print(f"[Twilio] SMS sent: {msg.sid}")
        return True
    except Exception as e:
        print(f"[Twilio] SMS failed: {e}")
        return False

def create_alert(sensor_id, alert_type, message,
                 severity="warning",
                 decision_impact="Moyen",
                 soil_health_impact="Moyen",
                 yield_risk="Faible",
                 send_sms_flag=False) -> Alert:
    alert = Alert(
        sensor_id=sensor_id,
        type=alert_type,
        message=message,
        severity=severity,
        decision_impact=decision_impact,
        soil_health_impact=soil_health_impact,
        yield_risk=yield_risk,
        sent_sms=False,
    )
    db.session.add(alert)
    if send_sms_flag and not _already_sent_recently(sensor_id, alert_type):
        sent = send_sms(message)
        alert.sent_sms = sent
    db.session.commit()
    return alert

def check_and_alert(sensor_id: str, moisture: float, battery: float = None,
                    temp: float = None, last_seen: datetime = None):
    sensor = Sensor.query.get(sensor_id)
    if not sensor:
        return

    from app.services.recommendation_service import CROP_THRESHOLDS
    t = CROP_THRESHOLDS.get(sensor.crop_type, CROP_THRESHOLDS["olive"])

    if moisture < t["critical"]:
        create_alert(
            sensor_id=sensor_id,
            alert_type="LOW_MOISTURE",
            message=(
                f"🚨 URGENT — IrriSmart\n"
                f"Parcelle: {sensor.name} ({sensor.crop_type.capitalize()})\n"
                f"💧 Humidité critique: {moisture}%\n"
                f"Seuil minimum: {t['critical']}%\n"
                f"👉 Irriguer immédiatement!"
            ),
            severity="critical",
            decision_impact="Élevé",
            soil_health_impact="Élevé",
            yield_risk="Élevé",
            send_sms_flag=True,
        )
    elif moisture < t["low"]:
        create_alert(
            sensor_id=sensor_id,
            alert_type="LOW_MOISTURE",
            message=f"⚠️ {sensor.name}: Humidité basse ({moisture}%). Irrigation recommandée.",
            severity="warning",
            decision_impact="Moyen",
            soil_health_impact="Moyen",
            yield_risk="Moyen",
            send_sms_flag=False,
        )

    if temp and temp > 38:
        create_alert(
            sensor_id=sensor_id,
            alert_type="HIGH_TEMP",
            message=(
                f"🌡️ IrriSmart — Alerte Chaleur\n"
                f"Parcelle: {sensor.name} ({sensor.crop_type.capitalize()})\n"
                f"Température: {temp}°C\n"
                f"⚠️ Risque de stress hydrique élevé.\n"
                f"Vérifiez l'humidité du sol aujourd'hui."
            ),
            severity="warning",
            decision_impact="Moyen",
            soil_health_impact="Moyen",
            yield_risk="Moyen",
            send_sms_flag=True,
        )

    if temp and temp < 2:
        create_alert(
            sensor_id=sensor_id,
            alert_type="FROST_WARNING",
            message=(
                f"❄️ IrriSmart — Alerte Gel\n"
                f"Parcelle: {sensor.name} ({sensor.crop_type.capitalize()})\n"
                f"Température: {temp}°C\n"
                f"🚨 Risque de gel détecté!\n"
                f"Protégez vos cultures immédiatement."
            ),
            severity="critical",
            decision_impact="Élevé",
            soil_health_impact="Élevé",
            yield_risk="Élevé",
            send_sms_flag=True,
        )

    if battery and battery < 20:
        create_alert(
            sensor_id=sensor_id,
            alert_type="LOW_BATTERY",
            message=f"🔋 {sensor.name}: Batterie faible ({battery:.0f}%). Remplacer bientôt.",
            severity="info",
            send_sms_flag=False,
        )

    if last_seen and (datetime.utcnow() - last_seen).total_seconds() > 7200:
        create_alert(
            sensor_id=sensor_id,
            alert_type="SENSOR_OFFLINE",
            message=(
                f"📡 IrriSmart — Alerte Capteur\n"
                f"Parcelle: {sensor.name}\n"
                f"Culture: {sensor.crop_type.capitalize()}\n"
                f"⚠️ Capteur hors ligne depuis {int((datetime.utcnow()-last_seen).total_seconds()/3600)}h.\n"
                f"Veuillez vérifier le matériel."
            ),
            severity="warning",
            send_sms_flag=True,
        )
