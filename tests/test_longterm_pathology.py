import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.assessment.longterm_pathology import (
    build_longterm_pathology_assessment,
    compute_longterm_pathology_assessment,
)
from src.storage.ecg_storage import save_prediction


def _prediction(
    patient_id,
    timestamp,
    rhythm_label="normal",
    afib_probability=0.0,
    af_burden_percent=0.0,
    ectopy_label="normal",
    hr_event_label="normal_hr",
    heart_rate_bpm=78.0,
    signal_quality="good",
    activity_state="REST",
    acc_vm_std=8.0,
):
    rhythm_alert_level = "medium" if rhythm_label == "possible_afib" else "normal"
    return {
        "patient_id": patient_id,
        "timestamp": timestamp.isoformat(),
        "sample_rate_hz": 130.0,
        "window_count": 1,
        "heart_rate_bpm": heart_rate_bpm,
        "stress": {"label": "non_stress"},
        "anomaly": {"label": "normal", "value": 0},
        "rhythm": {
            "label": rhythm_label,
            "possible_afib_probability": afib_probability,
            "probabilities": {"possible_afib": afib_probability},
        },
        "ectopy": {"label": ectopy_label},
        "hr_event": {"label": hr_event_label, "reason": "test"},
        "af_episode": {"af_burden_percent": af_burden_percent},
        "rhythm_alert": {"level": rhythm_alert_level, "message": ""},
        "signal_quality": {"label": signal_quality, "score": 1.0},
        "risk": {"level": "low"},
        "sensor_context": {
            "activity_state": activity_state,
            "activity_features": {"acc_vm_std": acc_vm_std},
            "fall": {"fall_candidate": False, "strong_fall": False},
        },
        "alert_level": "normal",
        "message": "",
    }


def _seed_day(db_path, patient_id, day_start, count, **kwargs):
    """Persist ``count`` predictions spread across one calendar day."""
    for index in range(count):
        ts = day_start + timedelta(minutes=index)
        save_prediction(
            _prediction(patient_id, ts, **kwargs),
            ecg_samples=[0, 1, 0, -1] * 40,
            sample_rate_hz=130.0,
            db_path=db_path,
        )


