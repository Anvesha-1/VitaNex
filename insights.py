"""USP evidence: lead time, workload-constrained alerting, fairness audit.
Run after train.py (needs artifacts/test_predictions.csv):   python insights.py
Outputs: artifacts/insights.json, artifacts/alert_budget.png  + a printed summary for slides.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ART = Path("artifacts")
BUDGET = 20          # target: alerts per 100 patient-days (change to taste)
PERSIST, COOLDOWN = 3, 12
WINDOW = 24          # an alert counts as an early warning only if it fires within 24h before onset

df = pd.read_csv(ART / "test_predictions.csv")
PID = df.columns[0]
df = df.sort_values([PID, "ICULOS"]).reset_index(drop=True)
patient_days = len(df) / 24                      # 1 row = 1 ICU hour

pats = {}
for pid, g in df.groupby(PID):
    pos = g.loc[g["SepsisLabel"] == 1, "ICULOS"]
    # Challenge labels turn 1 six hours BEFORE clinical onset -> onset ~ first label + 6h
    onset = pos.min() + 6 if len(pos) else None
    pats[pid] = (g["risk"].to_numpy(), g["ICULOS"].to_numpy(), onset)
n_septic = sum(1 for v in pats.values() if v[2] is not None)


def alarms(risk, hrs, thr, persist, cooldown):
    out, streak, last = [], 0, -10**9
    for i, r in enumerate(risk):
        streak = streak + 1 if r >= thr else 0
        if streak >= persist and i - last >= cooldown:
            out.append(hrs[i])
            last = i
    return out


def evaluate(thr, persist, cooldown):
    n_alarms, caught, leads = 0, 0, []
    for risk, hrs, onset in pats.values():
        a = alarms(risk, hrs, thr, persist, cooldown)
        n_alarms += len(a)                       # every alert still costs nurse attention
        if onset is not None:
            w = [x for x in a if onset - WINDOW <= x <= onset]
            if w:
                caught += 1
                leads.append(onset - w[0])
    return {
        "threshold": float(thr),
        "alerts_per_100_patient_days": 100 * n_alarms / patient_days,
        "septic_caught_early_pct": 100 * caught / max(n_septic, 1),
        "median_lead_hours": float(np.median(leads)) if leads else 0.0,
    }


thrs = np.unique(np.quantile(df["risk"], [0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99, 0.995]))
smart = [evaluate(t, PERSIST, COOLDOWN) for t in thrs]
naive = [evaluate(t, 1, 1) for t in thrs]

best = min(smart, key=lambda r: abs(r["alerts_per_100_patient_days"] - BUDGET))

# ---- fairness / robustness audit (row-level AUROC per subgroup)
audit = {}
def auc_of(sub):
    return round(float(roc_auc_score(sub["SepsisLabel"], sub["risk"])), 3) if sub["SepsisLabel"].nunique() == 2 else None
if "Age" in df.columns:
    bins = pd.cut(df["Age"], [0, 40, 65, 200], labels=["<40", "40-65", "65+"])
    for b in bins.cat.categories:
        audit[f"age {b}"] = auc_of(df[bins == b])
if "Gender" in df.columns:
    for gval, sub in df.groupby("Gender"):
        audit[f"gender {int(gval)}"] = auc_of(sub)

res = {"budget_target": BUDGET, "window_hours": WINDOW, "operating_point": best,
       "smart": smart, "naive": naive, "septic_patients": n_septic, "subgroup_auroc": audit}
json.dump(res, open(ART / "insights.json", "w"), indent=2)

plt.figure(figsize=(6, 4))
plt.plot([r["alerts_per_100_patient_days"] for r in naive], [r["septic_caught_early_pct"] for r in naive],
         "o--", label="Naive (alert every hour above threshold)")
plt.plot([r["alerts_per_100_patient_days"] for r in smart], [r["septic_caught_early_pct"] for r in smart],
         "o-", label="Ours (persistence + cooldown)")
plt.xlabel("Alerts per 100 patient-days (nurse workload)")
plt.ylabel(f"% sepsis patients alerted within {WINDOW}h before onset")
plt.legend(); plt.grid(alpha=.3); plt.tight_layout()
plt.savefig(ART / "alert_budget.png", dpi=150)

print("\n=== NUMBERS FOR YOUR SLIDES ===")
print(f"At ~{BUDGET} alerts/100 patient-days (threshold {best['threshold']:.3f}):")
print(f"  {best['septic_caught_early_pct']:.0f}% of sepsis patients alerted within {WINDOW}h before clinical onset")
print(f"  median lead time {best['median_lead_hours']:.1f} hours")
print("Subgroup AUROC:", audit)
print("Saved artifacts/insights.json and artifacts/alert_budget.png")