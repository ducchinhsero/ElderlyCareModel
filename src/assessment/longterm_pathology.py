"""Long-term pathology screening layer (roadmap section 4.5).

This module turns multi-day prediction history into recurrence/burden based
pathology indicators. It is intentionally a *deterministic rule layer*, not a
trained clinical-grade model: every output is explainable from the underlying
daily aggregates and event timeline, and the project does not yet have the
labelled multi-day clinical data needed to train/validate a diagnostic model.

Design vs the simpler ``temporal_health_report._long_term_layer`` (which flat
counts events over the whole window):

- Looks at **per-day recurrence** ("AFib-like pattern on 4 of 6 reliable days")
  instead of a single total count, which is far more meaningful for chronic /
  intermittent conditions.
- Computes **burden** (mean/max AF burden %, ectopy window ratio, HR event
  rate) and a coarse **trend** direction across the analysed days.
- Is **signal-quality corrected**: only days with enough reliable windows count
  toward recurrence, and coverage is surfaced so that an "all clear" result is
  not mistaken for "well monitored and clear".
- Frames every finding as a screening/referral suggestion
  ("discuss with medical staff" / "see a doctor if it recurs or symptoms
  appear"), never as a definite diagnosis.

Output is consumed by ``GET /pathology-report`` and embedded as the
``pathology`` block of the temporal health report.
"""

from datetime import datetime, timedelta, timezone

from src.assessment.daily_health_assessment import (
    DISCLAIMER,
    SEVERITY_ORDER,
    SEVERITY_SCORE,
)
from src.calibration.personal_baseline import (
    compare_history_to_baseline,
    load_personal_baseline,
)
from src.storage.ecg_storage import (
    build_event_timeline,
    compute_period_summary,
    get_history,
)


DEFAULT_LONG_TERM_DAYS = 7.0

# A calendar day needs at least this many windows and this good-signal ratio to
# be treated as "reliably monitored" and counted toward recurrence.
MIN_DAY_WINDOWS = 10
MIN_DAY_GOOD_SIGNAL_RATIO = 0.5
# Below this many reliably monitored days, findings are flagged "preview".
MIN_CONFIDENT_ADEQUATE_DAYS = 3

# Per-day presence thresholds.
AF_DAY_WINDOW_RATIO = 0.05
AF_DAY_BURDEN_PERCENT = 5.0
AF_DAY_PROBABILITY = 0.28
ECTOPY_DAY_WINDOW_RATIO = 0.05

# Trend ratios (later-half mean vs earlier-half mean of present-day burden).
TREND_UP_RATIO = 1.2
TREND_DOWN_RATIO = 0.8

# Event types grouped by clinical meaning.
HR_NOTIFICATION_EVENT_TYPES = ("tachycardia", "bradycardia")
HR_SUSTAINED_EVENT_TYPES = (
    "sustained_tachycardia_immobile",
    "sustained_bradycardia_immobile",
)
HR_CRITICAL_EVENT_TYPES = ("critical_hr_immobile",)
ECTOPY_EVENT_TYPES = ("ectopy_suspicion",)
FALL_EVENT_TYPES = ("fall_candidate",)


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


