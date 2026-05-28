import tempfile
import unittest
from pathlib import Path

from src.services.build_soak_report import render_markdown, summarize


class SoakReportTest(unittest.TestCase):
    def test_summary_handles_missing_alert_review(self):
        rows = [
            {"type": "pi_runtime_monitor_start", "started_at": "2026-05-28T00:00:00+00:00"},
            {
                "type": "pi_runtime_monitor_sample",
                "timestamp": "2026-05-28T00:01:00+00:00",
                "resources": {
                    "process_cpu_percent": 12.0,
                    "process_rss_bytes": 1000,
                    "system_cpu_percent": 20.0,
                    "system_memory_percent": 30.0,
                },
                "health": {
                    "ok": True,
                    "payload": {
                        "mqtt_connected": True,
                        "polar": {"reconnect_count": 1},
                    },
                },
                "latest_result": {
                    "ok": True,
                    "payload": {"latest_result": {"timestamp": "2026-05-28T00:01:00+00:00"}},
                },
                "storage": {
                    "ok": True,
                    "payload": {
                        "counts": {"predictions": 10},
                        "db_total_bytes": 2048,
                        "raw_signal_chunks": [{"unsynced_count": 2}],
                    },
                },
                "sync_scheduler": {"ok": True, "payload": {"last_result": {"status": "ok"}}},
                "events": {
                    "ok": True,
                    "payload": {
                        "events": [
                            {
                                "event_id": "evt-1",
                                "event_type": "fall_candidate",
                                "severity": "high",
                            }
                        ]
                    },
                },
            },
            {"type": "pi_runtime_monitor_finish", "finished_at": "2026-05-28T00:02:00+00:00"},
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            summary = summarize(rows, str(Path(tmp_dir) / "missing_alert_review.csv"))
        self.assertEqual(summary["reconnect_count"], 1)
        self.assertEqual(summary["alert_counts"]["fall_candidate"], 1)
        self.assertEqual(summary["alert_review"]["status"], "not_reviewed")
        self.assertIn("Raspberry Pi 24h Soak Test Report", render_markdown(summary))


if __name__ == "__main__":
    unittest.main()
