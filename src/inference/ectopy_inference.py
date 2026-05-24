import json
from pathlib import Path

import joblib
import numpy as np

from src.features.ectopy_features import ECTOPY_FEATURE_COLUMNS, ECTOPY_LABELS, ECTOPY_LABEL_MAP, extract_ectopy_feature_matrix
from src.preprocessing import TARGET_SAMPLE_RATE_HZ, normalize_ecg, resample_ecg, split_into_windows


DEFAULT_ECTOPY_MODEL_PATH = "models/ectopy/ectopy_feature_model.pkl"
DEFAULT_ECTOPY_SCALER_PATH = "models/ectopy/ectopy_scaler.pkl"
DEFAULT_ECTOPY_SCHEMA_PATH = "models/ectopy/ectopy_feature_schema.json"
DEFAULT_ECTOPY_LABEL_MAP_PATH = "models/ectopy/label_map.json"


def _unknown_result(reason, window_count=0):
    return {
        "label": "unknown",
        "class_id": None,
        "confidence": 0.0,
        "probabilities": {},
        "pvc_probability": 0.0,
        "pac_probability": 0.0,
        "ectopic_probability": 0.0,
        "window_count": int(window_count),
        "reason": reason,
        "model_source": "ectopy_feature_model",
    }


def _load_schema(path):
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return list(payload.get("features") or [])


def _load_labels(path):
    if not Path(path).exists():
        return dict(ECTOPY_LABELS)
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    labels = payload.get("labels") or {}
    return {int(key): value for key, value in labels.items()}


class EctopyFeaturePredictor:
    def __init__(
        self,
        model_path=DEFAULT_ECTOPY_MODEL_PATH,
        scaler_path=DEFAULT_ECTOPY_SCALER_PATH,
        schema_path=DEFAULT_ECTOPY_SCHEMA_PATH,
        label_map_path=DEFAULT_ECTOPY_LABEL_MAP_PATH,
        target_sample_rate_hz=TARGET_SAMPLE_RATE_HZ,
    ):
        self.model_path = Path(model_path)
        self.scaler_path = Path(scaler_path)
        self.schema_path = Path(schema_path)
        self.label_map_path = Path(label_map_path)
        self.target_sample_rate_hz = float(target_sample_rate_hz)
        self.model = None
        self.scaler = None
        self.feature_columns = list(ECTOPY_FEATURE_COLUMNS)
        self.labels = dict(ECTOPY_LABELS)
        self.loaded = False
        self.load_error = None
        self.load()

    def load(self):
        try:
            self.model = joblib.load(self.model_path)
            self.scaler = joblib.load(self.scaler_path)
            self.feature_columns = _load_schema(self.schema_path)
            self.labels = _load_labels(self.label_map_path)
            if list(self.feature_columns) != list(ECTOPY_FEATURE_COLUMNS):
                raise ValueError("ectopy feature schema mismatch. Retrain ectopy model.")
            self.loaded = True
            self.load_error = None
        except Exception as exc:
            self.model = None
            self.scaler = None
            self.loaded = False
            self.load_error = str(exc)

    def prepare_windows(self, ecg_samples, sample_rate_hz):
        ecg = np.asarray(ecg_samples, dtype=float).flatten()
        if ecg.size == 0:
            return []
        resampled = resample_ecg(ecg, source_rate_hz=sample_rate_hz, target_rate_hz=self.target_sample_rate_hz)
        normalized = normalize_ecg(resampled)
        return [window for _, window, _ in split_into_windows(normalized, include_partial=True)]

    def predict(self, ecg_samples, sample_rate_hz):
        if not self.loaded:
            return _unknown_result(self.load_error or "Ectopy model is not loaded.")
        windows = self.prepare_windows(ecg_samples, sample_rate_hz)
        if not windows:
            return _unknown_result("No ECG ectopy windows were generated.")

        X_features, _ = extract_ectopy_feature_matrix(
            np.asarray(windows),
            sample_rate_hz=self.target_sample_rate_hz,
            feature_columns=self.feature_columns,
        )
        X_scaled = self.scaler.transform(X_features)
        if hasattr(self.model, "predict_proba"):
            proba = self.model.predict_proba(X_scaled)
            classes = [int(value) for value in self.model.classes_]
            mean_proba = np.mean(proba, axis=0)
            best_index = int(np.argmax(mean_proba))
            class_id = classes[best_index]
            probabilities = {
                self.labels.get(classes[index], str(classes[index])): float(mean_proba[index])
                for index in range(len(classes))
            }
            confidence = float(mean_proba[best_index])
        else:
            predictions = self.model.predict(X_scaled)
            values, counts = np.unique(predictions, return_counts=True)
            best_index = int(np.argmax(counts))
            class_id = int(values[best_index])
            confidence = float(counts[best_index] / len(predictions))
            probabilities = {
                self.labels.get(int(value), str(int(value))): float(count / len(predictions))
                for value, count in zip(values, counts)
            }

        pvc_probability = float(probabilities.get("pvc", 0.0) + probabilities.get("mixed_ectopic", 0.0))
        pac_probability = float(probabilities.get("pac", 0.0) + probabilities.get("mixed_ectopic", 0.0))
        ectopic_probability = float(
            probabilities.get("pvc", 0.0)
            + probabilities.get("pac", 0.0)
            + probabilities.get("mixed_ectopic", 0.0)
        )
        return {
            "label": self.labels.get(class_id, str(class_id)),
            "class_id": int(class_id),
            "confidence": confidence,
            "probabilities": probabilities,
            "pvc_probability": pvc_probability,
            "pac_probability": pac_probability,
            "ectopic_probability": ectopic_probability,
            "window_count": int(len(windows)),
            "model_source": "ectopy_feature_model",
        }
