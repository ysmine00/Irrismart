"""
IrriSmart — Train Isolation Forest anomaly detector on existing training data.
Saves to models/anomaly_detector.pkl
"""
import os, joblib, numpy as np, pandas as pd
from sklearn.ensemble import IsolationForest

FEATURES = ["soil_moisture_pct", "temperature_c", "humidity_pct", "eto_mm_day"]

def train():
    data_file = "training_data.csv"
    if not os.path.exists(data_file):
        print("❌  training_data.csv not found — run generate_training_data.py first")
        return

    df = pd.read_csv(data_file)[FEATURES].dropna()
    print(f"🔍  Training Isolation Forest on {len(df)} samples, features: {FEATURES}")

    clf = IsolationForest(contamination=0.05, n_estimators=200,
                          max_samples="auto", random_state=42, n_jobs=-1)
    clf.fit(df)

    os.makedirs("models", exist_ok=True)
    out = "models/anomaly_detector.pkl"
    joblib.dump(clf, out)
    print(f"✅  Saved: {out}")

    # Quick sanity check
    scores = clf.score_samples(df)
    pct_flagged = (clf.predict(df) == -1).mean() * 100
    print(f"   Score range: [{scores.min():.3f}, {scores.max():.3f}]")
    print(f"   Flagged as anomaly: {pct_flagged:.1f}%  (target ≈ 5%)")

if __name__ == "__main__":
    train()
