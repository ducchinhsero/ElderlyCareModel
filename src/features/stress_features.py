import json
from pathlib import Path

import numpy as np
import scipy.signal as signal


STRESS_FEATURE_COLUMNS = [
    "mean_rr",
    "sdnn",
    "rmssd",
    "pnn50",
    "lf_power",
    "hf_power",
    "lf_hf_ratio",
    "lf_nu",
    "hf_nu",
    "sd1",
    "sd2",
    "sd1_sd2_ratio",
]

STRESS_LABELS = {
    0: "non_stress",
    1: "stress",
}

STRESS_WINDOW_SECONDS = 300.0
STRESS_STEP_SECONDS = 60.0
MIN_RR_PER_WINDOW = 20
RR_MIN_MS = 300.0
RR_MAX_MS = 2000.0
RR_MAX_DELTA_RATIO = 0.20


def save_stress_feature_schema(path, columns=STRESS_FEATURE_COLUMNS):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"features": list(columns)}, indent=2), encoding="utf-8")


def filter_rr_artifacts(rr_intervals_ms):
    rr = np.asarray(rr_intervals_ms, dtype=float).flatten()
    rr = rr[np.isfinite(rr)]
    if rr.size == 0:
        return rr

    rr = rr[(rr >= RR_MIN_MS) & (rr <= RR_MAX_MS)]
    if rr.size < 2:
        return rr

    keep = np.ones(rr.size, dtype=bool)
    previous = rr[0]
    for index in range(1, rr.size):
        if previous <= 0:
            keep[index] = False
            continue
        delta_ratio = abs(rr[index] - previous) / previous
        if delta_ratio > RR_MAX_DELTA_RATIO:
            keep[index] = False
        else:
            previous = rr[index]
    return rr[keep]


def rr_timestamps_from_intervals(rr_intervals_ms):
    rr = np.asarray(rr_intervals_ms, dtype=float).flatten()
    if rr.size == 0:
        return np.array([], dtype=float)
    return np.cumsum(rr) / 1000.0


def _lomb_scargle_power(rr_intervals_ms, rr_timestamps_sec=None):
    rr = np.asarray(rr_intervals_ms, dtype=float).flatten()
    if rr.size < 4:
        return 0.0, 0.0

    timestamps = (
        rr_timestamps_from_intervals(rr)
        if rr_timestamps_sec is None
        else np.asarray(rr_timestamps_sec, dtype=float).flatten()
    )
    if timestamps.size != rr.size:
        timestamps = rr_timestamps_from_intervals(rr)
    if timestamps.size < 4 or np.ptp(timestamps) <= 0:
        return 0.0, 0.0

    values = rr - np.mean(rr)
    frequencies = np.linspace(0.01, 0.5, 512)
    try:
        from astropy.timeseries import LombScargle

        power = LombScargle(timestamps, values).power(frequencies)
    except Exception:
        uniform_times = np.linspace(float(timestamps[0]), float(timestamps[-1]), rr.size)
        uniform_values = np.interp(uniform_times, timestamps, values)
        sample_rate = rr.size / max(float(timestamps[-1] - timestamps[0]), 1e-6)
        frequencies, power = signal.welch(
            uniform_values,
            fs=sample_rate,
            nperseg=min(256, uniform_values.size),
        )

    lf_mask = (frequencies >= 0.04) & (frequencies <= 0.15)
    hf_mask = (frequencies >= 0.15) & (frequencies <= 0.40)
    lf_power = float(np.trapezoid(power[lf_mask], frequencies[lf_mask])) if np.any(lf_mask) else 0.0
    hf_power = float(np.trapezoid(power[hf_mask], frequencies[hf_mask])) if np.any(hf_mask) else 0.0
    return max(0.0, lf_power), max(0.0, hf_power)


def extract_stress_features(rr_intervals_ms, rr_timestamps_sec=None):
    rr = filter_rr_artifacts(rr_intervals_ms)
    if rr.size < MIN_RR_PER_WINDOW:
        return None

    timestamps = None
    if rr_timestamps_sec is not None:
        original_rr = np.asarray(rr_intervals_ms, dtype=float).flatten()
        original_timestamps = np.asarray(rr_timestamps_sec, dtype=float).flatten()
        if original_rr.size == original_timestamps.size:
            valid = np.isfinite(original_rr)
            original_rr = original_rr[valid]
            original_timestamps = original_timestamps[valid]
            valid = (original_rr >= RR_MIN_MS) & (original_rr <= RR_MAX_MS)
            original_rr = original_rr[valid]
            original_timestamps = original_timestamps[valid]
            if original_rr.size == rr.size:
                timestamps = original_timestamps
    if timestamps is None:
        timestamps = rr_timestamps_from_intervals(rr)

    diff_rr = np.diff(rr)
    mean_rr = float(np.mean(rr))
    sdnn = float(np.std(rr, ddof=1)) if rr.size > 1 else 0.0
    rmssd = float(np.sqrt(np.mean(diff_rr**2))) if diff_rr.size else 0.0
    pnn50 = float(np.mean(np.abs(diff_rr) > 50.0)) if diff_rr.size else 0.0
    lf_power, hf_power = _lomb_scargle_power(rr, timestamps)
    total_power = lf_power + hf_power
    lf_hf_ratio = float(lf_power / hf_power) if hf_power > 0 else 0.0
    lf_nu = float(lf_power / total_power) if total_power > 0 else 0.0
    hf_nu = float(hf_power / total_power) if total_power > 0 else 0.0

    if diff_rr.size:
        sd1 = float(np.sqrt(np.var(diff_rr, ddof=1) / 2.0)) if diff_rr.size > 1 else 0.0
    else:
        sd1 = 0.0
    sd2_term = max(0.0, (2.0 * sdnn**2) - (0.5 * sd1**2))
    sd2 = float(np.sqrt(sd2_term))
    sd1_sd2_ratio = float(sd1 / sd2) if sd2 > 0 else 0.0

    row = {
        "mean_rr": mean_rr,
        "sdnn": sdnn,
        "rmssd": rmssd,
        "pnn50": pnn50,
        "lf_power": lf_power,
        "hf_power": hf_power,
        "lf_hf_ratio": lf_hf_ratio,
        "lf_nu": lf_nu,
        "hf_nu": hf_nu,
        "sd1": sd1,
        "sd2": sd2,
        "sd1_sd2_ratio": sd1_sd2_ratio,
    }
    return {column: float(row[column]) for column in STRESS_FEATURE_COLUMNS}


def stress_row_to_matrix(row):
    if row is None:
        return np.empty((0, len(STRESS_FEATURE_COLUMNS)), dtype=float)
    return np.array([[row[column] for column in STRESS_FEATURE_COLUMNS]], dtype=float)
