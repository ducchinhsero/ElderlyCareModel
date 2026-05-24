import json
import math
from pathlib import Path

import numpy as np
import scipy.signal as signal


TARGET_SAMPLE_RATE_HZ = 130
WINDOW_SECONDS = 30
SAMPLES_PER_WINDOW = TARGET_SAMPLE_RATE_HZ * WINDOW_SECONDS

RHYTHM_LABELS = {
    0: "normal",
    1: "possible_afib",
    2: "other_rhythm",
    3: "noise",
}

RHYTHM_LABEL_MAP = {label: class_id for class_id, label in RHYTHM_LABELS.items()}

CINC2017_LABEL_MAP = {
    "N": RHYTHM_LABEL_MAP["normal"],
    "normal": RHYTHM_LABEL_MAP["normal"],
    "A": RHYTHM_LABEL_MAP["possible_afib"],
    "AF": RHYTHM_LABEL_MAP["possible_afib"],
    "AFIB": RHYTHM_LABEL_MAP["possible_afib"],
    "possible_afib": RHYTHM_LABEL_MAP["possible_afib"],
    "O": RHYTHM_LABEL_MAP["other_rhythm"],
    "other": RHYTHM_LABEL_MAP["other_rhythm"],
    "other_rhythm": RHYTHM_LABEL_MAP["other_rhythm"],
    "~": RHYTHM_LABEL_MAP["noise"],
    "noise": RHYTHM_LABEL_MAP["noise"],
}


def save_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resample_ecg(ecg_signal, source_rate_hz, target_rate_hz=TARGET_SAMPLE_RATE_HZ):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    if ecg.size == 0:
        return ecg

    source_rate = float(source_rate_hz)
    target_rate = float(target_rate_hz)
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("source_rate_hz and target_rate_hz must be positive.")
    if math.isclose(source_rate, target_rate):
        return ecg.copy()

    source_i = int(round(source_rate))
    target_i = int(round(target_rate))
    gcd = math.gcd(source_i, target_i)
    return signal.resample_poly(ecg, target_i // gcd, source_i // gcd)


def normalize_ecg(ecg_signal):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    if ecg.size == 0:
        return ecg

    finite = np.isfinite(ecg)
    if not np.all(finite):
        median = float(np.nanmedian(ecg)) if np.any(finite) else 0.0
        ecg = np.where(finite, ecg, median)

    median = float(np.median(ecg))
    centered = ecg - median
    q75, q25 = np.percentile(centered, [75, 25])
    iqr = float(q75 - q25)
    if iqr > 1e-8:
        return centered / iqr

    std = float(np.std(centered))
    if std > 1e-8:
        return centered / std
    return np.zeros_like(centered)


def pad_or_crop_window(ecg_signal, samples_per_window=SAMPLES_PER_WINDOW):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    target = int(samples_per_window)
    if target <= 0:
        raise ValueError("samples_per_window must be positive.")
    if ecg.size == target:
        return ecg.copy()
    if ecg.size > target:
        return ecg[:target].copy()
    return np.pad(ecg, (0, target - ecg.size), mode="constant")


def split_into_windows(ecg_signal, samples_per_window=SAMPLES_PER_WINDOW, include_partial=True):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    target = int(samples_per_window)
    if target <= 0:
        raise ValueError("samples_per_window must be positive.")
    if ecg.size == 0:
        return []

    windows = []
    for start in range(0, ecg.size, target):
        chunk = ecg[start : start + target]
        if chunk.size == target:
            windows.append((start, chunk.copy(), False))
        elif include_partial:
            windows.append((start, pad_or_crop_window(chunk, target), True))
    return windows


def encode_rhythm_label(raw_label):
    key = str(raw_label).strip()
    if key in CINC2017_LABEL_MAP:
        return CINC2017_LABEL_MAP[key]
    upper_key = key.upper()
    if upper_key in CINC2017_LABEL_MAP:
        return CINC2017_LABEL_MAP[upper_key]
    raise ValueError(f"Unsupported rhythm label: {raw_label!r}")
