import numpy as np
import pandas as pd
from pipeline import Scorer

s = Scorer()
demo = pd.read_csv("artifacts/demo_raw.csv")

parts = []
for pid_val in demo[s.pid].unique():
    p = demo[demo[s.pid] == pid_val].sort_values("ICULOS").reset_index(drop=True)
    f = s.score(p)

    sv = s.explainer.shap_values(f[s.features])
    if isinstance(sv, list):
        sv = sv[1]
    sv = np.asarray(sv)
    if sv.ndim == 3:
        sv = sv[:, :, 1]

    top = []
    for row in sv:
        idx = np.argsort(-np.abs(row))[:3]
        top.append(", ".join(s.features[j] for j in idx))
    f["top_factors"] = top

    parts.append(f[[s.pid, "ICULOS", "SepsisLabel", "risk", "top_factors"]])

out = pd.concat(parts, ignore_index=True)
out.to_csv("artifacts/dashboard_data.csv", index=False)
print("Saved", len(out), "rows")