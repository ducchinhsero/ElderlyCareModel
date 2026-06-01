import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.storage.ecg_storage import (
    acknowledge_alert,
    build_event_timeline,
    compute_daily_summary,
    compute_session_summary,
    get_events,
    get_realtime_alerts,
    rebuild_event_table,
    save_prediction,
)


class StorageEventsTest(unittest.TestCase):
    def test_save_prediction_persists_events_and_summaries(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            timestamp = datetime.now(timezone.utc).isoformat()
            result = {
                "patient_id": "test_patient",
                "timestamp": timestamp,
                "sample_rate_hz": 130.0,
                "window_count": 1,
                "heart_rate_bpm": 122.5,
                "stress": {"label": "unknown"},
                "anomaly": {"label": "normal", "value": 0},
                "rhythm": {
                    "label": "possible_afib",
                    "possible_afib_probability": 0.42,
                },
                "hr_event": {
                    "label": "tachycardia_at_rest",
                    "reason": "High HR while activity is REST.",
                },
                "af_episode": {
                    "active": True,
                    "af_burden_percent": 12.0,
                },
                "rhythm_alert": {
                    "level": "medium",
                    "message": "Possible AFib pattern detected.",
                },
                "signal_quality": {"label": "good", "score": 0.9, "reasons": []},
                "risk": {"level": "low", "score": 0.1},
                "sensor_context": {
                    "activity_state": "REST",
                    "hr_context_alert": {"level": "WATCH", "reason": "HR high for rest."},
                    "fall": {"fall_candidate": False, "strong_fall": False},
                },
                "alert_level": "medium",
                "message": "Rhythm monitoring event.",
            }

            saved = save_prediction(
                result,
                ecg_samples=[0, 1, 0, -1] * 40,
                sample_rate_hz=130.0,
                db_path=db_path,
            )

            events = get_events(patient_id="test_patient", days=1, db_path=db_path)
            event_types = {event["event_type"] for event in events}
            self.assertEqual(saved["patient_id"], "test_patient")
            self.assertIn("af_suspicion", event_types)
            self.assertIn("tachycardia", event_types)
            self.assertIn("hr_context", event_types)

            timeline = build_event_timeline(patient_id="test_patient", days=1, db_path=db_path)
            self.assertEqual(timeline["event_count"], len(events))

            session_summary = compute_session_summary(
                patient_id="test_patient",
                days=1,
                db_path=db_path,
            )
            self.assertEqual(session_summary["window_count"], 1)
            self.assertEqual(session_summary["overall"]["event_counts"]["af_suspicion"], 1)

            daily_summary = compute_daily_summary(
                patient_id="test_patient",
                days=1,
                db_path=db_path,
            )
            self.assertEqual(daily_summary["day_count"], 1)
            self.assertEqual(daily_summary["overall"]["max_af_burden_percent"], 12.0)

    def test_rebuild_event_table_backfills_from_predictions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            timestamp = datetime.now(timezone.utc).isoformat()
            save_prediction(
                {
                    "patient_id": "test_patient",
                    "timestamp": timestamp,
                    "sample_rate_hz": 130.0,
                    "window_count": 1,
                    "heart_rate_bpm": 48.0,
                    "stress": {},
                    "anomaly": {},
                    "rhythm": {"label": "normal", "possible_afib_probability": 0.0},
                    "hr_event": {"label": "bradycardia", "reason": "Low HR."},
                    "af_episode": {},
                    "rhythm_alert": {"level": "low"},
                    "signal_quality": {"label": "good"},
                    "risk": {},
                    "sensor_context": {"activity_state": "REST"},
                    "alert_level": "medium",
                    "message": "Low HR.",
                },
                ecg_samples=[0, 1, 0, -1] * 40,
                sample_rate_hz=130.0,
                db_path=db_path,
            )

            result = rebuild_event_table(
                patient_id="test_patient",
                days=1,
                db_path=db_path,
            )
            events = get_events(patient_id="test_patient", days=1, db_path=db_path)
            self.assertGreaterEqual(result["event_count"], 1)
            self.assertIn("bradycardia", {event["event_type"] for event in events})

    def test_hr_context_critical_stays_critical_for_realtime_alerts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            timestamp = datetime.now(timezone.utc).isoformat()
            save_prediction(
                {
                    "patient_id": "critical_patient",
                    "timestamp": timestamp,
                    "sample_rate_hz": 130.0,
                    "window_count": 1,
                    "heart_rate_bpm": 42.0,
                    "stress": {},
                    "anomaly": {},
                    "rhythm": {"label": "normal"},
                    "hr_event": {"label": "bradycardia", "reason": "Low HR."},
                    "af_episode": {},
                    "rhythm_alert": {"level": "low"},
                    "signal_quality": {"label": "good"},
                    "risk": {},
                    "sensor_context": {
                        "activity_state": "REST",
                        "hr_context_alert": {
                            "level": "CRITICAL",
                            "reason": "Heart rate is dangerously low at rest.",
                        },
                    },
                    "alert_level": "critical",
                    "message": "Critical heart-rate context.",
                },
                ecg_samples=[0, 1, 0, -1] * 40,
                sample_rate_hz=130.0,
                db_path=db_path,
            )

            realtime = get_realtime_alerts(
                patient_id="critical_patient",
                db_path=db_path,
            )
            alerts = realtime["alerts"]
            self.assertTrue(alerts)
            self.assertIn("critical", {alert["severity"] for alert in alerts})
            self.assertIn("hr_context", {alert["event_type"] for alert in alerts})

    def test_strong_fall_realtime_alert_can_be_acknowledged(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            timestamp = datetime.now(timezone.utc).isoformat()
            save_prediction(
                {
                    "patient_id": "fall_patient",
                    "timestamp": timestamp,
                    "sample_rate_hz": 130.0,
                    "window_count": 1,
                    "heart_rate_bpm": 90.0,
                    "stress": {},
                    "anomaly": {},
                    "rhythm": {"label": "normal"},
                    "hr_event": {},
                    "af_episode": {},
                    "rhythm_alert": {"level": "low"},
                    "signal_quality": {"label": "good"},
                    "risk": {},
                    "sensor_context": {
                        "activity_state": "REST",
                        "fall": {
                            "fall_candidate": True,
                            "strong_fall": True,
                            "peak_vm": 3200.0,
                        },
                    },
                    "alert_level": "critical",
                    "message": "Strong fall detected.",
                },
                ecg_samples=[0, 1, 0, -1] * 40,
                sample_rate_hz=130.0,
                db_path=db_path,
            )

            realtime = get_realtime_alerts(patient_id="fall_patient", db_path=db_path)
            self.assertEqual(realtime["alert_count"], 1)
            alert = realtime["alerts"][0]
            self.assertEqual(alert["event_type"], "fall_candidate")
            self.assertEqual(alert["severity"], "critical")

            ack = acknowledge_alert(
                alert["event_id"],
                caregiver_id="caregiver_1",
                note="checked",
                db_path=db_path,
            )
            self.assertTrue(ack["ack_status"]["acknowledged"])
            ack_again = acknowledge_alert(
                alert["event_id"],
                caregiver_id="caregiver_1",
                note="checked again",
                db_path=db_path,
            )
            self.assertTrue(ack_again["ack_status"]["acknowledged"])

            hidden = get_realtime_alerts(patient_id="fall_patient", db_path=db_path)
            self.assertEqual(hidden["alert_count"], 0)
            visible = get_realtime_alerts(
                patient_id="fall_patient",
                include_acknowledged=True,
                db_path=db_path,
            )
            self.assertEqual(visible["alert_count"], 1)
            self.assertTrue(visible["alerts"][0]["ack_status"]["acknowledged"])


if __name__ == "__main__":
    unittest.main()
