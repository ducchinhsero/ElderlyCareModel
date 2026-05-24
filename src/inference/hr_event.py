MIN_RELIABLE_HR_EVENT_SECONDS = 29.0


def _hr_event(label, tachycardia, bradycardia, hr, activity, duration, reason=""):
    return {
        "label": label,
        "tachycardia": bool(tachycardia),
        "bradycardia": bool(bradycardia),
        "heart_rate_bpm": None if hr is None else round(float(hr), 2),
        "activity_state": activity,
        "duration_sec": round(float(duration or 0), 3),
        "min_duration_sec": MIN_RELIABLE_HR_EVENT_SECONDS,
        "reason": reason,
    }


def detect_hr_event(heart_rate_bpm, activity_state="unknown", duration_sec=30):
    if heart_rate_bpm is None:
        return _hr_event(
            "unknown",
            False,
            False,
            None,
            str(activity_state or "unknown").strip().lower(),
            duration_sec,
            reason="Heart rate is unavailable.",
        )

    hr = float(heart_rate_bpm)
    activity = str(activity_state or "unknown").strip().lower()
    duration = float(duration_sec or 0)
    has_reliable_duration = duration >= MIN_RELIABLE_HR_EVENT_SECONDS

    if hr > 100 and activity == "rest" and has_reliable_duration:
        return _hr_event(
            "tachycardia_at_rest",
            True,
            False,
            hr,
            activity,
            duration,
            reason="Heart rate is high while activity is rest.",
        )
    if hr < 50 and activity not in {"sleep", "unknown"} and has_reliable_duration:
        return _hr_event(
            "bradycardia",
            False,
            True,
            hr,
            activity,
            duration,
            reason="Heart rate is low for the current activity context.",
        )
    if not has_reliable_duration:
        return _hr_event(
            "normal_hr",
            False,
            False,
            hr,
            activity,
            duration,
            reason="ECG window is too short for a heart-rate event.",
        )
    return _hr_event("normal_hr", False, False, hr, activity, duration)