def _event_day(event):
    timestamp = event.get("timestamp")
    if timestamp:
        try:
            dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.date().isoformat()
        except ValueError:
            pass
    epoch = event.get("timestamp_epoch")
    if epoch is not None:
        try:
            return datetime.fromtimestamp(float(epoch), timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            return None
    return None


def _trend(values):
    """Coarse trend direction from a chronological burden series."""
    series = [v for v in values if v is not None]
    if len(series) < 2:
        return "insufficient"
    mid = len(series) // 2
    earlier = series[:mid] or series[:1]
    later = series[mid:] or series[-1:]
    earlier_mean = sum(earlier) / len(earlier)
    later_mean = sum(later) / len(later)
    if earlier_mean <= 1e-9:
        return "increasing" if later_mean > 1e-9 else "stable"
    ratio = later_mean / earlier_mean
    if ratio >= TREND_UP_RATIO:
        return "increasing"
    if ratio <= TREND_DOWN_RATIO:
        return "decreasing"
    return "stable"


def _recurrence(days_present, adequate_day_count):
    ratio = (days_present / adequate_day_count) if adequate_day_count else 0.0
    return {
        "days_present": int(days_present),
        "adequate_day_count": int(adequate_day_count),
        "recurrence_ratio": round(ratio, 4),
    }


def _indicator(indicator_type, level, title, reason, recurrence, burden, trend, referral, evidence):
    return {
        "type": indicator_type,
        "level": level,
        "title": title,
        "reason": reason,
        "recurrence": recurrence,
        "burden": burden,
        "trend": trend,
        "referral": referral,
        "evidence": evidence,
    }


def _is_adequate_day(day_row):
    window_count = int(day_row.get("window_count") or 0)
    good_ratio = _safe_float(day_row.get("good_signal_ratio"))
    return window_count >= MIN_DAY_WINDOWS and good_ratio >= MIN_DAY_GOOD_SIGNAL_RATIO


def _events_by_day(events):
    grouped = {}
    for event in events:
        day = _event_day(event)
        if day is None:
            continue
        grouped.setdefault(day, []).append(event)
    return grouped


def _day_event_count(day_events, event_types):
    types = set(event_types)
    return sum(1 for event in day_events if event.get("event_type") in types)


def _af_indicator(adequate_days, events_by_day, adequate_day_count):
    present_days = []
    burdens = []
    probabilities = []
    ratios = []
    for day_row in adequate_days:
        af_burden = _safe_float(day_row.get("max_af_burden_percent"))
        afib_prob = _safe_float(day_row.get("max_afib_probability"))
        af_ratio = _safe_float(day_row.get("af_suspicion_window_ratio"))
        present = (
            af_ratio >= AF_DAY_WINDOW_RATIO
            or af_burden >= AF_DAY_BURDEN_PERCENT
            or afib_prob >= AF_DAY_PROBABILITY
        )
        if present:
            present_days.append(day_row.get("day"))
            burdens.append(af_burden)
            probabilities.append(afib_prob)
            ratios.append(af_ratio)
    days_present = len(present_days)
    if days_present == 0:
        return None

    mean_burden = sum(burdens) / len(burdens) if burdens else 0.0
    max_burden = max(burdens) if burdens else 0.0
    recurrence_ratio = days_present / adequate_day_count if adequate_day_count else 0.0
    if (
        days_present >= 3
        or recurrence_ratio >= 0.4
        or mean_burden >= 10.0
        or max_burden >= 20.0
    ):
        level = "high"
        referral = (
            "AFib-like rhythm recurs across multiple reliably monitored days. "
            "Recommend discussing with medical staff and considering a Holter / "
            "12-lead ECG evaluation."
        )
    else:
        level = "medium"
        referral = (
            "AFib-like rhythm appeared on at least one reliably monitored day. "
            "Continue monitoring; consult medical staff if it recurs or symptoms occur."
        )
    return _indicator(
        "atrial_fibrillation_burden",
        level,
        "Recurrent AFib-like pattern",
        "AFib-like rhythm pattern recurs across the analysed days.",
        _recurrence(days_present, adequate_day_count),
        {
            "mean_af_burden_percent": round(mean_burden, 2),
            "max_af_burden_percent": round(max_burden, 2),
            "max_afib_probability": round(max(probabilities), 4) if probabilities else 0.0,
            "mean_af_suspicion_window_ratio": round(sum(ratios) / len(ratios), 4) if ratios else 0.0,
        },
        _trend(burdens),
        referral,
        {"present_days": present_days},
    )


def _hr_indicator(adequate_days, events_by_day, adequate_day_count):
    present_days = []
    daily_counts = []
    tachy_total = 0
    brady_total = 0
    sustained_total = 0
    critical_total = 0
    for day_row in adequate_days:
        day = day_row.get("day")
        day_events = events_by_day.get(day, [])
        notification = _day_event_count(day_events, HR_NOTIFICATION_EVENT_TYPES)
        sustained = _day_event_count(day_events, HR_SUSTAINED_EVENT_TYPES)
        critical = _day_event_count(day_events, HR_CRITICAL_EVENT_TYPES)
        tachy_total += _day_event_count(day_events, ("tachycardia",))
        brady_total += _day_event_count(day_events, ("bradycardia",))
        sustained_total += sustained
        critical_total += critical
        day_total = notification + sustained + critical
        if day_total > 0:
            present_days.append(day)
            daily_counts.append(day_total)
    days_present = len(present_days)
    total_events = tachy_total + brady_total + sustained_total + critical_total
    if days_present == 0 and total_events == 0:
        return None

    recurrence_ratio = days_present / adequate_day_count if adequate_day_count else 0.0
    if critical_total > 0:
        level = "critical"
        referral = (
            "Dangerously high/low heart rate occurred while the user appeared "
            "immobile. Check the user and seek urgent medical advice."
        )
    elif sustained_total > 0 or days_present >= 3 or total_events >= 10 or recurrence_ratio >= 0.4:
        level = "high"
        referral = (
            "Heart-rate abnormalities recur across multiple days (including "
            "sustained episodes while immobile). Recommend discussing with medical staff."
        )
    else:
        level = "medium"
        referral = (
            "Occasional tachycardia/bradycardia events were detected. Continue "
            "monitoring; consult medical staff if they recur or symptoms occur."
        )
    return _indicator(
        "heart_rate_abnormality_burden",
        level,
        "Recurrent heart-rate abnormality",
        "Tachycardia / bradycardia (including sustained-while-immobile) events recur across the analysed days.",
        _recurrence(days_present, adequate_day_count),
        {
            "total_event_count": total_events,
            "tachycardia_event_count": tachy_total,
            "bradycardia_event_count": brady_total,
            "sustained_immobile_event_count": sustained_total,
            "critical_immobile_event_count": critical_total,
        },
        _trend(daily_counts),
        referral,
        {"present_days": present_days},
    )


def _ectopy_indicator(adequate_days, events_by_day, adequate_day_count):
    present_days = []
    daily_ratios = []
    event_total = 0
    pvc_windows = 0
    pac_windows = 0
    for day_row in adequate_days:
        day = day_row.get("day")
        ectopy_counts = day_row.get("ectopy_counts") or {}
        window_count = int(day_row.get("window_count") or 0)
        pvc = int(ectopy_counts.get("pvc") or 0)
        pac = int(ectopy_counts.get("pac") or 0)
        mixed = int(ectopy_counts.get("mixed_ectopic") or 0)
        ectopy_windows = pvc + pac + mixed
        day_ratio = (ectopy_windows / window_count) if window_count else 0.0
        day_event_count = _day_event_count(events_by_day.get(day, []), ECTOPY_EVENT_TYPES)
        event_total += day_event_count
        pvc_windows += pvc
        pac_windows += pac
        if day_ratio >= ECTOPY_DAY_WINDOW_RATIO or day_event_count > 0:
            present_days.append(day)
            daily_ratios.append(day_ratio)
    days_present = len(present_days)
    if days_present == 0:
        return None

    recurrence_ratio = days_present / adequate_day_count if adequate_day_count else 0.0
    mean_ratio = sum(daily_ratios) / len(daily_ratios) if daily_ratios else 0.0
    if days_present >= 3 or recurrence_ratio >= 0.4:
        level = "high"
    else:
        level = "medium"
    referral = (
        "PVC/PAC-like activity recurs across the analysed days. This is an "
        "experimental secondary signal; mention it to medical staff if it "
        "persists or symptoms occur."
    )
    return _indicator(
        "ectopy_burden",
        level,
        "Recurrent PVC/PAC-like activity (experimental)",
        "PVC/PAC-like activity recurs across the analysed days and is treated as a secondary screening signal.",
        _recurrence(days_present, adequate_day_count),
        {
            "mean_ectopy_window_ratio": round(mean_ratio, 4),
            "ectopy_event_count": event_total,
            "pvc_window_count": pvc_windows,
            "pac_window_count": pac_windows,
            "assessment_role": "secondary_signal",
        },
        _trend(daily_ratios),
        referral,
        {"present_days": present_days},
    )


def _fall_indicator(events_by_day, adequate_day_count, analyzed_day_count):
    present_days = []
    total = 0
    critical_total = 0
    for day, day_events in events_by_day.items():
        fall_events = [e for e in day_events if e.get("event_type") in FALL_EVENT_TYPES]
        if not fall_events:
            continue
        present_days.append(day)
        total += len(fall_events)
        critical_total += sum(1 for e in fall_events if str(e.get("severity")) == "critical")
    if total == 0:
        return None
    level = "critical" if critical_total > 0 else "high"
    referral = (
        "One or more fall candidates were detected in the period. Confirm "
        "whether a fall occurred and review fall-prevention measures with caregivers."
    )
    # Fall recurrence is reported against analysed days (a fall on a poorly
    # monitored day still matters), so use analyzed_day_count as denominator.
    return _indicator(
        "fall_activity_risk",
        level,
        "Fall candidate in period",
        "Fall candidate events were detected across the analysed days.",
        _recurrence(len(present_days), analyzed_day_count or adequate_day_count),
        {"fall_event_count": total, "critical_fall_event_count": critical_total},
        _trend([1.0] * len(present_days)),
        referral,
        {"present_days": sorted(present_days)},
    )


def _monitoring_quality_indicator(analyzed_days, adequate_day_count, mean_good_signal_ratio):
    analyzed_count = len(analyzed_days)
    if analyzed_count == 0:
        return None
    inadequate = analyzed_count - adequate_day_count
    adequate_ratio = adequate_day_count / analyzed_count if analyzed_count else 0.0
    if adequate_ratio >= 0.7 and inadequate == 0:
        return None
    level = "high" if adequate_ratio < 0.5 else "medium"
    referral = (
        "ECG monitoring coverage was limited on several days. A clear long-term "
        "result may simply reflect insufficient reliable data; check strap "
        "contact and wear time before drawing conclusions."
    )
    return _indicator(
        "monitoring_quality",
        level,
        "Limited long-term monitoring coverage",
        "Several analysed days did not have enough reliable ECG windows for confident interpretation.",
        _recurrence(adequate_day_count, analyzed_count),
        {
            "adequate_day_count": adequate_day_count,
            "inadequate_day_count": inadequate,
            "adequate_day_ratio": round(adequate_ratio, 4),
            "mean_good_signal_ratio": round(mean_good_signal_ratio, 4),
        },
        "insufficient",
        referral,
        {},
    )


def _data_quality(analyzed_days, adequate_day_count, prediction_count):
    analyzed_count = len(analyzed_days)
    good_ratios = [_safe_float(day.get("good_signal_ratio")) for day in analyzed_days]
    mean_good = sum(good_ratios) / len(good_ratios) if good_ratios else 0.0
    if adequate_day_count == 0 or prediction_count < MIN_DAY_WINDOWS:
        label = "insufficient"
    elif adequate_day_count < MIN_CONFIDENT_ADEQUATE_DAYS:
        label = "preview"
    else:
        label = "confident"
    return {
        "label": label,
        "analyzed_day_count": analyzed_count,
        "adequate_day_count": adequate_day_count,
        "adequate_day_ratio": round(adequate_day_count / analyzed_count, 4) if analyzed_count else 0.0,
        "mean_good_signal_ratio": round(mean_good, 4),
        "prediction_count": int(prediction_count),
    }, mean_good


def _recommendations(overall_level, indicators, data_quality):
    recommendations = []
    indicator_types = {indicator["type"] for indicator in indicators}
    if data_quality["label"] == "insufficient":
        recommendations.append(
            "Collect more reliable multi-day ECG data before relying on the long-term assessment."
        )
    if "monitoring_quality" in indicator_types:
        recommendations.append(
            "Improve wear time and strap contact so long-term trends can be interpreted with confidence."
        )
    if "fall_activity_risk" in indicator_types:
        recommendations.append("Confirm whether a fall occurred and review fall-prevention measures.")
    if overall_level in {"critical", "high"}:
        recommendations.append(
            "Share the long-term report and event timeline with medical staff for review."
        )
    elif overall_level == "medium":
        recommendations.append(
            "Continue monitoring. If the pattern recurs or symptoms appear, consult medical staff."
        )
    else:
        recommendations.append("Continue routine long-term monitoring.")
    return recommendations


def _overall_summary(level, indicators, data_quality):
    if data_quality["label"] == "insufficient":
        return "Not enough reliable multi-day ECG data for a long-term pathology assessment."
    pathology = [i for i in indicators if i["type"] != "monitoring_quality"]
    if not pathology:
        return "No recurrent multi-day pathology pattern detected."
    titles = ", ".join(indicator["title"] for indicator in pathology[:3])
    prefix = "Preliminary " if data_quality["label"] == "preview" else ""
    return f"{prefix}{level} long-term risk/suspicion pattern detected: {titles}."


def _baseline_indicator(baseline_comparison):
    """Indicator when recent readings deviate from the user's own 7-day baseline."""
    if not baseline_comparison or not baseline_comparison.get("calibrated"):
        return None
    comparisons = baseline_comparison.get("comparisons") or {}
    if not comparisons:
        return None
    rest_delta = comparisons.get("resting_hr_delta_bpm")
    af_delta = _safe_float(comparisons.get("af_suspicion_ratio_delta"))
    abnormal_delta = _safe_float(comparisons.get("abnormal_ratio_delta"))
    ectopy_delta = _safe_float(comparisons.get("ectopy_ratio_delta"))

    signals = []
    score = 0
    if rest_delta is not None and abs(rest_delta) >= 12:
        signals.append(f"resting HR {rest_delta:+.0f} bpm vs personal baseline")
        score += 2 if abs(rest_delta) >= 20 else 1
    if af_delta >= 0.05:
        signals.append(f"AFib-suspicion ratio {af_delta:+.1%} vs baseline")
        score += 2 if af_delta >= 0.10 else 1
    if abnormal_delta >= 0.10:
        signals.append(f"ECG anomaly ratio {abnormal_delta:+.1%} vs baseline")
        score += 1
    if ectopy_delta >= 0.05:
        signals.append(f"PVC/PAC ratio {ectopy_delta:+.1%} vs baseline")
        score += 1
    if not signals:
        return None

    level = "high" if score >= 3 else "medium"
    return _indicator(
        "personal_baseline_deviation",
        level,
        "Deviation from personal baseline",
        "Recent readings differ from this user's established personal baseline: "
        + "; ".join(signals)
        + ".",
        _recurrence(0, 0),
        {
            "resting_hr_delta_bpm": rest_delta,
            "af_suspicion_ratio_delta": round(af_delta, 4),
            "abnormal_ratio_delta": round(abnormal_delta, 4),
            "ectopy_ratio_delta": round(ectopy_delta, 4),
            "deviation_score": score,
            "recent": comparisons.get("recent"),
            "baseline": comparisons.get("baseline"),
        },
        "insufficient",
        "Recent readings deviate from the user's own baseline. Discuss with "
        "medical staff if the change persists or symptoms occur.",
        {"recent_reliable_prediction_count": comparisons.get("recent_reliable_prediction_count")},
    )


def build_longterm_pathology_assessment(
    daily_summary,
    events,
    patient_id=None,
    days=DEFAULT_LONG_TERM_DAYS,
    baseline_comparison=None,
    now=None,
):
    """Build the long-term pathology assessment from pre-computed aggregates.

    ``daily_summary`` is the output of ``compute_period_summary`` (or the
    compatible ``compute_daily_summary``) and ``events``
    is the ``events`` list from ``build_event_timeline``. Kept pure (no DB
    access) so it is fully unit-testable.
    """
    if days is None or float(days) <= 0:
        raise ValueError("days must be a positive number.")
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=float(days))

    daily_summary = daily_summary or {}
    analyzed_days = list(daily_summary.get("days") or [])
    prediction_count = int(daily_summary.get("window_count") or 0)
    events = list(events or [])
    events_by_day = _events_by_day(events)

    adequate_days = [day for day in analyzed_days if _is_adequate_day(day)]
    adequate_day_count = len(adequate_days)
    data_quality, mean_good = _data_quality(analyzed_days, adequate_day_count, prediction_count)

    indicators = []
    if adequate_day_count > 0:
        for indicator in (
            _af_indicator(adequate_days, events_by_day, adequate_day_count),
            _hr_indicator(adequate_days, events_by_day, adequate_day_count),
            _ectopy_indicator(adequate_days, events_by_day, adequate_day_count),
        ):
            if indicator:
                indicators.append(indicator)
    # Fall candidates and coverage warnings are reported even when no day is
    # "adequate" — a fall on a poorly-monitored day still matters.
    fall = _fall_indicator(events_by_day, adequate_day_count, len(analyzed_days))
    if fall:
        indicators.append(fall)
    monitoring = _monitoring_quality_indicator(analyzed_days, adequate_day_count, mean_good)
    if monitoring:
        indicators.append(monitoring)
    baseline_indicator = _baseline_indicator(baseline_comparison)
    if baseline_indicator:
        indicators.append(baseline_indicator)

    pathology_indicators = [i for i in indicators if i["type"] != "monitoring_quality"]
    if data_quality["label"] == "insufficient":
        level = "unknown"
    elif pathology_indicators:
        level = _level_max(*(indicator["level"] for indicator in pathology_indicators))
    else:
        level = "low"

    resolved_patient = patient_id or daily_summary.get("patient_id")
    return {
        "patient_id": resolved_patient,
        "report_type": "longterm_pathology_assessment",
        "period": {
            "mode": "rolling_days",
            "days": float(days),
            "analyzed_day_count": len(analyzed_days),
            "adequate_day_count": adequate_day_count,
            "prediction_count": prediction_count,
            "start_timestamp": start.isoformat(),
            "end_timestamp": now.isoformat(),
        },
        "data_quality": data_quality,
        "overall": {
            "level": level,
            "score": SEVERITY_SCORE.get(level, 0.0),
            "summary": _overall_summary(level, indicators, data_quality),
        },
        "indicators": indicators,
        "personal_baseline": baseline_comparison
        or {"calibrated": False, "comparisons": {}},
        "recommendations": _recommendations(level, indicators, data_quality),
        "disclaimer": DISCLAIMER,
    }


