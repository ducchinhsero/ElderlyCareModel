import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from src.features.rhythm_features import RHYTHM_FEATURE_COLUMNS, extract_rhythm_feature_matrix
from src.preprocessing import RHYTHM_LABEL_MAP, TARGET_SAMPLE_RATE_HZ, save_json


DEFAULT_DATASET_DIR = "data_processed/rhythm"
DEFAULT_MODEL_DIR = "models/rhythm"
DEFAULT_METRICS_DIR = "models/metrics"
DEFAULT_DECISION_CONFIG_PATH = "models/rhythm/rhythm_decision_config.json"
DEFAULT_RUNTIME_CONFIG_PATH = "models/runtime/sensor_context_config.json"
AFIB_CLASS_ID = RHYTHM_LABEL_MAP["possible_afib"]


def _safe_stratify_labels(y):
    _, counts = np.unique(y, return_counts=True)
    if len(counts) < 2 or np.min(counts) < 2:
        return None
    return y


def _load_groups(dataset_path, expected_rows):
    metadata_path = Path(dataset_path) / "metadata.csv"
    if not metadata_path.exists():
        return None
    metadata = pd.read_csv(metadata_path)
    if "record_id" not in metadata.columns or len(metadata) != expected_rows:
        return None
    return metadata["record_id"].astype(str).to_numpy()


def _split_indices(X, y, groups=None, test_size=0.2, random_state=42):
    if groups is not None:
        splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
        train_idx, test_idx = next(splitter.split(X, y, groups=groups))
        return train_idx, test_idx, "group_shuffle_split"

    indices = np.arange(len(y))
    stratify = _safe_stratify_labels(y)
    train_idx, test_idx = train_test_split(
        indices,
        test_size=test_size,
        random_state=random_state,
        stratify=stratify,
    )
    return train_idx, test_idx, "stratified_random_split" if stratify is not None else "random_split"


def _predict_afib_probabilities(X_windows, model, scaler, chunk_size=512, sample_rate_hz=TARGET_SAMPLE_RATE_HZ):
    class_to_index = {int(class_id): index for index, class_id in enumerate(model.classes_)}
    if AFIB_CLASS_ID not in class_to_index:
        raise ValueError("Loaded rhythm model has no possible_afib class.")

    probabilities = []
    for start in range(0, len(X_windows), int(chunk_size)):
        batch = X_windows[start : start + int(chunk_size)]
        X_features, _ = extract_rhythm_feature_matrix(
            batch,
            sample_rate_hz=sample_rate_hz,
            feature_columns=RHYTHM_FEATURE_COLUMNS,
        )
        X_scaled = scaler.transform(X_features)
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X_scaled)
            probabilities.extend(proba[:, class_to_index[AFIB_CLASS_ID]].tolist())
        else:
            pred = model.predict(X_scaled)
            probabilities.extend((pred == AFIB_CLASS_ID).astype(float).tolist())
    return np.asarray(probabilities, dtype=float)


def threshold_metrics(y_true_afib, afib_probabilities, thresholds):
    rows = []
    y_true = np.asarray(y_true_afib, dtype=int)
    probs = np.asarray(afib_probabilities, dtype=float)
    for threshold in thresholds:
        pred = (probs >= float(threshold)).astype(int)
        rows.append(
            {
                "threshold": float(threshold),
                "precision": float(precision_score(y_true, pred, zero_division=0)),
                "recall": float(recall_score(y_true, pred, zero_division=0)),
                "f1": float(f1_score(y_true, pred, zero_division=0)),
                "predicted_positive_ratio": float(np.mean(pred)) if len(pred) else 0.0,
            }
        )
    return rows


def select_threshold(rows, target_recall=0.9, precision_floor=0.8):
    constrained = [
        row
        for row in rows
        if row["recall"] >= float(target_recall)
        and row["precision"] >= float(precision_floor)
    ]
    if constrained:
        selected = max(
            constrained,
            key=lambda row: (
                row["f1"],
                row["precision"],
                -row["predicted_positive_ratio"],
            ),
        )
        return selected, False

    selected = max(
        rows,
        key=lambda row: (
            row["f1"],
            row["recall"],
            row["precision"],
        ),
    )
    return selected, True


def _read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _update_decision_config(path, selected, report_path):
    payload = _read_json(path)
    payload.update(
        {
            "alert_threshold": float(selected["threshold"]),
            "alert_threshold_source": "rhythm_validation_threshold_tuning",
            "alert_threshold_metrics_path": str(report_path),
            "alert_threshold_selected_metrics": selected,
        }
    )
    save_json(path, payload)
    return payload


