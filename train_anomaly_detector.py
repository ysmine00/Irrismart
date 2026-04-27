"""
IrriSmart - Train Anomaly Detection Model
Uses Isolation Forest to detect abnormal sensor readings
"""
import pandas as pd
import numpy as np
import joblib
import os
from sklearn.ensemble import IsolationForest

print("🔍 IrriSmart Anomaly Detection Training")
print("=" * 70)

# Load training data
data_file = "training_data.csv"
if not os.path.exists(data_file):
    print(f"❌ Error: {data_file} not found!")
    exit(1)

print(f"Loading training data from {data_file}...")
df = pd.read_csv(data_file)
print(f"✓ Loaded {len(df)} samples")

# Features for anomaly detection
features = ["soil_moisture_pct", "temperature_c", "humidity_pct", "eto_mm_day"]
X = df[features]

print(f"\nTraining Isolation Forest with contamination=0.05...")
print(f"Features: {', '.join(features)}")

# Train Isolation Forest
model = IsolationForest(
    contamination=0.05,  # 5% expected anomalies
    random_state=42,
    n_estimators=100,
    max_samples='auto',
    n_jobs=-1
)

model.fit(X)

# Test predictions
predictions = model.predict(X)
scores = model.score_samples(X)

anomalies = sum(predictions == -1)
normal = sum(predictions == 1)

print(f"\n✓ Model trained successfully")
print(f"   Normal samples: {normal}")
print(f"   Detected anomalies: {anomalies}")
print(f"   Anomaly rate: {anomalies/len(X)*100:.1f}%")

# Save model
os.makedirs("models", exist_ok=True)
model_path = "models/anomaly_detector.pkl"
joblib.dump(model, model_path)
print(f"\n✅ Model saved to: {model_path}")

print("=" * 70)
print("Anomaly detector ready for production!")
