import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.api import pipeline
from src.features.acc_features import FS_ACC_HZ


DEFAULT_INPUT_DIR = "data_raw/real_data"
DEFAULT_OUTPUT_DIR = "data_processed/real_data_eval"
DEFAULT_WINDOW_SECONDS = 30.0


def _load_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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
    if not path.exists():
        return []
    df = pd.read_csv(path)
    required = ["x_mg", "y_mg", "z_mg", "vm_mg"]
    if all(column in df.columns for column in required):
        return [tuple(row) for row in df[required].astype(float).to_numpy()]
    required = ["x", "y", "z"]
    if all(column in df.columns for column in required):
        values = df[required].astype(float).to_numpy()
        vm = np.sqrt(np.sum(values**2, axis=1))
        return [tuple(row) for row in np.column_stack([values, vm])]
    return []


def _session_dirs(input_root, person_id=None):
    root = Path(input_root)
    if person_id:
        roots = [root / person_id]
    else:
        roots = [path for path in root.iterdir() if path.is_dir()]

    sessions = []
    for person_root in roots:
        if not person_root.exists():
            continue
        for metadata_path in person_root.glob("*/*/metadata.json"):
            session_dir = metadata_path.parent
            if (session_dir / "ecg.csv").exists():
                sessions.append(session_dir)
    return sorted(sessions)


def _slice_signal(signal, sample_rate_hz, start_seconds, window_seconds):
    start = int(round(start_seconds * sample_rate_hz))
    end = int(round((start_seconds + window_seconds) * sample_rate_hz))
    return signal[start:end]


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _quality_reason_text(result):
    reasons = ((result.get("signal_quality") or {}).get("reasons") or [])
    return "; ".join(str(item) for item in reasons)