def _update_runtime_config(path, selected, report_path):
    payload = _read_json(path)
    rhythm_alert = dict(payload.get("rhythm_alert") or {})
    rhythm_alert["possible_afib_medium_probability"] = float(selected["threshold"])
    rhythm_alert["possible_afib_medium_probability_source"] = "rhythm_validation_threshold_tuning"
    rhythm_alert["possible_afib_medium_probability_metrics_path"] = str(report_path)
    notes = list(rhythm_alert.get("notes") or [])
    note = (
        "possible_afib_medium_probability is tuned on rhythm validation data "
        "to improve AFib recall while keeping precision above the configured floor."
    )
    if note not in notes:
        notes.append(note)
    rhythm_alert["notes"] = notes
    payload["rhythm_alert"] = rhythm_alert
    save_json(path, payload)
    return payload


def tune_rhythm_thresholds(
    dataset_dir=DEFAULT_DATASET_DIR,
    model_dir=DEFAULT_MODEL_DIR,
    metrics_dir=DEFAULT_METRICS_DIR,
    decision_config_path=DEFAULT_DECISION_CONFIG_PATH,
    runtime_config_path=DEFAULT_RUNTIME_CONFIG_PATH,
    sample_rate_hz=TARGET_SAMPLE_RATE_HZ,
    test_size=0.2,
    random_state=42,
    chunk_size=512,
    target_recall=0.9,
    precision_floor=0.8,
    apply=False,
):
    dataset_path = Path(dataset_dir)
    model_path = Path(model_dir)
    metrics_path = Path(metrics_dir)
    X_path = dataset_path / "X.npy"
    y_path = dataset_path / "y.npy"
    if not X_path.exists() or not y_path.exists():
        raise FileNotFoundError(f"Missing {X_path} or {y_path}. Build rhythm dataset first.")

    X = np.load(X_path)
    y = np.load(y_path)
    groups = _load_groups(dataset_path, expected_rows=len(y))
    _, test_idx, split_strategy = _split_indices(
        X,
        y,
        groups=groups,
        test_size=test_size,
        random_state=random_state,
    )
    model = joblib.load(model_path / "rhythm_feature_model.pkl")
    scaler = joblib.load(model_path / "rhythm_scaler.pkl")
    probs = _predict_afib_probabilities(
        X[test_idx],
        model,
        scaler,
        chunk_size=chunk_size,
        sample_rate_hz=sample_rate_hz,
    )
    y_true_afib = (y[test_idx] == AFIB_CLASS_ID).astype(int)
    thresholds = np.round(np.arange(0.01, 0.61, 0.01), 2)
    rows = threshold_metrics(y_true_afib, probs, thresholds)
    selected, fallback_used = select_threshold(
        rows,
        target_recall=target_recall,
        precision_floor=precision_floor,
    )
    current_03 = min(rows, key=lambda row: abs(row["threshold"] - 0.30))

    report = {
        "source": "rhythm_validation_threshold_tuning",
        "dataset_dir": str(dataset_path),
        "model_dir": str(model_path),
        "sample_rate_hz": float(sample_rate_hz),
        "split": {
            "strategy": split_strategy,
            "test_size": float(test_size),
            "test_rows": int(len(test_idx)),
            "test_record_count": int(len(set(groups[test_idx]))) if groups is not None else None,
            "record_overlap_count": 0 if groups is not None else None,
        },
        "policy": {
            "target_recall": float(target_recall),
            "precision_floor": float(precision_floor),
            "fallback_used": bool(fallback_used),
            "objective": "maximize f1 among thresholds satisfying recall and precision constraints",
        },
        "selected_threshold": selected,
        "previous_0_30_threshold": current_03,
        "threshold_sweep": rows,
    }
    metrics_path.mkdir(parents=True, exist_ok=True)
    report_path = metrics_path / "rhythm_threshold_tuning.json"
    save_json(report_path, report)

    if apply:
        report["updated_decision_config"] = _update_decision_config(
            decision_config_path,
            selected,
            report_path,
        )
        report["updated_runtime_config_path"] = str(runtime_config_path)
        _update_runtime_config(runtime_config_path, selected, report_path)
        save_json(report_path, report)

    return report


def parse_args():
    parser = argparse.ArgumentParser(description="Tune realtime AFib probability threshold for rhythm feature model.")
    parser.add_argument("--dataset-dir", default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--metrics-dir", default=DEFAULT_METRICS_DIR)
    parser.add_argument("--decision-config-path", default=DEFAULT_DECISION_CONFIG_PATH)
    parser.add_argument("--runtime-config-path", default=DEFAULT_RUNTIME_CONFIG_PATH)
    parser.add_argument("--sample-rate-hz", type=float, default=TARGET_SAMPLE_RATE_HZ)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--target-recall", type=float, default=0.9)
    parser.add_argument("--precision-floor", type=float, default=0.8)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    report = tune_rhythm_thresholds(
        dataset_dir=args.dataset_dir,
        model_dir=args.model_dir,
        metrics_dir=args.metrics_dir,
        decision_config_path=args.decision_config_path,
        runtime_config_path=args.runtime_config_path,
        sample_rate_hz=args.sample_rate_hz,
        test_size=args.test_size,
        chunk_size=args.chunk_size,
        target_recall=args.target_recall,
        precision_floor=args.precision_floor,
        apply=args.apply,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
