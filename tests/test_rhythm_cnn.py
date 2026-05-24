import tempfile
import unittest
import importlib.util
from pathlib import Path

import numpy as np

from src.inference.rhythm_cnn_inference import RhythmCnn1D, RhythmCnnPredictor
from src.preprocessing import RHYTHM_LABELS, save_json


class RhythmCnnTest(unittest.TestCase):
    def test_predictor_reports_unknown_when_artifacts_missing(self):
        predictor = RhythmCnnPredictor(
            model_path="missing-rhythm-cnn.pt",
            metadata_path="missing-rhythm-cnn.json",
        )
        result = predictor.predict([0, 1, 0, -1], sample_rate_hz=130)
        self.assertEqual(result["label"], "unknown")
        self.assertIn("model_source", result)

    @unittest.skipIf(importlib.util.find_spec("torch") is None, "PyTorch is not installed.")
    def test_predictor_loads_state_dict_and_returns_probabilities(self):
        import torch

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            model_path = root / "rhythm_cnn_model.pt"
            metadata_path = root / "rhythm_cnn_metadata.json"
            model = RhythmCnn1D(input_length=3900, num_classes=4)
            torch.save({"state_dict": model.state_dict()}, model_path)
            save_json(
                metadata_path,
                {
                    "input_length": 3900,
                    "num_classes": 4,
                    "sample_rate_hz": 130.0,
                    "labels": {str(key): value for key, value in RHYTHM_LABELS.items()},
                    "dropout": 0.25,
                },
            )

            predictor = RhythmCnnPredictor(model_path=model_path, metadata_path=metadata_path)
            signal = np.sin(np.linspace(0, 30, 3900))
            result = predictor.predict(signal, sample_rate_hz=130)

            self.assertNotEqual(result["label"], "unknown")
            self.assertEqual(result["model_source"], "rhythm_cnn_model")
            self.assertEqual(result["window_count"], 1)
            self.assertIn("possible_afib", result["probabilities"])
            self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
