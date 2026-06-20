"""Pure, dependency-free long-term (multi-day) evaluation thresholds.

This is the coarse severity gate shared by:

- ``temporal_health_report._long_term_layer`` (edge pipeline, 7-day default), and
- ``daily_report.compute_period_report`` (cloud weekly/monthly report).

It is deliberately kept free of any DB / model / sklearn imports so the slim
cloud reader can reuse the exact same evaluation logic the edge backend uses.

The gates are **rate based** (events per reliably-monitored day) rather than
absolute counts, so the same thresholds stay meaningful whether the window is a
week or a month — "10 events" means very different things over 7 vs 30 days. The
per-day rates are tuned so a 7-day window reproduces the previous absolute gates
(~10 events -> high, ~3 -> medium, ~5 ectopy -> medium). The richer per-day
recurrence/burden/trend analysis lives in ``longterm_pathology.py``.
"""

SEVERITY_ORDER = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
SEVERITY_SCORE = {"unknown": 0.0, "low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}

# Need at least this many predictions before any multi-day call is made.
LONG_TERM_MIN_WINDOWS = 20

AF_EVENTS_PER_DAY_HIGH = 1.5
AF_EVENTS_PER_DAY_MEDIUM = 0.4
AF_WINDOW_RATIO_HIGH = 0.10         # >=10% of reliable windows look AFib-like
AF_WINDOW_RATIO_MEDIUM = 0.03
AF_BURDEN_PERCENT_HIGH = 10.0       # peak single-day AF burden
AF_PROBABILITY_MEDIUM = 0.28        # peak model probability

HR_EVENTS_PER_DAY_HIGH = 1.5        # tachy + brady notification events combined
HR_EVENTS_PER_DAY_MEDIUM = 0.4

ECTOPY_EVENTS_PER_DAY_MEDIUM = 0.7  # PVC/PAC-like (secondary screening signal)

MIN_GOOD_SIGNAL_RATIO = 0.5         # below this the window can't be trusted


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _event_count(events, event_type):
    return sum(1 for event in events if event.get("event_type") == event_type)


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


def evaluate_long_term_findings(overall, events, day_count):
    """Pure threshold evaluation for the long-term layer.

    Given the period ``overall`` aggregates (``max_af_burden_percent``,
    ``max_afib_probability``, ``af_suspicion_window_ratio``,
    ``good_signal_ratio``), the event list (dicts with ``event_type``) and the
    number of monitored ``day_count`` days, return ``(level, summary,
    findings)``. Identical for weekly and monthly windows because every count is
    normalised to a per-day rate.
    """
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

    # Normalise raw event counts by the number of monitored days so the gates
    # behave the same for a 7-day or a 30-day window.
    denom_days = max(day_count, 1)
    af_per_day = af_count / denom_days
    hr_event_count = tachy_count + brady_count
    hr_per_day = hr_event_count / denom_days
    ectopy_per_day = ectopy_count / denom_days

    if (
        af_per_day >= AF_EVENTS_PER_DAY_HIGH
        or af_ratio >= AF_WINDOW_RATIO_HIGH
        or max_af_burden >= AF_BURDEN_PERCENT_HIGH
    ):
        af_level = "high"
    elif (
        af_per_day >= AF_EVENTS_PER_DAY_MEDIUM
        or af_ratio >= AF_WINDOW_RATIO_MEDIUM
        or max_afib_probability >= AF_PROBABILITY_MEDIUM
    ):
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
                    "events_per_day": round(af_per_day, 2),
                    "af_suspicion_window_ratio": round(af_ratio, 4),
                    "max_afib_probability": round(max_afib_probability, 4),
                    "max_af_burden_percent": round(max_af_burden, 2),
                },
            )
        )

    ectopy_level = "medium" if ectopy_per_day >= ECTOPY_EVENTS_PER_DAY_MEDIUM else None
    if ectopy_level:
        findings.append(
            _finding(
                "long_term_ectopy_activity",
                ectopy_level,
                "Repeated PVC/PAC-like activity (experimental)",
                "PVC/PAC-like events recur across the selected days and should be interpreted as a secondary signal.",
                {
                    "event_count": ectopy_count,
                    "events_per_day": round(ectopy_per_day, 2),
                    "assessment_role": "secondary_signal",
                },
            )
        )

    if hr_per_day >= HR_EVENTS_PER_DAY_HIGH:
        hr_level = "high"
    elif hr_per_day >= HR_EVENTS_PER_DAY_MEDIUM:
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
                    "events_per_day": round(hr_per_day, 2),
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

    if good_signal_ratio and good_signal_ratio < MIN_GOOD_SIGNAL_RATIO:
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
    return level, summary, findings
