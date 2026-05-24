import argparse
import json
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from src.features.rhythm_features import RHYTHM_FEATURE_COLUMNS, extract_rhythm_feature_matrix
from src.preprocessing import RHYTHM_LABELS, TARGET_SAMPLE_RATE_HZ, save_json


DEFAULT_DATASET_DIR = "data_processed/rhythm"
DEFAULT_MODEL_DIR = "models/rhythm"
DEFAULT_METRICS_DIR = "models/metrics"
AFIB_CLASS_ID = 1
NOISE_CLASS_ID = 3


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


def _split_train_test(X, y, groups=None, test_size=0.2, random_state=42):
    if groups is not None:
        splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
        train_idx, test_idx = next(splitter.split(X, y, groups=groups))
        return train_idx, test_idx, "group_shuffle_split"

    stratify = _safe_stratify_labels(y)
    indices = np.arange(len(y))
    train_idx, test_idx = train_test_split(
        indices,
        test_size=test_size,
        random_state=random_state,
        stratify=stratify,
    )
    return train_idx, test_idx, "stratified_random_split" if stratify is not None else "random_split"


def _candidate_models(random_state):
    return {
        "RandomForestClassifier": RandomForestClassifier(
            n_estimators=500,
            class_weight="balanced_subsample",
            max_depth=None,
            min_samples_leaf=1,
            random_state=random_state,
            n_jobs=-1,
        ),
        "ExtraTreesClassifier": ExtraTreesClassifier(
            n_estimators=700,
            class_weight="balanced",
            max_depth=None,
            min_samples_leaf=1,
            random_state=random_state,
            n_jobs=-1,
        ),
        "HistGradientBoostingClassifier": HistGradientBoostingClassifier(
            max_iter=250,
            learning_rate=0.05,
            l2_regularization=0.05,
            random_state=random_state,
        ),
    }


def _class_weight_dict():
    # Extra emphasis on AFib recall and noise rejection. These classes are both
    # clinically important and under-represented in CinC 2017.
    return {
        0: 1.0,
        1: 2.8,
        2: 1.4,
        3: 4.0,
    }


