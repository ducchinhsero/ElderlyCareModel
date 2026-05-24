from src.config.runtime_config import get_config_section


def map_rhythm_to_alert(
    rhythm_label,
    confidence,
    hr_event=None,
    signal_quality_label="good",
    possible_afib_probability=None,
    activity_state=None,
):
    hr_event = hr_event or {}
    quality = signal_quality_label or "unknown"
    confidence = float(confidence or 0.0)
    activity = str(activity_state or "unknown").strip().upper()
    config = get_config_section("rhythm_alert")
    high_afib_threshold = float(config.get("possible_afib_high_probability", 0.8))
    medium_afib_threshold = float(config.get("possible_afib_medium_probability", 0.3))
    activity_other_threshold = float(
        config.get("activity_other_rhythm_afib_probability_threshold", 0.10)
    )

    if quality in {"noise", "poor", "poor_contact", "motion_artifact"}:
        return "unknown", "Poor ECG signal quality. Please adjust the strap."

    afib_probability = confidence if possible_afib_probability is None else float(possible_afib_probability or 0.0)
    if rhythm_label == "possible_afib" and afib_probability >= high_afib_threshold:
        return "high", "Possible AFib detected."

    if rhythm_label == "possible_afib" and afib_probability >= medium_afib_threshold:
        return "medium", "Possible AFib pattern detected. Continue monitoring."

    if rhythm_label == "other_rhythm" and activity in {"WALK", "ACTIVE"} and afib_probability < activity_other_threshold:
        return (
            "normal",
            "Rhythm variation detected during activity, with low AFib probability. Continue monitoring.",
        )

    if rhythm_label == "other_rhythm":
        return "medium", "Irregular rhythm detected. Continue monitoring."

    if hr_event.get("label") == "tachycardia_at_rest":
        return "medium", "High heart rate at rest detected."

    if hr_event.get("label") == "bradycardia":
        return "medium", "Low heart rate detected."

    if rhythm_label == "noise":
        return "unknown", "ECG signal is too noisy for a reliable rhythm result."

    return "normal", "No significant rhythm abnormality detected."
