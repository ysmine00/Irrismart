"""
IrriSmart - Generate Training Data for AI Decision Models
Produces 36,000 samples (12,000 per crop: olive, citrus, wheat)
Based on FAO-56 Penman-Monteith ETo and Beni Mellal-Khénifra climate data
"""
import pandas as pd
import numpy as np
import random
from datetime import datetime

# Crop configurations
CROPS = {
    "olive":  {"id": 0, "emoji": "🫒"},
    "citrus": {"id": 1, "emoji": "🍊"},
    "wheat":  {"id": 2, "emoji": "🌾"},
}

# Crop moisture thresholds by growth stage (%) — FAO-56 Tadla calibrated
# Olive: drought-tolerant, fine at 40-60%; irrigate only when <35%
# Citrus: water-demanding but not at 48%; irrigate when <42%
# Wheat: irrigate when <32%
MOISTURE_THRESHOLDS = {
    "olive":  {0: 30, 1: 35, 2: 40, 3: 37, 4: 32},
    "citrus": {0: 40, 1: 42, 2: 48, 3: 46, 4: 42},
    "wheat":  {0: 30, 1: 35, 2: 42, 3: 45, 4: 25},
}

# Crop coefficients (Kc) by growth stage
KC_BY_STAGE = {
    "olive":  [0.65, 0.70, 0.75, 0.75, 0.70],
    "citrus": [0.70, 0.75, 0.85, 0.85, 0.75],
    "wheat":  [0.40, 0.70, 1.15, 1.15, 0.50],
}

# Months by growth stage
STAGE_MONTHS = {
    "olive":  {0: [12, 1, 2], 1: [3, 4], 2: [5, 6], 3: [7, 8], 4: [9, 10, 11]},
    "citrus": {0: [1, 2], 1: [3, 4], 2: [5], 3: [6, 7, 8, 9], 4: [10, 11, 12]},
    "wheat":  {0: [11, 12], 1: [1, 2], 2: [3], 3: [4, 5], 4: [6]},
}

# Beni Mellal-Khénifra monthly climate averages
# [temp_mean, temp_std, humidity_mean, rain_probability, eto_mean]
CLIMATE = {
    1:  [10.5, 3.0, 72, 0.35, 2.1],
    2:  [12.0, 3.5, 68, 0.30, 2.8],
    3:  [15.0, 4.0, 62, 0.25, 3.8],
    4:  [18.5, 4.5, 55, 0.20, 5.0],
    5:  [22.0, 4.0, 48, 0.10, 6.2],
    6:  [27.5, 4.0, 38, 0.05, 7.8],
    7:  [31.0, 3.5, 30, 0.02, 8.5],
    8:  [31.5, 3.5, 32, 0.02, 8.0],
    9:  [26.0, 4.0, 42, 0.08, 6.5],
    10: [20.0, 4.0, 55, 0.20, 4.5],
    11: [14.5, 3.5, 68, 0.30, 2.8],
    12: [11.0, 3.0, 74, 0.35, 1.9],
}


def get_growth_stage_for_month(crop, month):
    """Return growth stage (0-4) for given crop and month"""
    for stage, months in STAGE_MONTHS[crop].items():
        if month in months:
            return stage
    return 0  # fallback


def simplified_eto(temp_c, humidity_pct, wind_kmh, solar_radiation):
    """
    Simplified Penman-Monteith ETo calculation (mm/day)
    Based on FAO-56 approximation
    """
    # Radiation factor (simplified - would use latitude/day-of-year in full FAO-56)
    radiation_factor = solar_radiation / 20.0  # normalize

    # Vapor pressure deficit approximation
    svp = 0.6108 * np.exp((17.27 * temp_c) / (temp_c + 237.3))  # saturated vapor pressure
    avp = svp * (humidity_pct / 100.0)  # actual vapor pressure
    vpd = svp - avp  # vapor pressure deficit

    # Wind effect
    wind_effect = 0.25 + 0.05 * (wind_kmh / 10.0)

    # Simplified ETo (mm/day)
    eto = 0.408 * radiation_factor * (temp_c + 17.8) * vpd * wind_effect
    return max(0.5, min(12.0, eto))  # clamp to reasonable range


