import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.assessment.daily_health_assessment import (
    build_daily_health_assessment,
    compute_daily_health_assessment,
)
from src.storage.ecg_storage import save_prediction


def _prediction(
    patient_id="test_patient",
    rhythm_label="normal",
    afib_probability=0.0,
    ectopy_label="normal",
    anomaly_value=0,
    signal_quality="good",
    hr_event_label="normal_hr",
    fall_candidate=False,
    stress_label="non_stress",
):
    return {
        "patient_id": patient_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_rate_hz": 130.0,
        "window_count": 1,
        "heart_rate_bpm": 80.0,
        "stress": {"label": stress_label, "confidence": 0.8},
        "anomaly": {
            "label": "abnormal" if anomaly_value == 1 else "normal",
            "value": anomaly_value,
        },
        "rhythm": {
            "label": rhythm_label,
            "possible_afib_probability": afib_probability,
            "probabilities": {"possible_afib": afib_probability},
        },
        "ectopy": {
            "label": ectopy_label,
            "pvc_probability": 0.8 if ectopy_label == "pvc" else 0.0,
            "pac_probability": 0.8 if ectopy_label == "pac" else 0.0,
        },
        "hr_event": {"label": hr_event_label},
        "af_episode": {"af_burden_percent": 12.0 if rhythm_label == "possible_afib" else 0.0},
        "rhythm_alert": {
            "level": "medium" if rhythm_label == "possible_afib" else "normal",
            "message": "Possible AFib pattern detected." if rhythm_label == "possible_afib" else "",
        },
        "signal_quality": {"label": signal_quality, "score": 1.0 if signal_quality == "good" else 0.2},
        "risk": {"level": "low"},
        "sensor_context": {
            "activity_state": "REST",
            "fall": {"fall_candidate": fall_candidate, "strong_fall": False},
        },
        "alert_level": "medium" if rhythm_label == "possible_afib" else "normal",
        "message": "Test prediction.",
    }


class DailyHealthAssessmentTest(unittest.TestCase):
    def test_no_data_returns_unknown_and_insufficient(self):
        result = build_daily_health_assessment([], [], patient_id="test_patient")
        self.assertEqual(result["overall"]["level"], "unknown")
        self.assertEqual(result["data_quality"]["label"], "insufficient")

    def test_few_predictions_returns_preview_confidence(self):
        history = [_prediction(), _prediction(), _prediction()]
        result = build_daily_health_assessment(history, [], patient_id="test_patient")
        self.assertEqual(result["data_quality"]["assessment_confidence"], "preview")
        self.assertEqual(result["overall"]["level"], "low")

    def test_repeated_afib_events_produce_afib_finding(self):
        history = [
            _prediction(rhythm_label="possible_afib", afib_probability=0.42)
            for _ in range(20)
        ]
        events = [
            {"event_type": "af_suspicion", "severity": "medium", "label": "possible_afib"}
            for _ in range(5)
        ]
        result = build_daily_health_assessment(history, events, patient_id="test_patient")
        findings = {item["type"]: item for item in result["findings"]}
        self.assertEqual(findings["afib_suspicion"]["level"], "high")
        self.assertEqual(result["overall"]["level"], "high")

    def test_repeated_ectopy_events_produce_ectopy_finding(self):
        history = [_prediction(ectopy_label="pvc") for _ in range(20)]
        events = [
            {"event_type": "ectopy_suspicion", "severity": "medium", "label": "pvc"}
            for _ in range(3)
        ]
        result = build_daily_health_assessment(history, events, patient_id="test_patient")
        findings = {item["type"]: item for item in result["findings"]}
        self.assertIn("ectopy_activity", findings)
        self.assertEqual(findings["ectopy_activity"]["level"], "medium")
        self.assertEqual(findings["ectopy_activity"]["evidence"]["assessment_role"], "secondary_signal")

    def test_poor_signal_ratio_produces_signal_finding(self):
        history = [_prediction(signal_quality="poor") for _ in range(20)]
        events = [{"event_type": "poor_signal", "severity": "unknown", "label": "poor"}]
        result = build_daily_health_assessment(history, events, patient_id="test_patient")
        findings = {item["type"]: item for item in result["findings"]}
        self.assertEqual(result["data_quality"]["label"], "poor")
        self.assertEqual(findings["poor_signal"]["level"], "high")

    def test_fall_candidate_produces_high_finding(self):
        history = [_prediction() for _ in range(20)]
        events = [{"event_type": "fall_candidate", "severity": "high", "label": "fall_candidate"}]
        result = build_daily_health_assessment(history, events, patient_id="test_patient")
        findings = {item["type"]: item for item in result["findings"]}
        self.assertEqual(findings["fall_risk"]["level"], "high")
        self.assertEqual(result["overall"]["level"], "high")

    def test_repeated_stress_windows_produce_stress_finding(self):
        history = [_prediction(stress_label="stress") for _ in range(20)]
        events = [{"event_type": "stress_suspicion", "severity": "medium", "label": "stress"} for _ in range(3)]
        result = build_daily_health_assessment(history, events, patient_id="test_patient")
        findings = {item["type"]: item for item in result["findings"]}
        self.assertEqual(findings["stress_pattern"]["level"], "high")

    def test_mixed_events_choose_highest_overall_severity(self):
        history = [_prediction(ectopy_label="pvc") for _ in range(20)]
        events = [
            {"event_type": "ectopy_suspicion", "severity": "medium", "label": "pvc"},
            {"event_type": "fall_candidate", "severity": "critical", "label": "strong_fall"},
        ]
        result = build_daily_health_assessment(history, events, patient_id="test_patient")
        self.assertEqual(result["overall"]["level"], "critical")

    def test_compute_assessment_reads_sqlite_and_patient_filter(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            for _ in range(3):
                save_prediction(
                    _prediction(patient_id="target", rhythm_label="possible_afib", afib_probability=0.42),
                    ecg_samples=[0, 1, 0, -1] * 40,
                    sample_rate_hz=130.0,
                    db_path=db_path,
                )
            save_prediction(
                _prediction(patient_id="other"),
                ecg_samples=[0, 1, 0, -1] * 40,
                sample_rate_hz=130.0,
                db_path=db_path,
            )

            result = compute_daily_health_assessment(
                patient_id="target",
                hours=24,
                db_path=db_path,
            )
            self.assertEqual(result["patient_id"], "target")
            self.assertEqual(result["data_quality"]["prediction_count"], 3)
            self.assertIn("overall", result)
            self.assertIn("findings", result)


if __name__ == "__main__":
    unittest.main()
