import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.storage.ecg_storage import (
    compute_period_comparison,
    compute_period_summary,
    get_connection,
    get_daily_rollups,
    rebuild_daily_rollups,
    run_rollup_maintenance,
    save_prediction,
)

NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)


def _prediction(patient_id, ts, afib=0.0, rhythm="normal", hr=78.0, quality="good", activity="REST"):
    return {
        "patient_id": patient_id,
        "timestamp": ts.isoformat(),
        "sample_rate_hz": 130.0,
        "window_count": 1,
        "heart_rate_bpm": hr,
        "stress": {"label": "non_stress"},
        "anomaly": {"label": "normal", "value": 0},
        "rhythm": {"label": rhythm, "possible_afib_probability": afib,
                   "probabilities": {"possible_afib": afib}},
        "ectopy": {"label": "normal"},
        "hr_event": {"label": "normal_hr"},
        "af_episode": {"af_burden_percent": 0.0},
        "rhythm_alert": {"level": "medium" if rhythm == "possible_afib" else "normal"},
        "signal_quality": {"label": quality},
        "risk": {"level": "low"},
        "sensor_context": {"activity_state": activity,
                           "activity_features": {"acc_vm_std": 8.0},
                           "fall": {"fall_candidate": False, "strong_fall": False}},
        "alert_level": "normal",
        "message": "",
    }


def _seed_day(db_path, patient, day_start, count, **kw):
    for i in range(count):
        save_prediction(
            _prediction(patient, day_start + timedelta(minutes=i), **kw),
            ecg_samples=[0, 1, 0, -1] * 40, sample_rate_hz=130.0, db_path=db_path,
        )


class DailyRollupsTest(unittest.TestCase):
    def test_period_summary_aggregates_multiple_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ecg.db")
            # day-3 and day-2 have AFib-like windows, day-1 normal
            _seed_day(db, "polar_h10", NOW - timedelta(days=3, hours=2), 12,
                      afib=0.85, rhythm="possible_afib")
            _seed_day(db, "polar_h10", NOW - timedelta(days=2, hours=2), 10,
                      afib=0.80, rhythm="possible_afib")
            _seed_day(db, "polar_h10", NOW - timedelta(days=1, hours=2), 8)

            summary = compute_period_summary(patient_id="polar_h10", days=7, db_path=db, now=NOW)
            self.assertEqual(summary["source"], "daily_rollups")
            self.assertEqual(summary["day_count"], 3)
            self.assertEqual(summary["window_count"], 30)
            self.assertGreaterEqual(summary["overall"]["max_afib_probability"], 0.8)
            self.assertGreater(summary["overall"]["af_suspicion_window_ratio"], 0.0)
            self.assertGreaterEqual(summary["overall"]["af_suspicion_event_count"], 1)

    def test_past_days_finalized_today_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ecg.db")
            _seed_day(db, "polar_h10", NOW - timedelta(days=2, hours=2), 5)
            _seed_day(db, "polar_h10", NOW - timedelta(hours=2), 5)  # today
            get_daily_rollups(patient_id="polar_h10", days=7, db_path=db, now=NOW)

            conn = get_connection(db)
            try:
                rows = {r["day"]: r["is_final"] for r in
                        conn.execute("SELECT day, is_final FROM daily_rollups").fetchall()}
            finally:
                conn.close()
            today = NOW.date().isoformat()
            past = (NOW - timedelta(days=2)).date().isoformat()
            self.assertEqual(rows.get(past), 1)
            self.assertEqual(rows.get(today), 0)

    def test_rebuild_refreshes_finalized_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ecg.db")
            past_day = NOW - timedelta(days=2, hours=2)
            _seed_day(db, "polar_h10", past_day, 4)
            # finalize past day via read
            get_daily_rollups(patient_id="polar_h10", days=7, db_path=db, now=NOW)
            # late-arriving data for the same past day
            _seed_day(db, "polar_h10", past_day + timedelta(minutes=30), 6)

            # cached read still returns the old (finalized) count
            cached = compute_period_summary(patient_id="polar_h10", days=7, db_path=db, now=NOW)
            past_row_cached = next(d for d in cached["days"]
                                   if d["day"] == (NOW - timedelta(days=2)).date().isoformat())
            self.assertEqual(past_row_cached["window_count"], 4)

            # rebuild picks up the late data
            result = rebuild_daily_rollups(patient_id="polar_h10", days=7, db_path=db, now=NOW)
            self.assertGreaterEqual(result["rebuilt_day_count"], 1)
            refreshed = compute_period_summary(patient_id="polar_h10", days=7, db_path=db, now=NOW)
            past_row = next(d for d in refreshed["days"]
                            if d["day"] == (NOW - timedelta(days=2)).date().isoformat())
            self.assertEqual(past_row["window_count"], 10)

    def test_period_comparison_detects_worsening_af(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ecg.db")
            # previous week (10 days ago): normal
            _seed_day(db, "polar_h10", NOW - timedelta(days=10, hours=2), 10)
            # current week (3 days ago): AFib-like
            _seed_day(db, "polar_h10", NOW - timedelta(days=3, hours=2), 10,
                      afib=0.85, rhythm="possible_afib")

            cmp = compute_period_comparison(patient_id="polar_h10", window_days=7, db_path=db, now=NOW)
            self.assertTrue(cmp["has_previous"])
            af = cmp["deltas"]["af_suspected_seconds"]
            self.assertGreater(af["current"], 0.0)
            self.assertEqual(af["previous"], 0.0)
            self.assertEqual(af["direction"], "worsening")
            self.assertEqual(cmp["deltas"]["af_suspicion_window_ratio"]["direction"], "worsening")
            self.assertIn("af_suspected_seconds", cmp["worsening_metrics"])

    def test_period_comparison_no_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ecg.db")
            _seed_day(db, "polar_h10", NOW - timedelta(days=2, hours=2), 8)  # current only
            cmp = compute_period_comparison(patient_id="polar_h10", window_days=7, db_path=db, now=NOW)
            self.assertFalse(cmp["has_previous"])
            self.assertEqual(cmp["deltas"]["rest_heart_rate_mean"]["direction"], "unknown")

    def test_rollup_maintenance_finalizes_without_report_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ecg.db")
            _seed_day(db, "polar_h10", NOW - timedelta(days=1, hours=2), 6)  # yesterday
            result = run_rollup_maintenance(lookback_days=2, db_path=db, now=NOW)
            self.assertIn("polar_h10", result["patients"])
            self.assertGreaterEqual(result["finalized_rollup_count"], 1)
            conn = get_connection(db)
            try:
                row = conn.execute(
                    "SELECT is_final FROM daily_rollups WHERE day = ?",
                    ((NOW - timedelta(days=1)).date().isoformat(),),
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["is_final"], 1)

    def test_empty_history_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ecg.db")
            summary = compute_period_summary(patient_id="polar_h10", days=7, db_path=db, now=NOW)
            self.assertEqual(summary["day_count"], 0)
            self.assertEqual(summary["window_count"], 0)
            self.assertEqual(summary["overall"]["max_afib_probability"], 0.0)


if __name__ == "__main__":
    unittest.main()
