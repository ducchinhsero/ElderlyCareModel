from src.assessment.daily_health_assessment import (
    DISCLAIMER,
    SEVERITY_ORDER,
    compute_daily_health_assessment,
)
from src.assessment.longterm_pathology import compute_longterm_pathology_assessment
from src.calibration.personal_baseline import compare_history_to_baseline, load_personal_baseline
from src.storage.ecg_storage import (
    build_event_timeline,
    compute_period_summary,
    get_history,
)


DEFAULT_REALTIME_MINUTES = 5.0
DEFAULT_DAILY_HOURS = 24.0
DEFAULT_LONG_TERM_DAYS = 7.0


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _level_max(*levels):
    values = [level for level in levels if level]
    if not values:
        return "unknown"
    return max(values, key=lambda level: SEVERITY_ORDER.get(level, 0))


def _finding(finding_type, level, title, reason, evidence):
    return {
        "type": finding_type,
        "level": level,
        "title": title,
        "reason": reason,
        "evidence": evidence,
    }


def _current_level(latest):
    if not latest:
        return "unknown"
    fall = ((latest.get("sensor_context") or {}).get("fall") or {})
    if fall.get("strong_fall"):
        return "critical"
    if fall.get("fall_candidate"):
        return "high"
    return _level_max(
        latest.get("alert_level"),
        (latest.get("rhythm_alert") or {}).get("level"),
        (latest.get("risk") or {}).get("level"),
    )


def _realtime_layer(latest, minutes=DEFAULT_REALTIME_MINUTES):
    if not latest:
        return {
            "layer": "realtime",
            "title": "Realtime status",
            "window": {"mode": "latest_window", "minutes": float(minutes)},
            "overall": {
                "level": "unknown",
                "score": 0.0,
                "summary": "No realtime prediction is available yet.",
            },
            "findings": [],
            "evidence": {},
        }

    rhythm = latest.get("rhythm") or {}
    rhythm_alert = latest.get("rhythm_alert") or {}
    ectopy = latest.get("ectopy") or {}
    hr_event = latest.get("hr_event") or {}
    stress = latest.get("stress") or {}
    quality = latest.get("signal_quality") or {}
    sensor = latest.get("sensor_context") or {}
    fall = sensor.get("fall") or {}
    level = _current_level(latest)

    findings = []
    if rhythm_alert.get("level") in {"medium", "high", "critical"}:
        findings.append(
            _finding(
                "current_rhythm_alert",
                rhythm_alert.get("level"),
                "Current rhythm alert",
                rhythm_alert.get("message") or "Realtime rhythm model raised an alert.",
                {
                    "rhythm_label": rhythm.get("label"),
                    "possible_afib_probability": round(
                        _safe_float(
                            rhythm.get("possible_afib_probability")
                            if rhythm.get("possible_afib_probability") is not None
                            else (rhythm.get("probabilities") or {}).get("possible_afib")
                        ),
                        4,
                    ),
                },
            )
        )
    if ectopy.get("label") in {"pvc", "pac", "mixed_ectopic"}:
        findings.append(
            _finding(
                "current_ectopy",
                "medium",
                "Current PVC/PAC-like activity (experimental)",
                "PVC/PAC-like activity appears in the latest window and is treated as a secondary screening signal.",
                {
                    "ectopy_label": ectopy.get("label"),
                    "pvc_probability": round(_safe_float(ectopy.get("pvc_probability")), 4),
                    "pac_probability": round(_safe_float(ectopy.get("pac_probability")), 4),
                    "assessment_role": "secondary_signal",
                },
            )
        )
    if hr_event.get("level") in {"medium", "high", "critical"}:
        findings.append(
            _finding(
                "current_heart_rate_event",
                hr_event.get("level"),
                "Current heart-rate event",
                hr_event.get("message") or "Heart-rate event detected in the latest window.",
                {"label": hr_event.get("label"), "heart_rate_bpm": latest.get("heart_rate_bpm")},
            )
        )
    if fall.get("strong_fall") or fall.get("fall_candidate"):
        findings.append(
            _finding(
                "current_fall_candidate",
                "critical" if fall.get("strong_fall") else "high",
                "Current fall candidate",
                "Possible fall event detected from the latest ACC window.",
                {
                    "strong_fall": bool(fall.get("strong_fall")),
                    "fall_candidate": bool(fall.get("fall_candidate")),
                    "peak_vm": fall.get("peak_vm"),
                },
            )
        )
    if quality.get("label") not in {"good", "fair"}:
        findings.append(
            _finding(
                "current_signal_quality",
                "medium",
                "Current signal quality issue",
                "Latest ECG signal quality may reduce confidence.",
                {"label": quality.get("label"), "score": quality.get("score")},
            )
        )
    if stress.get("label") == "stress" and quality.get("label") in {"good", "fair"}:
        findings.append(
            _finding(
                "current_stress_pattern",
                "medium",
                "Current stress-like pattern",
                "Latest reliable ECG window indicates a stress-like HRV pattern.",
                {
                    "confidence": stress.get("confidence"),
                    "stress_probability": (stress.get("probabilities") or {}).get("stress"),
                },
            )
        )
    alert_level = latest.get("alert_level")
    strongest_finding = _level_max(*(finding["level"] for finding in findings)) if findings else "unknown"
    if SEVERITY_ORDER.get(alert_level, 0) > SEVERITY_ORDER.get(strongest_finding, 0):
        findings.append(
            _finding(
                "current_overall_alert",
                alert_level,
                "Current overall alert",
                latest.get("message") or "Latest window raised an overall alert.",
                {
                    "alert_level": alert_level,
                    "risk_level": (latest.get("risk") or {}).get("level"),
                    "rhythm_alert_level": rhythm_alert.get("level"),
                },
            )
        )

    summary = (
        "Latest window is stable."
        if level in {"unknown", "normal", "low"}
        else "Latest window contains a realtime alert that should be reviewed."
    )
    return {
        "layer": "realtime",
        "title": "Realtime status",
        "window": {
            "mode": "latest_window",
            "minutes": float(minutes),
            "timestamp": latest.get("timestamp"),
            "window_count": latest.get("window_count"),
        },
        "overall": {
            "level": "low" if level == "normal" else level,
            "score": _safe_float((latest.get("risk") or {}).get("score")),
            "summary": summary,
        },
        "findings": findings,
        "evidence": {
            "patient_id": latest.get("patient_id"),
            "heart_rate_bpm": latest.get("heart_rate_bpm"),
            "stress": stress.get("label"),
            "rhythm": rhythm.get("label"),
            "ectopy": ectopy.get("label"),
            "anomaly": (latest.get("anomaly") or {}).get("label"),
            "signal_quality": quality.get("label"),
            "activity": sensor.get("activity_state"),
        },
    }


