import json
from pathlib import Path

import numpy as np
import scipy.signal as signal

from src.config.runtime_config import get_config_section


ANOMALY_FEATURE_COLUMNS = [
    "RR_mean",
    "SDNN",
    "RMSSD",
    "pNN50",
    "LF/HF",
    "mean_amplitude",
    "std_amplitude",
    "mean_energy",
    "std_energy",
    "mean_qrs_slope",
]

def save_feature_schema(path, columns):
    Path(path).write_text(json.dumps({"features": list(columns)}, indent=2), encoding="utf-8")


def load_feature_schema(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["features"]


def bandpass_filter(ecg_signal, sample_rate_hz, low_hz=5.0, high_hz=40.0):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    if ecg.size == 0:
        return ecg

    nyquist = 0.5 * float(sample_rate_hz)
    high = min(high_hz, nyquist * 0.95)
    low = min(low_hz, high * 0.5)
    if low <= 0 or high <= low:
        return ecg

    b, a = signal.butter(2, [low / nyquist, high / nyquist], btype="band")
    padlen = 3 * max(len(a), len(b))
    if ecg.size <= padlen:
        return ecg
    return signal.filtfilt(b, a, ecg)


def detect_r_peaks(ecg_signal, sample_rate_hz):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    if ecg.size == 0:
        return np.array([], dtype=int)

    prominence = max(0.15, 0.5 * float(np.std(ecg)))
    peaks, _ = signal.find_peaks(
        ecg,
        distance=max(1, int(0.3 * sample_rate_hz)),
        prominence=prominence,
    )
    return peaks




def _beat_template_correlation(ecg_signal, peaks, sample_rate_hz, max_beats=20):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    peaks = np.asarray(peaks, dtype=int).flatten()
    if ecg.size == 0 or peaks.size < 3:
        return None

    before = int(0.12 * float(sample_rate_hz))
    after = int(0.24 * float(sample_rate_hz))
    beats = []
    for peak in peaks[:max_beats]:
        start = int(peak) - before
        end = int(peak) + after
        if start < 0 or end > ecg.size:
            continue
        beat = np.asarray(ecg[start:end], dtype=float)
        beat = beat - float(np.mean(beat))
        std = float(np.std(beat))
        if std <= 1e-9:
            continue
        beats.append(beat / std)

    if len(beats) < 3:
        return None

    min_len = min(len(beat) for beat in beats)
    matrix = np.vstack([beat[:min_len] for beat in beats])
    template = np.median(matrix, axis=0)
    template = template - float(np.mean(template))
    template_std = float(np.std(template))
    if template_std <= 1e-9:
        return None
    template = template / template_std

    correlations = []
    for beat in matrix:
        corr = np.corrcoef(beat, template)[0, 1]
        if np.isfinite(corr):
            correlations.append(float(corr))
    if not correlations:
        return None
    return float(np.median(correlations))


def rr_intervals_ms_from_peaks(peaks, sample_rate_hz):
    peaks = np.asarray(peaks, dtype=int).flatten()
    if peaks.size < 2:
        return np.array([], dtype=float)
    return np.diff(peaks) * 1000.0 / float(sample_rate_hz)


def _window_indices(length, window_size, step_size):
    if step_size is None:
        step_size = window_size
    if length < window_size:
        return []
    return [(i, i + window_size) for i in range(0, length - window_size + 1, step_size)]


def extract_hrv_features(rr_window):
    rr = np.asarray(rr_window, dtype=float).flatten()
    if rr.size < 2:
        return None

    diff_rr = np.diff(rr)
    rr_mean = float(np.mean(rr))
    rr_min = float(np.min(rr))
    rr_max = float(np.max(rr))
    rr_range = float(rr_max - rr_min)
    sdnn = float(np.std(rr))
    cvrr = float(sdnn / rr_mean) if rr_mean > 0 else 0.0
    mean_hr = float(60000.0 / rr_mean) if rr_mean > 0 else 0.0
    rmssd = float(np.sqrt(np.mean(diff_rr**2)))
    pnn50 = float(100.0 * np.sum(np.abs(diff_rr) > 50.0) / len(diff_rr))

    if rr_mean <= 0:
        lf_hf_ratio = 0.0
    else:
        fft_result = np.fft.fft(rr)
        freqs = np.fft.fftfreq(len(rr), d=rr_mean / 1000.0)
        power = np.abs(fft_result) ** 2
        lf_power = float(np.sum(power[(freqs >= 0.04) & (freqs <= 0.15)]))
        hf_power = float(np.sum(power[(freqs >= 0.15) & (freqs <= 0.40)]))
        lf_hf_ratio = lf_power / hf_power if hf_power > 0 else 0.0

    return {
        "RR_mean": rr_mean,
        "mean_HR": mean_hr,
        "RR_min": rr_min,
        "RR_max": rr_max,
        "RR_range": rr_range,
        "CVRR": cvrr,
        "SDNN": sdnn,
        "RMSSD": rmssd,
        "pNN50": pnn50,
        "LF/HF": float(lf_hf_ratio),
    }


def evaluate_signal_quality(ecg_signal, sample_rate_hz, min_seconds=8):
    quality_config = get_config_section("signal_quality")
    min_seconds = float(quality_config.get("min_seconds", min_seconds))
    max_nan_ratio = float(quality_config.get("max_nan_ratio", 0.01))
    max_zero_ratio = float(quality_config.get("max_zero_ratio", 0.8))
    min_amplitude_std = float(quality_config.get("min_amplitude_std", 1e-6))
    min_amplitude_range = float(quality_config.get("min_amplitude_range", 1e-6))
    min_r_peak_count = int(quality_config.get("min_r_peak_count", 6))
    min_valid_rr_ratio = float(quality_config.get("min_valid_rr_ratio", 0.8))
    max_rr_outlier_ratio = float(quality_config.get("max_rr_outlier_ratio", 0.35))
    min_beat_template_correlation = float(quality_config.get("min_beat_template_correlation", 0.35))
    min_noise_template_correlation = float(quality_config.get("min_noise_template_correlation", 0.65))
    max_noise_rr_outlier_ratio = float(quality_config.get("max_noise_rr_outlier_ratio", 0.2))
    max_physiological_hr_bpm = float(quality_config.get("max_physiological_hr_bpm", 220.0))
    min_median_peak_width_ms = float(quality_config.get("min_median_peak_width_ms", 15.0))
    max_median_peak_width_ms = float(quality_config.get("max_median_peak_width_ms", 220.0))

    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    metrics = {
        "sample_count": int(ecg.size),
        "duration_seconds": float(ecg.size / float(sample_rate_hz)) if sample_rate_hz else 0.0,
        "nan_ratio": 1.0,
        "zero_ratio": 1.0,
        "amplitude_std": 0.0,
        "amplitude_range": 0.0,
        "r_peak_count": 0,
        "r_peak_rate_bpm": 0.0,
        "valid_rr_ratio": 0.0,
        "rr_outlier_ratio": 1.0,
        "beat_template_correlation": None,
        "median_peak_width_ms": None,
    }
    reasons = []
    score = 1.0

    if ecg.size == 0:
        return {"label": "poor", "score": 0.0, "reasons": ["empty ECG signal"], "metrics": metrics}

    finite = np.isfinite(ecg)
    nan_ratio = float(1.0 - np.mean(finite))
    metrics["nan_ratio"] = nan_ratio
    if nan_ratio > max_nan_ratio:
        reasons.append("too many NaN/invalid samples")
        score -= 0.35

    ecg = ecg[finite]
    if ecg.size == 0:
        return {"label": "poor", "score": 0.0, "reasons": reasons or ["no finite samples"], "metrics": metrics}

    duration = ecg.size / float(sample_rate_hz)
    metrics["duration_seconds"] = float(duration)
    if duration < min_seconds:
        reasons.append("ECG segment is too short")
        score -= 0.25

    zero_ratio = float(np.mean(ecg == 0))
    amplitude_std = float(np.std(ecg))
    amplitude_range = float(np.max(ecg) - np.min(ecg))
    metrics["zero_ratio"] = zero_ratio
    metrics["amplitude_std"] = amplitude_std
    metrics["amplitude_range"] = amplitude_range

    if zero_ratio > max_zero_ratio:
        reasons.append("mostly zero samples")
        score -= 0.45
    if amplitude_std < min_amplitude_std or amplitude_range < min_amplitude_range:
        reasons.append("flatline or near-flatline signal")
        score -= 0.55

    filtered = bandpass_filter(ecg, sample_rate_hz)
    peaks = detect_r_peaks(filtered, sample_rate_hz)
    rr_ms = rr_intervals_ms_from_peaks(peaks, sample_rate_hz)
    metrics["r_peak_count"] = int(len(peaks))
    duration = max(float(metrics["duration_seconds"]), 1e-9)
    r_peak_rate_bpm = float(len(peaks) * 60.0 / duration)
    metrics["r_peak_rate_bpm"] = r_peak_rate_bpm

    if len(peaks) < min_r_peak_count:
        reasons.append("not enough R-peaks detected")
        score -= 0.35
    if r_peak_rate_bpm > max_physiological_hr_bpm:
        reasons.append("too many R-peak candidates for physiological ECG")
        score -= 0.55
    if len(peaks) >= 3:
        try:
            widths = signal.peak_widths(filtered, peaks, rel_height=0.5)[0]
            median_peak_width_ms = float(np.median(widths) * 1000.0 / float(sample_rate_hz))
            metrics["median_peak_width_ms"] = median_peak_width_ms
            if median_peak_width_ms < min_median_peak_width_ms:
                reasons.append("R-peak candidates are too narrow; possible noise or loose contact")
                score -= 0.55
            elif median_peak_width_ms > max_median_peak_width_ms:
                reasons.append("R-peak candidates are too wide; possible motion artifact")
                score -= 0.35
        except Exception:
            metrics["median_peak_width_ms"] = None

    if rr_ms.size > 0:
        valid_rr = (rr_ms >= 300) & (rr_ms <= 2000)
        valid_rr_ratio = float(np.mean(valid_rr))
        metrics["valid_rr_ratio"] = valid_rr_ratio
        if valid_rr_ratio < min_valid_rr_ratio:
            reasons.append("many RR intervals outside physiological range")
            score -= 0.3

        valid_values = rr_ms[valid_rr]
        if valid_values.size >= 3:
            median_rr = np.median(valid_values)
            if median_rr > 0:
                outlier_ratio = float(np.mean(np.abs(valid_values - median_rr) / median_rr > 0.25))
                metrics["rr_outlier_ratio"] = outlier_ratio
                if outlier_ratio > max_rr_outlier_ratio:
                    reasons.append("unstable RR intervals")
                    score -= 0.45
    else:
        reasons.append("no RR intervals detected")
        score -= 0.35

    beat_template_correlation = _beat_template_correlation(filtered, peaks, sample_rate_hz)
    metrics["beat_template_correlation"] = beat_template_correlation
    if beat_template_correlation is None:
        if len(peaks) >= min_r_peak_count:
            reasons.append("unable to verify ECG beat shape consistency")
            score -= 0.2
    elif beat_template_correlation < min_beat_template_correlation:
        reasons.append("inconsistent ECG beat morphology; possible loose contact or noise")
        score -= 0.55
    elif (
        beat_template_correlation < min_noise_template_correlation
        and float(metrics.get("rr_outlier_ratio") or 1.0) > max_noise_rr_outlier_ratio
    ):
        reasons.append("noise-like ECG morphology with unstable RR intervals")
        score -= 0.75

    score = float(max(0.0, min(1.0, score)))
    if score >= 0.75:
        label = "good"
    elif score >= 0.5:
        label = "fair"
    else:
        label = "poor"

    return {
        "label": label,
        "score": score,
        "reasons": reasons,
        "metrics": metrics,
    }


def extract_beat_features(ecg_signal, peaks, sample_rate_hz):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    features = []
    before = int(0.2 * sample_rate_hz)
    after = int(0.4 * sample_rate_hz)

    for peak in np.asarray(peaks, dtype=int).flatten():
        start = peak - before
        end = peak + after
        if start < 0 or end > ecg.size:
            continue

        beat = ecg[start:end]
        if beat.size < 2:
            continue

        diff_beat = np.diff(beat)
        features.append(
            {
                "beat_amplitude": float(np.max(beat) - np.min(beat)),
                "beat_energy": float(np.sum(beat**2)),
                "qrs_slope": float(np.max(diff_beat)),
            }
        )

    return features


def aggregate_morphological_features(beat_feature_window):
    if not beat_feature_window:
        return None

    amplitudes = np.array([x["beat_amplitude"] for x in beat_feature_window], dtype=float)
    energies = np.array([x["beat_energy"] for x in beat_feature_window], dtype=float)
    qrs_slopes = np.array([x["qrs_slope"] for x in beat_feature_window], dtype=float)

    return {
        "mean_amplitude": float(np.mean(amplitudes)),
        "std_amplitude": float(np.std(amplitudes)),
        "mean_energy": float(np.mean(energies)),
        "std_energy": float(np.std(energies)),
        "mean_qrs_slope": float(np.mean(qrs_slopes)),
    }


def rows_to_matrix(rows, columns):
    if not rows:
        return np.empty((0, len(columns)), dtype=float)
    return np.array([[row[col] for col in columns] for row in rows], dtype=float)


def extract_anomaly_feature_rows(
    ecg_signal,
    sample_rate_hz,
    window_size=10,
    step_size=None,
    filter_signal=True,
):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    if filter_signal:
        ecg = bandpass_filter(ecg, sample_rate_hz)

    peaks = detect_r_peaks(ecg, sample_rate_hz)
    rr_ms = rr_intervals_ms_from_peaks(peaks, sample_rate_hz)
    beat_features = extract_beat_features(ecg, peaks, sample_rate_hz)

    if rr_ms.size < window_size or len(beat_features) < window_size:
        return []

    rows = []
    limit = min(len(rr_ms), len(beat_features))
    for start, end in _window_indices(limit, window_size, step_size):
        hrv = extract_hrv_features(rr_ms[start:end])
        morph = aggregate_morphological_features(beat_features[start:end])
        if hrv is None or morph is None:
            continue

        row = {**hrv, **morph, "start_idx": start, "end_idx": end}
        rows.append(row)
    return rows


def estimate_heart_rate_bpm(feature_rows):
    rr_values = [row["RR_mean"] for row in feature_rows if row.get("RR_mean", 0) > 0]
    if not rr_values:
        return None
    return float(60000.0 / np.mean(rr_values))
