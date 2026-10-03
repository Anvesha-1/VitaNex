"""Shared feature pipeline + live scorer. Used by train.py (batch) and app.py (hour-by-hour stream).
Every feature is causal (uses only current and past hours), so scoring the first h hours of a
patient gives exactly the same answer for hour h as scoring the full stay. `python pipeline.py`
verifies this.
"""
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap

TARGET = "SepsisLabel"
VITALS = ["HR", "O2Sat", "Temp", "SBP", "MAP", "DBP", "Resp"]
STATIC = {"ICULOS", "Age", "Gender", "Unit1", "Unit2", "HospAdmTime"}


def measured_cols(base):
    return [c for c in base if c not in STATIC]


def vital_cols(base):
    return [v for v in VITALS if v in base]


def feature_names(base):
    vit = vital_cols(base)
    return (list(base)
            + [c + "_since" for c in measured_cols(base)]
            + [f"{v}_{s}" for v in vit for s in ("roll6", "delta6")])


def pretty(name):
    if name.endswith("_since"):
        return f"hours since {name[:-6]} measured"
    if name.endswith("_delta6"):
        return f"{name[:-7]} change (6h)"
    if name.endswith("_roll6"):
        return f"{name[:-6]} average (6h)"
    return name


def make_features(df, pid, base, medians):
    """Raw hourly rows (many patients allowed) -> model features. Returns a new, sorted frame."""
    df = df.copy()
    for c in base:
        if c not in df.columns:
            df[c] = np.nan
    df = df.sort_values([pid, "ICULOS"]).reset_index(drop=True)
    p = df[pid]

    # hours since each signal was last measured (0 = measured this hour). Missingness is a signal.
    for c in measured_cols(base):
        run = df[c].notna().groupby(p).cumsum()
        df[c + "_since"] = df.groupby([p, run]).cumcount()

    # missing values: carry last known value forward, never-measured -> training median
    df[base] = df.groupby(pid)[base].ffill()
    df[base] = df[base].fillna(medians)

    # short-term trends of the vitals
    g = df.groupby(pid)
    for v in vital_cols(base):
        df[v + "_roll6"] = g[v].rolling(6, min_periods=1).mean().reset_index(level=0, drop=True)
        df[v + "_delta6"] = g[v].diff(6).fillna(0)
    return df


class Scorer:
    """Loads the trained model + calibrator and scores raw hourly records."""

    def __init__(self, art="artifacts"):
        art = Path(art)
        b = joblib.load(art / "model.joblib")
        self.model, self.features, self.base = b["model"], b["features"], b["base"]
        self.medians, self.pid = b["medians"], b["pid"]
        self.iso = joblib.load(art / "calibrator.joblib")
        self.explainer = shap.TreeExplainer(self.model)

    def score(self, raw):
        f = make_features(raw, self.pid, self.base, self.medians)
        f["risk"] = self.iso.predict(self.model.predict_proba(f[self.features])[:, 1])
        return f

    def top_factors(self, row, k=3):
        """row: one-row feature frame -> [(readable name, shap value)], largest impact first."""
        sv = self.explainer.shap_values(row[self.features])[0]
        idx = np.argsort(-np.abs(sv))[:k]
        return [(pretty(self.features[j]), float(sv[j])) for j in idx]


def score_at(scorer, patient_raw, h):
    """Score using ONLY the first h hours (what has 'arrived' so far). patient_raw must be sorted."""
    f = scorer.score(patient_raw.iloc[:h])
    return f, scorer.top_factors(f.iloc[[-1]])


def stream(scorer, patient_raw):
    """The live pipeline: yields (hour, features_so_far_with_risk, top_factors) as each hour arrives."""
    patient_raw = patient_raw.sort_values("ICULOS").reset_index(drop=True)
    for h in range(1, len(patient_raw) + 1):
        f, factors = score_at(scorer, patient_raw, h)
        yield h, f, factors


if __name__ == "__main__":  # self-check: streaming == batch
    s = Scorer()
    demo = pd.read_csv("artifacts/demo_raw.csv")
    for pid_val in demo[s.pid].unique()[:5]:
        p = demo[demo[s.pid] == pid_val].sort_values("ICULOS").reset_index(drop=True)
        batch = s.score(p)["risk"].to_numpy()
        live = np.array([f["risk"].iloc[-1] for _, f, _ in stream(s, p)])
        assert np.allclose(batch, live, atol=1e-6), f"MISMATCH for patient {pid_val}"
    print("OK: hour-by-hour streaming scores match batch scores")
