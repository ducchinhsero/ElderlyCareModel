import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from src.services.collect_clinical_arrhythmia_data import (
    ClinicalCollectionConfig,
    collect_dry_run_session,
    parse_args,
    parse_event_command,
    validate_duration_minutes,
)


class ClinicalArrhythmiaCollectionTests(unittest.TestCase):
    def test_parse_cli_accepts_one_and_two_hour_sessions(self):
        one_hour = parse_args(
            [
                "--participant-id",
                "p001",
                "--condition-group",
                "confirmed_afib",
                "--clinical-source",
                "doctor_confirmed",
                "--duration-minutes",
                "60",
            ]
        )
        two_hours = parse_args(
            [
                "--participant-id",
                "p001",
                "--condition-group",
                "confirmed_afib",
                "--clinical-source",
                "doctor_confirmed",
                "--duration-minutes",
                "120",
            ]
        )

        self.assertEqual(one_hour.duration_minutes, 60.0)
        self.assertEqual(two_hours.duration_minutes, 120.0)

    def test_duration_rejects_outside_clinical_range_without_short_test_flag(self):
        with self.assertRaises(ValueError):
            validate_duration_minutes(10, allow_short_test=False)
        self.assertEqual(validate_duration_minutes(5, allow_short_test=True), 5.0)

    def test_cli_rejects_invalid_condition_group(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(
                    [
                        "--participant-id",
                        "p001",
                        "--condition-group",
                        "definitely_afib",
                        "--clinical-source",
                        "doctor_confirmed",
                    ]
                )

    def test_event_command_parser(self):
        _, symptom = parse_event_command("symptom palpitation")
        _, activity = parse_event_command("activity strap_adjustment")
        _, note = parse_event_command("note patient coughed")
        action, event = parse_event_command("stop")

        self.assertEqual(symptom["event_type"], "symptom")
        self.assertEqual(symptom["label"], "palpitation")
        self.assertEqual(activity["label"], "strap_adjustment")
        self.assertEqual(note["note"], "patient coughed")
        self.assertEqual(action, "stop")
        self.assertIsNone(event)

    def test_dry_run_writes_expected_session_files_and_quality_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = ClinicalCollectionConfig(
                participant_id="p001",
                condition_group="confirmed_afib",
                clinical_source="doctor_confirmed",
                duration_minutes=1.0,
                output_root=tmp_dir,
                visit_id="visit_test",
                dry_run=True,
                allow_short_test=True,
                no_interactive_events=True,
                acc_sample_rate_hz=25,
            )

            with redirect_stdout(StringIO()):
                session_dir, metadata = collect_dry_run_session(config)
            session_path = Path(session_dir)

            self.assertEqual(metadata["status"], "completed")
            for filename in [
                "ecg.csv",
                "acc.csv",
                "rr.csv",
                "events.csv",
                "segments.csv",
                "metadata.json",
                "quality_report.json",
                "predictions_preview.csv",
            ]:
                self.assertTrue((session_path / filename).exists(), filename)

            saved_metadata = json.loads((session_path / "metadata.json").read_text(encoding="utf-8"))
            quality = json.loads((session_path / "quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_metadata["condition_group"], "confirmed_afib")
            self.assertEqual(saved_metadata["window_rhythm_label"], "unlabeled")
            self.assertGreaterEqual(quality["window_count"], 1)
            self.assertIn("usable_for_analysis", quality)


if __name__ == "__main__":
    unittest.main()
