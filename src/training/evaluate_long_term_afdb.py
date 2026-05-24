import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_score, recall_score

from src.features.rhythm_features import RHYTHM_FEATURE_COLUMNS, extract_rhythm_feature_matrix
from src.inference.af_episode_tracker import AFEpisodeTracker
from src.preprocessing import RHYTHM_LABEL_MAP, save_json


DEFAULT_DATASET_DIR = "data_processed/afdb_windows"
DEFAULT_MODEL_DIR = "models/rhythm"
DEFAULT_METRICS_DIR = "models/metrics"
DEFAULT_CACHE_NAME = "afdb_rhythm_eval_cache.npz"
DEFAULT_DECISION_CONFIG_PATH = "models/rhythm/rhythm_decision_config.json"
AFIB_CLASS_ID = RHYTHM_LABEL_MAP["possible_afib"]


def _segments_from_binary(values, window_seconds=30.0):
    segments = []
    start = None
    for index, value in enumerate(list(values) + [0]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            segments.append(
                {
                    "start_window": int(start),
                    "end_window": int(index),
                    "start_seconds": float(start * window_seconds),
                    "end_seconds": float(index * window_seconds),
                    "duration_seconds": float((index - start) * window_seconds),
                }
            )
            start = None
    return segments


def _keep_min_consecutive_windows(values, min_consecutive_windows=2):
    values = np.asarray(values).astype(int)
    filtered = np.zeros_like(values)
    start = None
    for index, value in enumerate(list(values) + [0]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index - start >= int(min_consecutive_windows):
                filtered[start:index] = 1
            start = None
    return filtered


def _overlaps(a, b):
    return min(a["end_seconds"], b["end_seconds"]) > max(a["start_seconds"], b["start_seconds"])


def _episode_metrics(true_binary, pred_binary, window_seconds=30.0, include_segments=False):
    true_segments = _segments_from_binary(true_binary, window_seconds)
    pred_segments = _segments_from_binary(pred_binary, window_seconds)
    matched_true = set()
    matched_pred = set()
    for pred_index, pred in enumerate(pred_segments):
        for true_index, true in enumerate(true_segments):
            if _overlaps(pred, true):
                matched_pred.add(pred_index)
                matched_true.add(true_index)
                break
    total_hours = max(len(true_binary) * window_seconds / 3600.0, 1e-9)
    metrics = {
        "true_episode_count": int(len(true_segments)),
        "predicted_episode_count": int(len(pred_segments)),
        "episode_sensitivity": float(len(matched_true) / len(true_segments)) if true_segments else 0.0,
        "episode_precision": float(len(matched_pred) / len(pred_segments)) if pred_segments else 0.0,
        "false_episode_per_hour": float((len(pred_segments) - len(matched_pred)) / total_hours),
    }
    if include_segments:
        metrics["true_segments_preview"] = true_segments[:20]
        metrics["predicted_segments_preview"] = pred_segments[:20]
    return metrics


def _binary_prediction_at_threshold(pred_labels, afib_probabilities, threshold, decision_mode):
    afib_probabilities = np.asarray(afib_probabilities)
    if decision_mode == "argmax_and_threshold":
        return (
            (np.asarray(pred_labels) == AFIB_CLASS_ID)
            & (afib_probabilities >= float(threshold))
        ).astype(int)
    if decision_mode == "probability_only":
        return (afib_probabilities >= float(threshold)).astype(int)
    raise ValueError(f"Unsupported decision mode: {decision_mode}")


def _binary_metrics_at_threshold(
    y_true_afib,
    pred_labels,
    afib_probabilities,
    threshold,
    window_seconds,
    decision_mode,
    min_consecutive_windows=2,
):
    pred_binary = _binary_prediction_at_threshold(
        pred_labels,
        afib_probabilities,
        threshold=threshold,
        decision_mode=decision_mode,
    )
    episode_binary = _keep_min_consecutive_windows(
        pred_binary,
        min_consecutive_windows=min_consecutive_windows,
    )
    episode_metrics = _episode_metrics(y_true_afib, episode_binary, window_seconds=window_seconds)
    true_burden = float(100.0 * np.mean(y_true_afib)) if len(y_true_afib) else 0.0
    pred_burden = float(100.0 * np.mean(pred_binary)) if len(pred_binary) else 0.0
    episode_burden = float(100.0 * np.mean(episode_binary)) if len(episode_binary) else 0.0
    return {
        "decision_mode": decision_mode,
        "threshold": float(threshold),
        "min_consecutive_windows": int(min_consecutive_windows),
        "precision": float(precision_score(y_true_afib, pred_binary, zero_division=0)),
        "recall": float(recall_score(y_true_afib, pred_binary, zero_division=0)),
        "f1": float(f1_score(y_true_afib, pred_binary, zero_division=0)),
        "predicted_af_burden_percent": pred_burden,
        "episode_af_burden_percent": episode_burden,
        "af_burden_absolute_error_percent": abs(pred_burden - true_burden),
        "episode_af_burden_absolute_error_percent": abs(episode_burden - true_burden),
        "episode_sensitivity": episode_metrics["episode_sensitivity"],
        "episode_precision": episode_metrics["episode_precision"],
        "false_episode_per_hour": episode_metrics["false_episode_per_hour"],
    }


def _select_deployment_config(
    threshold_sweep,
    alert_threshold=0.3,
    precision_floor=0.8,
    episode_precision_floor=0.75,
    max_false_episode_per_hour=1.0,
):
    probability_candidates = [
        item
        for item in threshold_sweep
        if item["decision_mode"] == "probability_only"
    ]
    constrained = [
        item
        for item in probability_candidates
        if item["precision"] >= float(precision_floor)
        and item["episode_precision"] >= float(episode_precision_floor)
        and item["false_episode_per_hour"] <= float(max_false_episode_per_hour)
    ]
    candidate_pool = constrained or probability_candidates
    selected = max(
        candidate_pool,
        key=lambda item: (
            item["f1"],
            -item["episode_af_burden_absolute_error_percent"],
            -item["false_episode_per_hour"],
        ),
    )
    return {
        "source": "afdb_long_term_evaluation",
        "decision_mode": selected["decision_mode"],
        "episode_threshold": float(selected["threshold"]),
        "afib_probability_threshold": float(selected["threshold"]),
        "alert_threshold": float(max(float(alert_threshold), float(selected["threshold"]))),
        "min_consecutive_windows": int(selected["min_consecutive_windows"]),
        "selection_policy": {
            "candidate_mode": "probability_only",
            "precision_floor": float(precision_floor),
            "episode_precision_floor": float(episode_precision_floor),
            "max_false_episode_per_hour": float(max_false_episode_per_hour),
            "fallback_used": not bool(constrained),
            "objective": "maximize f1, then minimize episode burden error and false episode/hour",
        },
        "selected_metrics": selected,
    }


def _cache_is_valid(cache, window_count, model_path, scaler_path):
    try:
        return (
            int(cache["window_count"][0]) == int(window_count)
            and str(cache["model_mtime"][0]) == str(model_path.stat().st_mtime)
            and str(cache["scaler_mtime"][0]) == str(scaler_path.stat().st_mtime)
        )
    except Exception:
        return False


def _load_or_compute_predictions(
    X_windows,
    model_path,
    scaler_path,
    chunk_size,
    cache_path,
    use_cache=True,
):
    if use_cache and cache_path.exists():
        cache = np.load(cache_path, allow_pickle=False)
        if _cache_is_valid(cache, len(X_windows), model_path, scaler_path):
            return cache["pred_labels"].astype(int), cache["afib_probabilities"].astype(float), True

    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path)
    pred_labels = []
    afib_probabilities = []
    for start in range(0, len(X_windows), int(chunk_size)):
        batch = X_windows[start : start + int(chunk_size)]
        X_features, _ = extract_rhythm_feature_matrix(
            batch,
            sample_rate_hz=130,
            feature_columns=RHYTHM_FEATURE_COLUMNS,
        )
        X_scaled = scaler.transform(X_features)
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X_scaled)
            classes = [int(value) for value in model.classes_]
            class_to_index = {class_id: index for index, class_id in enumerate(classes)}
            pred = np.asarray(classes, dtype=int)[np.argmax(proba, axis=1)]
            afib_prob = proba[:, class_to_index.get(AFIB_CLASS_ID, 0)]
        else:
            pred = model.predict(X_scaled)
            afib_prob = (pred == AFIB_CLASS_ID).astype(float)
        pred_labels.extend([int(value) for value in pred])
        afib_probabilities.extend([float(value) for value in afib_prob])

    pred_labels = np.asarray(pred_labels, dtype=int)
    afib_probabilities = np.asarray(afib_probabilities, dtype=float)
    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            cache_path,
            pred_labels=pred_labels,
            afib_probabilities=afib_probabilities,
            window_count=np.asarray([len(X_windows)], dtype=int),
            model_mtime=np.asarray([str(model_path.stat().st_mtime)]),
            scaler_mtime=np.asarray([str(scaler_path.stat().st_mtime)]),
        )
    return pred_labels, afib_probabilities, False


