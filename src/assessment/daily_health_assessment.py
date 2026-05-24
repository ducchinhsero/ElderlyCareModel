from datetime import datetime, timedelta, timezone

from src.storage.ecg_storage import build_event_timeline, get_history


DISCLAIMER = "This is a screening/risk assessment output, not a medical diagnosis."
RELIABLE_QUALITY = {"good", "fair"}
POOR_QUALITY = {"poor", "noise", "poor_contact", "motion_artifact"}
SEVERITY_ORDER = {
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
SEVERITY_SCORE = {
    "unknown": 0.0,
    "low": 0.2,
    "medium": 0.5,
    "high": 0.8,
    "critical": 1.0,
}


def _utc_now():
    return datetime.now(timezone.utc)


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _count_events(events, event_type):
    return sum(1 for event in events if event.get("event_type") == event_type)


def _max_afib_probability(history):
    values = []
    for item in history:
        rhythm = item.get("rhythm") or {}
        if rhythm.get("possible_afib_probability") is not None:
            values.append(_safe_float(rhythm.get("possible_afib_probability")))
        else:
            values.append(_safe_float((rhythm.get("probabilities") or {}).get("possible_afib")))
    return max(values) if values else 0.0


def _max_af_burden(history):
    values = [_safe_float((item.get("af_episode") or {}).get("af_burden_percent")) for item in history]
    return max(values) if values else 0.0


def _quality_label(item):
    return (item.get("signal_quality") or {}).get("label")


def _is_reliable(item):
    return _quality_label(item) in RELIABLE_QUALITY


def _is_poor_signal(item):
    return _quality_label(item) in POOR_QUALITY


def _af_suspicion_item(item):
    rhythm = item.get("rhythm") or {}
    rhythm_alert = item.get("rhythm_alert") or {}
    probability = (
        rhythm.get("possible_afib_probability")
        if rhythm.get("possible_afib_probability") is not None
        else (rhythm.get("probabilities") or {}).get("possible_afib")
    )
    return (
        rhythm.get("label") == "possible_afib"
        or _safe_float(probability) >= 0.28
        or rhythm_alert.get("level") in {"medium", "high", "critical"}
    )


def _ectopy_item(item):
    ectopy = item.get("ectopy") or {}
    return ectopy.get("label") in {"pvc", "pac", "mixed_ectopic"}


def _abnormal_anomaly_item(item):
    anomaly = item.get("anomaly") or {}
    return anomaly.get("value") == 1 or anomaly.get("label") == "abnormal"


def _event_label_count(events, event_type, label=None):
    return sum(
        1
        for event in events
        if event.get("event_type") == event_type
        and (label is None or event.get("label") == label)
    )


def _level_from_findings(findings):
    if not findings:
        return "low"
    return max((finding["level"] for finding in findings), key=lambda level: SEVERITY_ORDER.get(level, 0))


def _finding(finding_type, level, title, reason, evidence):
    return {
        "type": finding_type,
        "level": level,
        "title": title,
        "reason": reason,
        "evidence": evidence,
    }


def _data_quality(history):
    prediction_count = len(history)
    reliable_count = sum(1 for item in history if _is_reliable(item))
    valid_signal_ratio = reliable_count / prediction_count if prediction_count else 0.0
    poor_signal_count = sum(1 for item in history if _is_poor_signal(item))

    if prediction_count < 3:
        label = "insufficient"
        confidence = "insufficient"
    elif valid_signal_ratio < 0.5:
        label = "poor"
        confidence = "preview" if prediction_count < 20 else "confident"
    elif valid_signal_ratio < 0.8:
        label = "fair"
        confidence = "preview" if prediction_count < 20 else "confident"
    else:
        label = "good"
        confidence = "preview" if prediction_count < 20 else "confident"

    return {
        "label": label,
        "assessment_confidence": confidence,
        "valid_signal_ratio": round(float(valid_signal_ratio), 4),
        "prediction_count": int(prediction_count),
        "reliable_prediction_count": int(reliable_count),
        "poor_signal_count": int(poor_signal_count),
    }


def _build_findings(history, events, data_quality):
    findings = []
    prediction_count = len(history)
    denominator = max(prediction_count, 1)

    afib_event_count = _count_events(events, "af_suspicion")
    af_suspicion_window_count = sum(1 for item in history if _af_suspicion_item(item))
    af_suspicion_ratio = af_suspicion_window_count / denominator
    max_afib_probability = _max_afib_probability(history)
    max_af_burden_percent = _max_af_burden(history)
    if (
        afib_event_count >= 5
        or af_suspicion_ratio >= 0.15
        or max_af_burden_percent >= 10.0
    ):
        findings.append(
            _finding(
                "afib_suspicion",
                "high",
                "Possible AFib pattern",
                "AFib-like rhythm pattern appears repeatedly in the last 24 hours.",
                {
                    "event_count": afib_event_count,
                    "window_count": af_suspicion_window_count,
                    "max_afib_probability": round(max_afib_probability, 4),
                    "af_suspicion_window_ratio": round(af_suspicion_ratio, 4),
                    "max_af_burden_percent": round(max_af_burden_percent, 2),
                },
            )
        )
    elif (
        afib_event_count >= 2
        or af_suspicion_ratio >= 0.03
        or max_afib_probability >= 0.28
    ):
        findings.append(
            _finding(
                "afib_suspicion",
                "medium",
                "Possible AFib pattern",
                "Possible AFib-like rhythm was detected and should be monitored.",
                {
                    "event_count": afib_event_count,
                    "window_count": af_suspicion_window_count,
                    "max_afib_probability": round(max_afib_probability, 4),
                    "af_suspicion_window_ratio": round(af_suspicion_ratio, 4),
                    "max_af_burden_percent": round(max_af_burden_percent, 2),
                },
            )
        )

    ectopy_event_count = _count_events(events, "ectopy_suspicion")
    ectopy_window_count = sum(1 for item in history if _ectopy_item(item))
    ectopy_ratio = ectopy_window_count / denominator
    pvc_event_count = _event_label_count(events, "ectopy_suspicion", "pvc")
    pac_event_count = _event_label_count(events, "ectopy_suspicion", "pac")
    if ectopy_event_count >= 10 or ectopy_ratio >= 0.20:
        ectopy_level = "high"
    elif ectopy_event_count >= 3 or ectopy_ratio >= 0.05:
        ectopy_level = "medium"
    else:
        ectopy_level = None
    if ectopy_level:
        findings.append(
            _finding(
                "ectopy_activity",
                ectopy_level,
                "PVC/PAC-like activity",
                "PVC/PAC-like activity was observed repeatedly in the monitoring period.",
                {
                    "event_count": ectopy_event_count,
                    "window_count": ectopy_window_count,
                    "ectopy_window_ratio": round(ectopy_ratio, 4),
                    "pvc_event_count": pvc_event_count,
                    "pac_event_count": pac_event_count,
                },
            )
        )

    tachy_count = _count_events(events, "tachycardia")
    brady_count = _count_events(events, "bradycardia")
    hr_event_count = tachy_count + brady_count
    if hr_event_count >= 5:
        hr_level = "high"
    elif hr_event_count >= 2:
        hr_level = "medium"
    else:
        hr_level = None
    if hr_level:
        findings.append(
            _finding(
                "heart_rate_abnormality",
                hr_level,
                "Heart-rate abnormality pattern",
                "Repeated tachycardia or bradycardia events were observed.",
                {
                    "event_count": hr_event_count,
                    "tachycardia_event_count": tachy_count,
                    "bradycardia_event_count": brady_count,
                },
            )
        )

    fall_events = [event for event in events if event.get("event_type") == "fall_candidate"]
    if fall_events:
        level = "critical" if any(event.get("severity") == "critical" for event in fall_events) else "high"
        findings.append(
            _finding(
                "fall_risk",
                level,
                "Possible fall event",
                "A fall candidate was detected and should be checked immediately.",
                {
                    "event_count": len(fall_events),
                    "critical_event_count": sum(1 for event in fall_events if event.get("severity") == "critical"),
                },
            )
        )

    valid_signal_ratio = _safe_float(data_quality.get("valid_signal_ratio"))
    poor_signal_event_count = _count_events(events, "poor_signal")
    if data_quality.get("label") == "poor":
        signal_level = "high"
    elif data_quality.get("label") == "fair" or poor_signal_event_count >= 2:
        signal_level = "medium"
    elif poor_signal_event_count > 0:
        signal_level = "low"
    else:
        signal_level = None
    if signal_level:
        findings.append(
            _finding(
                "poor_signal",
                signal_level,
                "ECG signal quality issue",
                "Signal quality reduced confidence in the health assessment.",
                {
                    "poor_signal_event_count": poor_signal_event_count,
                    "poor_signal_prediction_count": int(data_quality.get("poor_signal_count") or 0),
                    "valid_signal_ratio": round(valid_signal_ratio, 4),
                },
            )
        )

    anomaly_count = sum(1 for item in history if _abnormal_anomaly_item(item))
    anomaly_ratio = anomaly_count / denominator
    if anomaly_count >= 10 or anomaly_ratio >= 0.20:
        anomaly_level = "high"
    elif anomaly_count >= 3 or anomaly_ratio >= 0.05:
        anomaly_level = "medium"
    else:
        anomaly_level = None
    if anomaly_level:
        findings.append(
            _finding(
                "anomaly_trend",
                anomaly_level,
                "Repeated ECG anomaly pattern",
                "The general ECG anomaly detector found repeated abnormal windows.",
                {
                    "abnormal_window_count": anomaly_count,
                    "abnormal_window_ratio": round(anomaly_ratio, 4),
                },
            )
        )

    return findings


def _recommendations(overall_level, findings, data_quality):
    recommendations = []
    finding_types = {finding["type"] for finding in findings}
    if data_quality.get("label") == "insufficient":
        recommendations.append("Collect more ECG data before relying on the daily assessment.")
    if "poor_signal" in finding_types:
        recommendations.append("Check strap position and skin contact before interpreting rhythm findings.")
    if "fall_risk" in finding_types:
        recommendations.append("Check the user immediately and confirm whether a fall occurred.")
    if overall_level in {"critical", "high"}:
        recommendations.append("Review the event timeline and contact medical staff if symptoms are present.")
    elif overall_level == "medium":
        recommendations.append("Continue monitoring. If symptoms occur or medium/high risk repeats, consult medical staff.")
    else:
        recommendations.append("Continue routine monitoring.")
    return recommendations


def _overall_summary(level, findings, data_quality):
    if data_quality.get("label") == "insufficient":
        return "Not enough reliable ECG data for a daily health assessment."
    if not findings:
        return "No significant daily cardiovascular risk pattern detected."
    titles = ", ".join(finding["title"] for finding in findings[:3])
    prefix = "Preliminary " if data_quality.get("assessment_confidence") == "preview" else ""
    return f"{prefix}{level} risk/suspicion pattern detected: {titles}."


def build_daily_health_assessment(
    history,
    events,
    patient_id=None,
    hours=24,
    now=None,
):
    if hours is None or float(hours) <= 0:
        raise ValueError("hours must be a positive number.")
    now = now or _utc_now()
    start = now - timedelta(hours=float(hours))
    history = list(history or [])
    events = list(events or [])
    data_quality = _data_quality(history)
    findings = _build_findings(history, events, data_quality)
    level = _level_from_findings(findings)
    if data_quality["label"] == "insufficient":
        level = "unknown"
    overall = {
        "level": level,
        "score": SEVERITY_SCORE.get(level, 0.0),
        "summary": _overall_summary(level, findings, data_quality),
    }
    resolved_patient = patient_id or (
        history[0].get("patient_id") if history and history[0].get("patient_id") else None
    )
    return {
        "patient_id": resolved_patient,
        "period": {
            "mode": "rolling_24h",
            "hours": float(hours),
            "start_timestamp": start.isoformat(),
            "end_timestamp": now.isoformat(),
        },
        "data_quality": data_quality,
        "overall": overall,
        "findings": findings,
        "recommendations": _recommendations(level, findings, data_quality),
        "disclaimer": DISCLAIMER,
    }


def compute_daily_health_assessment(patient_id=None, hours=24, db_path=None):
    if hours is None or float(hours) <= 0:
        raise ValueError("hours must be a positive number.")
    days = float(hours) / 24.0
    history_kwargs = {"patient_id": patient_id, "days": days, "limit": 10000}
    events_kwargs = {"patient_id": patient_id, "days": days, "limit": 10000}
    if db_path is not None:
        history_kwargs["db_path"] = db_path
        events_kwargs["db_path"] = db_path
    history = get_history(**history_kwargs)
    events = build_event_timeline(**events_kwargs).get("events") or []
    return build_daily_health_assessment(
        history=history,
        events=events,
        patient_id=patient_id,
        hours=hours,
    )
