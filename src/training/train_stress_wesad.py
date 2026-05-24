import argparse
import json
import os
import pickle
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from src.features.stress_features import (
    STRESS_FEATURE_COLUMNS,
    STRESS_LABELS,
    STRESS_STEP_SECONDS,
    STRESS_WINDOW_SECONDS,
    extract_stress_features,
    filter_rr_artifacts,
    save_stress_feature_schema,
)


WESAD_SAMPLE_RATE_HZ = 700.0
DEFAULT_WESAD_ROOT = os.getenv("WESAD_ROOT", "data_raw/wesad")
DEFAULT_MODEL_DIR = "models/stress"
DEFAULT_METRICS_DIR = "models/metrics"
DEFAULT_CACHE_DIR = "data_processed/stress"
VALID_SUBJECTS = [
    "S2",
    "S3",
    "S4",
    "S5",
    "S6",
    "S7",
    "S8",
    "S9",
    "S10",
    "S11",
    "S13",
    "S14",
    "S15",
    "S16",
    "S17",
]
LABEL_MAP = {1: 0, 2: 1}
LABEL_PURITY = 0.70
MIN_RR_PER_STRESS_WINDOW = 20


def _load_subject_pickle(path):
    with open(path, "rb") as f:
        return pickle.load(f, encoding="latin1")


def discover_wesad_subjects(wesad_root):
    root = Path(wesad_root)
    subjects = []
    for subject in VALID_SUBJECTS:
        path = root / subject / f"{subject}.pkl"
        if path.exists():
            subjects.append((subject, path))
    return subjects


def _detect_rr_with_labels(ecg, labels):
    try:
        import neurokit2 as nk
    except ImportError as exc:
        raise ImportError(
            "neurokit2 is required for WESAD stress training. "
            "Install dependencies with: python -m pip install -r requirements.txt"
        ) from exc

    ecg = np.asarray(ecg, dtype=float).flatten()
    labels = np.asarray(labels).flatten()
    cleaned = nk.ecg_clean(ecg, sampling_rate=int(WESAD_SAMPLE_RATE_HZ), method="neurokit")
    _, peaks = nk.ecg_peaks(cleaned, sampling_rate=int(WESAD_SAMPLE_RATE_HZ), method="pantompkins1985")
    peak_indices = np.asarray(peaks.get("ECG_R_Peaks", []), dtype=int)
    peak_indices = peak_indices[(peak_indices >= 0) & (peak_indices < labels.size)]
    if peak_indices.size < 2:
        return np.array([], dtype=float), np.array([], dtype=float), np.array([], dtype=int)

    rr_ms = np.diff(peak_indices) * 1000.0 / WESAD_SAMPLE_RATE_HZ
    rr_timestamps = peak_indices[1:] / WESAD_SAMPLE_RATE_HZ
    rr_labels = labels[peak_indices[1:]]
    valid_label_mask = np.isin(rr_labels, list(LABEL_MAP.keys()))
    rr_ms = rr_ms[valid_label_mask]
    rr_timestamps = rr_timestamps[valid_label_mask]
    rr_labels = np.array([LABEL_MAP[int(value)] for value in rr_labels[valid_label_mask]], dtype=int)

    valid_rr = filter_rr_artifacts(rr_ms)
    if valid_rr.size == rr_ms.size:
        return rr_ms, rr_timestamps, rr_labels

    keep = np.isfinite(rr_ms) & (rr_ms >= 300.0) & (rr_ms <= 2000.0)
    rr_ms = rr_ms[keep]
    rr_timestamps = rr_timestamps[keep]
    rr_labels = rr_labels[keep]
    if rr_ms.size < 2:
        return rr_ms, rr_timestamps, rr_labels

    stable = np.ones(rr_ms.size, dtype=bool)
    previous = rr_ms[0]
    for index in range(1, rr_ms.size):
        if previous <= 0:
            stable[index] = False
            continue
        if abs(rr_ms[index] - previous) / previous > 0.20:
            stable[index] = False
        else:
            previous = rr_ms[index]
    return rr_ms[stable], rr_timestamps[stable], rr_labels[stable]


