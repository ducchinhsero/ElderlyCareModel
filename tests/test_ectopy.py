import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.features.ectopy_features import (
    ECTOPY_FEATURE_COLUMNS,
    ECTOPY_LABEL_MAP,
    extract_ectopy_feature_matrix,
    label_window_from_symbols,
)
from src.inference.ectopy_inference import EctopyFeaturePredictor
from src.storage.ecg_storage import get_events, save_prediction


class EctopyTest(unittest.TestCase):
    def test_window_label_mapping_for_pvc_pac(self):
        class_id, label, counts = label_window_from_symbols(["N", "V", "A"])
        self.assertEqual(class_id, ECTOPY_LABEL_MAP["mixed_ectopic"])
        self.assertEqual(label, "mixed_ectopic")
        self.assertEqual(counts["pvc"], 1)
        self.assertEqual(counts["pac"], 1)

        class_id, label, _ = label_window_from_symbols(["N", "N", "V"])
        self.assertEqual(class_id, ECTOPY_LABEL_MAP["pvc"])
        self.assertEqual(label, "pvc")

        class_id, label, _ = label_window_from_symbols(["N", "A", "N"])
        self.assertEqual(class_id, ECTOPY_LABEL_MAP["pac"])
        self.assertEqual(label, "pac")

    def test_ectopy_feature_schema_shape(self):
        windows = np.vstack(
            [
                np.sin(np.linspace(0, 20, 3900)),
                np.sin(np.linspace(0, 24, 3900)),
            ]
        )
        matrix, rows = extract_ectopy_feature_matrix(windows, sample_rate_hz=130)
        self.assertEqual(matrix.shape, (2, len(ECTOPY_FEATURE_COLUMNS)))
        self.assertEqual(len(rows), 2)
        self.assertIn("pvc_like_ratio", rows[0])
        self.assertIn("pac_like_ratio", rows[0])

    def test_predictor_reports_unknown_when_artifacts_missing(self):
        predictor = EctopyFeaturePredictor(
            model_path="missing-ectopy.pkl",
            scaler_path="missing-scaler.pkl",
            schema_path="missing-schema.json",
            label_map_path="missing-label-map.json",
        )
        result = predictor.predict([0, 1, 0, -1], sample_rate_hz=130)
        self.assertEqual(result["label"], "unknown")
        self.assertEqual(result["model_source"], "ectopy_feature_model")

    def test_storage_creates_ectopy_event(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "ecg_monitor.db")
            save_prediction(
                {
                    "patient_id": "test_patient",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sample_rate_hz": 130.0,
                    "window_count": 1,
                    "heart_rate_bpm": 80.0,
                    "emotion": {},
                    "anomaly": {},
                    "rhythm": {"label": "normal", "possible_afib_probability": 0.0},
                    "ectopy": {
                        "label": "pvc",
                        "confidence": 0.8,
                        "pvc_probability": 0.8,
                        "pac_probability": 0.0,
                    },
                    "hr_event": {"label": "normal_hr"},
                    "af_episode": {},
                    "rhythm_alert": {"level": "normal"},
                    "signal_quality": {"label": "good"},
                    "risk": {},
                    "sensor_context": {"activity_state": "REST"},
                    "alert_level": "normal",
                    "message": "PVC/PAC test.",
                },
                ecg_samples=[0, 1, 0, -1] * 40,
                sample_rate_hz=130.0,
                db_path=db_path,
            )
            events = get_events(patient_id="test_patient", days=1, db_path=db_path)
            self.assertIn("ectopy_suspicion", {event["event_type"] for event in events})


if __name__ == "__main__":
    unittest.main()
