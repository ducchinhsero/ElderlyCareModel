import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


def _hr_prediction(patient_id, timestamp, heart_rate_bpm, activity_state="REST", acc_vm_std=8.0):
    if heart_rate_bpm >= 130 or heart_rate_bpm <= 40:
        hr_level = "CRITICAL"
    elif heart_rate_bpm >= 100 or heart_rate_bpm <= 50:
        hr_level = "ALERT"
    else:
        hr_level = "SAFE"
    hr_event_label = "normal_hr"
    if heart_rate_bpm >= 100 and activity_state == "REST":
        hr_event_label = "tachycardia_at_rest"
    elif heart_rate_bpm <= 50:
        hr_event_label = "bradycardia"
    return {
        "patient_id": patient_id,
        "timestamp": timestamp.isoformat(),
        "sample_rate_hz": 130.0,
        "window_count": 1,
        "heart_rate_bpm": heart_rate_bpm,
        "stress": {},
        "anomaly": {},
        "rhythm": {"label": "normal", "possible_afib_probability": 0.0},
        "hr_event": {"label": hr_event_label, "reason": "Heart-rate context event."},
        "af_episode": {},
        "rhythm_alert": {"level": "low"},
        "signal_quality": {"label": "good"},
        "risk": {},
        "sensor_context": {
            "activity_state": activity_state,
            "activity_features": {"acc_vm_std": acc_vm_std},
            "hr_context_alert": {
                "level": hr_level,
                "reason": "Heart rate outside the usual range for this activity.",
            },
            "fall": {"fall_candidate": False, "strong_fall": False},
        },
        "alert_level": "medium" if hr_level != "SAFE" else "normal",
        "message": "Heart-rate monitoring event.",
    }


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

    def test_single_window_bradycardia_at_rest_is_realtime_warning(self):
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
            events = get_events(patient_id="critical_patient", days=1, db_path=db_path)
            hr_context = [event for event in events if event["event_type"] == "hr_context"]
            self.assertTrue(hr_context)
            self.assertEqual(hr_context[0]["severity"], "medium")
            self.assertEqual(realtime["alert_count"], 1)
            self.assertEqual(realtime["alerts"][0]["event_type"], "bradycardia")
            self.assertEqual(realtime["alerts"][0]["severity"], "medium")

    def test_single_window_tachycardia_at_rest_is_realtime_warning(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            timestamp = datetime.now(timezone.utc)
            save_prediction(
                _hr_prediction(
                    "tachy_rest_patient",
                    timestamp,
                    108.0,
                    activity_state="REST",
                    acc_vm_std=8.0,
                ),
                ecg_samples=[0, 1, 0, -1] * 40,
                sample_rate_hz=130.0,
                db_path=db_path,
            )

            realtime = get_realtime_alerts(
                patient_id="tachy_rest_patient",
                db_path=db_path,
            )
            self.assertEqual(realtime["alert_count"], 1)
            self.assertEqual(realtime["alerts"][0]["event_type"], "tachycardia")
            self.assertEqual(realtime["alerts"][0]["severity"], "medium")

    def test_sustained_high_hr_while_immobile_becomes_realtime_alert(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            started = datetime.now(timezone.utc)
            for offset in (0, 60, 120, 180):
                save_prediction(
                    _hr_prediction(
                        "sustained_patient",
                        started + timedelta(seconds=offset),
                        115.0,
                        activity_state="REST",
                        acc_vm_std=7.5,
                    ),
                    ecg_samples=[0, 1, 0, -1] * 40,
                    sample_rate_hz=130.0,
                    db_path=db_path,
                )

            realtime = get_realtime_alerts(
                patient_id="sustained_patient",
                db_path=db_path,
            )
            self.assertGreaterEqual(realtime["alert_count"], 1)
            alert = next(
                event
                for event in realtime["alerts"]
                if event["event_type"] == "sustained_tachycardia_immobile"
            )
            self.assertEqual(alert["event_type"], "sustained_tachycardia_immobile")
            self.assertEqual(alert["severity"], "high")
            context = alert["metadata"]["sustained_alert_context"]
            self.assertGreaterEqual(context["duration_seconds"], 180.0)

    def test_sustained_critical_hr_while_immobile_becomes_critical_alert(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            started = datetime.now(timezone.utc)
            for offset in (0, 30, 60):
                save_prediction(
                    _hr_prediction(
                        "critical_hr_patient",
                        started + timedelta(seconds=offset),
                        135.0,
                        activity_state="REST",
                        acc_vm_std=8.0,
                    ),
                    ecg_samples=[0, 1, 0, -1] * 40,
                    sample_rate_hz=130.0,
                    db_path=db_path,
                )

            realtime = get_realtime_alerts(
                patient_id="critical_hr_patient",
                db_path=db_path,
            )
            self.assertGreaterEqual(realtime["alert_count"], 1)
            alert = next(
                event
                for event in realtime["alerts"]
                if event["event_type"] == "critical_hr_immobile"
            )
            self.assertEqual(alert["event_type"], "critical_hr_immobile")
            self.assertEqual(alert["severity"], "critical")

    def test_sustained_low_hr_while_immobile_becomes_realtime_alert(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            started = datetime.now(timezone.utc)
            for offset in (0, 60, 120):
                save_prediction(
                    _hr_prediction(
                        "low_hr_patient",
                        started + timedelta(seconds=offset),
                        44.0,
                        activity_state="REST",
                        acc_vm_std=7.0,
                    ),
                    ecg_samples=[0, 1, 0, -1] * 40,
                    sample_rate_hz=130.0,
                    db_path=db_path,
                )

            realtime = get_realtime_alerts(patient_id="low_hr_patient", db_path=db_path)
            self.assertGreaterEqual(realtime["alert_count"], 1)
            alert = next(
                event
                for event in realtime["alerts"]
                if event["event_type"] == "sustained_bradycardia_immobile"
            )
            self.assertEqual(alert["event_type"], "sustained_bradycardia_immobile")
            self.assertEqual(alert["severity"], "high")

    def test_active_high_hr_does_not_become_realtime_alert(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            started = datetime.now(timezone.utc)
            for offset in (0, 60, 120, 180):
                save_prediction(
                    _hr_prediction(
                        "active_patient",
                        started + timedelta(seconds=offset),
                        125.0,
                        activity_state="WALK",
                        acc_vm_std=120.0,
                    ),
                    ecg_samples=[0, 1, 0, -1] * 40,
                    sample_rate_hz=130.0,
                    db_path=db_path,
                )

            realtime = get_realtime_alerts(patient_id="active_patient", db_path=db_path)
            self.assertEqual(realtime["alert_count"], 0)

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
