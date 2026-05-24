import csv
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from src.features.ecg_features import (
    ANOMALY_FEATURE_COLUMNS,
    evaluate_signal_quality,
    extract_anomaly_feature_rows,
)
from src.storage.ecg_storage import decode_raw_chunk, get_predictions_for_session, get_raw_chunk


CALIBRATION_ROOT = "dataset/realtime_logs/calibration"
MIN_BASELINE_FEATURE_ROWS = 20


def _safe_name(value):
    value = value or "unknown"
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in value)


def calibration_dir(patient_id):
    path = Path(CALIBRATION_ROOT) / _safe_name(patient_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def calibration_paths(patient_id):
    base = calibration_dir(patient_id)
    return {
        "model": base / "polar_anomaly_model.pkl",
        "scaler": base / "polar_anomaly_scaler.pkl",
        "metadata": base / "polar_anomaly_metadata.json",
    }


def has_calibration(patient_id):
    paths = calibration_paths(patient_id)
    return paths["model"].exists() and paths["scaler"].exists() and paths["metadata"].exists()


def load_calibrated_anomaly(patient_id):
    if not has_calibration(patient_id):
        return None
    paths = calibration_paths(patient_id)
    with open(paths["metadata"], "r", encoding="utf-8") as f:
        metadata = json.load(f)
    return {
        "model": joblib.load(paths["model"]),
        "scaler": joblib.load(paths["scaler"]),
        "metadata": metadata,
    }


def read_raw_ecg_csv(path):
    samples = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            samples.append(float(row["ecg_uv"]))
    return samples


def read_raw_ecg_from_prediction(prediction):
    chunk_ids = prediction.get("raw_ecg_chunk_ids") or []
    samples = []
    for chunk_id in chunk_ids:
        chunk = get_raw_chunk(chunk_id, include_payload=True)
        if chunk is not None:
            samples.extend(decode_raw_chunk(chunk))
    if samples:
        return samples
    path = prediction.get("raw_ecg_path")
    if path and Path(path).exists():
        return read_raw_ecg_csv(path)
    return []


def _fit_and_save_calibration(
    patient_id,
    rows,
    source_metadata,
    contamination=0.03,
):
    if len(rows) < MIN_BASELINE_FEATURE_ROWS:
        raise ValueError(
            f"Need at least {MIN_BASELINE_FEATURE_ROWS} baseline feature rows, got {len(rows)}. "
            "Collect a longer normal baseline session before calibration."
        )

    X = pd.DataFrame(
        [[row[col] for col in ANOMALY_FEATURE_COLUMNS] for row in rows],
        columns=ANOMALY_FEATURE_COLUMNS,
    )
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = IsolationForest(
        n_estimators=200,
        contamination=float(contamination),
        max_features=len(ANOMALY_FEATURE_COLUMNS),
        random_state=42,
    )
    model.fit(X_scaled)
    train_decision_scores = model.decision_function(X_scaled)
    # The user explicitly marks this source as normal baseline. Use the lowest
    # baseline score as the threshold so the marked baseline does not immediately
    # alert on itself; future segments below this baseline envelope are abnormal.
    decision_threshold = float(np.min(train_decision_scores) - 1e-6)

    paths = calibration_paths(patient_id)
    joblib.dump(model, paths["model"])
    joblib.dump(scaler, paths["scaler"])

    metadata = {
        "patient_id": patient_id,
        "feature_columns": ANOMALY_FEATURE_COLUMNS,
        "feature_row_count": len(rows),
        "contamination": float(contamination),
        "decision_threshold": decision_threshold,
        "model_path": str(paths["model"]),
        "scaler_path": str(paths["scaler"]),
        **source_metadata,
    }
    with open(paths["metadata"], "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    return metadata


def train_calibration_from_session(patient_id, session_id, contamination=0.03):
    predictions = get_predictions_for_session(patient_id=patient_id, session_id=session_id)
    good_predictions = [
        p
        for p in predictions
        if (p.get("raw_ecg_chunk_ids") or (p.get("raw_ecg_path") and Path(p["raw_ecg_path"]).exists()))
        and (p.get("signal_quality") or {}).get("label") in ("good", "fair")
    ]

    rows = []
    source_prediction_ids = []
    for prediction in good_predictions:
        samples = read_raw_ecg_from_prediction(prediction)
        if not samples:
            continue
        feature_rows = extract_anomaly_feature_rows(
            samples,
            sample_rate_hz=prediction["sample_rate_hz"],
            window_size=10,
            step_size=5,
            filter_signal=True,
        )
        rows.extend(feature_rows)
        source_prediction_ids.append(prediction["prediction_id"])

    return _fit_and_save_calibration(
        patient_id=patient_id,
        rows=rows,
        contamination=contamination,
        source_metadata={
            "source_type": "sqlite_session",
            "session_id": session_id,
            "source_prediction_count": len(good_predictions),
            "source_prediction_ids": source_prediction_ids,
        },
    )


def _load_real_data_metadata(path):
    metadata_path = Path(path) / "metadata.json"
    if not metadata_path.exists():
        return {}
    with open(metadata_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _real_data_session_dirs(input_dir, person_id, states):
    root = Path(input_dir) / _safe_name(person_id)
    sessions = []
    for state in states:
        state_dir = root / _safe_name(state)
        if not state_dir.exists():
            continue
        for session_dir in sorted(path for path in state_dir.iterdir() if path.is_dir()):
            if (session_dir / "ecg.csv").exists():
                sessions.append(session_dir)
    return sessions


def train_calibration_from_real_data(
    patient_id,
    input_dir="data_raw/real_data",
    states=("rest",),
    contamination=0.03,
    real_data_person_id=None,
):
    states = tuple(str(state).strip().lower() for state in states)
    source_person_id = real_data_person_id or patient_id
    session_dirs = _real_data_session_dirs(input_dir, source_person_id, states)
    if not session_dirs:
        raise FileNotFoundError(
            f"No real-data ECG sessions found for {source_person_id!r} under {input_dir} "
            f"with states {states}."
        )

    rows = []
    source_sessions = []
    skipped_sessions = []
    for session_dir in session_dirs:
        metadata = _load_real_data_metadata(session_dir)
        ecg_path = session_dir / "ecg.csv"
        sample_rate_hz = float(metadata.get("ecg_sample_rate_hz") or 130.0)
        samples = read_raw_ecg_csv(ecg_path)
        quality = evaluate_signal_quality(samples, sample_rate_hz)
        if quality.get("label") not in {"good", "fair"}:
            skipped_sessions.append(
                {
                    "session_dir": str(session_dir),
                    "reason": f"signal_quality={quality.get('label')}",
                    "signal_quality": quality,
                }
            )
            continue

        feature_rows = extract_anomaly_feature_rows(
            samples,
            sample_rate_hz=sample_rate_hz,
            window_size=10,
            step_size=5,
            filter_signal=True,
        )
        rows.extend(feature_rows)
        source_sessions.append(
            {
                "session_dir": str(session_dir),
                "state": metadata.get("state") or session_dir.parent.name,
                "sample_rate_hz": sample_rate_hz,
                "sample_count": len(samples),
                "feature_row_count": len(feature_rows),
                "signal_quality": quality,
            }
        )

    return _fit_and_save_calibration(
        patient_id=patient_id,
        rows=rows,
        contamination=contamination,
        source_metadata={
            "source_type": "real_data",
            "input_dir": str(Path(input_dir)),
            "real_data_person_id": source_person_id,
            "states": list(states),
            "source_session_count": len(source_sessions),
            "source_sessions": source_sessions,
            "skipped_sessions": skipped_sessions,
        },
    )
