from pathlib import Path

import pandas as pd
import streamlit as st

ART = Path(__file__).resolve().parent.parent / "artifacts"
st.set_page_config(page_title="Ward Board", page_icon="🏥", layout="wide")
df = pd.read_csv(ART / "dashboard_data.csv")
PID = df.columns[0]

NAMES = {"HR": "heart rate", "O2Sat": "oxygen saturation", "Temp": "temperature", "SBP": "systolic BP",
         "MAP": "mean arterial pressure", "DBP": "diastolic BP", "Resp": "respiratory rate",
         "ICULOS": "time in ICU"}


def plain(f):
    """Translate a model feature name into words a nurse understands."""
    for suffix, tmpl in (("_delta6", "rapid change in {} over 6h"), ("_roll6", "sustained shift in {}"),
                         ("_measured", "changed monitoring pattern of {}")):
        if f.endswith(suffix):
            base = f[: -len(suffix)]
            return tmpl.format(NAMES.get(base, base))
    return NAMES.get(f, f)


st.title("🏥 Ward Board: who to see first")
st.caption("Alert workload is limited. The board ranks patients by risk level plus 6-hour trend "
           "and only escalates as many as the team can actually attend.")

max_h = int(df["ICULOS"].max())
h = st.slider("ICU hour (ward clock)", 1, max_h, min(24, max_h))
K = st.sidebar.slider("Nurses' attention budget (patients reviewed now)", 1, 10, 3)

rows = []
for pid, g in df.groupby(PID):
    g = g.sort_values("ICULOS")
    upto = g[g["ICULOS"] <= h]
    if upto.empty:
        continue
    cur = upto.iloc[-1]
    past = g[g["ICULOS"] <= max(h - 6, 0)]
    prev = past.iloc[-1]["risk"] if len(past) else upto.iloc[0]["risk"]
    change = cur["risk"] - prev
    rows.append({"patient": pid, "risk": cur["risk"], "change_6h": change,
                 "priority": cur["risk"] + 0.5 * max(change, 0),
                 "drivers": ", ".join(plain(x.strip()) for x in str(cur["top_factors"]).split(",")),
                 "truth": "sepsis" if cur["SepsisLabel"] == 1 else "no sepsis"})

if not rows:
    st.warning("No patients have data at this hour. Move the slider.")
    st.stop()

board = pd.DataFrame(rows).sort_values("priority", ascending=False).reset_index(drop=True)

st.subheader(f"Review now (top {K})")
for _, r in board.head(K).iterrows():
    arrow = "rising" if r["change_6h"] > 0.005 else "falling" if r["change_6h"] < -0.005 else "flat"
    st.error(f"**Patient {r['patient']}**: risk {r['risk'] * 100:.1f}% ({arrow}, "
             f"{r['change_6h'] * 100:+.1f} pts over 6h). Main drivers: {r['drivers']}.")

st.subheader("Full ward")
show = board.copy()
show["risk"] = (show["risk"] * 100).round(1).astype(str) + "%"
show["change_6h"] = (show["change_6h"] * 100).round(1).astype(str) + " pts"
st.dataframe(show[["patient", "risk", "change_6h", "drivers", "truth"]].rename(
    columns={"truth": "ground truth (demo only)"}), use_container_width=True, hide_index=True)