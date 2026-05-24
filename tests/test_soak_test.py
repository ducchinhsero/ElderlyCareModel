import json
import tempfile
import unittest
from pathlib import Path

from src.services.soak_test import (
    append_log,
    build_ingest_payload,
    generate_synthetic_acc,
    generate_synthetic_ecg,
    summarize_ingest_response,
)


class SoakTestHelpersTests(unittest.TestCase):
    def test_synthetic_ecg_length_matches_sample_rate_and_duration(self):
        samples = generate_synthetic_ecg(sample_rate_hz=130, duration_seconds=30, seed=1)

        self.assertEqual(len(samples), 3900)
        self.assertGreater(max(samples), 500)
        self.assertLess(min(samples), 0)

    def test_synthetic_acc_payload_shape(self):
        rows = generate_synthetic_acc(sample_rate_hz=200, duration_seconds=3, activity="WALK", seed=1)

        self.assertEqual(len(rows), 600)
        self.assertIn("vm_mg", rows[0])

    def test_build_ingest_payload_contains_ecg_and_acc(self):
        payload = build_ingest_payload(
            patient_id="test_patient",
            sample_rate_hz=130,
            window_seconds=2,
            include_acc=True,
            seed=1,
        )

        self.assertEqual(payload["patient_id"], "test_patient")
        self.assertEqual(len(payload["ecg_samples"]), 260)
        self.assertEqual(len(payload["acc_samples"]), 400)

    def test_append_log_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "soak.jsonl"
            append_log(path, {"status": "ok"})

            line = path.read_text(encoding="utf-8").strip()
            self.assertEqual(json.loads(line), {"status": "ok"})

    def test_summarize_ingest_response_keeps_dashboard_fields(self):
        summary = summarize_ingest_response(
            {
                "patient_id": "test_patient",
                "heart_rate_bpm": 72,
                "alert_level": "normal",
                "signal_quality": {"label": "good"},
                "rhythm": {"label": "normal"},
                "risk": {"level": "low"},
                "raw_ecg_chunk_ids": ["a", "b"],
                "raw_acc_chunk_ids": ["c"],
            }
        )

        self.assertEqual(summary["signal_quality"], "good")
        self.assertEqual(summary["raw_ecg_chunk_count"], 2)
        self.assertEqual(summary["raw_acc_chunk_count"], 1)


if __name__ == "__main__":
    unittest.main()