def evaluate_afdb(
    dataset_dir=DEFAULT_DATASET_DIR,
    model_dir=DEFAULT_MODEL_DIR,
    metrics_dir=DEFAULT_METRICS_DIR,
    chunk_size=512,
    afib_probability_threshold=0.7,
    decision_mode="argmax_and_threshold",
    window_seconds=30.0,
    min_consecutive_windows=2,
    use_cache=True,
    decision_config_path=DEFAULT_DECISION_CONFIG_PATH,
):
    dataset_path = Path(dataset_dir)
    model_path = Path(model_dir)
    metrics_path = Path(metrics_dir)
    X_path = dataset_path / "X_windows.npy"
    y_path = dataset_path / "y_windows.npy"
    metadata_path = dataset_path / "metadata.csv"
    if not X_path.exists() or not y_path.exists():
        raise FileNotFoundError(f"Missing {X_path} or {y_path}. Run build_afdb first.")

    X_windows = np.load(X_path)
    y = np.load(y_path)
    metadata = pd.read_csv(metadata_path) if metadata_path.exists() else pd.DataFrame()
    model_file = model_path / "rhythm_feature_model.pkl"
    scaler_file = model_path / "rhythm_scaler.pkl"
    cache_path = metrics_path / DEFAULT_CACHE_NAME
    pred_labels, afib_probabilities, cache_used = _load_or_compute_predictions(
        X_windows,
        model_file,
        scaler_file,
        chunk_size=chunk_size,
        cache_path=cache_path,
        use_cache=use_cache,
    )

    y_true_afib = (y == AFIB_CLASS_ID).astype(int)
    y_pred_afib = _binary_prediction_at_threshold(
        pred_labels,
        afib_probabilities,
        threshold=afib_probability_threshold,
        decision_mode=decision_mode,
    )
    thresholds = np.round(np.arange(0.05, 0.91, 0.05), 2)
    threshold_sweep = []
    for mode in ["argmax_and_threshold", "probability_only"]:
        threshold_sweep.extend(
            _binary_metrics_at_threshold(
                y_true_afib,
                pred_labels,
                afib_probabilities,
                threshold=threshold,
                window_seconds=window_seconds,
                decision_mode=mode,
                min_consecutive_windows=min_consecutive_windows,
            )
            for threshold in thresholds
        )

    tracker = AFEpisodeTracker(
        window_seconds=window_seconds,
        afib_probability_threshold=afib_probability_threshold,
        decision_mode=decision_mode,
        min_consecutive_windows=min_consecutive_windows,
    )
    for label, prob in zip(pred_labels, afib_probabilities):
        rhythm_label = "possible_afib" if int(label) == AFIB_CLASS_ID else "normal"
        tracker.update(rhythm_label, possible_afib_probability=prob)

    true_burden = float(100.0 * np.mean(y_true_afib)) if len(y_true_afib) else 0.0
    pred_burden = float(100.0 * np.mean(y_pred_afib)) if len(y_pred_afib) else 0.0
    cm = confusion_matrix(y_true_afib, y_pred_afib, labels=[0, 1])
    y_pred_afib_for_episode = _keep_min_consecutive_windows(
        y_pred_afib,
        min_consecutive_windows=min_consecutive_windows,
    )
    episode_burden = float(100.0 * np.mean(y_pred_afib_for_episode)) if len(y_pred_afib_for_episode) else 0.0
    episode_metrics = _episode_metrics(
        y_true_afib,
        y_pred_afib_for_episode,
        window_seconds=window_seconds,
        include_segments=True,
    )
    metrics = {
        "dataset_dir": str(dataset_path),
        "model_dir": str(model_path),
        "window_count": int(len(y)),
        "record_count": int(metadata["record_id"].nunique()) if "record_id" in metadata.columns else None,
        "afib_probability_threshold": float(afib_probability_threshold),
        "decision_mode": decision_mode,
        "min_consecutive_windows": int(min_consecutive_windows),
        "cache_used": bool(cache_used),
        "window_accuracy": float(accuracy_score(y_true_afib, y_pred_afib)),
        "afib_precision": float(precision_score(y_true_afib, y_pred_afib, zero_division=0)),
        "afib_recall": float(recall_score(y_true_afib, y_pred_afib, zero_division=0)),
        "afib_f1": float(f1_score(y_true_afib, y_pred_afib, zero_division=0)),
        "classification_report": classification_report(
            y_true_afib,
            y_pred_afib,
            labels=[0, 1],
            target_names=["non_afib", "afib"],
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": cm.tolist(),
        "true_af_burden_percent": true_burden,
        "predicted_af_burden_percent": pred_burden,
        "af_burden_absolute_error_percent": abs(pred_burden - true_burden),
        "episode_af_burden_percent": episode_burden,
        "episode_af_burden_absolute_error_percent": abs(episode_burden - true_burden),
        "tracker_summary": tracker.summary(),
        "threshold_sweep": threshold_sweep,
        "best_threshold_by_f1": max(threshold_sweep, key=lambda item: item["f1"]),
        "best_threshold_by_burden_error": min(
            threshold_sweep,
            key=lambda item: item["af_burden_absolute_error_percent"],
        ),
        "best_probability_only_by_f1": max(
            [item for item in threshold_sweep if item["decision_mode"] == "probability_only"],
            key=lambda item: item["f1"],
        ),
        "best_probability_only_by_burden_error": min(
            [item for item in threshold_sweep if item["decision_mode"] == "probability_only"],
            key=lambda item: item["af_burden_absolute_error_percent"],
        ),
        "best_probability_only_by_episode_burden_error": min(
            [item for item in threshold_sweep if item["decision_mode"] == "probability_only"],
            key=lambda item: item["episode_af_burden_absolute_error_percent"],
        ),
        **episode_metrics,
    }
    deployment_config = _select_deployment_config(
        threshold_sweep,
        alert_threshold=0.3,
        max_false_episode_per_hour=1.0,
    )
    deployment_config["generated_from_metrics_path"] = str(metrics_path / "afdb_long_term_metrics.json")
    deployment_config["dataset_dir"] = str(dataset_path)
    deployment_config["model_dir"] = str(model_path)
    deployment_config["window_count"] = int(len(y))
    metrics["deployment_decision_config"] = deployment_config
    metrics_path.mkdir(parents=True, exist_ok=True)
    save_json(metrics_path / "afdb_long_term_metrics.json", metrics)
    if decision_config_path:
        save_json(decision_config_path, deployment_config)
    return metrics


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate rhythm model on AFDB long-term windows.")
    parser.add_argument("--dataset-dir", default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--metrics-dir", default=DEFAULT_METRICS_DIR)
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--afib-probability-threshold", type=float, default=0.7)
    parser.add_argument("--min-consecutive-windows", type=int, default=2)
    parser.add_argument(
        "--decision-mode",
        choices=["argmax_and_threshold", "probability_only"],
        default="argmax_and_threshold",
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--decision-config-path", default=DEFAULT_DECISION_CONFIG_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    metrics = evaluate_afdb(
        dataset_dir=args.dataset_dir,
        model_dir=args.model_dir,
        metrics_dir=args.metrics_dir,
        chunk_size=args.chunk_size,
        afib_probability_threshold=args.afib_probability_threshold,
        decision_mode=args.decision_mode,
        min_consecutive_windows=args.min_consecutive_windows,
        use_cache=not args.no_cache,
        decision_config_path=args.decision_config_path,
    )
    print("AFDB long-term evaluation complete.")
    print(metrics)


if __name__ == "__main__":
    main()
