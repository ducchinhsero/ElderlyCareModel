import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.api import pipeline
from src.features.ecg_features import evaluate_signal_quality
from src.preprocessing import save_json


DEFAULT_INPUT_DIR = "data_raw/real_data"
DEFAULT_OUTPUT_PATH = "models/runtime/sensor_context_config.json"
DEFAULT_WINDOW_SECONDS = 30.0


def _load_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _session_dirs(input_dir, person_id=None):
    root = Path(input_dir)
    roots = [root / person_id] if person_id else [path for path in root.iterdir() if path.is_dir()]
    sessions = []
    for person_root in roots:
        if not person_root.exists():
            continue
        for metadata_path in person_root.glob("*/*/metadata.json"):
            session_dir = metadata_path.parent
            if (session_dir / "ecg.csv").exists():
                sessions.append(session_dir)
    return sorted(sessions)


def _read_ecg(path):
    df = pd.read_csv(path)
    for column in ["ecg_uv", "ecg", "value"]:
        if column in df.columns:
            return df[column].astype(float).to_numpy()
    numeric_columns = df.select_dtypes(include=["number"]).columns
    if len(numeric_columns) == 0:
        raise ValueError(f"No numeric ECG column found in {path}")
    return df[numeric_columns[-1]].astype(float).to_numpy()


def _read_acc(path):
    if not Path(path).exists():
        return np.empty((0, 4), dtype=float)
    df = pd.read_csv(path)
    if all(column in df.columns for column in ["x_mg", "y_mg", "z_mg", "vm_mg"]):
        return df[["x_mg", "y_mg", "z_mg", "vm_mg"]].astype(float).to_numpy()
    if all(column in df.columns for column in ["x", "y", "z"]):
        values = df[["x", "y", "z"]].astype(float).to_numpy()
        vm = np.sqrt(np.sum(values**2, axis=1))
        return np.column_stack([values, vm])
    return np.empty((0, 4), dtype=float)


def _quantile(values, q, default=None):
    values = [float(value) for value in values if value is not None and np.isfinite(value)]
    if not values:
        return default
    return float(np.percentile(np.asarray(values, dtype=float), q))


def _bounded(value, low, high, default):
    if value is None or not np.isfinite(value):
        value = default
    return float(max(low, min(high, value)))


def _stats(values):
    values = [float(value) for value in values if value is not None and np.isfinite(value)]
    if not values:
        return {"count": 0}
    arr = np.asarray(values, dtype=float)
    return {
        "count": int(arr.size),
        "min": round(float(np.min(arr)), 3),
        "p05": round(float(np.percentile(arr, 5)), 3),
        "median": round(float(np.median(arr)), 3),
        "p95": round(float(np.percentile(arr, 95)), 3),
        "p99": round(float(np.percentile(arr, 99)), 3),
        "max": round(float(np.max(arr)), 3),
    }


def _build_activity_config(acc_rows):
    by_state = {}
    for row in acc_rows:
        by_state.setdefault(row["state"], []).append(row)

    rest_std = [row["vm_std"] for row in by_state.get("rest", [])]
    walk_std = [row["vm_std"] for row in by_state.get("walk", [])]
    active_std = [row["vm_std"] for row in by_state.get("active", [])]

    rest_p95 = _quantile(rest_std, 95, 20)
    walk_p05 = _quantile(walk_std, 5, 80)
    walk_p95 = _quantile(walk_std, 95, 80)
    active_p05 = _quantile(active_std, 5, 300)

    rest_threshold = _bounded((rest_p95 + walk_p05) / 2.0, 20, 50, 20)
    slow_threshold = _bounded(max(80.0, walk_p95 + 5.0), 80, 120, 80)
    walk_threshold = _bounded((walk_p95 + active_p05) / 2.0, 250, 350, 300)

    if slow_threshold <= rest_threshold:
        slow_threshold = rest_threshold + 10.0
    if walk_threshold <= slow_threshold:
        walk_threshold = slow_threshold + 50.0

    return {
        "vm_std_thresholds_mg": {
            str(round(rest_threshold, 3)): "REST",
            str(round(slow_threshold, 3)): "SLOW_WALK",
            str(round(walk_threshold, 3)): "WALK",
        },
        "observed_vm_std_by_state": {
            state: _stats([row["vm_std"] for row in rows])
            for state, rows in sorted(by_state.items())
        },
        "notes": [
            "Thresholds are calibrated from labeled rest/walk/active Polar H10 real_data windows.",
            "Values below the first threshold are REST; above the last threshold are ACTIVE.",
        ],
    }