class LongTermPathologyBuilderTest(unittest.TestCase):
    """Pure-builder tests that do not need a database."""

    def _daily_summary(self, days):
        return {
            "patient_id": "p",
            "day_count": len(days),
            "window_count": sum(int(d.get("window_count") or 0) for d in days),
            "days": days,
            "overall": {},
        }

    def _day(self, day, **overrides):
        base = {
            "day": day,
            "window_count": 30,
            "good_signal_ratio": 1.0,
            "max_af_burden_percent": 0.0,
            "max_afib_probability": 0.0,
            "af_suspicion_window_ratio": 0.0,
            "ectopy_counts": {},
        }
        base.update(overrides)
        return base

    def test_insufficient_data_is_unknown(self):
        summary = self._daily_summary([self._day("2026-06-01", window_count=2)])
        report = build_longterm_pathology_assessment(summary, [], patient_id="p", days=7)
        self.assertEqual(report["data_quality"]["label"], "insufficient")
        self.assertEqual(report["overall"]["level"], "unknown")

    def test_no_pathology_is_low(self):
        days = [self._day(f"2026-06-0{n}") for n in range(1, 5)]
        report = build_longterm_pathology_assessment(self._daily_summary(days), [], days=7)
        self.assertEqual(report["overall"]["level"], "low")
        types = {i["type"] for i in report["indicators"]}
        self.assertNotIn("atrial_fibrillation_burden", types)

    def test_recurrent_af_across_days_is_high(self):
        days = [
            self._day("2026-06-01", max_af_burden_percent=6.0, af_suspicion_window_ratio=0.2),
            self._day("2026-06-02", max_af_burden_percent=8.0, af_suspicion_window_ratio=0.3),
            self._day("2026-06-03", max_af_burden_percent=12.0, af_suspicion_window_ratio=0.4),
            self._day("2026-06-04"),
        ]
        report = build_longterm_pathology_assessment(self._daily_summary(days), [], days=7)
        af = next(i for i in report["indicators"] if i["type"] == "atrial_fibrillation_burden")
        self.assertEqual(af["level"], "high")
        self.assertEqual(af["recurrence"]["days_present"], 3)
        self.assertEqual(af["trend"], "increasing")
        self.assertEqual(report["overall"]["level"], "high")

    def test_single_day_af_is_medium(self):
        days = [
            self._day("2026-06-01", max_afib_probability=0.4),
            self._day("2026-06-02"),
            self._day("2026-06-03"),
        ]
        report = build_longterm_pathology_assessment(self._daily_summary(days), [], days=7)
        af = next(i for i in report["indicators"] if i["type"] == "atrial_fibrillation_burden")
        self.assertEqual(af["level"], "medium")
        self.assertEqual(af["recurrence"]["days_present"], 1)

    def test_poor_coverage_surfaces_monitoring_quality(self):
        days = [
            self._day("2026-06-01", window_count=30, good_signal_ratio=0.9),
            self._day("2026-06-02", window_count=4, good_signal_ratio=0.2),
            self._day("2026-06-03", window_count=30, good_signal_ratio=0.3),
        ]
        report = build_longterm_pathology_assessment(self._daily_summary(days), [], days=7)
        types = {i["type"] for i in report["indicators"]}
        self.assertIn("monitoring_quality", types)

    def test_critical_immobile_hr_event_is_critical(self):
        days = [self._day("2026-06-01"), self._day("2026-06-02"), self._day("2026-06-03")]
        events = [
            {
                "event_type": "critical_hr_immobile",
                "severity": "critical",
                "timestamp": "2026-06-02T10:00:00+00:00",
            }
        ]
        report = build_longterm_pathology_assessment(self._daily_summary(days), events, days=7)
        hr = next(i for i in report["indicators"] if i["type"] == "heart_rate_abnormality_burden")
        self.assertEqual(hr["level"], "critical")
        self.assertEqual(report["overall"]["level"], "critical")

    def test_fall_candidate_reported_even_on_poor_days(self):
        days = [self._day("2026-06-01", window_count=2, good_signal_ratio=0.1)]
        events = [
            {
                "event_type": "fall_candidate",
                "severity": "critical",
                "timestamp": "2026-06-01T08:00:00+00:00",
            }
        ]
        report = build_longterm_pathology_assessment(self._daily_summary(days), events, days=7)
        fall = next(i for i in report["indicators"] if i["type"] == "fall_activity_risk")
        self.assertEqual(fall["level"], "critical")


    def test_personal_baseline_deviation_indicator(self):
        days = [self._day(f"2026-06-0{n}") for n in range(1, 5)]
        comparison = {
            "calibrated": True,
            "comparisons": {
                "resting_hr_delta_bpm": 22.0,
                "af_suspicion_ratio_delta": 0.12,
                "abnormal_ratio_delta": 0.0,
                "ectopy_ratio_delta": 0.0,
                "recent": {},
                "baseline": {},
            },
        }
        report = build_longterm_pathology_assessment(
            self._daily_summary(days), [], days=7, baseline_comparison=comparison
        )
        dev = next(i for i in report["indicators"] if i["type"] == "personal_baseline_deviation")
        self.assertEqual(dev["level"], "high")  # rest>=20 (2) + af>=0.10 (2) = 4
        self.assertEqual(report["overall"]["level"], "high")
        self.assertTrue(report["personal_baseline"]["calibrated"])

    def test_no_baseline_no_deviation_indicator(self):
        days = [self._day(f"2026-06-0{n}") for n in range(1, 5)]
        report = build_longterm_pathology_assessment(
            self._daily_summary(days), [], days=7, baseline_comparison=None
        )
        types = {i["type"] for i in report["indicators"]}
        self.assertNotIn("personal_baseline_deviation", types)
        self.assertFalse(report["personal_baseline"]["calibrated"])


class LongTermPathologyDbTest(unittest.TestCase):
    def test_compute_from_db_detects_recurrent_af(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
            for offset in (1, 2, 3):
                day_start = now - timedelta(days=offset)
                _seed_day(
                    db_path,
                    "afib_patient",
                    day_start,
                    15,
                    rhythm_label="possible_afib",
                    afib_probability=0.85,
                    af_burden_percent=12.0,
                )
            report = compute_longterm_pathology_assessment(
                patient_id="afib_patient", days=7, db_path=db_path
            )
            af = next(
                i for i in report["indicators"] if i["type"] == "atrial_fibrillation_burden"
            )
            self.assertEqual(af["level"], "high")
            self.assertGreaterEqual(af["recurrence"]["days_present"], 3)
            self.assertEqual(report["overall"]["level"], "high")
            self.assertTrue(report["disclaimer"])

    def test_compute_from_db_clean_history_is_low(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
            for offset in (1, 2, 3):
                _seed_day(db_path, "healthy_patient", now - timedelta(days=offset), 15)
            report = compute_longterm_pathology_assessment(
                patient_id="healthy_patient", days=7, db_path=db_path
            )
            self.assertIn(report["overall"]["level"], {"low", "medium"})
            self.assertEqual(report["data_quality"]["label"], "confident")


if __name__ == "__main__":
    unittest.main()
