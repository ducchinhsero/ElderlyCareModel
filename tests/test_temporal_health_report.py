import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.assessment.temporal_health_report import (
    build_temporal_health_report,
    compute_temporal_health_report,
)
from src.storage.ecg_storage import save_prediction


def _prediction(
    patient_id="test_patient",
    rhythm_label="normal",
    afib_probability=0.0,
    signal_quality="good",
    alert_level="normal",
):
    return {
        "patient_id": patient_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_rate_hz": 130.0,
        "window_count": 1,
        "heart_rate_bpm": 80.0,
        "emotion": {"label": "neutral"},
        "anomaly": {"label": "normal", "value": 0},
        "rhythm": {
            "label": rhythm_label,
            "possible_afib_probability": afib_probability,
            "probabilities": {"possible_afib": afib_probability},
        },
        "rhythm_alert": {
            "level": "medium" if rhythm_label == "possible_afib" else "normal",
            "message": "Possible AFib pattern detected." if rhythm_label == "possible_afib" else "",
        },
        "ectopy": {"label": "normal"},
        "hr_event": {"label": "normal_hr"},
        "af_episode": {"af_burden_percent": 0.0},
        "signal_quality": {"label": signal_quality, "score": 1.0},
        "risk": {"level": "low", "score": 0.05},
        "sensor_context": {"activity_state": "REST", "fall": {"fall_candidate": False}},
        "alert_level": alert_level,
        "message": "Test prediction.",
    }


class TemporalHealthReportTest(unittest.TestCase):
    def test_report_has_three_time_layers(self):
        latest = _prediction(rhythm_label="possible_afib", afib_probability=0.42, alert_level="medium")
        report = build_temporal_health_report(latest_prediction=latest, patient_id="test_patient")

        self.assertEqual(report["report_type"], "temporal_health_report")
        self.assertEqual(set(report["layers"]), {"realtime", "daily", "long_term"})
        self.assertIn("personal_baseline", report)
        self.assertFalse(report["personal_baseline"]["calibrated"])
        self.assertEqual(report["layers"]["realtime"]["overall"]["level"], "medium")
        self.assertEqual(report["layers"]["daily"]["period"]["mode"], "rolling_24h")
        self.assertEqual(report["layers"]["long_term"]["window"]["mode"], "rolling_days")

    def test_compute_report_reads_latest_prediction_from_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            for _ in range(3):
                save_prediction(
                    _prediction(patient_id="target"),
                    ecg_samples=[0, 1, 0, -1] * 40,
                    sample_rate_hz=130.0,
                    db_path=db_path,
                )

            report = compute_temporal_health_report(
                patient_id="target",
                daily_hours=24,
                long_term_days=7,
                db_path=db_path,
            )

            self.assertEqual(report["patient_id"], "target")
            self.assertEqual(report["layers"]["realtime"]["evidence"]["patient_id"], "target")
            self.assertEqual(report["layers"]["daily"]["data_quality"]["prediction_count"], 3)


if __name__ == "__main__":
    unittest.main()