def _build_fall_config(acc_rows):
    by_state = {}
    for row in acc_rows:
        by_state.setdefault(row["state"], []).append(row)

    rest_walk_max = [
        row["vm_max"]
        for state in ["rest", "walk"]
        for row in by_state.get(state, [])
    ]
    active_max = [row["vm_max"] for row in by_state.get("active", [])]
    base_impact = max(2000.0, (_quantile(rest_walk_max, 99, 1900.0) or 1900.0) + 100.0)
    base_impact = _bounded(base_impact, 2000.0, 2600.0, 2000.0)

    strong_impact = max(2800.0, (_quantile(active_max, 75, 2800.0) or 2800.0) + 50.0)
    strong_impact = _bounded(strong_impact, 2800.0, 3800.0, 2800.0)

    active_candidate_min = max(strong_impact, (_quantile(active_max, 90, 3200.0) or 3200.0) + 100.0)
    active_candidate_min = _bounded(active_candidate_min, 2800.0, 4500.0, 3200.0)

    rest_std_p95 = _quantile([row["vm_std"] for row in by_state.get("rest", [])], 95, 30.0)
    post_still_std = _bounded(max(120.0, (rest_std_p95 or 30.0) + 20.0), 100.0, 180.0, 120.0)

    return {
        "impact_threshold_mg": round(base_impact, 3),
        "strong_impact_mg": round(strong_impact, 3),
        "active_fall_candidate_min_impact_mg": round(active_candidate_min, 3),
        "free_fall_threshold_mg": 500.0,
        "post_still_std_mg": round(post_still_std, 3),
        "prox_s": 1.0,
        "post_still_seconds": 3.0,
        "min_post_still_seconds": 2.0,
        "observed_vm_max_by_state": {
            state: _stats([row["vm_max"] for row in rows])
            for state, rows in sorted(by_state.items())
        },
        "notes": [
            "No real fall labels are assumed. ACTIVE false-fall reduction is handled by a higher active_fall_candidate_min_impact_mg gate.",
            "Fall still requires impact + free-fall + post-still.",
        ],
    }


def _build_signal_quality_config(quality_rows):
    amp_std = [row["amplitude_std"] for row in quality_rows]
    amp_range = [row["amplitude_range"] for row in quality_rows]
    rr_outlier = [row["rr_outlier_ratio"] for row in quality_rows]

    # Keep amplitude thresholds scale-safe. Polar raw ECG is in a high numeric
    # range, but API clients may send normalized ECG; RR/flatline checks should
    # carry most of the quality decision.
    min_amplitude_std = min(0.05, max(1e-6, (_quantile(amp_std, 5, 1.0) or 1.0) * 0.01))
    min_amplitude_range = min(0.2, max(1e-6, (_quantile(amp_range, 5, 1.0) or 1.0) * 0.01))
    max_rr_outlier = min(0.50, max(0.35, (_quantile(rr_outlier, 95, 0.35) or 0.35) + 0.05))

    by_state = {}
    for row in quality_rows:
        by_state.setdefault(row["state"], []).append(row)

    return {
        "min_seconds": 10.0,
        "max_nan_ratio": 0.01,
        "max_zero_ratio": 0.8,
        "min_amplitude_std": round(float(min_amplitude_std), 3),
        "min_amplitude_range": round(float(min_amplitude_range), 3),
        "min_r_peak_count": 6,
        "min_valid_rr_ratio": 0.8,
        "min_beat_template_correlation": 0.35,
        "max_physiological_hr_bpm": 220.0,
        "min_median_peak_width_ms": 30.0,
        "max_median_peak_width_ms": 220.0,
        "max_rr_outlier_ratio": round(float(max_rr_outlier), 3),
        "observed_by_state": {
            state: {
                "score": _stats([row["score"] for row in rows]),
                "amplitude_std": _stats([row["amplitude_std"] for row in rows]),
                "amplitude_range": _stats([row["amplitude_range"] for row in rows]),
                "rr_outlier_ratio": _stats([row["rr_outlier_ratio"] for row in rows]),
            }
            for state, rows in sorted(by_state.items())
        },
    }


def _build_rhythm_alert_config(rhythm_rows):
    activity_rows = [row for row in rhythm_rows if row["state"] in {"walk", "active"}]
    activity_afib_p95 = _quantile([row["possible_afib_probability"] for row in activity_rows], 95, 0.0)
    activity_other_threshold = max(0.10, min(0.20, (activity_afib_p95 or 0.0) + 0.02))
    by_state = {}
    for row in rhythm_rows:
        by_state.setdefault(row["state"], []).append(row)

    return {
        "activity_other_rhythm_afib_probability_threshold": round(float(activity_other_threshold), 4),
        "possible_afib_medium_probability": 0.3,
        "possible_afib_high_probability": 0.8,
        "observed_possible_afib_probability_by_state": {
            state: _stats([row["possible_afib_probability"] for row in rows])
            for state, rows in sorted(by_state.items())
        },
        "notes": [
            "other_rhythm during WALK/ACTIVE remains normal only when AF probability is below the calibrated activity threshold.",
            "Possible AFib alert thresholds remain clinically conservative unless overridden separately.",
        ],
    }


