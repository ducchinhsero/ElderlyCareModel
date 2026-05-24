import json
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from src.features.stress_features import STRESS_FEATURE_COLUMNS, STRESS_WINDOW_SECONDS
from src.inference.stress_inference import RollingRRBuffer, StressPredictor
from src.training.train_stress_wesad import discover_wesad_subjects


def _training_frame():
    rng = np.random.default_rng(42)
    base = rng.normal(0, 0.05, size=(20, len(STRESS_FEATURE_COLUMNS)))
    stress = rng.normal(1, 0.05, size=(20, len(STRESS_FEATURE_COLUMNS)))
    X = pd.DataFrame(np.vstack([base, stress]), columns=STRESS_FEATURE_COLUMNS)
    y = np.array([0] * 20 + [1] * 20)
    return X, y


class StressInferenceTest(unittest.TestCase):
    def test_missing_model_returns_unknown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            predictor = StressPredictor(tmp_dir)
            result = predictor.predict_from_rr([800.0] * 30)
            self.assertEqual(result["label"], "unknown")
            self.assertEqual(result["reason"], "stress_model_not_loaded")

    def test_predictor_returns_binary_stress_label_when_loaded(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            X, y = _training_frame()
            rf = RandomForestClassifier(n_estimators=10, random_state=1).fit(X, y)
            svm = Pipeline(
                [("scaler", StandardScaler()), ("svc", SVC(probability=True, random_state=1))]
            ).fit(X, y)
            model_dir = Path(tmp_dir)
            joblib.dump(rf, model_dir / "rf_model.pkl")
            joblib.dump(svm, model_dir / "svm_pipeline.pkl")
            joblib.dump(StandardScaler().fit(X), model_dir / "scaler_final.pkl")
            (model_dir / "model_metadata.json").write_text(
                json.dumps(
                    {
                        "model_version": "test_stress_model",
                        "feature_names": STRESS_FEATURE_COLUMNS,
                        "window_size_sec": STRESS_WINDOW_SECONDS,
                    }
                ),
                encoding="utf-8",
            )
            predictor = StressPredictor(tmp_dir)

            rr_ms = np.array([800 + ((i % 4) - 2) * 5 for i in range(360)], dtype=float)
            timestamps = np.cumsum(rr_ms) / 1000.0
            result = predictor.predict_from_rr(rr_ms, rr_timestamps_sec=timestamps)

            self.assertIn(result["label"], {"non_stress", "stress"})
            self.assertIn("stress", result["probabilities"])

    def test_rolling_rr_buffer_requires_window_coverage(self):
        buffer = RollingRRBuffer(max_seconds=360)
        sample_rate_hz = 130
        peaks = np.arange(sample_rate_hz, sample_rate_hz * 30, sample_rate_hz)
        buffer.add_from_peaks(peaks, sample_rate_hz, chunk_start_epoch=1000.0)
        self.assertFalse(buffer.ready(window_seconds=300.0))

        for chunk in range(10):
            chunk_start = 1000.0 + chunk * 30.0
            peaks = np.arange(sample_rate_hz, sample_rate_hz * 30, sample_rate_hz)
            buffer.add_from_peaks(peaks, sample_rate_hz, chunk_start_epoch=chunk_start)
        rr, _, coverage = buffer.stress_window(window_seconds=300.0)
        self.assertGreaterEqual(rr.size, 20)
        self.assertGreaterEqual(coverage, 240.0)
        self.assertTrue(buffer.ready(window_seconds=300.0))

    def test_discover_wesad_subjects_uses_project_data_raw_layout(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "S2").mkdir()
            (root / "S2" / "S2.pkl").write_bytes(b"placeholder")
            subjects = discover_wesad_subjects(root)
            self.assertEqual(subjects[0][0], "S2")


if __name__ == "__main__":
    unittest.main()
