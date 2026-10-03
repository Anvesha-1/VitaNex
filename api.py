"""Backend for the custom Ward Board UI. Same ranking logic as pages/Ward_Board.py.
Run:  uvicorn api:app --reload      then open http://127.0.0.1:8000

Fix in this version: patient IDs are normalised ("16577", 16577 and "16577.0" all match),
vitals are carried forward AND back-filled so early hours are never blank, and a
/api/debug endpoint shows what the server actually loaded.
"""
import json
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts"
WEB = ROOT / "web"


def norm(x):
    """One canonical string per patient id, whatever dtype the CSV gave us."""
    s = str(x).strip()
    return s[:-2] if s.endswith(".0") else s


df = pd.read_csv(ART / "dashboard_data.csv")
PID = df.columns[0]
GROUPS = {norm(p): g.sort_values("ICULOS").reset_index(drop=True) for p, g in df.groupby(PID)}

NAMES = {"HR": "heart rate", "O2Sat": "oxygen saturation", "Temp": "temperature", "SBP": "systolic BP",
         "MAP": "mean arterial pressure", "DBP": "diastolic BP", "Resp": "respiratory rate",
         "ICULOS": "time in ICU"}


def plain(f):
    """Translate a model feature name into words a nurse understands."""
    for suffix, tmpl in (("_delta6", "rapid change in {} over 6h"), ("_roll6", "sustained shift in {}"),
                         ("_since", "changed monitoring pattern of {}"),
                         ("_measured", "changed monitoring pattern of {}")):
        if f.endswith(suffix):
            base = f[: -len(suffix)]
            return tmpl.format(NAMES.get(base, base))
    return NAMES.get(f, f)


def _f(x):
    return 0.0 if pd.isna(x) else float(x)


app = FastAPI(title="ICU Early Warning")


@app.exception_handler(Exception)
async def _err(request, exc):
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.get("/api/meta")
def meta():
    return {"max_hour": int(df["ICULOS"].max()), "patients": int(df[PID].nunique())}


@app.get("/api/board")
def board(hour: int = 24, k: int = 3):
    rows = []
    for pid, g in GROUPS.items():
        upto = g[g["ICULOS"] <= hour]
        if upto.empty:
            continue
        cur = upto.iloc[-1]
        past = g[g["ICULOS"] <= max(hour - 6, 0)]
        prev = past.iloc[-1]["risk"] if len(past) else upto.iloc[0]["risk"]
        change = _f(cur["risk"] - prev)
        rows.append({
            "patient": pid, "risk": _f(cur["risk"]), "change_6h": change,
            "priority": _f(cur["risk"]) + 0.5 * max(change, 0),
            "drivers": [plain(x.strip()) for x in str(cur["top_factors"]).split(",")],
            "truth": "sepsis" if cur["SepsisLabel"] == 1 else "no sepsis",
            "trend": [round(_f(v), 4) for v in upto["risk"].tolist()[-24:]],
        })
    rows.sort(key=lambda r: r["priority"], reverse=True)
    return {"hour": hour, "k": k, "board": rows}


@app.get("/api/metrics")
def metrics():
    p = ART / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else {}


DEMO = pd.read_csv(ART / "demo_raw.csv")
DEMO[PID] = DEMO[PID].map(norm)
RAW = DEMO.sort_values([PID, "ICULOS"]).reset_index(drop=True)   # full feature rows (used for live SHAP: demo patients only)
ALLV = ["HR", "O2Sat", "Resp", "SBP", "DBP", "Temp", "Lactate", "MAP"]


