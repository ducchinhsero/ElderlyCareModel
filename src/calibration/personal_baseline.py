import json
from datetime import datetime, timezone
from pathlib import Path

from src.storage.ecg_storage import DB_PATH, get_history


BASELINE_ROOT = "dataset/realtime_logs/personal_baseline"
DEFAULT_MIN_BASELINE_PREDICTIONS = 20
DEFAULT_TARGET_BASELINE_DAYS = 7
RELIABLE_SIGNAL_LABELS = {"good", "fair"}
EXCLUDED_ALERT_LEVELS = {"high", "critical"}
AFIB_PROBABILITY_THRESHOLD = 0.28
ECTOPY_LABELS = {"pvc", "pac", "mixed_ectopic"}


def _safe_patient_id(patient_id):
    safe = patient_id or "unknown"
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in safe)


def baseline_path(patient_id, root=BASELINE_ROOT):
    return Path(root) / _safe_patient_id(patient_id) / "personal_baseline.json"


def has_personal_baseline(patient_id, root=BASELINE_ROOT):
    return baseline_path(patient_id, root=root).exists()


def load_personal_baseline(patient_id, root=BASELINE_ROOT):
    path = baseline_path(patient_id, root=root)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_personal_baseline(baseline, root=BASELINE_ROOT):
    path = baseline_path(baseline["patient_id"], root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)
    return str(path)


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(items, predicate):
    if not items:
        return 0.0
    return sum(1 for item in items if predicate(item)) / len(items)


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _stats(values):
    clean = [_safe_float(value) for value in values]
    clean = [value for value in clean if value is not None]
    if not clean:
        return {"count": 0}
    mean = sum(clean) / len(clean)
    variance = sum((value - mean) ** 2 for value in clean) / len(clean)
    return {
        "count": len(clean),
        "mean": round(mean, 3),
        "median": round(_percentile(clean, 0.5), 3),
        "p05": round(_percentile(clean, 0.05), 3),
        "p95": round(_percentile(clean, 0.95), 3),
        "min": round(min(clean), 3),
        "max": round(max(clean), 3),
        "std": round(variance ** 0.5, 3),
    }


def _quality_label(item):
    return (item.get("signal_quality") or {}).get("label")


def _is_reliable(item, include_alert_windows=False):
    if _quality_label(item) not in RELIABLE_SIGNAL_LABELS:
        return False
    if include_alert_windows:
        return True
    if item.get("alert_level") in EXCLUDED_ALERT_LEVELS:
        return False
    rhythm_alert_level = (item.get("rhythm_alert") or {}).get("level")
    if rhythm_alert_level in EXCLUDED_ALERT_LEVELS:
        return False
    return True


def _activity_state(item):
    return ((item.get("sensor_context") or {}).get("activity_state") or "UNKNOWN").upper()


def _afib_probability(item):
    rhythm = item.get("rhythm") or {}
    probability = rhythm.get("possible_afib_probability")
    if probability is None:
        probability = (rhythm.get("probabilities") or {}).get("possible_afib")
    return _safe_float(probability) or 0.0


def _is_af_suspicion(item):
    rhythm = item.get("rhythm") or {}
    rhythm_alert = item.get("rhythm_alert") or {}
    return (
        rhythm.get("label") == "possible_afib"
        or _afib_probability(item) >= AFIB_PROBABILITY_THRESHOLD
        or rhythm_alert.get("level") in {"medium", "high", "critical"}
    )


def _is_ectopy(item):
    return (item.get("ectopy") or {}).get("label") in ECTOPY_LABELS


def _is_abnormal_anomaly(item):
    anomaly = item.get("anomaly") or {}
    return anomaly.get("value") == 1 or anomaly.get("label") in {"abnormal", "anomaly"}


def _timestamps(history):
    values = [item.get("timestamp") for item in history if item.get("timestamp")]
    return {
        "start_timestamp": min(values) if values else None,
        "end_timestamp": max(values) if values else None,
    }


