"""ICU Early Warning dashboard.  Run:  streamlit run app.py
Live monitor: raw hourly records are fed one hour at a time through pipeline.py
(features -> XGBoost -> calibration -> SHAP). Nothing is precomputed for that tab.
"""
import json
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pipeline import Scorer, stream, score_at, vital_cols

ART = Path("artifacts")
st.set_page_config(page_title="ICU Early Warning", page_icon="🫀", layout="wide")

if not (ART / "model.joblib").exists():
    st.error("No trained model found. Run:  python train.py data/sepsis.csv")
    st.stop()


@st.cache_resource
def get_scorer():
    return Scorer(ART)


@st.cache_data
def load_demo():
    return pd.read_csv(ART / "demo_raw.csv")


@st.cache_data
def load_test():
    t = pd.read_csv(ART / "test_risk.csv")
    pts = []
    for _, g in t.sort_values([t.columns[0], "ICULOS"]).groupby(t.columns[0]):
        lab = g["SepsisLabel"].to_numpy()
        pts.append((g["risk"].tolist(), int(lab.argmax()) if lab.any() else -1))
    return pts


def smart_alarm_hours(risk, thr, persist, cooldown):
    """Fire only if risk stays >= thr for `persist` hours, then stay quiet for `cooldown` hours."""
    fires, streak, last = [], 0, -10**9
    for i, r in enumerate(risk):
        streak = streak + 1 if r >= thr else 0
        if streak >= persist and i - last >= cooldown:
            fires.append(i)
            last = i
    return fires


@st.cache_data
def alarm_stats(thr, persist, cooldown):
    raw_total = smart_total = septic = caught = healthy_alarmed = healthy = 0
    leads = []
    for r, onset in load_test():
        raw_total += sum(x >= thr for x in r)
        f = smart_alarm_hours(r, thr, persist, cooldown)
        smart_total += len(f)
        if onset >= 0:
            septic += 1
            if f and f[0] <= onset + 6:
                caught += 1
                leads.append(onset - f[0])
        else:
            healthy += 1
            healthy_alarmed += bool(f)
    return raw_total, smart_total, septic, caught, leads, healthy, healthy_alarmed


scorer = get_scorer()
demo = load_demo()
PID = scorer.pid
VITALS = vital_cols(scorer.base)

# ---------------- sidebar ----------------
st.sidebar.title("Alarm settings")
thr = st.sidebar.slider("Risk threshold", 0.01, 0.90, 0.20, 0.01)
persist = st.sidebar.slider("Persistence (hours above threshold)", 1, 6, 3)
cooldown = st.sidebar.slider("Cooldown after alarm (hours)", 1, 24, 12)
st.sidebar.caption("Decision-support prototype on public data (PhysioNet 2019). Not a clinical diagnostic tool.")

st.title("🫀 ICU Early Warning Engine")
tab1, tab2, tab3 = st.tabs(["Live monitor", "Alarm fatigue", "Model"])

# ---------------- tab 1: live monitor ----------------
with tab1:
    pid = st.selectbox("Patient", sorted(demo[PID].unique()))
    p = demo[demo[PID] == pid].sort_values("ICULOS").reset_index(drop=True)
    n = len(p)
    upto = st.slider("Hours in ICU (drag to replay)", 1, n, min(n, 12)) if n > 1 else 1
    play = st.button("▶ Play live stream")
    slot = st.empty()

    def render(h, view, factors):
        cur = view.iloc[-1]
        fires = smart_alarm_hours(view["risk"].tolist(), thr, persist, cooldown)
        with slot.container():
            if fires and h - 1 - fires[-1] < 3:
                st.error(f"🚨 ALARM: patient {pid} at high risk of deterioration")
            elif cur["risk"] >= thr:
                st.warning("⚠️ Risk elevated, monitoring (alarm not yet triggered)")
            else:
                st.success("✅ Stable")
            c1, c2, c3 = st.columns(3)
            c1.metric("Current risk", f"{cur['risk'] * 100:.1f}%")
            c2.metric("ICU hour", int(cur["ICULOS"]))
            c3.metric("Ground truth (demo only)", "Sepsis" if cur["SepsisLabel"] == 1 else "No sepsis")
            drivers = "  ·  ".join(f"{'↑' if s > 0 else '↓'} {name}" for name, s in factors)
            st.info(f"**Top contributing factors (SHAP):** {drivers}")
            st.caption("↑ pushes risk up, ↓ pushes risk down. Scored using only the hours that have arrived so far.")

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=view["ICULOS"], y=view["risk"], mode="lines", name="Risk"))
            fig.add_hline(y=thr, line_dash="dash", line_color="red", annotation_text="threshold")
            if fires:
                fig.add_trace(go.Scatter(x=view["ICULOS"].iloc[fires], y=view["risk"].iloc[fires],
                                         mode="markers", marker=dict(size=13, color="red"), name="Alarm"))
            fig.update_layout(height=320, yaxis_title="Calibrated risk", xaxis_title="ICU hour",
                              margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch", key=f"risk{pid}{h}")

            if VITALS:
                vf = go.Figure()
                for v in VITALS:
                    vf.add_trace(go.Scatter(x=view["ICULOS"], y=view[v], mode="lines", name=v))
                vf.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(vf, width="stretch", key=f"vit{pid}{h}")

    if play:
        for h, view, factors in stream(scorer, p):   # the live pipeline
            render(h, view, factors)
            time.sleep(0.1)
    else:
        view, factors = score_at(scorer, p, upto)
        render(upto, view, factors)

# ---------------- tab 2: alarm fatigue (full held-out test set, real prevalence) ----------------
with tab2:
    raw_total, smart_total, septic, caught, leads, healthy, healthy_alarmed = alarm_stats(thr, persist, cooldown)
    red = 100 * (1 - smart_total / raw_total) if raw_total else 0
    a, b, c, d = st.columns(4)
    a.metric("Naive alerts (every hour above threshold)", raw_total)
    b.metric("Smart alerts (persistence + cooldown)", smart_total)
    c.metric("Alert reduction", f"{red:.0f}%")
    d.metric("Sepsis patients caught", f"{caught}/{septic}")
    st.caption(f"Evaluated on all {septic + healthy} held-out test patients ({septic} with sepsis), "
               f"so the mix matches real prevalence. Healthy patients with any alarm: {healthy_alarmed}/{healthy}.")
    if leads:
        st.caption(f"Median lead vs. first positive label: {pd.Series(leads).median():.0f} h (positive = earlier)")
    st.write("Tune the sliders in the sidebar and watch the trade-off between fewer alarms and patients caught.")

# ---------------- tab 3: model ----------------
with tab3:
    mp = ART / "metrics.json"
    if mp.exists():
        m = json.load(open(mp))
        cols = st.columns(3)
        cols[0].metric("AUROC", m["AUROC"])
        cols[1].metric("AUPRC", m["AUPRC"])
        cols[2].metric("Brier (calibration)", m["Brier"])
        st.caption(f"Held-out test set: {m['test_patients']} patients, split by patient (no leakage).")
    left, right = st.columns(2)
    if (ART / "shap_summary.png").exists():
        left.image(str(ART / "shap_summary.png"), caption="Global feature importance (SHAP)")
    if (ART / "calibration.png").exists():
        right.image(str(ART / "calibration.png"), caption="Calibration: predicted risk vs observed sepsis rate")