def _subject_rows(subject, path):
    payload = _load_subject_pickle(path)
    ecg = payload["signal"]["chest"]["ECG"]
    labels = payload["label"]
    rr_ms, rr_timestamps, rr_labels = _detect_rr_with_labels(ecg, labels)
    if rr_ms.size < MIN_RR_PER_STRESS_WINDOW:
        return []

    rows = []
    start_time = float(rr_timestamps[0])
    end_time = float(rr_timestamps[-1])
    current = start_time
    while current + STRESS_WINDOW_SECONDS <= end_time:
        mask = (rr_timestamps >= current) & (rr_timestamps < current + STRESS_WINDOW_SECONDS)
        if np.sum(mask) >= MIN_RR_PER_STRESS_WINDOW:
            window_labels = rr_labels[mask]
            values, counts = np.unique(window_labels, return_counts=True)
            best_index = int(np.argmax(counts))
            label = int(values[best_index])
            purity = float(counts[best_index] / max(1, np.sum(counts)))
            if purity >= LABEL_PURITY:
                timestamps = rr_timestamps[mask]
                features = extract_stress_features(rr_ms[mask], rr_timestamps_sec=timestamps - timestamps[0])
                if features is not None:
                    rows.append(
                        {
                            **features,
                            "label": label,
                            "subject": subject,
                            "start_sec": current,
                            "end_sec": current + STRESS_WINDOW_SECONDS,
                            "label_purity": purity,
                        }
                    )
        current += STRESS_STEP_SECONDS
    return rows


def build_stress_dataset(wesad_root, cache_dir=DEFAULT_CACHE_DIR, force=False):
    out_dir = Path(cache_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = out_dir / "stress_features.csv"
    if dataset_path.exists() and not force:
        return pd.read_csv(dataset_path)

    subjects = discover_wesad_subjects(wesad_root)
    if not subjects:
        raise FileNotFoundError(
            f"No WESAD subject pickle files found under {wesad_root}. "
            "Expected data_raw/wesad/S2/S2.pkl, data_raw/wesad/S3/S3.pkl, ..."
        )

    rows = []
    for subject, path in subjects:
        subject_rows = _subject_rows(subject, path)
        rows.extend(subject_rows)
        print(f"{subject}: {len(subject_rows)} stress windows")

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("No stress feature windows were generated from WESAD.")
    df.to_csv(dataset_path, index=False)
    return df


def _make_models():
    rf = RandomForestClassifier(
        n_estimators=400,
        random_state=42,
        class_weight="balanced_subsample",
        min_samples_leaf=2,
        n_jobs=-1,
    )
    svm = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "svc",
                SVC(
                    kernel="rbf",
                    C=2.0,
                    gamma="scale",
                    probability=True,
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ]
    )
    return rf, svm


def _soft_vote_predict(rf, svm, X):
    rf_proba = rf.predict_proba(X)
    svm_proba = svm.predict_proba(X)
    rf_classes = [int(value) for value in rf.classes_]
    svm_classes = [int(value) for value in svm.classes_]
    probabilities = []
    for index in range(len(X)):
        by_class = {0: 0.0, 1: 0.0}
        for class_index, class_id in enumerate(rf_classes):
            by_class[class_id] += float(rf_proba[index, class_index]) / 2.0
        for class_index, class_id in enumerate(svm_classes):
            by_class[class_id] += float(svm_proba[index, class_index]) / 2.0
        probabilities.append([by_class[0], by_class[1]])
    probabilities = np.asarray(probabilities, dtype=float)
    return np.argmax(probabilities, axis=1), probabilities


