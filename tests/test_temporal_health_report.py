import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.assessment.temporal_health_report import (
    build_temporal_health_report,
    compute_temporal_health_report,
)
from src.assessment.longterm_thresholds import evaluate_long_term_findings
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
        "stress": {"label": "non_stress", "confidence": 0.8},
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


class LongTermThresholdTest(unittest.TestCase):
    """Rate-based gating must stay consistent across window lengths."""

    @staticmethod
    def _af_events(n):
        return [{"event_type": "af_suspicion"} for _ in range(n)]

    def test_same_event_rate_gives_same_level_week_vs_month(self):
        # ~1.6 AF events/day is "high" whether observed over 7 or 30 days.
        week_level, _, _ = evaluate_long_term_findings({}, self._af_events(11), day_count=7)
        month_level, _, _ = evaluate_long_term_findings({}, self._af_events(48), day_count=30)
        self.assertEqual(week_level, "high")
        self.assertEqual(month_level, "high")

    def test_absolute_count_does_not_over_trigger_over_a_month(self):
        # 20 AF events over 30 days (~0.67/day) is medium, NOT high. The old
        # absolute "count >= 10 -> high" rule ignored window length and would
        # have over-escalated this to high.
        level, _, findings = evaluate_long_term_findings({}, self._af_events(20), day_count=30)
        self.assertNotEqual(level, "high")
        af = next(f for f in findings if f["type"] == "long_term_afib_suspicion")
        self.assertEqual(af["level"], "medium")

    def test_clean_history_is_low(self):
        level, _, findings = evaluate_long_term_findings({}, [], day_count=7)
        self.assertEqual(level, "low")
        self.assertEqual(findings, [])

    def test_burden_ratio_still_triggers_regardless_of_count(self):
        # A short intense burst (high burden / window ratio) still escalates even
        # with few discrete events.
        overall = {"max_af_burden_percent": 12.0, "af_suspicion_window_ratio": 0.15}
        level, _, _ = evaluate_long_term_findings(overall, [], day_count=7)
        self.assertEqual(level, "high")


if __name__ == "__main__":
    unittest.main()
