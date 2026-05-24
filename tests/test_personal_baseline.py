import tempfile
import unittest
from pathlib import Path

from src.calibration.personal_baseline import (
    build_personal_baseline,
    compare_history_to_baseline,
    get_personal_baseline_status,
    save_personal_baseline,
)


def _prediction(
    heart_rate=72.0,
    activity_state="REST",
    signal_quality="good",
    alert_level="normal",
    rhythm_label="normal",
    afib_probability=0.0,
    ectopy_label="normal",
    anomaly_label="normal",
    anomaly_value=0,
    timestamp="2026-05-22T01:00:00+00:00",
):
    return {
        "patient_id": "test_patient",
        "timestamp": timestamp,
        "heart_rate_bpm": heart_rate,
        "signal_quality": {"label": signal_quality, "score": 1.0},
        "alert_level": alert_level,
        "rhythm_alert": {"level": "normal"},
        "rhythm": {
            "label": rhythm_label,
            "possible_afib_probability": afib_probability,
            "probabilities": {"possible_afib": afib_probability},
        },
        "ectopy": {"label": ectopy_label},
        "anomaly": {"label": anomaly_label, "value": anomaly_value},
        "stress": {"label": "non_stress"},
        "sensor_context": {"activity_state": activity_state},
    }


class PersonalBaselineTest(unittest.TestCase):
    def test_build_baseline_filters_unreliable_and_alert_windows(self):
        history = [_prediction(heart_rate=70 + i) for i in range(25)]
        history.append(_prediction(heart_rate=200, alert_level="critical"))
        history.append(_prediction(heart_rate=30, signal_quality="poor"))

        baseline = build_personal_baseline(
            history,
            patient_id="test_patient",
            days=2,
            min_predictions=20,
        )

        self.assertEqual(baseline["source"]["prediction_count"], 27)
        self.assertEqual(baseline["source"]["reliable_prediction_count"], 25)
        self.assertEqual(baseline["calibration"]["status"], "warming_up")
        self.assertEqual(baseline["calibration"]["target_days"], 7)
        self.assertEqual(baseline["heart_rate"]["overall"]["count"], 25)
        self.assertLess(baseline["heart_rate"]["overall"]["max"], 200)
        self.assertIn("REST", baseline["heart_rate"]["by_activity"])
        self.assertIn("non_stress", baseline["stress"]["distribution"])

    def test_save_and_status_load_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            baseline = build_personal_baseline(
                [_prediction(heart_rate=72 + i % 3) for i in range(20)],
                patient_id="test_patient",
                min_predictions=20,
            )
            path = save_personal_baseline(baseline, root=tmp_dir)
            status = get_personal_baseline_status("test_patient", root=tmp_dir)

            self.assertTrue(Path(path).exists())
            self.assertTrue(status["calibrated"])
            self.assertEqual(status["baseline"]["patient_id"], "test_patient")

    def test_compare_history_to_baseline_reports_deltas(self):
        baseline = build_personal_baseline(
            [_prediction(heart_rate=70 + i % 4) for i in range(20)],
            patient_id="test_patient",
            min_predictions=20,
        )
        recent = [
            _prediction(heart_rate=90, rhythm_label="possible_afib", afib_probability=0.4)
            for _ in range(5)
        ]

        comparison = compare_history_to_baseline(recent, baseline)

        self.assertTrue(comparison["calibrated"])
        self.assertGreater(comparison["comparisons"]["mean_hr_delta_bpm"], 0)
        self.assertGreater(comparison["comparisons"]["af_suspicion_ratio_delta"], 0)

    def test_progressive_baseline_can_save_not_ready_partial_data(self):
        baseline = build_personal_baseline(
            [_prediction(heart_rate=72 + i % 2) for i in range(5)],
            patient_id="test_patient",
            min_predictions=20,
            target_days=7,
            allow_partial=True,
        )

        self.assertEqual(baseline["calibration"]["status"], "not_ready")
        self.assertEqual(baseline["source"]["reliable_prediction_count"], 5)

    def test_progressive_baseline_ready_after_target_days(self):
        history = []
        for day in range(7):
            for index in range(3):
                history.append(
                    _prediction(
                        heart_rate=70 + index,
                        timestamp=f"2026-05-{day + 1:02d}T01:00:00+00:00",
                    )
                )

        baseline = build_personal_baseline(
            history,
            patient_id="test_patient",
            min_predictions=20,
            target_days=7,
            allow_partial=True,
        )

        self.assertEqual(baseline["calibration"]["status"], "ready")
        self.assertEqual(baseline["calibration"]["day_count"], 7)
        self.assertEqual(baseline["calibration"]["progress_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