def load_vitals():
    """Vitals for EVERY board patient come from data/sepsis.csv (read in chunks); fall back to demo_raw.csv."""
    src = ROOT / "data" / "sepsis.csv"
    if src.exists():
        head = pd.read_csv(src, nrows=0).columns
        if PID in head and "ICULOS" in head:
            cols = [PID, "ICULOS"] + [c for c in ALLV + ["Age", "Gender"] if c in head]
            keep, parts = set(GROUPS), []
            for ch in pd.read_csv(src, usecols=cols, chunksize=250_000):
                ch[PID] = ch[PID].map(norm)
                parts.append(ch[ch[PID].isin(keep)])
            v = pd.concat(parts, ignore_index=True)
            if len(v):
                return v, "data/sepsis.csv"
    cols = [c for c in [PID, "ICULOS"] + ALLV + ["Age", "Gender"] if c in RAW.columns]
    return RAW[cols].copy(), "artifacts/demo_raw.csv"


RAWF, VSRC = load_vitals()
VIT = [c for c in ALLV if c in RAWF.columns]
RAWF = RAWF.sort_values([PID, "ICULOS"]).reset_index(drop=True)
# Fill each patient's vitals forward (last known reading), then backward so the first hours are not blank.
RAWF[VIT] = RAWF.groupby(PID)[VIT].transform(lambda s: s.ffill().bfill())
FIRST = RAWF.groupby(PID).head(1)


def _n(v, d=1):
    return None if pd.isna(v) else round(float(v), d)


@app.get("/api/patient/{pid}")
def patient(pid: str, hour: int = 24):
    """Latest vitals + 24h history + demographics for one patient at a given hour."""
    pid = norm(pid)
    g = RAWF[RAWF[PID] == pid]
    if g.empty:
        return {"vitals": {}, "hr": [], "spo2": [], "age": None, "gender": None}
    upto = g[g["ICULOS"] <= hour]
    if upto.empty:                      # patient's first reading is later than this hour: show the earliest one
        upto = g.head(1)
    v = upto.iloc[-1]
    return {"vitals": {c: _n(v[c]) for c in VIT},
            "hr": [_n(x) for x in upto["HR"].tolist()[-24:]] if "HR" in upto else [],
            "spo2": [_n(x) for x in upto["O2Sat"].tolist()[-24:]] if "O2Sat" in upto else [],
            "age": _n(upto["Age"].iloc[-1], 0) if "Age" in upto else None,
            "gender": (None if "Gender" not in upto or pd.isna(upto["Gender"].iloc[-1])
                       else ("Female" if int(upto["Gender"].iloc[-1]) == 0 else "Male"))}


@app.get("/api/vitals")
def vitals(hour: int = 24):
    """Latest vitals for every patient at a given hour (the live vitals feed for the whole ward)."""
    now = RAWF[RAWF["ICULOS"] <= hour]
    g = pd.concat([FIRST, now]).groupby(PID).tail(1).set_index(PID)[VIT].round(1)   # current row, else the earliest
    return {k: {c: (None if pd.isna(x) else float(x)) for c, x in r.items()} for k, r in g.to_dict("index").items()}


@app.get("/api/debug")
def debug():
    """Open /api/debug in the browser if vitals look empty."""
    a, b = set(GROUPS), set(RAWF[PID])
    return {"id_column": PID, "board_patients": len(a), "raw_patients": len(b), "matching": len(a & b),
            "sample_board_ids": sorted(a)[:5], "sample_raw_ids": sorted(b)[:5],
            "vitals_source": VSRC, "vital_columns_found": VIT, "raw_columns": list(RAW.columns)[:40]}


_scorer = None


@app.get("/api/shap/{pid}")
def shap_factors(pid: str, hour: int = 24, k: int = 5):
    """Top SHAP drivers for one patient at a given hour, using the same Scorer as pipeline.py."""
    global _scorer
    try:
        from pipeline import Scorer
        if _scorer is None:
            _scorer = Scorer(ART)
        g = RAW[RAW[PID] == norm(pid)].sort_values("ICULOS")
        g = g[g["ICULOS"] <= hour].reset_index(drop=True)
        if g.empty:
            return {"factors": []}
        f = _scorer.score(g)
        return {"factors": [[n, v] for n, v in _scorer.top_factors(f.iloc[[-1]], k=k)]}
    except Exception as e:
        return {"factors": [], "error": str(e)}


app.mount("/artifacts", StaticFiles(directory=ART), name="artifacts")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")