def _safe_datetime(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _day_count(history):
    days = set()
    for item in history:
        dt = _safe_datetime(item.get("timestamp"))
        if dt is not None:
            days.add(dt.date().isoformat())
    return len(days)


def _calibration_status(day_count, reliable_count, min_predictions, target_days):
    if reliable_count < int(min_predictions):
        return "not_ready"
    if day_count < int(target_days):
        return "warming_up"
    return "ready"


def _hr_stats_by_activity(history):
    grouped = {}
    for item in history:
        grouped.setdefault(_activity_state(item), []).append(item.get("heart_rate_bpm"))
    return {activity: _stats(values) for activity, values in sorted(grouped.items())}


def _emotion_distribution(history):
    counts = {}
    for item in history:
        label = (item.get("emotion") or {}).get("label") or "unknown"
        counts[label] = counts.get(label, 0) + 1
    total = len(history) or 1
    return {
        label: {"count": count, "ratio": round(count / total, 4)}
        for label, count in sorted(counts.items())
    }


def build_personal_baseline(
    history,
    patient_id=None,
    days=None,
    min_predictions=DEFAULT_MIN_BASELINE_PREDICTIONS,
    include_alert_windows=False,
    target_days=DEFAULT_TARGET_BASELINE_DAYS,
    allow_partial=False,
    source_metadata=None,
):
    if not history:
        raise ValueError("No prediction history is available for baseline calibration.")

    patient_id = patient_id or history[0].get("patient_id") or "unknown"
    reliable = [item for item in history if _is_reliable(item, include_alert_windows=include_alert_windows)]
    if len(reliable) < int(min_predictions) and not allow_partial:
        raise ValueError(
            f"Need at least {int(min_predictions)} reliable predictions for personal baseline, "
            f"got {len(reliable)}."
        )
    if not reliable:
        raise ValueError("Need at least one reliable prediction for progressive personal baseline.")

    all_hr = [item.get("heart_rate_bpm") for item in reliable]
    valid_signal_ratio = _ratio(history, lambda item: _quality_label(item) in RELIABLE_SIGNAL_LABELS)
    calibration_day_count = _day_count(reliable)
    calibration_status = _calibration_status(
        calibration_day_count,
        len(reliable),
        min_predictions=min_predictions,
        target_days=target_days,
    )
    baseline = {
        "patient_id": patient_id,
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_updated_at": datetime.now(timezone.utc).isoformat(),
        "calibration": {
            "mode": "progressive" if allow_partial else "fixed_window",
            "status": calibration_status,
            "target_days": int(target_days),
            "day_count": calibration_day_count,
            "progress_ratio": round(min(1.0, calibration_day_count / float(target_days)), 4),
            "min_predictions": int(min_predictions),
            "data_quality_ok": valid_signal_ratio >= 0.8 and len(reliable) >= int(min_predictions),
        },
        "source": {
            "type": "sqlite_predictions",
            "days": None if days is None else float(days),
            "prediction_count": len(history),
            "reliable_prediction_count": len(reliable),
            "include_alert_windows": bool(include_alert_windows),
            **_timestamps(history),
            **(source_metadata or {}),
        },
        "quality": {
            "valid_signal_ratio": round(valid_signal_ratio, 4),
            "poor_signal_ratio": round(1.0 - valid_signal_ratio, 4),
            "quality_counts": _count_labels(history, lambda item: _quality_label(item) or "unknown"),
        },
        "heart_rate": {
            "overall": _stats(all_hr),
            "by_activity": _hr_stats_by_activity(reliable),
        },
        "rhythm": {
            "af_suspicion_ratio": round(_ratio(reliable, _is_af_suspicion), 4),
            "max_afib_probability": round(max((_afib_probability(item) for item in reliable), default=0.0), 4),
            "mean_afib_probability": round(
                sum(_afib_probability(item) for item in reliable) / len(reliable), 4
            ),
            "rhythm_counts": _count_labels(reliable, lambda item: (item.get("rhythm") or {}).get("label") or "unknown"),
        },
        "ectopy": {
            "ectopy_ratio": round(_ratio(reliable, _is_ectopy), 4),
            "ectopy_counts": _count_labels(reliable, lambda item: (item.get("ectopy") or {}).get("label") or "unknown"),
        },
        "anomaly": {
            "abnormal_ratio": round(_ratio(reliable, _is_abnormal_anomaly), 4),
            "anomaly_counts": _count_labels(
                reliable, lambda item: (item.get("anomaly") or {}).get("label") or "unknown"
            ),
        },
        "emotion": {
            "distribution": _emotion_distribution(reliable),
        },
    }
    return baseline


def _count_labels(items, getter):
    counts = {}
    for item in items:
        label = getter(item)
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def calibrate_personal_baseline(
    patient_id,
    days=2,
    min_predictions=DEFAULT_MIN_BASELINE_PREDICTIONS,
    include_alert_windows=False,
    db_path=DB_PATH,
    root=BASELINE_ROOT,
):
    if not patient_id:
        raise ValueError("patient_id is required.")
    if float(days) <= 0:
        raise ValueError("days must be positive.")
    if int(min_predictions) <= 0:
        raise ValueError("min_predictions must be positive.")

    history = get_history(patient_id=patient_id, days=days, limit=20000, db_path=db_path)
    baseline = build_personal_baseline(
        history,
        patient_id=patient_id,
        days=days,
        min_predictions=min_predictions,
        include_alert_windows=include_alert_windows,
    )
    path = save_personal_baseline(baseline, root=root)
    return {"status": "calibrated", "path": path, "baseline": baseline}


def update_progressive_personal_baseline(
    patient_id,
    target_days=DEFAULT_TARGET_BASELINE_DAYS,
    min_predictions=DEFAULT_MIN_BASELINE_PREDICTIONS,
    include_alert_windows=False,
    db_path=DB_PATH,
    root=BASELINE_ROOT,
    history=None,
    source_metadata=None,
):
    if not patient_id:
        raise ValueError("patient_id is required.")
    if int(target_days) <= 0:
        raise ValueError("target_days must be positive.")
    if int(min_predictions) <= 0:
        raise ValueError("min_predictions must be positive.")

    if history is None:
        history = get_history(patient_id=patient_id, days=target_days, limit=50000, db_path=db_path)
    baseline = build_personal_baseline(
        history,
        patient_id=patient_id,
        days=target_days,
        min_predictions=min_predictions,
        include_alert_windows=include_alert_windows,
        target_days=target_days,
        allow_partial=True,
        source_metadata=source_metadata,
    )
    path = save_personal_baseline(baseline, root=root)
    return {
        "status": baseline["calibration"]["status"],
        "path": path,
        "baseline": baseline,
    }


def get_personal_baseline_status(patient_id, root=BASELINE_ROOT):
    if not patient_id:
        raise ValueError("patient_id is required.")
    baseline = load_personal_baseline(patient_id, root=root)
    return {
        "patient_id": patient_id,
        "calibrated": baseline is not None,
        "calibration": None if baseline is None else baseline.get("calibration"),
        "baseline": baseline,
    }


def compare_history_to_baseline(history, baseline):
    if not baseline:
        return {"calibrated": False, "comparisons": {}, "summary": "No personal baseline has been calibrated."}
    calibration = baseline.get("calibration") or {}
    reliable = [item for item in history if _quality_label(item) in RELIABLE_SIGNAL_LABELS]
    if not reliable:
        return {
            "calibrated": True,
            "calibration": calibration,
            "comparisons": {},
            "summary": "Personal baseline exists, but recent reliable data is unavailable.",
            "baseline_source": baseline.get("source") or {},
        }

    baseline_hr = baseline.get("heart_rate") or {}
    baseline_overall = (baseline_hr.get("overall") or {}).get("mean")
    recent_overall = (_stats(item.get("heart_rate_bpm") for item in reliable) or {}).get("mean")
    recent_by_activity = _hr_stats_by_activity(reliable)
    baseline_by_activity = baseline_hr.get("by_activity") or {}

    rest_delta = None
    if "REST" in recent_by_activity and "REST" in baseline_by_activity:
        if recent_by_activity["REST"].get("mean") is not None and baseline_by_activity["REST"].get("mean") is not None:
            rest_delta = round(recent_by_activity["REST"]["mean"] - baseline_by_activity["REST"]["mean"], 2)

    abnormal_ratio = round(_ratio(reliable, _is_abnormal_anomaly), 4)
    baseline_abnormal = float((baseline.get("anomaly") or {}).get("abnormal_ratio") or 0.0)
    af_ratio = round(_ratio(reliable, _is_af_suspicion), 4)
    baseline_af = float((baseline.get("rhythm") or {}).get("af_suspicion_ratio") or 0.0)
    ectopy_ratio = round(_ratio(reliable, _is_ectopy), 4)
    baseline_ectopy = float((baseline.get("ectopy") or {}).get("ectopy_ratio") or 0.0)

    comparisons = {
        "recent_reliable_prediction_count": len(reliable),
        "mean_hr_delta_bpm": (
            round(recent_overall - baseline_overall, 2)
            if recent_overall is not None and baseline_overall is not None
            else None
        ),
        "resting_hr_delta_bpm": rest_delta,
        "abnormal_ratio_delta": round(abnormal_ratio - baseline_abnormal, 4),
        "af_suspicion_ratio_delta": round(af_ratio - baseline_af, 4),
        "ectopy_ratio_delta": round(ectopy_ratio - baseline_ectopy, 4),
        "recent": {
            "mean_hr_bpm": recent_overall,
            "abnormal_ratio": abnormal_ratio,
            "af_suspicion_ratio": af_ratio,
            "ectopy_ratio": ectopy_ratio,
        },
        "baseline": {
            "mean_hr_bpm": baseline_overall,
            "abnormal_ratio": baseline_abnormal,
            "af_suspicion_ratio": baseline_af,
            "ectopy_ratio": baseline_ectopy,
        },
    }
    summary_parts = []
    if comparisons["mean_hr_delta_bpm"] is not None:
        summary_parts.append(f"mean HR delta {comparisons['mean_hr_delta_bpm']:+.1f} bpm")
    if rest_delta is not None:
        summary_parts.append(f"REST HR delta {rest_delta:+.1f} bpm")
    summary_parts.append(f"AF suspicion delta {comparisons['af_suspicion_ratio_delta']:+.1%}")
    summary_parts.append(f"anomaly delta {comparisons['abnormal_ratio_delta']:+.1%}")

    return {
        "calibrated": True,
        "calibration": calibration,
        "baseline_source": baseline.get("source") or {},
        "comparisons": comparisons,
        "summary": "Compared with personal baseline: " + ", ".join(summary_parts) + ".",
    }
