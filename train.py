"""ICU early-warning engine: PhysioNet 2019 sepsis data.
Usage (from project root):  python train.py data/sepsis.csv
Outputs go to artifacts/: model.joblib, calibrator.joblib, metrics.json, shap_summary.png,
calibration.png, test_risk.csv (risk for every held-out test row), demo_raw.csv (raw records the
dashboard streams through the live pipeline).
"""
import sys
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
import shap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.isotonic import IsotonicRegression
from sklearn.calibration import calibration_curve
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

from pipeline import TARGET, make_features, feature_names, pretty

ART = Path("artifacts")
ART.mkdir(exist_ok=True)

path = sys.argv[1] if len(sys.argv) > 1 else "data/sepsis.csv"
df = pd.read_csv(path)
df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
print("Shape:", df.shape, "| sepsis rate:", round(df[TARGET].mean(), 4))

# ---- patient id (fallback: ICULOS resets to a lower value at each new patient)
pid = next((c for c in df.columns if c.lower().replace("_", "") in ("patientid", "pid", "id")), None)
if pid is None:
    df["pid"] = (df["ICULOS"].diff().fillna(1) <= 0).cumsum()
    pid = "pid"
df = df.sort_values([pid, "ICULOS"]).reset_index(drop=True)
base = [c for c in df.columns if c not in (TARGET, pid) and pd.api.types.is_numeric_dtype(df[c])]

# ---- split BY PATIENT (no leakage): 70/15/15
rng = np.random.RandomState(42)
ids = rng.permutation(df[pid].unique())
n = len(ids)
tr_ids, va_ids, te_ids = ids[: int(.7 * n)], ids[int(.7 * n): int(.85 * n)], ids[int(.85 * n):]

# ---- features (shared with the live app). Medians come from TRAIN patients only.
medians = df[df[pid].isin(tr_ids)][base].median()
feats = make_features(df, pid, base, medians)
features = feature_names(base)
print("Features:", len(features))
tr, va, te = (feats[feats[pid].isin(s)].copy() for s in (tr_ids, va_ids, te_ids))

# ---- model
spw = (tr[TARGET] == 0).sum() / max((tr[TARGET] == 1).sum(), 1)
model = xgb.XGBClassifier(
    n_estimators=500, max_depth=5, learning_rate=0.05, subsample=0.8,
    colsample_bytree=0.8, scale_pos_weight=spw, eval_metric="aucpr",
    tree_method="hist", early_stopping_rounds=30, n_jobs=-1,
)
model.fit(tr[features], tr[TARGET], eval_set=[(va[features], va[TARGET])], verbose=50)

# ---- calibration (isotonic on validation set) -> real probabilities
iso = IsotonicRegression(out_of_bounds="clip").fit(model.predict_proba(va[features])[:, 1], va[TARGET])
te["risk"] = iso.predict(model.predict_proba(te[features])[:, 1])
keep = [pid, "ICULOS", TARGET, "risk"] + [c for c in ("Age", "Gender") if c in te.columns]
te[keep].to_csv(ART / "test_predictions.csv", index=False)
metrics = {
    "AUROC": round(float(roc_auc_score(te[TARGET], te["risk"])), 3),
    "AUPRC": round(float(average_precision_score(te[TARGET], te["risk"])), 3),
    "Brier": round(float(brier_score_loss(te[TARGET], te["risk"])), 4),
    "test_patients": int(len(te_ids)),
    "sepsis_rate_rows": round(float(df[TARGET].mean()), 4),
}
print("\nTEST", metrics)
json.dump(metrics, open(ART / "metrics.json", "w"), indent=2)

# ---- calibration curve
obs, pred = calibration_curve(te[TARGET], te["risk"], n_bins=10, strategy="quantile")
plt.figure(figsize=(4.5, 4.5))
plt.plot([0, 1], [0, 1], "--", color="grey", label="perfect")
plt.plot(pred, obs, "o-", label="our model")
plt.xlabel("Predicted risk"); plt.ylabel("Observed sepsis rate")
plt.title("Calibration (held-out patients)"); plt.legend(); plt.tight_layout()
plt.savefig(ART / "calibration.png", dpi=150); plt.close()

# ---- save model bundle (everything the live pipeline needs)
joblib.dump({"model": model, "features": features, "base": base, "medians": medians, "pid": pid},
            ART / "model.joblib")
joblib.dump(iso, ART / "calibrator.joblib")

# ---- SHAP global plot
expl = shap.TreeExplainer(model)
samp = te[features].sample(min(3000, len(te)), random_state=0)
shap.summary_plot(expl.shap_values(samp), samp.rename(columns=pretty), plot_type="bar",
                  max_display=15, show=False)
plt.tight_layout(); plt.savefig(ART / "shap_summary.png", dpi=150); plt.close()

# ---- exports for the dashboard
te[[pid, "ICULOS", TARGET, "risk"]].round(5).to_csv(ART / "test_risk.csv", index=False)  # realistic stats
septic_all = te[te[TARGET] == 1][pid].unique()
healthy_all = te[~te[pid].isin(septic_all)][pid].unique()
demo_ids = np.concatenate([septic_all[:15], healthy_all[:15]])
df[df[pid].isin(demo_ids)][[pid] + base + [TARGET]].to_csv(ART / "demo_raw.csv", index=False)  # RAW records
print("Saved everything to artifacts/")
