import unittest

import numpy as np

from src.features.ecg_features import (
    ANOMALY_FEATURE_COLUMNS,
    EMOTION_FEATURE_COLUMNS,
    evaluate_signal_quality,
    extract_anomaly_feature_rows,
    extract_emotion_feature_rows,
    rows_to_matrix,
)
from src.calibration.anomaly_calibration import MIN_BASELINE_FEATURE_ROWS
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
    def test_emotion_features_have_expected_schema(self):
        rows = extract_emotion_feature_rows(
            synthetic_ecg(),
            sample_rate_hz=130,
            window_size=10,
            step_size=5,
            filter_signal=False,
        )
        matrix = rows_to_matrix(rows, EMOTION_FEATURE_COLUMNS)
        self.assertGreater(len(rows), 0)
        self.assertEqual(matrix.shape[1], 10)

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
        self.assertEqual(result["sensor_context"]["activity_state"], "REST")


if __name__ == "__main__":
    unittest.main()