def _evaluate_predictions(y_test, y_pred, model_name, X_shape, feature_shape, split_info, sample_rate_hz):
    labels = sorted(int(label) for label in np.unique(np.concatenate([y_test, y_pred])))
    target_names = [RHYTHM_LABELS.get(label, str(label)) for label in labels]
    report = classification_report(
        y_test,
        y_pred,
        labels=labels,
        target_names=target_names,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(y_test, y_pred, labels=labels)
    label_to_index = {label: index for index, label in enumerate(labels)}

    afib_recall = float(report.get("possible_afib", {}).get("recall", 0.0))
    noise_recall = float(report.get("noise", {}).get("recall", 0.0))
    macro_f1 = float(f1_score(y_test, y_pred, average="macro", zero_division=0))

    false_afib_from_noise_rate = 0.0
    if NOISE_CLASS_ID in label_to_index and AFIB_CLASS_ID in label_to_index:
        noise_row = cm[label_to_index[NOISE_CLASS_ID]]
        noise_total = float(np.sum(noise_row))
        if noise_total > 0:
            false_afib_from_noise_rate = float(noise_row[label_to_index[AFIB_CLASS_ID]] / noise_total)

    selection_score = macro_f1 + (0.35 * afib_recall) + (0.25 * noise_recall) - (
        0.3 * false_afib_from_noise_rate
    )

    return {
        "model": model_name,
        "sample_rate_hz": float(sample_rate_hz),
        "features": RHYTHM_FEATURE_COLUMNS,
        "classes": {str(key): value for key, value in RHYTHM_LABELS.items()},
        "dataset_shape": list(X_shape),
        "feature_shape": list(feature_shape),
        "split": split_info,
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "macro_f1": macro_f1,
        "afib_recall": afib_recall,
        "noise_recall": noise_recall,
        "false_afib_from_noise_rate": false_afib_from_noise_rate,
        "selection_score": float(selection_score),
        "classification_report": report,
        "confusion_matrix": cm.tolist(),
        "labels": labels,
    }


def _save_confusion_matrix(cm, labels, path, title):
    target_names = [RHYTHM_LABELS.get(int(label), str(label)) for label in labels]
    plt.figure(figsize=(6, 5))
    plt.imshow(cm, interpolation="nearest", cmap="Blues")
    plt.title(title)
    plt.colorbar()
    tick_marks = np.arange(len(labels))
    plt.xticks(tick_marks, target_names, rotation=30, ha="right")
    plt.yticks(tick_marks, target_names)
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def train_rhythm_feature_model(
    dataset_dir=DEFAULT_DATASET_DIR,
    model_dir=DEFAULT_MODEL_DIR,
    metrics_dir=DEFAULT_METRICS_DIR,
    sample_rate_hz=TARGET_SAMPLE_RATE_HZ,
    test_size=0.2,
    random_state=42,
):
    dataset_path = Path(dataset_dir)
    model_path = Path(model_dir)
    metrics_path = Path(metrics_dir)
    X_windows_path = dataset_path / "X.npy"
    y_path = dataset_path / "y.npy"
    if not X_windows_path.exists() or not y_path.exists():
        raise FileNotFoundError(
            f"Missing {X_windows_path} or {y_path}. "
            "Run src.dataset_builders.build_cinc2017 first."
        )

    X_windows = np.load(X_windows_path)
    y = np.load(y_path)
    X_features, _ = extract_rhythm_feature_matrix(X_windows, sample_rate_hz=sample_rate_hz)
    groups = _load_groups(dataset_path, expected_rows=len(y))

    train_idx, test_idx, split_strategy = _split_train_test(
        X_features,
        y,
        groups=groups,
        test_size=test_size,
        random_state=random_state,
    )
    X_train = X_features[train_idx]
    X_test = X_features[test_idx]
    y_train = y[train_idx]
    y_test = y[test_idx]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    sample_weight = compute_sample_weight(class_weight=_class_weight_dict(), y=y_train)
    split_info = {
        "strategy": split_strategy,
        "test_size": float(test_size),
        "train_rows": int(len(train_idx)),
        "test_rows": int(len(test_idx)),
        "train_record_count": int(len(set(groups[train_idx]))) if groups is not None else None,
        "test_record_count": int(len(set(groups[test_idx]))) if groups is not None else None,
        "record_overlap_count": int(len(set(groups[train_idx]) & set(groups[test_idx]))) if groups is not None else None,
    }

    candidate_metrics = []
    best_model = None
    best_metrics = None
    for model_name, model in _candidate_models(random_state).items():
        model.fit(X_train_scaled, y_train, sample_weight=sample_weight)
        y_pred = model.predict(X_test_scaled)
        metrics = _evaluate_predictions(
            y_test,
            y_pred,
            model_name=model_name,
            X_shape=X_windows.shape,
            feature_shape=X_features.shape,
            split_info=split_info,
            sample_rate_hz=sample_rate_hz,
        )
        candidate_metrics.append(metrics)
        if best_metrics is None or metrics["selection_score"] > best_metrics["selection_score"]:
            best_metrics = metrics
            best_model = model

    metrics = {
        **best_metrics,
        "selected_model": best_metrics["model"],
        "candidate_metrics": candidate_metrics,
    }

    model_path.mkdir(parents=True, exist_ok=True)
    metrics_path.mkdir(parents=True, exist_ok=True)
    joblib.dump(best_model, model_path / "rhythm_feature_model.pkl")
    joblib.dump(scaler, model_path / "rhythm_scaler.pkl")
    save_json(model_path / "rhythm_feature_schema.json", {"features": RHYTHM_FEATURE_COLUMNS})
    save_json(model_path / "label_map.json", {"labels": {str(key): value for key, value in RHYTHM_LABELS.items()}})
    save_json(metrics_path / "rhythm_feature_metrics.json", metrics)

    labels = metrics["labels"]
    cm = np.asarray(metrics["confusion_matrix"])
    _save_confusion_matrix(
        cm,
        labels,
        metrics_path / "rhythm_feature_confusion_matrix.png",
        f"Rhythm Feature Model - {metrics['selected_model']}",
    )

    return metrics


def parse_args():
    parser = argparse.ArgumentParser(description="Train rhythm feature baseline model.")
    parser.add_argument("--dataset-dir", default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--metrics-dir", default=DEFAULT_METRICS_DIR)
    parser.add_argument("--sample-rate-hz", type=float, default=TARGET_SAMPLE_RATE_HZ)
    parser.add_argument("--test-size", type=float, default=0.2)
    return parser.parse_args()


def main():
    args = parse_args()
    metrics = train_rhythm_feature_model(
        dataset_dir=args.dataset_dir,
        model_dir=args.model_dir,
        metrics_dir=args.metrics_dir,
        sample_rate_hz=args.sample_rate_hz,
        test_size=args.test_size,
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