def _event_count(events, event_type):
    return sum(1 for event in events if event.get("event_type") == event_type)


def _long_term_layer(patient_id=None, days=DEFAULT_LONG_TERM_DAYS, db_path=None):
    summary_kwargs = {"patient_id": patient_id, "days": days}
    events_kwargs = {"patient_id": patient_id, "days": days, "limit": 10000}
    if db_path is not None:
        summary_kwargs["db_path"] = db_path
        events_kwargs["db_path"] = db_path
    daily_summary = compute_period_summary(**summary_kwargs)
    events = build_event_timeline(**events_kwargs).get("events") or []

    window_count = int(daily_summary.get("window_count") or 0)
    day_count = int(daily_summary.get("day_count") or 0)
    overall = daily_summary.get("overall") or {}
    if window_count < 20:
        level = "unknown"
        summary = "Not enough multi-day data for a long-term assessment."
        findings = []
    else:
        findings = []
        af_count = _event_count(events, "af_suspicion")
        ectopy_count = _event_count(events, "ectopy_suspicion")
        tachy_count = _event_count(events, "tachycardia")
        brady_count = _event_count(events, "bradycardia")
        fall_count = _event_count(events, "fall_candidate")
        poor_signal_count = _event_count(events, "poor_signal")
        max_af_burden = _safe_float(overall.get("max_af_burden_percent"))
        max_afib_probability = _safe_float(overall.get("max_afib_probability"))
        af_ratio = _safe_float(overall.get("af_suspicion_window_ratio"))
        good_signal_ratio = _safe_float(overall.get("good_signal_ratio"))

        if af_count >= 10 or af_ratio >= 0.10 or max_af_burden >= 10.0:
            af_level = "high"
        elif af_count >= 3 or af_ratio >= 0.03 or max_afib_probability >= 0.28:
            af_level = "medium"
        else:
            af_level = None
        if af_level:
            findings.append(
                _finding(
                    "long_term_afib_suspicion",
                    af_level,
                    "Repeated AFib-like pattern",
                    "AFib-like rhythm patterns appear repeatedly across the selected days.",
                    {
                        "event_count": af_count,
                        "af_suspicion_window_ratio": round(af_ratio, 4),
                        "max_afib_probability": round(max_afib_probability, 4),
                        "max_af_burden_percent": round(max_af_burden, 2),
                    },
                )
            )

        if ectopy_count >= 5:
            ectopy_level = "medium"
        else:
            ectopy_level = None
        if ectopy_level:
            findings.append(
                _finding(
                    "long_term_ectopy_activity",
                    ectopy_level,
                    "Repeated PVC/PAC-like activity (experimental)",
                    "PVC/PAC-like events recur across the selected days and should be interpreted as a secondary signal.",
                    {"event_count": ectopy_count, "assessment_role": "secondary_signal"},
                )
            )

        hr_event_count = tachy_count + brady_count
        if hr_event_count >= 10:
            hr_level = "high"
        elif hr_event_count >= 3:
            hr_level = "medium"
        else:
            hr_level = None
        if hr_level:
            findings.append(
                _finding(
                    "long_term_heart_rate_abnormality",
                    hr_level,
                    "Repeated heart-rate abnormality",
                    "Tachycardia or bradycardia events recur across the selected days.",
                    {
                        "event_count": hr_event_count,
                        "tachycardia_event_count": tachy_count,
                        "bradycardia_event_count": brady_count,
                    },
                )
            )

        if fall_count:
            findings.append(
                _finding(
                    "long_term_fall_risk",
                    "high",
                    "Fall candidate in selected period",
                    "At least one fall candidate exists in the selected days.",
                    {"event_count": fall_count},
                )
            )

        if good_signal_ratio and good_signal_ratio < 0.5:
            findings.append(
                _finding(
                    "long_term_poor_signal",
                    "high",
                    "Poor long-term signal quality",
                    "Signal quality is too low for reliable long-term interpretation.",
                    {
                        "good_signal_ratio": round(good_signal_ratio, 4),
                        "poor_signal_event_count": poor_signal_count,
                    },
                )
            )

        level = _level_max(*(finding["level"] for finding in findings)) if findings else "low"
        summary = (
            "No significant multi-day risk pattern detected."
            if not findings
            else "Multi-day risk/suspicion pattern detected: "
            + ", ".join(finding["title"] for finding in findings[:3])
            + "."
        )

    return {
        "layer": "long_term",
        "title": "Long-term trend",
        "window": {
            "mode": "rolling_days",
            "days": float(days),
            "day_count": day_count,
            "prediction_count": window_count,
        },
        "overall": {
            "level": level,
            "score": {"unknown": 0.0, "low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}.get(level, 0.0),
            "summary": summary,
        },
        "findings": findings,
        "evidence": {
            "overall": overall,
            "day_count": day_count,
            "prediction_count": window_count,
            "event_count": len(events),
        },
    }


def build_temporal_health_report(
    latest_prediction=None,
    patient_id=None,
    realtime_minutes=DEFAULT_REALTIME_MINUTES,
    daily_hours=DEFAULT_DAILY_HOURS,
    long_term_days=DEFAULT_LONG_TERM_DAYS,
    db_path=None,
):
    resolved_patient_id = patient_id or (latest_prediction or {}).get("patient_id")
    daily_kwargs = {"patient_id": resolved_patient_id, "hours": daily_hours}
    if db_path is not None:
        daily_kwargs["db_path"] = db_path
    daily = compute_daily_health_assessment(**daily_kwargs)
    realtime = _realtime_layer(latest_prediction, minutes=realtime_minutes)
    long_term = _long_term_layer(patient_id=resolved_patient_id, days=long_term_days, db_path=db_path)
    history_kwargs = {
        "patient_id": resolved_patient_id,
        "days": max(float(long_term_days), 1.0 / 24.0),
        "limit": 5000,
    }
    if db_path is not None:
        history_kwargs["db_path"] = db_path
    baseline = load_personal_baseline(resolved_patient_id) if resolved_patient_id else None
    personal_baseline = compare_history_to_baseline(get_history(**history_kwargs), baseline)
    pathology = compute_longterm_pathology_assessment(
        patient_id=resolved_patient_id,
        days=long_term_days,
        db_path=db_path,
    )
    levels = [
        realtime.get("overall", {}).get("level"),
        daily.get("overall", {}).get("level"),
        long_term.get("overall", {}).get("level"),
    ]
    overall_level = _level_max(*[level for level in levels if level != "unknown"])
    if all(level == "unknown" for level in levels):
        overall_level = "unknown"
    return {
        "patient_id": resolved_patient_id or daily.get("patient_id"),
        "report_type": "temporal_health_report",
        "layers": {
            "realtime": realtime,
            "daily": daily,
            "long_term": long_term,
        },
        "personal_baseline": personal_baseline,
        "pathology": pathology,
        "overall": {
            "level": overall_level,
            "summary": "Highest current risk/suspicion level across realtime, daily, and long-term layers.",
        },
        "disclaimer": DISCLAIMER,
    }


def compute_temporal_health_report(
    patient_id=None,
    realtime_minutes=DEFAULT_REALTIME_MINUTES,
    daily_hours=DEFAULT_DAILY_HOURS,
    long_term_days=DEFAULT_LONG_TERM_DAYS,
    db_path=None,
):
    history_kwargs = {
        "patient_id": patient_id,
        "days": max(float(long_term_days), 1.0 / 24.0),
        "limit": 1,
    }
    if db_path is not None:
        history_kwargs["db_path"] = db_path
    latest = (get_history(**history_kwargs) or [None])[0]
    return build_temporal_health_report(
        latest_prediction=latest,
        patient_id=patient_id,
        realtime_minutes=realtime_minutes,
        daily_hours=daily_hours,
        long_term_days=long_term_days,
        db_path=db_path,
    )
