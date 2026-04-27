"""
IrriSmart - Train RandomForest Models for Irrigation Decision
One model per crop: olive, citrus, wheat
Publication-quality plots and performance metrics
"""
import pandas as pd
import numpy as np
import joblib
import json
import os
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_curve,
    auc,
    f1_score,
    accuracy_score,
    recall_score,
)
import matplotlib.pyplot as plt
import seaborn as sns

# Set style for professional plots
sns.set_style("whitegrid")
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.size"] = 10
plt.rcParams["figure.dpi"] = 100

CROPS = ["olive", "citrus", "wheat"]
CROP_EMOJI = {"olive": "🫒", "citrus": "🍊", "wheat": "🌾"}

FEATURES = [
    "soil_moisture_pct",
    "temperature_c",
    "humidity_pct",
    "rainfall_24h_mm",
    "wind_speed_kmh",
    "eto_mm_day",
    "etc_mm_day",
    "growth_stage",
    "days_since_irrigation",
    "month",
    "moisture_threshold",
]

# Model hyperparameters
PARAMS = {
    "n_estimators": 200,
    "max_depth": 12,
    "min_samples_split": 5,
    "class_weight": "balanced",
    "random_state": 42,
    "n_jobs": -1,
}


def train_crop_model(crop, df):
    """Train RandomForest model for one crop"""
    print(f"\n{CROP_EMOJI[crop]} Training {crop.upper()} model...")
    print("=" * 70)

    # Filter data for this crop
    crop_df = df[df["crop"] == crop].copy()

    X = crop_df[FEATURES]
    y = crop_df["irrigate"]

    print(f"   Dataset size: {len(X)} samples")
    print(f"   Irrigate rate: {y.mean()*100:.1f}%")

    # Train/test split (80/20, stratified)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    print(f"   Train set: {len(X_train)} | Test set: {len(X_test)}")

    # Train model
    print("\n   Training RandomForest...")
    model = RandomForestClassifier(**PARAMS)
    model.fit(X_train, y_train)

    # Cross-validation F1 score (5-fold)
    print("   Running 5-fold cross-validation...")
    cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring="f1", n_jobs=-1)
    cv_f1 = cv_scores.mean()
    print(f"   ✓ Cross-validation F1: {cv_f1:.4f} (±{cv_scores.std():.4f})")

    # Test set evaluation
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    accuracy = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    recall = recall_score(y_test, y_pred)

    print(f"   ✓ Test Accuracy: {accuracy*100:.2f}%")
    print(f"   ✓ Test F1 Score: {f1:.4f}")
    print(f"   ✓ Test Recall:   {recall:.4f}")

    # Classification report
    print("\n   Classification Report:")
    print("   " + "-" * 66)
    report = classification_report(y_test, y_pred, target_names=["Wait", "Irrigate"])
    for line in report.split("\n"):
        if line.strip():
            print(f"   {line}")

    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred)
    print("\n   Confusion Matrix:")
    print(f"   {cm}")

    # Feature importance
    importances = model.feature_importances_
    feature_importance = sorted(
        zip(FEATURES, importances), key=lambda x: x[1], reverse=True
    )
    print("\n   Top 5 Feature Importances:")
    for feat, imp in feature_importance[:5]:
        print(f"   {feat:25s} {imp:.4f}")

    # ROC curve data
    fpr, tpr, _ = roc_curve(y_test, y_proba)
    roc_auc = auc(fpr, tpr)

    # Check quality threshold
    if f1 < 0.85:
        print(f"\n   ⚠️  WARNING: F1 score {f1:.4f} is below 0.85 threshold!")
        print(
            "   Consider tuning hyperparameters or generating more diverse training data."
        )

    return {
        "model": model,
        "cv_f1": cv_f1,
        "accuracy": accuracy,
        "f1_score": f1,
        "recall": recall,
        "confusion_matrix": cm,
        "feature_importance": feature_importance,
        "roc_curve": (fpr, tpr, roc_auc),
        "test_samples": len(X_test),
    }


def save_confusion_matrix_plot(crop, cm, output_path):
    """Generate and save confusion matrix heatmap"""
    fig, ax = plt.subplots(figsize=(6, 5))

    sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Greens",
        cbar=True,
        square=True,
        ax=ax,
        annot_kws={"fontsize": 14, "fontweight": "bold"},
        linewidths=1,
        linecolor="white",
    )

    ax.set_xlabel("Prédiction", fontsize=12, fontweight="bold")
    ax.set_ylabel("Vérité terrain", fontsize=12, fontweight="bold")
    ax.set_title(
        f"Matrice de Confusion - {crop.capitalize()} {CROP_EMOJI[crop]}",
        fontsize=14,
        fontweight="bold",
        pad=15,
    )
    ax.set_xticklabels(["Attendre", "Irriguer"], fontsize=11)
    ax.set_yticklabels(["Attendre", "Irriguer"], fontsize=11, rotation=0)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   ✓ Saved confusion matrix: {output_path}")