def generate_sample(crop, month):
    """Generate one training sample for given crop and month"""
    growth_stage = get_growth_stage_for_month(crop, month)
    kc = KC_BY_STAGE[crop][growth_stage]
    moisture_threshold = MOISTURE_THRESHOLDS[crop][growth_stage]

    # Climate data for this month
    temp_mean, temp_std, humidity_mean, rain_prob, eto_mean = CLIMATE[month]

    # Generate realistic feature values
    temperature_c = np.random.normal(temp_mean, temp_std)
    temperature_c = max(-5, min(45, temperature_c))  # clamp

    humidity_pct = np.random.normal(humidity_mean, 8)
    humidity_pct = max(15, min(95, humidity_pct))

    # Solar radiation (higher in summer, lower in winter)
    solar_radiation = 10 + 12 * (1 + np.sin((month - 1) * np.pi / 6))  # seasonal pattern
    solar_radiation += np.random.normal(0, 2)
    solar_radiation = max(5, min(25, solar_radiation))

    wind_speed_kmh = np.random.gamma(2, 2) + 1  # typically 1-10 km/h, skewed
    wind_speed_kmh = min(25, wind_speed_kmh)

    # Calculate ETo
    eto_mm_day = simplified_eto(temperature_c, humidity_pct, wind_speed_kmh, solar_radiation)

    # ETc = ETo × Kc
    etc_mm_day = eto_mm_day * kc

    # Rainfall (based on monthly probability)
    has_rain = np.random.random() < rain_prob
    if has_rain:
        # Exponential distribution for rain amounts when it rains
        rainfall_24h_mm = np.random.exponential(8) + 1
        rainfall_24h_mm = min(60, rainfall_24h_mm)  # cap at 60mm
    else:
        rainfall_24h_mm = 0

    # Days since last irrigation (affects soil moisture)
    days_since_irrigation = np.random.randint(0, 15)

    # Soil moisture — centered at realistic field values so the model sees
    # plenty of "wait" examples in the 40-60% range for each crop
    if crop == "olive":
        base_moisture = np.random.normal(48, 14)  # fine at 40-60%
    elif crop == "citrus":
        base_moisture = np.random.normal(52, 12)
    else:  # wheat
        base_moisture = np.random.normal(42, 11)

    # Moisture depletion from days without irrigation
    moisture_loss = days_since_irrigation * (etc_mm_day / 10.0)  # simplified depletion

    # Moisture gain from recent rain
    moisture_gain = rainfall_24h_mm * 0.8  # 80% infiltration efficiency

    soil_moisture_pct = base_moisture - moisture_loss + moisture_gain
    soil_moisture_pct = max(10, min(80, soil_moisture_pct))  # clamp

    # LABEL LOGIC (FAO-grounded irrigation decision)
    # irrigate = 1 if:
    #   - moisture < threshold AND
    #   - no significant recent rain (>8mm) AND
    #   - high ETo demand

    moisture_deficit = soil_moisture_pct < moisture_threshold
    no_recent_rain = rainfall_24h_mm < 8
    high_demand = etc_mm_day > 4.0

    if moisture_deficit and no_recent_rain:
        irrigate = 1
    elif moisture_deficit and high_demand:
        # Even with some rain, irrigate if demand is very high
        irrigate = 1 if etc_mm_day > 6.5 else 0
    else:
        irrigate = 0

    # Add 5% random label noise for realism
    if np.random.random() < 0.05:
        irrigate = 1 - irrigate

    return {
        "crop": crop,
        "crop_id": CROPS[crop]["id"],
        "month": month,
        "growth_stage": growth_stage,
        "soil_moisture_pct": round(soil_moisture_pct, 1),
        "temperature_c": round(temperature_c, 1),
        "humidity_pct": round(humidity_pct, 1),
        "rainfall_24h_mm": round(rainfall_24h_mm, 1),
        "wind_speed_kmh": round(wind_speed_kmh, 1),
        "solar_radiation": round(solar_radiation, 1),
        "eto_mm_day": round(eto_mm_day, 2),
        "kc": round(kc, 2),
        "etc_mm_day": round(etc_mm_day, 2),
        "days_since_irrigation": days_since_irrigation,
        "moisture_threshold": moisture_threshold,
        "irrigate": irrigate,
    }


def generate_all_data(samples_per_crop=12000):
    """Generate complete training dataset"""
    print("🌱 IrriSmart AI Training Data Generator")
    print("=" * 60)
    print(f"Generating {samples_per_crop} samples per crop...")
    print()

    all_samples = []

    for crop in CROPS.keys():
        print(f"{CROPS[crop]['emoji']} Generating {crop} samples...")
        crop_samples = []

        for i in range(samples_per_crop):
            # Distribute samples across months based on growth stage distribution
            month = np.random.randint(1, 13)
            sample = generate_sample(crop, month)
            crop_samples.append(sample)

        all_samples.extend(crop_samples)

        # Print crop summary
        irrigate_count = sum(1 for s in crop_samples if s["irrigate"] == 1)
        irrigate_rate = irrigate_count / len(crop_samples) * 100
        print(f"   Samples: {len(crop_samples)}")
        print(f"   Irrigate rate: {irrigate_rate:.1f}%")
        print()

    df = pd.DataFrame(all_samples)

    # Shuffle
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    # Save
    output_file = "training_data.csv"
    df.to_csv(output_file, index=False)

    print("=" * 60)
    print(f"✅ Training data saved to: {output_file}")
    print(f"   Total samples: {len(df)}")
    print()
    print("Summary by crop:")
    print("-" * 60)
    for crop in CROPS.keys():
        crop_df = df[df["crop"] == crop]
        irrigate_rate = crop_df["irrigate"].mean() * 100
        print(f"{CROPS[crop]['emoji']} {crop.capitalize():8s} | Samples: {len(crop_df):6d} | Irrigate: {irrigate_rate:5.1f}%")
    print("=" * 60)

    return df


if __name__ == "__main__":
    random.seed(42)
    np.random.seed(42)
    df = generate_all_data(samples_per_crop=12000)
