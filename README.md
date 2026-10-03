# ICU Early Warning Engine (JNU Hackathon, Track 4.6)

Predicts ICU patient deterioration hours early, with a calibrated risk score,
SHAP explanations and alarm-fatigue reduction. Decision-support prototype on
public data (PhysioNet/Computing in Cardiology Challenge 2019). Not for clinical use.

## Run
    pip install -r requirements.txt
    python train.py data/sepsis.csv     # one CSV with a Patient_ID column
    python pipeline.py                  # optional check: streaming scores == batch scores
    streamlit run app.py

## Structure
    data/          raw CSV (not committed)
    artifacts/     created by train.py (model, calibrator, metrics, plots, demo data)
    pipeline.py    shared features + Scorer + hour-by-hour stream() (used by train and app)
    train.py       split by patient, XGBoost, isotonic calibration, SHAP, calibration curve
    app.py         dashboard: live monitor streams RAW hourly records through pipeline.py

## Pipeline
raw hourly record -> forward-fill + "hours since measured" + 6h trends -> XGBoost
-> isotonic calibration -> SHAP top drivers -> persistence/cooldown alarm logic