def save_feature_importance_plot(crop, feature_importance, output_path):
    """Generate and save feature importance horizontal bar chart"""
    # Take top 10 features
    top_features = feature_importance[:10]
    names, values = zip(*top_features)

    fig, ax = plt.subplots(figsize=(8, 6))

    colors = plt.cm.Greens(np.linspace(0.4, 0.8, len(values)))
    bars = ax.barh(range(len(values)), values, color=colors, edgecolor="white", linewidth=1)

    ax.set_yticks(range(len(values)))
    ax.set_yticklabels(names, fontsize=10)
    ax.set_xlabel("Importance", fontsize=12, fontweight="bold")
    ax.set_title(
        f"Importance des Variables - {crop.capitalize()} {CROP_EMOJI[crop]}",
        fontsize=14,
        fontweight="bold",
        pad=15,
    )
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)

    # Add value labels on bars
    for i, (bar, val) in enumerate(zip(bars, values)):
        ax.text(
            val + 0.005,
            i,
            f"{val:.3f}",
            va="center",
            fontsize=9,
            fontweight="bold",
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   ✓ Saved feature importance: {output_path}")


def save_roc_curves_all(results, output_path):
    """Generate combined ROC curve plot for all crops"""
    fig, ax = plt.subplots(figsize=(8, 7))

    colors = {"olive": "#6B8E23", "citrus": "#FF8C00", "wheat": "#DAA520"}

    for crop in CROPS:
        fpr, tpr, roc_auc = results[crop]["roc_curve"]
        ax.plot(
            fpr,
            tpr,
            color=colors[crop],
            lw=2.5,
            label=f"{crop.capitalize()} {CROP_EMOJI[crop]} (AUC = {roc_auc:.3f})",
        )

    # Diagonal reference line
    ax.plot([0, 1], [0, 1], "k--", lw=1.5, alpha=0.5, label="Hasard (AUC = 0.5)")

    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.05])
    ax.set_xlabel("Taux de Faux Positifs", fontsize=12, fontweight="bold")
    ax.set_ylabel("Taux de Vrais Positifs", fontsize=12, fontweight="bold")
    ax.set_title(
        "Courbes ROC - Tous les Modèles",
        fontsize=14,
        fontweight="bold",
        pad=15,
    )
    ax.legend(loc="lower right", fontsize=10, frameon=True, shadow=True)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   ✓ Saved ROC curves: {output_path}")


def print_summary_table(results):
    """Print beautiful summary table to console"""
    print("\n")
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║           IrriSmart AI — Training Summary                   ║")
    print("╠══════════╦══════════╦═══════════╦════════╦══════════╦═══════╣")
    print("║ Crop     ║ Accuracy ║ F1 Score  ║ Recall ║ Samples  ║ AUC   ║")
    print("╠══════════╬══════════╬═══════════╬════════╬══════════╬═══════╣")

    for crop in CROPS:
        r = results[crop]
        emoji = CROP_EMOJI[crop]
        acc = r["accuracy"] * 100
        f1 = r["f1_score"]
        recall = r["recall"]
        samples = r["test_samples"]
        _, _, roc_auc = r["roc_curve"]

        print(
            f"║ {emoji} {crop.capitalize():6s} ║ {acc:7.2f}% ║   {f1:.4f}  ║ {recall:.4f} ║  {samples:6d}  ║ {roc_auc:.3f} ║"
        )

    print("╚══════════╩══════════╩═══════════╩════════╩══════════╩═══════╝")
    print()


def main():
    """Main training pipeline"""
    print("🌱 IrriSmart AI Model Training")
    print("=" * 70)

    # Load training data
    data_file = "training_data.csv"
    if not os.path.exists(data_file):
        print(f"❌ Error: {data_file} not found!")
        print("   Run generate_training_data.py first.")
        return

    print(f"Loading training data from {data_file}...")
    df = pd.read_csv(data_file)
    print(f"✓ Loaded {len(df)} samples")

    # Create output directories
    os.makedirs("models", exist_ok=True)
    os.makedirs("models/plots", exist_ok=True)

    # Train models for each crop
    results = {}
    for crop in CROPS:
        results[crop] = train_crop_model(crop, df)

    print("\n" + "=" * 70)
    print("SAVING MODELS AND PLOTS")
    print("=" * 70)

    # Save models and generate plots
    metadata = {
        "training_date": datetime.now().isoformat(),
        "total_samples": len(df),
        "model_params": PARAMS,
        "crops": {},
    }

    for crop in CROPS:
        r = results[crop]

        # Save model
        model_path = f"models/{crop}_model.pkl"
        joblib.dump(r["model"], model_path)
        print(f"✓ Saved model: {model_path}")

        # Save plots
        save_confusion_matrix_plot(
            crop, r["confusion_matrix"], f"models/plots/confusion_matrix_{crop}.png"
        )
        save_feature_importance_plot(
            crop, r["feature_importance"], f"models/plots/feature_importance_{crop}.png"
        )

        # Store metadata
        metadata["crops"][crop] = {
            "cv_f1": round(r["cv_f1"], 4),
            "test_accuracy": round(r["accuracy"], 4),
            "test_f1": round(r["f1_score"], 4),
            "test_recall": round(r["recall"], 4),
            "roc_auc": round(r["roc_curve"][2], 4),
            "test_samples": r["test_samples"],
            "top_features": [
                {"name": feat, "importance": round(imp, 4)}
                for feat, imp in r["feature_importance"][:5]
            ],
        }

    # Save combined ROC curve
    save_roc_curves_all(results, "models/plots/roc_curve_all_crops.png")

    # Save metadata JSON
    metadata_path = "models/model_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"✓ Saved metadata: {metadata_path}")

    # Print summary table
    print_summary_table(results)

    # Final quality check
    print("QUALITY CHECK")
    print("=" * 70)
    all_passed = True
    for crop in CROPS:
        f1 = results[crop]["f1_score"]
        status = "✅ PASS" if f1 >= 0.85 else "❌ FAIL"
        print(f"{CROP_EMOJI[crop]} {crop.capitalize():8s} F1={f1:.4f} {status}")
        if f1 < 0.85:
            all_passed = False

    if all_passed:
        print("\n🎉 All models meet the F1 ≥ 0.85 quality threshold!")
        print("   Models are ready for production deployment.")
    else:
        print("\n⚠️  Some models are below quality threshold.")
        print("   Consider retraining with adjusted hyperparameters.")

    print("=" * 70)
    print("✅ Training complete!")


if __name__ == "__main__":
    main()
