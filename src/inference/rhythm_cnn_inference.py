import json
from pathlib import Path

import numpy as np

from src.preprocessing import (
    RHYTHM_LABELS,
    RHYTHM_LABEL_MAP,
    TARGET_SAMPLE_RATE_HZ,
    normalize_ecg,
    resample_ecg,
    split_into_windows,
)


DEFAULT_RHYTHM_CNN_MODEL_PATH = "models/research/rhythm_cnn/rhythm_cnn_model.pt"
DEFAULT_RHYTHM_CNN_METADATA_PATH = "models/research/rhythm_cnn/rhythm_cnn_metadata.json"


def _unknown_result(reason, window_count=0):
    return {
        "label": "unknown",
        "class_id": None,
        "confidence": 0.0,
        "probabilities": {},
        "window_count": int(window_count),
        "reason": reason,
        "model_source": "rhythm_cnn_model",
    }


def _load_torch():
    try:
        import torch
        import torch.nn as nn
    except ImportError as exc:
        raise ImportError("PyTorch is required for the rhythm CNN model. Install torch first.") from exc
    return torch, nn


class RhythmCnn1D:
    def __new__(cls, input_length=3900, num_classes=4, dropout=0.25):
        torch, nn = _load_torch()

        class _Model(nn.Module):
            def __init__(self):
                super().__init__()
                self.net = nn.Sequential(
                    nn.Conv1d(1, 32, kernel_size=15, stride=2, padding=7),
                    nn.BatchNorm1d(32),
                    nn.ReLU(),
                    nn.MaxPool1d(kernel_size=2),
                    nn.Conv1d(32, 64, kernel_size=9, stride=2, padding=4),
                    nn.BatchNorm1d(64),
                    nn.ReLU(),
                    nn.MaxPool1d(kernel_size=2),
                    nn.Conv1d(64, 128, kernel_size=7, stride=2, padding=3),
                    nn.BatchNorm1d(128),
                    nn.ReLU(),
                    nn.Conv1d(128, 128, kernel_size=5, stride=1, padding=2),
                    nn.BatchNorm1d(128),
                    nn.ReLU(),
                    nn.AdaptiveAvgPool1d(1),
                )
                self.head = nn.Sequential(
                    nn.Flatten(),
                    nn.Dropout(float(dropout)),
                    nn.Linear(128, int(num_classes)),
                )

            def forward(self, x):
                return self.head(self.net(x))

        model = _Model()
        model.input_length = int(input_length)
        model.num_classes = int(num_classes)
        model.dropout = float(dropout)
        return model


def load_cnn_metadata(path):
    metadata_path = Path(path)
    if not metadata_path.exists():
        return {}
    with open(metadata_path, "r", encoding="utf-8") as f:
        return json.load(f)


class RhythmCnnPredictor:
    def __init__(
        self,
        model_path=DEFAULT_RHYTHM_CNN_MODEL_PATH,
        metadata_path=DEFAULT_RHYTHM_CNN_METADATA_PATH,
        target_sample_rate_hz=TARGET_SAMPLE_RATE_HZ,
        device=None,
    ):
        self.model_path = Path(model_path)
        self.metadata_path = Path(metadata_path)
        self.target_sample_rate_hz = float(target_sample_rate_hz)
        self.device_name = device
        self.model = None
        self.labels = dict(RHYTHM_LABELS)
        self.input_length = None
        self.loaded = False
        self.load_error = None
        self.load()

    def load(self):
        try:
            torch, _ = _load_torch()
            if not self.model_path.exists():
                raise FileNotFoundError(str(self.model_path))
            metadata = load_cnn_metadata(self.metadata_path)
            labels = metadata.get("labels") or {str(key): value for key, value in RHYTHM_LABELS.items()}
            self.labels = {int(key): value for key, value in labels.items()}
            self.input_length = int(metadata.get("input_length") or 3900)
            num_classes = int(metadata.get("num_classes") or len(self.labels))
            dropout = float(metadata.get("dropout") or 0.25)
            self.target_sample_rate_hz = float(metadata.get("sample_rate_hz") or self.target_sample_rate_hz)

            device = self.device_name or ("cuda" if torch.cuda.is_available() else "cpu")
            self.device = torch.device(device)
            self.model = RhythmCnn1D(
                input_length=self.input_length,
                num_classes=num_classes,
                dropout=dropout,
            )
            payload = torch.load(self.model_path, map_location=self.device)
            state_dict = payload.get("state_dict") if isinstance(payload, dict) else payload
            self.model.load_state_dict(state_dict)
            self.model.to(self.device)
            self.model.eval()
            self.loaded = True
            self.load_error = None
        except Exception as exc:
            self.model = None
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
            return _unknown_result(self.load_error or "Rhythm CNN model is not loaded.")

        windows = self.prepare_windows(ecg_samples, sample_rate_hz)
        if not windows:
            return _unknown_result("No ECG rhythm windows were generated.")

        torch, _ = _load_torch()
        X = np.asarray(windows, dtype=np.float32)
        if self.input_length is not None and X.shape[1] != self.input_length:
            return _unknown_result(
                f"Rhythm CNN input length mismatch: expected {self.input_length}, got {X.shape[1]}.",
                window_count=len(windows),
            )
        with torch.no_grad():
            tensor = torch.from_numpy(X[:, None, :]).to(self.device)
            logits = self.model(tensor)
            probs = torch.softmax(logits, dim=1).cpu().numpy()

        mean_proba = np.mean(probs, axis=0)
        class_ids = list(range(len(mean_proba)))
        best_index = int(np.argmax(mean_proba))
        class_id = class_ids[best_index]
        probabilities = {
            self.labels.get(class_ids[index], str(class_ids[index])): float(mean_proba[index])
            for index in range(len(class_ids))
        }
        afib_id = RHYTHM_LABEL_MAP["possible_afib"]
        afib_probability = float(mean_proba[afib_id]) if afib_id < len(mean_proba) else 0.0

        return {
            "label": self.labels.get(class_id, str(class_id)),
            "class_id": int(class_id),
            "confidence": float(mean_proba[best_index]),
            "probabilities": probabilities,
            "possible_afib_probability": afib_probability,
            "window_count": int(len(windows)),
            "model_source": "rhythm_cnn_model",
        }
