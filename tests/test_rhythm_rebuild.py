import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy.io import savemat

from src.dataset_builders.build_cinc2017 import build_cinc2017_dataset
from src.dataset_builders.augment_rhythm_with_nstdb import _mix_at_snr
from src.dataset_builders.build_afdb import _afib_fraction_for_window, _rhythm_intervals_seconds
from src.features.rhythm_features import RHYTHM_FEATURE_COLUMNS, extract_rhythm_feature_matrix
from src.inference.alert_engine import map_rhythm_to_alert
from src.inference.af_episode_tracker import AFEpisodeTracker
from src.inference.hr_event import detect_hr_event
from src.inference.rhythm_inference import RhythmFeaturePredictor
from src.preprocessing import (
    SAMPLES_PER_WINDOW,
    encode_rhythm_label,
    normalize_ecg,
    pad_or_crop_window,
    resample_ecg,
    split_into_windows,
)


def synthetic_ecg(sample_rate_hz=130, seconds=30):
    total = sample_rate_hz * seconds
    x = np.arange(total)
    signal = np.zeros(total, dtype=float)
    for peak in np.arange(sample_rate_hz, total - sample_rate_hz, sample_rate_hz):
        signal += np.exp(-0.5 * ((x - peak) / 3.0) ** 2)
    return signal


class RhythmRebuildTests(unittest.TestCase):
    def test_cinc_label_mapping(self):
        self.assertEqual(encode_rhythm_label("N"), 0)
        self.assertEqual(encode_rhythm_label("A"), 1)
        self.assertEqual(encode_rhythm_label("O"), 2)
        self.assertEqual(encode_rhythm_label("~"), 3)

    def test_preprocessing_outputs_fixed_window(self):
        raw = synthetic_ecg(sample_rate_hz=300, seconds=10)
        resampled = resample_ecg(raw, source_rate_hz=300, target_rate_hz=130)
        normalized = normalize_ecg(resampled)
        window = pad_or_crop_window(normalized)
        self.assertEqual(window.shape[0], SAMPLES_PER_WINDOW)

    def test_split_into_windows_pads_final_window(self):
        signal = np.ones(SAMPLES_PER_WINDOW + 100)
        windows = split_into_windows(signal)
        self.assertEqual(len(windows), 2)
        self.assertFalse(windows[0][2])
        self.assertTrue(windows[1][2])
        self.assertEqual(windows[1][1].shape[0], SAMPLES_PER_WINDOW)

    def test_rhythm_feature_schema(self):
        X = np.vstack([synthetic_ecg(), synthetic_ecg()]).astype(np.float32)
        matrix, rows = extract_rhythm_feature_matrix(X, sample_rate_hz=130)
        self.assertEqual(matrix.shape, (2, len(RHYTHM_FEATURE_COLUMNS)))
        self.assertEqual(len(rows), 2)
        self.assertTrue(np.isfinite(matrix).all())

    def test_af_episode_requires_two_consecutive_windows(self):
        tracker = AFEpisodeTracker(window_seconds=30, afib_probability_threshold=0.7)
        first = tracker.update("possible_afib", 0.8)
        second = tracker.update("possible_afib", 0.9)
        self.assertFalse(first["active"])
        self.assertTrue(second["active"])
        self.assertEqual(second["current_episode_duration_sec"], 60.0)

    def test_af_episode_probability_only_can_track_without_argmax_afib_label(self):
        tracker = AFEpisodeTracker(
            window_seconds=30,
            afib_probability_threshold=0.3,
            decision_mode="probability_only",
        )
        first = tracker.update("normal", 0.35)
        second = tracker.update("normal", 0.4)
        self.assertFalse(first["active"])
        self.assertTrue(second["active"])
        self.assertEqual(second["afib_probability_threshold"], 0.3)
        self.assertEqual(second["decision_mode"], "probability_only")

    def test_rhythm_alert_medium_for_possible_afib_probability(self):
        level, message = map_rhythm_to_alert(
            "possible_afib",
            0.4,
            possible_afib_probability=0.4,
            signal_quality_label="good",
        )
        self.assertEqual(level, "medium")
        self.assertIn("AFib", message)

    def test_rhythm_alert_downgrades_activity_other_rhythm_with_low_afib_probability(self):
        level, message = map_rhythm_to_alert(
            "other_rhythm",
            0.95,
            possible_afib_probability=0.01,
            signal_quality_label="good",
            activity_state="ACTIVE",
        )
        self.assertEqual(level, "normal")
        self.assertIn("activity", message)

    def test_hr_event_allows_realtime_collection_tolerance(self):
        result = detect_hr_event(103.52, activity_state="REST", duration_sec=29.76)
        self.assertEqual(result["label"], "tachycardia_at_rest")
        self.assertTrue(result["tachycardia"])
        self.assertEqual(result["activity_state"], "rest")

    def test_build_cinc2017_dataset_from_minimal_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "cinc2017"
            output_dir = root / "processed"
            input_dir.mkdir()
            ecg = synthetic_ecg(sample_rate_hz=300, seconds=10).reshape(1, -1)
            savemat(input_dir / "A00001.mat", {"val": ecg})
            (input_dir / "A00001.hea").write_text("A00001 1 300 3000\n", encoding="utf-8")
            (input_dir / "REFERENCE.csv").write_text("A00001,N\n", encoding="utf-8")

            summary = build_cinc2017_dataset(input_dir=input_dir, output_dir=output_dir)
            X = np.load(output_dir / "X.npy")
            y = np.load(output_dir / "y.npy")

            self.assertEqual(summary["X_shape"], [1, SAMPLES_PER_WINDOW])
            self.assertEqual(X.shape, (1, SAMPLES_PER_WINDOW))
            self.assertEqual(y.tolist(), [0])
            self.assertTrue((output_dir / "metadata.csv").exists())

    def test_rhythm_predictor_reports_unknown_when_artifacts_missing(self):
        predictor = RhythmFeaturePredictor(
            model_path="missing-model.pkl",
            scaler_path="missing-scaler.pkl",
            schema_path="missing-schema.json",
        )
        result = predictor.predict(synthetic_ecg(), sample_rate_hz=130)
        self.assertEqual(result["label"], "unknown")
        self.assertIn("reason", result)

    def test_noise_mix_keeps_fixed_window_shape(self):
        clean = synthetic_ecg()
        noise = np.random.default_rng(42).normal(size=clean.shape[0])
        mixed = _mix_at_snr(clean, noise, snr_db=0.0)
        self.assertEqual(mixed.shape[0], clean.shape[0])
        self.assertTrue(np.isfinite(mixed).all())

    def test_afdb_window_afib_fraction(self):
        intervals = [
            {"start_seconds": 0.0, "end_seconds": 10.0, "is_afib": False},
            {"start_seconds": 10.0, "end_seconds": 30.0, "is_afib": True},
        ]
        self.assertAlmostEqual(_afib_fraction_for_window(0.0, 30.0, intervals), 20.0 / 30.0)


if __name__ == "__main__":
    unittest.main()
