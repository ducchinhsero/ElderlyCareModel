import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.storage.ecg_storage import (
    decode_raw_chunk,
    get_latest_ecg,
    get_assessment_snapshots,
    get_raw_chunk,
    get_raw_chunks,
    mark_raw_chunks_synced,
    purge_synced_raw_chunks,
    save_assessment_snapshot,
    save_prediction,
    save_raw_signal_chunks,
    storage_status,
)


class RawSignalChunksTest(unittest.TestCase):
    def test_ecg_chunk_roundtrip_is_lossless(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            samples = [0, 100, -200, 300, -400] * 130
            rows = save_raw_signal_chunks(
                samples,
                sample_rate_hz=130,
                patient_id="test_patient",
                timestamp=datetime.now(timezone.utc).isoformat(),
                signal_type="ecg",
                db_path=db_path,
            )

            self.assertEqual(len(rows), 1)
            chunk = get_raw_chunk(rows[0]["chunk_id"], include_payload=True, db_path=db_path)
            self.assertEqual(chunk["sample_count"], len(samples))
            self.assertEqual(decode_raw_chunk(chunk), samples)

    def test_save_prediction_creates_raw_chunks_and_latest_ecg_reads_chunks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            timestamp = datetime.now(timezone.utc).isoformat()
            ecg_samples = list(range(130 * 11))
            acc_samples = [{"x_mg": 1, "y_mg": 2, "z_mg": 3} for _ in range(200 * 2)]
            saved = save_prediction(
                {
                    "patient_id": "test_patient",
                    "timestamp": timestamp,
                    "sample_rate_hz": 130.0,
                    "window_count": 2,
                    "heart_rate_bpm": 72.0,
                    "stress": {},
                    "anomaly": {"label": "normal", "value": 0},
                    "rhythm": {},
                    "ectopy": {},
                    "hr_event": {},
                    "af_episode": {},
                    "rhythm_alert": {},
                    "signal_quality": {"label": "good"},
                    "risk": {},
                    "sensor_context": {"activity_state": "REST"},
                    "alert_level": "normal",
                    "message": "ok",
                },
                ecg_samples=ecg_samples,
                sample_rate_hz=130,
                acc_samples=acc_samples,
                acc_sample_rate_hz=200,
                db_path=db_path,
            )

            self.assertEqual(len(saved["raw_ecg_chunk_ids"]), 3)
            self.assertEqual(len(saved["raw_acc_chunk_ids"]), 1)

            chunks = get_raw_chunks(patient_id="test_patient", hours=1, db_path=db_path)
            self.assertEqual(len(chunks), 4)

            latest = get_latest_ecg(patient_id="test_patient", max_samples=2000, db_path=db_path)
            self.assertEqual(latest["source"], "raw_signal_chunks")
            self.assertEqual(latest["samples"][:5], ecg_samples[:5])

            status = storage_status(db_path=db_path)
            self.assertEqual(status["counts"]["raw_signal_chunks"], 4)

    def test_latest_ecg_keeps_prediction_when_local_raw_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            timestamp = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            saved = save_prediction(
                {
                    "patient_id": "test_patient",
                    "timestamp": timestamp,
                    "sample_rate_hz": 130.0,
                    "window_count": 1,
                    "heart_rate_bpm": 72.0,
                    "stress": {},
                    "anomaly": {"label": "normal", "value": 0},
                    "rhythm": {},
                    "ectopy": {},
                    "hr_event": {},
                    "af_episode": {},
                    "rhythm_alert": {},
                    "signal_quality": {"label": "good"},
                    "risk": {},
                    "sensor_context": {"activity_state": "REST"},
                    "alert_level": "normal",
                    "message": "ok",
                },
                ecg_samples=list(range(130 * 6)),
                sample_rate_hz=130,
                db_path=db_path,
            )
            mark_raw_chunks_synced(saved["raw_ecg_chunk_ids"], db_path=db_path)
            purge_synced_raw_chunks(retention_hours=24, db_path=db_path)

            latest = get_latest_ecg(patient_id="test_patient", max_samples=1000, db_path=db_path)

            self.assertIsNotNone(latest["prediction"])
            self.assertEqual(latest["samples"], [])
            self.assertEqual(latest["source"], "missing_raw")

    def test_raw_chunk_rejects_invalid_sample_rate(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            with self.assertRaises(ValueError):
                save_raw_signal_chunks(
                    [1, 2, 3],
                    sample_rate_hz=0,
                    patient_id="test_patient",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    signal_type="ecg",
                    db_path=db_path,
                )

    def test_purge_only_deletes_synced_old_chunks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            new_ts = datetime.now(timezone.utc).isoformat()
            old_rows = save_raw_signal_chunks(
                [1, 2, 3],
                sample_rate_hz=130,
                patient_id="test_patient",
                timestamp=old_ts,
                signal_type="ecg",
                db_path=db_path,
            )
            new_rows = save_raw_signal_chunks(
                [4, 5, 6],
                sample_rate_hz=130,
                patient_id="test_patient",
                timestamp=new_ts,
                signal_type="ecg",
                db_path=db_path,
            )
            mark_raw_chunks_synced([old_rows[0]["chunk_id"], new_rows[0]["chunk_id"]], db_path=db_path)

            result = purge_synced_raw_chunks(retention_hours=24, db_path=db_path)

            self.assertEqual(result["purged"], 1)
            self.assertIsNone(get_raw_chunk(old_rows[0]["chunk_id"], db_path=db_path))
            self.assertIsNotNone(get_raw_chunk(new_rows[0]["chunk_id"], db_path=db_path))

    def test_assessment_snapshot_dedupes_repeated_polling(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            first = save_assessment_snapshot(
                "health_report",
                {"overall": {"level": "low"}},
                patient_id="test_patient",
                period={"daily_hours": 24, "long_term_days": 7},
                db_path=db_path,
            )
            second = save_assessment_snapshot(
                "health_report",
                {"overall": {"level": "low"}},
                patient_id="test_patient",
                period={"long_term_days": 7, "daily_hours": 24},
                db_path=db_path,
            )
            snapshots = get_assessment_snapshots(patient_id="test_patient", db_path=db_path)

            self.assertFalse(first["deduped"])
            self.assertTrue(second["deduped"])
            self.assertEqual(first["snapshot_id"], second["snapshot_id"])
            self.assertEqual(len(snapshots), 1)

    def test_storage_queries_reject_invalid_windows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            with self.assertRaises(ValueError):
                get_raw_chunks(hours=0, db_path=db_path)
            with self.assertRaises(ValueError):
                purge_synced_raw_chunks(retention_hours=-1, db_path=db_path)


if __name__ == "__main__":
    unittest.main()
