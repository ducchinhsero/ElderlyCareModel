import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.storage.background_sync import (
    BackgroundSyncConfig,
    close_background_sync_logger,
    get_background_sync_status,
    run_background_sync_once,
    start_background_sync_scheduler,
    stop_background_sync_scheduler,
)


class BackgroundSyncTests(unittest.TestCase):
    def tearDown(self):
        close_background_sync_logger()

    def test_run_once_syncs_purges_and_writes_logs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = BackgroundSyncConfig(
                enabled=True,
                interval_seconds=60,
                patient_id="test_patient",
                days=1,
                limit=10,
                purge_retention_hours=24,
                log_path=str(Path(tmp_dir) / "background_sync.log"),
                run_log_path=str(Path(tmp_dir) / "background_sync_runs.jsonl"),
            )

            try:
                result = run_background_sync_once(
                    config=config,
                    configured_func=lambda: True,
                    sync_func=lambda **kwargs: {"status": "synced", "raw_chunk_count": 3, **kwargs},
                    purge_func=lambda **kwargs: {"purged": 2, **kwargs},
                    storage_status_func=lambda: {"counts": {"raw_signal_chunks": 1}},
                )

                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["sync"]["raw_chunk_count"], 3)
                self.assertEqual(result["purge"]["purged"], 2)
                self.assertTrue(Path(config.log_path).exists())

                lines = Path(config.run_log_path).read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(lines), 1)
                self.assertEqual(json.loads(lines[0])["status"], "ok")
            finally:
                close_background_sync_logger()

    def test_run_once_skips_when_mongodb_not_configured(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = BackgroundSyncConfig(
                enabled=True,
                log_path=str(Path(tmp_dir) / "background_sync.log"),
                run_log_path=str(Path(tmp_dir) / "background_sync_runs.jsonl"),
            )

            try:
                result = run_background_sync_once(
                    config=config,
                    configured_func=lambda: False,
                    sync_func=lambda **kwargs: self.fail("sync should not run"),
                )

                self.assertEqual(result["status"], "skipped")
                self.assertIn("MONGODB_URI", result["reason"])
            finally:
                close_background_sync_logger()

    def test_scheduler_start_stop_uses_background_task(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as tmp_dir:
                config = BackgroundSyncConfig(
                    enabled=True,
                    interval_seconds=0.05,
                    run_immediately=True,
                    log_path=str(Path(tmp_dir) / "background_sync.log"),
                    run_log_path=str(Path(tmp_dir) / "background_sync_runs.jsonl"),
                )
                with patch(
                    "src.storage.background_sync.run_background_sync_once",
                    return_value={"status": "ok"},
                ):
                    try:
                        started = await start_background_sync_scheduler(config)
                        await asyncio.sleep(0.12)
                        running = get_background_sync_status()
                    finally:
                        stopped = await stop_background_sync_scheduler()
                        close_background_sync_logger()

            self.assertEqual(started["status"], "started")
            self.assertTrue(running["task_active"])
            self.assertGreaterEqual(running["cycle_count"], 1)
            self.assertEqual(stopped["status"], "stopped")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