def compute_longterm_pathology_assessment(
    patient_id=None,
    days=DEFAULT_LONG_TERM_DAYS,
    db_path=None,
):
    """DB-backed long-term pathology assessment for a patient."""
    if days is None or float(days) <= 0:
        raise ValueError("days must be a positive number.")
    summary_kwargs = {"patient_id": patient_id, "days": days}
    events_kwargs = {"patient_id": patient_id, "days": days, "limit": 10000}
    if db_path is not None:
        summary_kwargs["db_path"] = db_path
        events_kwargs["db_path"] = db_path
    daily_summary = compute_period_summary(**summary_kwargs)
    events = build_event_timeline(**events_kwargs).get("events") or []

    baseline_comparison = None
    if patient_id:
        baseline = load_personal_baseline(patient_id)
        if baseline:
            history_kwargs = {
                "patient_id": patient_id,
                "days": min(float(days), 2.0),
                "limit": 5000,
            }
            if db_path is not None:
                history_kwargs["db_path"] = db_path
            baseline_comparison = compare_history_to_baseline(
                get_history(**history_kwargs), baseline
            )

    return build_longterm_pathology_assessment(
        daily_summary=daily_summary,
        events=events,
        patient_id=patient_id,
        days=days,
        baseline_comparison=baseline_comparison,
    )