def collect_real_data_calibration_rows(input_dir, person_id=None, window_seconds=DEFAULT_WINDOW_SECONDS):
    acc_rows = []
    quality_rows = []
    rhythm_rows = []
    source_sessions = []

    for session_dir in _session_dirs(input_dir, person_id=person_id):
        metadata = _load_json(session_dir / "metadata.json")
        state = str(metadata.get("state") or session_dir.parent.name).strip().lower()
        person = metadata.get("person_id") or session_dir.parents[1].name
        ecg_rate = float(metadata.get("ecg_sample_rate_hz") or 130.0)
        acc_rate = float(metadata.get("acc_sample_rate_hz") or 50.0)

        ecg = _read_ecg(session_dir / "ecg.csv")
        acc = _read_acc(session_dir / "acc.csv")
        ecg_window_n = int(round(float(window_seconds) * ecg_rate))
        acc_window_n = int(round(float(window_seconds) * acc_rate))
        window_count = int(len(ecg) // ecg_window_n)

        source_sessions.append(
            {
                "person_id": person,
                "state": state,
                "session_id": metadata.get("session_id") or session_dir.name,
                "session_dir": str(session_dir),
                "window_count": window_count,
            }
        )

        for window_index in range(window_count):
            ecg_window = ecg[window_index * ecg_window_n : (window_index + 1) * ecg_window_n]
            quality = evaluate_signal_quality(ecg_window, ecg_rate)
            quality_rows.append(
                {
                    "person_id": person,
                    "state": state,
                    "session_id": metadata.get("session_id") or session_dir.name,
                    "window_index": window_index,
                    "score": float(quality.get("score") or 0.0),
                    **quality.get("metrics", {}),
                }
            )

            rhythm = pipeline.rhythm_predictor.predict(ecg_window, ecg_rate)
            rhythm_rows.append(
                {
                    "person_id": person,
                    "state": state,
                    "session_id": metadata.get("session_id") or session_dir.name,
                    "window_index": window_index,
                    "rhythm_label": rhythm.get("label"),
                    "possible_afib_probability": float(
                        rhythm.get("possible_afib_probability")
                        if rhythm.get("possible_afib_probability") is not None
                        else (rhythm.get("probabilities") or {}).get("possible_afib", 0.0)
                    ),
                }
            )

            if acc.size and acc_window_n > 0:
                acc_window = acc[window_index * acc_window_n : (window_index + 1) * acc_window_n]
                if acc_window.size:
                    vm = acc_window[:, 3]
                    acc_rows.append(
                        {
                            "person_id": person,
                            "state": state,
                            "session_id": metadata.get("session_id") or session_dir.name,
                            "window_index": window_index,
                            "vm_std": float(np.std(vm)),
                            "vm_mean": float(np.mean(vm)),
                            "vm_min": float(np.min(vm)),
                            "vm_max": float(np.max(vm)),
                            "vm_range": float(np.max(vm) - np.min(vm)),
                        }
                    )

    return {
        "source_sessions": source_sessions,
        "acc_rows": acc_rows,
        "quality_rows": quality_rows,
        "rhythm_rows": rhythm_rows,
    }


def build_sensor_context_config(input_dir=DEFAULT_INPUT_DIR, person_id=None, window_seconds=DEFAULT_WINDOW_SECONDS):
    rows = collect_real_data_calibration_rows(
        input_dir=input_dir,
        person_id=person_id,
        window_seconds=window_seconds,
    )
    if not rows["source_sessions"]:
        raise FileNotFoundError(f"No real_data sessions found under {input_dir}.")
    if not rows["acc_rows"]:
        raise ValueError("No ACC windows found. Collect real_data with ACC before sensor-context calibration.")

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_type": "real_data_sensor_context_calibration",
        "input_dir": str(Path(input_dir)),
        "person_id": person_id,
        "window_seconds": float(window_seconds),
        "source_sessions": rows["source_sessions"],
        "window_counts": {
            "acc": len(rows["acc_rows"]),
            "signal_quality": len(rows["quality_rows"]),
            "rhythm": len(rows["rhythm_rows"]),
        },
        "activity": _build_activity_config(rows["acc_rows"]),
        "fall": _build_fall_config(rows["acc_rows"]),
        "signal_quality": _build_signal_quality_config(rows["quality_rows"]),
        "rhythm_alert": _build_rhythm_alert_config(rows["rhythm_rows"]),
    }


def calibrate_sensor_context(
    input_dir=DEFAULT_INPUT_DIR,
    person_id=None,
    output_path=DEFAULT_OUTPUT_PATH,
    window_seconds=DEFAULT_WINDOW_SECONDS,
):
    config = build_sensor_context_config(
        input_dir=input_dir,
        person_id=person_id,
        window_seconds=window_seconds,
    )
    save_json(output_path, config)
    return config


def parse_args():
    parser = argparse.ArgumentParser(
        description="Calibrate activity/fall/signal/rhythm runtime thresholds from Polar real_data."
    )
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--person-id", default=None)
    parser.add_argument("--output-path", default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--window-seconds", type=float, default=DEFAULT_WINDOW_SECONDS)
    return parser.parse_args()


def main():
    args = parse_args()
    config = calibrate_sensor_context(
        input_dir=args.input_dir,
        person_id=args.person_id,
        output_path=args.output_path,
        window_seconds=args.window_seconds,
    )
    print(json.dumps(config, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
