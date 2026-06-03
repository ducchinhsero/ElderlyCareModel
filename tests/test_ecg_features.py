import unittest

import numpy as np

from src.features.ecg_features import (
    ANOMALY_FEATURE_COLUMNS,
    evaluate_signal_quality,
    extract_anomaly_feature_rows,
    rows_to_matrix,
)
from src.features.stress_features import STRESS_FEATURE_COLUMNS, extract_stress_features, stress_row_to_matrix
from src.calibration.anomaly_calibration import MIN_BASELINE_FEATURE_ROWS
from src.api import pipeline
from src.api.pipeline import predict_ecg


def synthetic_ecg(sample_rate_hz=130, seconds=30):
    total = sample_rate_hz * seconds
    signal = np.zeros(total, dtype=float)
    peak_positions = np.arange(sample_rate_hz, total - sample_rate_hz, sample_rate_hz)
    x = np.arange(total)
    for peak in peak_positions:
        signal += np.exp(-0.5 * ((x - peak) / 3.0) ** 2)
    return signal


class ECGFeatureTests(unittest.TestCase):
    def test_stress_features_have_expected_schema(self):
        rr_ms = np.array([800 + ((i % 5) - 2) * 8 for i in range(360)], dtype=float)
        timestamps = np.cumsum(rr_ms) / 1000.0
        row = extract_stress_features(rr_ms, rr_timestamps_sec=timestamps)
        matrix = stress_row_to_matrix(row)
        self.assertIsNotNone(row)
        self.assertEqual(list(row.keys()), STRESS_FEATURE_COLUMNS)
        self.assertEqual(matrix.shape[1], 12)

    def test_anomaly_features_have_expected_schema(self):
        rows = extract_anomaly_feature_rows(
            synthetic_ecg(),
            sample_rate_hz=130,
            window_size=10,
            step_size=5,
            filter_signal=False,
        )
        matrix = rows_to_matrix(rows, ANOMALY_FEATURE_COLUMNS)
        self.assertGreater(len(rows), 0)
        self.assertEqual(matrix.shape[1], 10)

    def test_signal_quality_good_for_synthetic_ecg(self):
        quality = evaluate_signal_quality(synthetic_ecg(), sample_rate_hz=130)
        self.assertIn(quality["label"], {"good", "fair"})

    def test_signal_quality_poor_for_flatline(self):
        quality = evaluate_signal_quality(np.zeros(3900), sample_rate_hz=130)
        self.assertEqual(quality["label"], "poor")

    def test_signal_quality_poor_for_random_noise_contact_loss(self):
        rng = np.random.default_rng(1)
        noisy_signal = rng.normal(0, 200, 3900)
        quality = evaluate_signal_quality(noisy_signal, sample_rate_hz=130)
        self.assertEqual(quality["label"], "poor")
        self.assertTrue(
            any("noise" in reason or "loose contact" in reason for reason in quality["reasons"])
        )

    def test_poor_signal_result_clears_heart_rate(self):
        result = pipeline._poor_signal_result(
            patient_id="polar_h10",
            sample_rate_hz=130,
            reason="No ECG samples received.",
        )
        self.assertEqual(result["signal_quality"]["label"], "poor")
        self.assertIsNone(result["heart_rate_bpm"])
        self.assertEqual(result["alert_level"], "medium")

    def test_synthetic_ecg_can_supply_baseline_rows(self):
        rows = extract_anomaly_feature_rows(
            synthetic_ecg(seconds=120),
            sample_rate_hz=130,
            window_size=10,
            step_size=5,
            filter_signal=False,
        )
        self.assertGreaterEqual(len(rows), MIN_BASELINE_FEATURE_ROWS)

    def test_predict_ecg_accepts_optional_acc_context(self):
        acc_samples = [(1000, 0, 0), (1010, 0, 0), (990, 0, 0)] * 250
        result = predict_ecg(
            synthetic_ecg(seconds=30),
            sample_rate_hz=130,
            patient_id="test",
            acc_samples=acc_samples,
            acc_sample_rate_hz=25,
        )

        self.assertIn("sensor_context", result)
        self.assertIn("stress", result)
        self.assertNotIn("emotion", result)
        self.assertEqual(result["sensor_context"]["activity_state"], "REST")

    def test_realtime_pipeline_does_not_load_cnn_runtime(self):
        self.assertFalse(hasattr(pipeline, "rhythm_cnn_predictor"))
        self.assertFalse(hasattr(pipeline, "RHYTHM_PREDICTOR_MODE"))


if __name__ == "__main__":
    unittest.main()