def train_and_validate(df):
    X = df[STRESS_FEATURE_COLUMNS]
    y = df["label"].astype(int).to_numpy()
    groups = df["subject"].astype(str).to_numpy()
    logo = LeaveOneGroupOut()

    predictions = np.zeros_like(y)
    stress_probabilities = np.zeros(y.shape[0], dtype=float)
    fold_metrics = []
    for fold_index, (train_idx, test_idx) in enumerate(logo.split(X, y, groups), start=1):
        rf, svm = _make_models()
        rf.fit(X.iloc[train_idx], y[train_idx])
        svm.fit(X.iloc[train_idx], y[train_idx])
        fold_pred, fold_proba = _soft_vote_predict(rf, svm, X.iloc[test_idx])
        predictions[test_idx] = fold_pred
        stress_probabilities[test_idx] = fold_proba[:, 1]
        fold_metrics.append(
            {
                "fold": fold_index,
                "test_subject": str(groups[test_idx][0]),
                "accuracy": float(accuracy_score(y[test_idx], fold_pred)),
                "f1_macro": float(f1_score(y[test_idx], fold_pred, average="macro", zero_division=0)),
                "f1_stress": float(f1_score(y[test_idx], fold_pred, pos_label=1, zero_division=0)),
                "support": int(len(test_idx)),
            }
        )

    final_rf, final_svm = _make_models()
    final_rf.fit(X, y)
    final_svm.fit(X, y)
    final_scaler = StandardScaler().fit(X)

    labels = [0, 1]
    metrics = {
        "model": "soft_voting_rf_svm_wesad",
        "sample_rate_hz": WESAD_SAMPLE_RATE_HZ,
        "window_size_sec": STRESS_WINDOW_SECONDS,
        "step_size_sec": STRESS_STEP_SECONDS,
        "feature_names": STRESS_FEATURE_COLUMNS,
        "classes": {str(key): value for key, value in STRESS_LABELS.items()},
        "dataset_shape": [int(df.shape[0]), int(len(STRESS_FEATURE_COLUMNS))],
        "label_distribution": {
            STRESS_LABELS[int(label)]: int(count)
            for label, count in zip(*np.unique(y, return_counts=True))
        },
        "subject_count": int(len(set(groups))),
        "loso_accuracy_mean": float(np.mean([item["accuracy"] for item in fold_metrics])),
        "loso_f1_macro_mean": float(np.mean([item["f1_macro"] for item in fold_metrics])),
        "loso_f1_stress_mean": float(np.mean([item["f1_stress"] for item in fold_metrics])),
        "classification_report": classification_report(
            y,
            predictions,
            labels=labels,
            target_names=[STRESS_LABELS[label] for label in labels],
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": confusion_matrix(y, predictions, labels=labels).tolist(),
        "fold_metrics": fold_metrics,
        "mean_prediction_confidence": float(np.mean(np.max(np.column_stack([1 - stress_probabilities, stress_probabilities]), axis=1))),
    }
    return final_rf, final_svm, final_scaler, metrics


def save_artifacts(rf, svm, scaler, metrics, model_dir=DEFAULT_MODEL_DIR, metrics_dir=DEFAULT_METRICS_DIR):
    model_dir = Path(model_dir)
    metrics_dir = Path(metrics_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(rf, model_dir / "rf_model.pkl")
    joblib.dump(svm, model_dir / "svm_pipeline.pkl")
    joblib.dump(scaler, model_dir / "scaler_final.pkl")
    save_stress_feature_schema(model_dir / "stress_feature_schema.json")
    metadata = {
        "model_version": "soft_voting_rf_svm_wesad",
        "model_type": "soft_voting(RF + SVM_pipeline)",
        "feature_names": STRESS_FEATURE_COLUMNS,
        "classes": {str(key): value for key, value in STRESS_LABELS.items()},
        "window_size_sec": STRESS_WINDOW_SECONDS,
        "step_size_sec": STRESS_STEP_SECONDS,
        "sample_rate_hz": WESAD_SAMPLE_RATE_HZ,
        "loso_accuracy_mean": metrics["loso_accuracy_mean"],
        "loso_f1_macro_mean": metrics["loso_f1_macro_mean"],
        "loso_f1_stress_mean": metrics["loso_f1_stress_mean"],
        "dataset_shape": metrics["dataset_shape"],
        "label_distribution": metrics["label_distribution"],
    }
    (model_dir / "model_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (metrics_dir / "stress_metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "model_dir": str(model_dir),
        "metrics_path": str(metrics_dir / "stress_metrics.json"),
        "metadata": metadata,
    }


def main():
    parser = argparse.ArgumentParser(description="Train binary stress detection model from WESAD ECG RR features.")
    parser.add_argument("--wesad-root", default=DEFAULT_WESAD_ROOT, help="WESAD root, e.g. data_raw/wesad")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR, help="Output artifact directory.")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="Feature cache directory.")
    parser.add_argument("--metrics-dir", default=DEFAULT_METRICS_DIR, help="Metrics output directory.")
    parser.add_argument("--force-preprocess", action="store_true", help="Rebuild stress feature CSV.")
    parser.add_argument("--force-features", action="store_true", help="Alias for --force-preprocess.")
    parser.add_argument("--skip-importance", action="store_true", help="Accepted for compatibility; no-op.")
    args = parser.parse_args()

    df = build_stress_dataset(
        args.wesad_root,
        cache_dir=args.cache_dir,
        force=bool(args.force_preprocess or args.force_features),
    )
    rf, svm, scaler, metrics = train_and_validate(df)
    result = save_artifacts(
        rf,
        svm,
        scaler,
        metrics,
        model_dir=args.model_dir,
        metrics_dir=args.metrics_dir,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