def evaluate_session(session_dir, window_seconds=DEFAULT_WINDOW_SECONDS):
    metadata = _load_json(session_dir / "metadata.json")
    person_id = metadata.get("person_id") or session_dir.parents[1].name
    state = metadata.get("state") or session_dir.parent.name
    session_id = metadata.get("session_id") or session_dir.name
    ecg_rate = _safe_float(metadata.get("ecg_sample_rate_hz"), 130.0)
    acc_rate = _safe_float(metadata.get("acc_sample_rate_hz"), FS_ACC_HZ)

    ecg = _read_ecg(session_dir / "ecg.csv")
    acc = _read_acc(session_dir / "acc.csv")

    sample_count_per_window = int(round(window_seconds * ecg_rate))
    total_windows = int(len(ecg) // sample_count_per_window)
    rows = []

    pipeline.af_episode_trackers.pop(person_id, None)

    for window_index in range(total_windows):
        start_seconds = window_index * window_seconds
        ecg_window = _slice_signal(ecg, ecg_rate, start_seconds, window_seconds)
        acc_window = _slice_signal(acc, acc_rate, start_seconds, window_seconds) if acc else []
        result = pipeline.predict_ecg(
            ecg_window,
            sample_rate_hz=ecg_rate,
            patient_id=person_id,
            acc_samples=acc_window,
            acc_sample_rate_hz=acc_rate,
        )
        rhythm = result.get("rhythm") or {}
        anomaly = result.get("anomaly") or {}
        hr_event = result.get("hr_event") or {}
        af_episode = result.get("af_episode") or {}
        rhythm_alert = result.get("rhythm_alert") or {}
        risk = result.get("risk") or {}
        signal_quality = result.get("signal_quality") or {}
        sensor_context = result.get("sensor_context") or {}
        activity_features = sensor_context.get("activity_features") or {}
        hr_context = sensor_context.get("hr_context_alert") or {}
        rows.append(
            {
                "person_id": person_id,
                "expected_state": state,
                "session_id": session_id,
                "window_index": window_index,
                "start_seconds": start_seconds,
                "end_seconds": start_seconds + window_seconds,
                "ecg_samples": len(ecg_window),
                "acc_samples": len(acc_window),
                "heart_rate_bpm": result.get("heart_rate_bpm"),
                "emotion_label": (result.get("emotion") or {}).get("label"),
                "emotion_confidence": (result.get("emotion") or {}).get("confidence"),
                "rhythm_label": rhythm.get("label"),
                "rhythm_confidence": rhythm.get("confidence"),
                "rhythm_alert_level": rhythm_alert.get("level"),
                "rhythm_alert_message": rhythm_alert.get("message"),
                "possible_afib_probability": rhythm.get("possible_afib_probability"),
                "af_episode_active": af_episode.get("active"),
                "af_burden_percent": af_episode.get("af_burden_percent"),
                "anomaly_label": anomaly.get("label"),
                "anomaly_reason": anomaly.get("reason"),
                "risk_level": risk.get("level"),
                "risk_reason": risk.get("reason"),
                "hr_event_label": hr_event.get("label"),
                "signal_quality_label": signal_quality.get("label"),
                "signal_quality_score": signal_quality.get("score"),
                "signal_quality_reasons": _quality_reason_text(result),
                "detected_activity": sensor_context.get("activity_state"),
                "acc_vm_std_mg": activity_features.get("acc_vm_std"),
                "hr_context_level": hr_context.get("level"),
                "hr_context_reason": hr_context.get("reason"),
                "fall_candidate": (sensor_context.get("fall") or {}).get("fall_candidate"),
                "alert_level": result.get("alert_level"),
                "message": result.get("message"),
            }
        )
    return metadata, rows


def _counts(rows, key):
    return dict(Counter(row.get(key) or "unknown" for row in rows))


def _mean(rows, key):
    values = [row.get(key) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return float(np.mean(np.asarray(values, dtype=float)))


def _max(rows, key):
    values = [row.get(key) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return float(np.max(np.asarray(values, dtype=float)))


def build_event_rows(rows):
    events = []
    for row in rows:
        base = {
            "person_id": row["person_id"],
            "expected_state": row["expected_state"],
            "session_id": row["session_id"],
            "window_index": row["window_index"],
            "start_seconds": row["start_seconds"],
            "end_seconds": row["end_seconds"],
            "heart_rate_bpm": row.get("heart_rate_bpm"),
            "detected_activity": row.get("detected_activity"),
        }

        rhythm_level = row.get("rhythm_alert_level")
        if rhythm_level in {"medium", "high", "critical"}:
            events.append(
                {
                    **base,
                    "event_type": "rhythm_alert",
                    "severity": rhythm_level,
                    "label": row.get("rhythm_label"),
                    "reason": row.get("rhythm_alert_message"),
                }
            )

        hr_event = row.get("hr_event_label")
        if hr_event in {"tachycardia_at_rest", "bradycardia"}:
            events.append(
                {
                    **base,
                    "event_type": "heart_rate_event",
                    "severity": "medium",
                    "label": hr_event,
                    "reason": f"{hr_event} at {row.get('heart_rate_bpm')} bpm",
                }
            )

        hr_context_level = row.get("hr_context_level")
        if hr_context_level in {"WATCH", "ALERT", "CRITICAL"}:
            events.append(
                {
                    **base,
                    "event_type": "hr_context",
                    "severity": "medium" if hr_context_level == "WATCH" else "high",
                    "label": hr_context_level,
                    "reason": row.get("hr_context_reason"),
                }
            )

        if str(row.get("fall_candidate")).lower() == "true" or row.get("fall_candidate") is True:
            events.append(
                {
                    **base,
                    "event_type": "fall_candidate",
                    "severity": "high",
                    "label": "fall_candidate",
                    "reason": row.get("message"),
                }
            )

        quality = row.get("signal_quality_label")
        if quality in {"poor", "noise", "poor_contact", "motion_artifact"}:
            events.append(
                {
                    **base,
                    "event_type": "signal_quality",
                    "severity": "unknown",
                    "label": quality,
                    "reason": row.get("signal_quality_reasons"),
                }
            )
    return events


def summarize_rows(rows, session_metadata):
    by_session = defaultdict(list)
    for row in rows:
        by_session[(row["person_id"], row["expected_state"], row["session_id"])].append(row)

    sessions = []
    for (person_id, state, session_id), session_rows in sorted(by_session.items()):
        metadata = session_metadata.get(session_id, {})
        sessions.append(
            {
                "person_id": person_id,
                "state": state,
                "session_id": session_id,
                "requested_duration_seconds": metadata.get("requested_duration_seconds"),
                "ecg_duration_seconds": metadata.get("ecg_duration_seconds"),
                "acc_duration_seconds": metadata.get("acc_duration_seconds"),
                "window_count": len(session_rows),
                "mean_heart_rate_bpm": _mean(session_rows, "heart_rate_bpm"),
                "max_heart_rate_bpm": _max(session_rows, "heart_rate_bpm"),
                "mean_afib_probability": _mean(session_rows, "possible_afib_probability"),
                "max_afib_probability": _max(session_rows, "possible_afib_probability"),
                "max_af_burden_percent": _max(session_rows, "af_burden_percent"),
                "rhythm_counts": _counts(session_rows, "rhythm_label"),
                "rhythm_alert_counts": _counts(session_rows, "rhythm_alert_level"),
                "quality_counts": _counts(session_rows, "signal_quality_label"),
                "detected_activity_counts": _counts(session_rows, "detected_activity"),
                "hr_event_counts": _counts(session_rows, "hr_event_label"),
                "anomaly_counts": _counts(session_rows, "anomaly_label"),
                "risk_counts": _counts(session_rows, "risk_level"),
                "alert_counts": _counts(session_rows, "alert_level"),
            }
        )

    return {
        "window_count": len(rows),
        "session_count": len(sessions),
        "event_count": len(build_event_rows(rows)),
        "overall": {
            "rhythm_counts": _counts(rows, "rhythm_label"),
            "rhythm_alert_counts": _counts(rows, "rhythm_alert_level"),
            "quality_counts": _counts(rows, "signal_quality_label"),
            "detected_activity_counts": _counts(rows, "detected_activity"),
            "hr_event_counts": _counts(rows, "hr_event_label"),
            "anomaly_counts": _counts(rows, "anomaly_label"),
            "risk_counts": _counts(rows, "risk_level"),
            "alert_counts": _counts(rows, "alert_level"),
            "mean_heart_rate_bpm": _mean(rows, "heart_rate_bpm"),
            "max_heart_rate_bpm": _max(rows, "heart_rate_bpm"),
            "mean_afib_probability": _mean(rows, "possible_afib_probability"),
            "max_afib_probability": _max(rows, "possible_afib_probability"),
        },
        "sessions": sessions,
    }


def write_predictions_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_events_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate collected real ECG/ACC data with the realtime pipeline.")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--person-id", default=None)
    parser.add_argument("--window-seconds", type=float, default=DEFAULT_WINDOW_SECONDS)
    return parser.parse_args()


def main():
    args = parse_args()
    sessions = _session_dirs(args.input_dir, person_id=args.person_id)
    if not sessions:
        raise FileNotFoundError(f"No real-data sessions found under {args.input_dir}")

    all_rows = []
    session_metadata = {}
    for session_dir in sessions:
        metadata, rows = evaluate_session(session_dir, window_seconds=args.window_seconds)
        session_metadata[metadata.get("session_id") or session_dir.name] = metadata
        all_rows.extend(rows)
        print(f"Evaluated {session_dir}: {len(rows)} windows")

    output_root = Path(args.output_dir)
    if args.person_id:
        output_root = output_root / args.person_id
    output_root.mkdir(parents=True, exist_ok=True)

    summary = summarize_rows(all_rows, session_metadata)
    summary["input_dir"] = str(Path(args.input_dir))
    summary["output_dir"] = str(output_root)
    summary["window_seconds"] = args.window_seconds

    write_predictions_csv(output_root / "predictions.csv", all_rows)
    events = build_event_rows(all_rows)
    write_events_csv(output_root / "events.csv", events)
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_root / "events.json").write_text(
        json.dumps(events, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved predictions: {output_root / 'predictions.csv'}")
    print(f"Saved events: {output_root / 'events.csv'}")
    print(f"Saved summary: {output_root / 'summary.json'}")
    print(json.dumps(summary["overall"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
