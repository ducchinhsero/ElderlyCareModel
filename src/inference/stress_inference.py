import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from src.features.stress_features import (
    MIN_RR_PER_WINDOW,
    STRESS_FEATURE_COLUMNS,
    STRESS_LABELS,
    STRESS_WINDOW_SECONDS,
    extract_stress_features,
)


DEFAULT_MODEL_VERSION = "soft_voting_rf_svm_wesad"


def unknown_stress(reason, model_version=DEFAULT_MODEL_VERSION, window_seconds=STRESS_WINDOW_SECONDS):
    return {
        "label": "unknown",
        "value": None,
        "confidence": 0.0,
        "probabilities": {"non_stress": 0.0, "stress": 0.0},
        "model_version": model_version,
        "window_seconds": float(window_seconds),
        "reason": reason,
    }


class StressPredictor:
    def __init__(self, model_dir="models/stress"):
        self.model_dir = model_dir
        self.rf_model = None
        self.svm_pipeline = None
        self.scaler = None
        self.metadata = {}
        self.loaded = False
        self.load_error = None
        self.feature_columns = list(STRESS_FEATURE_COLUMNS)
        self.window_seconds = float(STRESS_WINDOW_SECONDS)
        self.model_version = DEFAULT_MODEL_VERSION
        self._load()

    def _load_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load(self):
        try:
            metadata_path = os.path.join(self.model_dir, "model_metadata.json")
            if os.path.exists(metadata_path):
                self.metadata = self._load_json(metadata_path)
                self.feature_columns = list(
                    self.metadata.get("feature_names")
                    or self.metadata.get("features")
                    or STRESS_FEATURE_COLUMNS
                )
                self.window_seconds = float(
                    self.metadata.get("window_size_sec")
                    or self.metadata.get("window_seconds")
                    or STRESS_WINDOW_SECONDS
                )
                self.model_version = (
                    self.metadata.get("model_version")
                    or self.metadata.get("model_type")
                    or DEFAULT_MODEL_VERSION
                )

            rf_path = os.path.join(self.model_dir, "rf_model.pkl")
            svm_path = os.path.join(self.model_dir, "svm_pipeline.pkl")
            scaler_path = os.path.join(self.model_dir, "scaler_final.pkl")
            self.rf_model = joblib.load(rf_path)
            self.svm_pipeline = joblib.load(svm_path)
            if os.path.exists(scaler_path):
                self.scaler = joblib.load(scaler_path)

            if self.feature_columns != STRESS_FEATURE_COLUMNS:
                raise ValueError(
                    "stress feature schema mismatch. "
                    f"Expected {STRESS_FEATURE_COLUMNS}, got {self.feature_columns}."
                )
            self.loaded = True
            self.load_error = None
        except Exception as exc:
            self.rf_model = None
            self.svm_pipeline = None
            self.scaler = None
            self.loaded = False
            self.load_error = str(exc)

    def _model_probability(self, model, X):
        if hasattr(model, "predict_proba"):
            proba = np.asarray(model.predict_proba(X), dtype=float)[0]
            classes = [int(value) for value in getattr(model, "classes_", [0, 1])]
            return {
                STRESS_LABELS.get(classes[index], str(classes[index])): float(proba[index])
                for index in range(len(classes))
            }
        pred = int(model.predict(X)[0])
        return {
            "non_stress": 1.0 if pred == 0 else 0.0,
            "stress": 1.0 if pred == 1 else 0.0,
        }

    def predict_from_rr(self, rr_intervals_ms, rr_timestamps_sec=None):
        if not self.loaded:
            return unknown_stress(
                "stress_model_not_loaded",
                model_version=self.model_version,
                window_seconds=self.window_seconds,
            )

        feature_row = extract_stress_features(rr_intervals_ms, rr_timestamps_sec=rr_timestamps_sec)
        if feature_row is None:
            return unknown_stress(
                "insufficient_rr_for_stress_features",
                model_version=self.model_version,
                window_seconds=self.window_seconds,
            )

        try:
            X = pd.DataFrame([[feature_row[column] for column in STRESS_FEATURE_COLUMNS]], columns=STRESS_FEATURE_COLUMNS)
            rf_proba = self._model_probability(self.rf_model, X)
            svm_proba = self._model_probability(self.svm_pipeline, X)
            stress_probability = float(
                (
                    float(rf_proba.get("stress", 0.0))
                    + float(svm_proba.get("stress", 0.0))
                )
                / 2.0
            )
            non_stress_probability = max(0.0, 1.0 - stress_probability)
            probabilities = {
                "non_stress": non_stress_probability,
                "stress": stress_probability,
            }
            value = 1 if stress_probability >= 0.5 else 0
            label = STRESS_LABELS[value]
            confidence = stress_probability if value == 1 else non_stress_probability
            return {
                "label": label,
                "value": value,
                "confidence": float(confidence),
                "probabilities": probabilities,
                "model_version": self.model_version,
                "window_seconds": float(self.window_seconds),
                "reason": None,
            }
        except Exception as exc:
            return unknown_stress(
                f"stress_prediction_failed: {exc}",
                model_version=self.model_version,
                window_seconds=self.window_seconds,
            )


@dataclass
class RollingRRBuffer:
    max_seconds: float = 360.0
    points: list[tuple[float, float]] = field(default_factory=list)

    def add_from_peaks(self, peaks, sample_rate_hz, chunk_start_epoch=None):
        peaks = np.asarray(peaks, dtype=int).flatten()
        sample_rate_hz = float(sample_rate_hz)
        if peaks.size < 2 or sample_rate_hz <= 0:
            return 0

        if chunk_start_epoch is None:
            chunk_start_epoch = datetime.now(timezone.utc).timestamp() - (float(peaks[-1]) / sample_rate_hz)
        rr_ms = np.diff(peaks) * 1000.0 / sample_rate_hz
        rr_end_times = float(chunk_start_epoch) + (peaks[1:] / sample_rate_hz)
        for timestamp_sec, interval_ms in zip(rr_end_times, rr_ms):
            if np.isfinite(interval_ms):
                self.points.append((float(timestamp_sec), float(interval_ms)))
        self._trim()
        return int(rr_ms.size)

    def _trim(self):
        if not self.points:
            return
        latest = max(timestamp for timestamp, _ in self.points)
        cutoff = latest - float(self.max_seconds)
        self.points = [(timestamp, rr) for timestamp, rr in self.points if timestamp >= cutoff]

    def stress_window(self, window_seconds=STRESS_WINDOW_SECONDS):
        if not self.points:
            return np.array([], dtype=float), np.array([], dtype=float), 0.0
        self._trim()
        latest = max(timestamp for timestamp, _ in self.points)
        cutoff = latest - float(window_seconds)
        window = [(timestamp, rr) for timestamp, rr in self.points if timestamp >= cutoff]
        if not window:
            return np.array([], dtype=float), np.array([], dtype=float), 0.0
        timestamps = np.array([timestamp for timestamp, _ in window], dtype=float)
        rr = np.array([rr for _, rr in window], dtype=float)
        coverage = float(timestamps[-1] - timestamps[0]) if timestamps.size >= 2 else 0.0
        return rr, timestamps - timestamps[0], coverage

    def ready(self, window_seconds=STRESS_WINDOW_SECONDS):
        rr, _, coverage = self.stress_window(window_seconds=window_seconds)
        required_coverage = max(60.0, float(window_seconds) * 0.8)
        return rr.size >= MIN_RR_PER_WINDOW and coverage >= required_coverage
