import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.calibration.guided_baseline import (
    complete_guided_baseline_day,
    complete_guided_baseline_segment,
    get_guided_baseline_status,
    start_guided_baseline_session,
)
from src.storage.ecg_storage import save_prediction


def _prediction(timestamp, activity_state="REST", quality="good"):
    return {
        "patient_id": "test_patient",
        "timestamp": timestamp,
        "sample_rate_hz": 130.0,
        "window_count": 1,
        "heart_rate_bpm": 72.0,
        "stress": {"label": "non_stress"},
        "anomaly": {"label": "normal", "value": 0},
        "rhythm": {"label": "normal", "possible_afib_probability": 0.0},
        "ectopy": {"label": "normal"},
        "hr_event": {"label": "normal"},
        "af_episode": {},
        "rhythm_alert": {"level": "normal"},
        "signal_quality": {"label": quality, "score": 0.9},
        "risk": {"level": "low", "score": 0.0},
        "sensor_context": {"activity_state": activity_state},
        "alert_level": "normal",
        "message": "ok",
    }


class GuidedBaselineTest(unittest.TestCase):
    def test_guided_segment_validation_and_day_completion(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            started = datetime.now(timezone.utc) - timedelta(minutes=4)
            ended = started + timedelta(minutes=3)
            session = start_guided_baseline_session(
                patient_id="test_patient",
                target_days=7,
                db_path=db_path,
            )["session"]

            for offset in (30, 90):
                save_prediction(
                    _prediction((started + timedelta(seconds=offset)).isoformat()),
                    ecg_samples=[0, 1, 0, -1] * 40,
                    sample_rate_hz=130.0,
                    db_path=db_path,
                )
                save_prediction(
                    _prediction(
                        (started + timedelta(seconds=offset + 5)).isoformat(),
                        activity_state="WALK",
                    ),
                    ecg_samples=[0, 1, 0, -1] * 40,
                    sample_rate_hz=130.0,
                    db_path=db_path,
                )

            result = complete_guided_baseline_segment(
                patient_id="test_patient",
                session_id=session["session_id"],
                segment_type="REST",
                started_at=started.isoformat(),
                ended_at=ended.isoformat(),
                db_path=db_path,
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["segment"]["valid_window_count"], 2)

            complete_guided_baseline_segment(
                patient_id="test_patient",
                session_id=session["session_id"],
                segment_type="WALK",
                started_at=started.isoformat(),
                ended_at=ended.isoformat(),
                db_path=db_path,
            )
            complete_guided_baseline_segment(
                patient_id="test_patient",
                session_id=session["session_id"],
                segment_type="ACTIVE",
                allow_skip=True,
                db_path=db_path,
            )

            day = complete_guided_baseline_day(
                patient_id="test_patient",
                session_id=session["session_id"],
                target_days=7,
                db_path=db_path,
                baseline_root=tmp_dir,
            )
            self.assertEqual(day["status"], "partial")
            self.assertEqual(day["day_count"], 1)
            self.assertIsNotNone(day["baseline"])

            status = get_guided_baseline_status(
                patient_id="test_patient",
                db_path=db_path,
            )
            self.assertEqual(status["status"], "warming_up")

    def test_guided_segment_fails_with_wrong_activity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            started = datetime.now(timezone.utc) - timedelta(minutes=4)
            ended = started + timedelta(minutes=3)
            session = start_guided_baseline_session(
                patient_id="test_patient",
                db_path=db_path,
            )["session"]

            for offset in (30, 90):
                save_prediction(
                    _prediction((started + timedelta(seconds=offset)).isoformat(), activity_state="ACTIVE"),
                    ecg_samples=[0, 1, 0, -1] * 40,
                    sample_rate_hz=130.0,
                    db_path=db_path,
                )

            result = complete_guided_baseline_segment(
                patient_id="test_patient",
                session_id=session["session_id"],
                segment_type="REST",
                started_at=started.isoformat(),
                ended_at=ended.isoformat(),
                db_path=db_path,
            )
            self.assertEqual(result["status"], "failed")
            self.assertGreater(result["segment"]["rejected_window_count"], 0)


if __name__ == "__main__":
    unittest.main()
