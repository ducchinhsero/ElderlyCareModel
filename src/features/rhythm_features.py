import numpy as np

from src.features.ecg_features import (
    bandpass_filter,
    detect_r_peaks,
    evaluate_signal_quality,
    rr_intervals_ms_from_peaks,
)


RHYTHM_FEATURE_COLUMNS = [
    "r_peak_count",
    "rr_count",
    "valid_rr_ratio",
    "mean_hr",
    "median_hr",
    "min_hr",
    "max_hr",
    "heart_rate_range",
    "heart_rate_std",
    "mean_rr",
    "median_rr",
    "min_rr",
    "max_rr",
    "std_rr",
    "rr_iqr",
    "rr_range",
    "rmssd",
    "sdnn",
    "pnn50",
    "rr_diff_mean_abs",
    "rr_diff_std",
    "rr_irregularity_index",
    "rr_outlier_ratio",
    "sample_entropy",
    "turning_point_ratio",
    "qrs_width_mean",
    "qrs_width_std",
    "r_amplitude_mean",
    "r_amplitude_std",
    "ecg_mean",
    "ecg_std",
    "ecg_iqr",
    "ecg_range",
    "ecg_skewness",
    "ecg_kurtosis",
    "ecg_energy",
    "line_length",
    "zero_crossing_rate",
    "spectral_entropy",
    "high_freq_power_ratio",
    "signal_quality_score",
]


def _safe_float(value):
    value = float(value)
    if np.isfinite(value):
        return value
    return 0.0


def _sample_entropy(values, m=2):
    values = np.asarray(values, dtype=float).flatten()
    if values.size < m + 3:
        return 0.0
    std = float(np.std(values))
    if std <= 1e-12:
        return 0.0
    r = 0.2 * std

    def count_matches(order):
        templates = np.array([values[i : i + order] for i in range(values.size - order + 1)])
        count = 0
        for i in range(len(templates)):
            distance = np.max(np.abs(templates[i + 1 :] - templates[i]), axis=1)
            count += int(np.sum(distance <= r))
        return count

    b = count_matches(m)
    a = count_matches(m + 1)
    if a == 0 or b == 0:
        return 0.0
    return _safe_float(-np.log(a / b))


def _turning_point_ratio(values):
    values = np.asarray(values, dtype=float).flatten()
    if values.size < 3:
        return 0.0
    middle = values[1:-1]
    previous_values = values[:-2]
    next_values = values[2:]
    turning = ((middle > previous_values) & (middle > next_values)) | (
        (middle < previous_values) & (middle < next_values)
    )
    return _safe_float(np.mean(turning))


def _iqr(values):
    values = np.asarray(values, dtype=float).flatten()
    if values.size == 0:
        return 0.0
    q75, q25 = np.percentile(values, [75, 25])
    return _safe_float(q75 - q25)


def _skewness(values):
    values = np.asarray(values, dtype=float).flatten()
    if values.size < 3:
        return 0.0
    std = float(np.std(values))
    if std <= 1e-12:
        return 0.0
    centered = values - np.mean(values)
    return _safe_float(np.mean((centered / std) ** 3))


def _kurtosis(values):
    values = np.asarray(values, dtype=float).flatten()
    if values.size < 4:
        return 0.0
    std = float(np.std(values))
    if std <= 1e-12:
        return 0.0
    centered = values - np.mean(values)
    return _safe_float(np.mean((centered / std) ** 4) - 3.0)


def _zero_crossing_rate(values):
    values = np.asarray(values, dtype=float).flatten()
    if values.size < 2:
        return 0.0
    centered = values - np.median(values)
    return _safe_float(np.mean(np.diff(np.signbit(centered)) != 0))


def _spectral_features(values, sample_rate_hz):
    values = np.asarray(values, dtype=float).flatten()
    if values.size < 16:
        return {"spectral_entropy": 0.0, "high_freq_power_ratio": 0.0}

    centered = values - np.mean(values)
    freqs = np.fft.rfftfreq(centered.size, d=1.0 / float(sample_rate_hz))
    power = np.abs(np.fft.rfft(centered)) ** 2
    total_power = float(np.sum(power))
    if total_power <= 1e-12:
        return {"spectral_entropy": 0.0, "high_freq_power_ratio": 0.0}

    prob = power / total_power
    entropy = -np.sum(prob * np.log2(prob + 1e-12))
    entropy = entropy / np.log2(prob.size) if prob.size > 1 else 0.0
    high_freq_power = float(np.sum(power[freqs >= 25.0]))
    return {
        "spectral_entropy": _safe_float(entropy),
        "high_freq_power_ratio": _safe_float(high_freq_power / total_power),
    }


def _qrs_widths_and_amplitudes(filtered_ecg, peaks, sample_rate_hz):
    ecg = np.asarray(filtered_ecg, dtype=float).flatten()
    widths = []
    amplitudes = []
    half_window = int(0.12 * float(sample_rate_hz))
    if half_window < 2:
        return widths, amplitudes

    for peak in np.asarray(peaks, dtype=int).flatten():
        start = max(0, peak - half_window)
        end = min(ecg.size, peak + half_window + 1)
        segment = ecg[start:end]
        if segment.size < 3:
            continue
        local_baseline = float(np.median(segment))
        peak_value = float(ecg[peak])
        amplitude = abs(peak_value - local_baseline)
        if amplitude <= 1e-12:
            continue
        threshold = local_baseline + 0.5 * (peak_value - local_baseline)
        if peak_value >= local_baseline:
            above = segment >= threshold
        else:
            above = segment <= threshold
        indices = np.where(above)[0]
        if indices.size > 0:
            widths.append((indices[-1] - indices[0] + 1) * 1000.0 / float(sample_rate_hz))
        amplitudes.append(amplitude)
    return widths, amplitudes


def extract_rhythm_feature_row(ecg_signal, sample_rate_hz=130):
    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    quality = evaluate_signal_quality(ecg, sample_rate_hz)
    filtered = bandpass_filter(ecg, sample_rate_hz)
    peaks = detect_r_peaks(filtered, sample_rate_hz)
    rr_ms = rr_intervals_ms_from_peaks(peaks, sample_rate_hz)
    valid_rr = rr_ms[(rr_ms >= 300) & (rr_ms <= 2000)]

    row = {feature: 0.0 for feature in RHYTHM_FEATURE_COLUMNS}
    row["signal_quality_score"] = _safe_float(quality.get("score", 0.0))
    row["r_peak_count"] = _safe_float(len(peaks))
    row["rr_count"] = _safe_float(rr_ms.size)
    row["valid_rr_ratio"] = _safe_float(valid_rr.size / rr_ms.size) if rr_ms.size else 0.0
    row["ecg_mean"] = _safe_float(np.mean(ecg)) if ecg.size else 0.0
    row["ecg_std"] = _safe_float(np.std(ecg)) if ecg.size else 0.0
    row["ecg_iqr"] = _iqr(ecg)
    row["ecg_range"] = _safe_float(np.max(ecg) - np.min(ecg)) if ecg.size else 0.0
    row["ecg_skewness"] = _skewness(ecg)
    row["ecg_kurtosis"] = _kurtosis(ecg)
    row["ecg_energy"] = _safe_float(np.mean(ecg**2)) if ecg.size else 0.0
    row["line_length"] = _safe_float(np.sum(np.abs(np.diff(ecg))) / ecg.size) if ecg.size > 1 else 0.0
    row["zero_crossing_rate"] = _zero_crossing_rate(ecg)
    row.update(_spectral_features(ecg, sample_rate_hz))

    if valid_rr.size >= 2:
        hr = 60000.0 / valid_rr
        diff_rr = np.diff(valid_rr)
        median_rr = float(np.median(valid_rr))
        rr_outlier_ratio = (
            float(np.mean(np.abs(valid_rr - median_rr) / median_rr > 0.25)) if median_rr > 0 else 0.0
        )
        row.update(
            {
                "mean_hr": _safe_float(np.mean(hr)),
                "median_hr": _safe_float(np.median(hr)),
                "min_hr": _safe_float(np.min(hr)),
                "max_hr": _safe_float(np.max(hr)),
                "heart_rate_range": _safe_float(np.max(hr) - np.min(hr)),
                "heart_rate_std": _safe_float(np.std(hr)),
                "mean_rr": _safe_float(np.mean(valid_rr)),
                "median_rr": _safe_float(median_rr),
                "min_rr": _safe_float(np.min(valid_rr)),
                "max_rr": _safe_float(np.max(valid_rr)),
                "std_rr": _safe_float(np.std(valid_rr)),
                "rr_iqr": _iqr(valid_rr),
                "rr_range": _safe_float(np.max(valid_rr) - np.min(valid_rr)),
                "rmssd": _safe_float(np.sqrt(np.mean(diff_rr**2))) if diff_rr.size else 0.0,
                "sdnn": _safe_float(np.std(valid_rr)),
                "pnn50": _safe_float(100.0 * np.mean(np.abs(diff_rr) > 50.0)) if diff_rr.size else 0.0,
                "rr_diff_mean_abs": _safe_float(np.mean(np.abs(diff_rr))) if diff_rr.size else 0.0,
                "rr_diff_std": _safe_float(np.std(diff_rr)) if diff_rr.size else 0.0,
                "rr_irregularity_index": _safe_float(np.std(valid_rr) / np.mean(valid_rr))
                if np.mean(valid_rr) > 0
                else 0.0,
                "rr_outlier_ratio": _safe_float(rr_outlier_ratio),
                "sample_entropy": _sample_entropy(valid_rr),
                "turning_point_ratio": _turning_point_ratio(valid_rr),
            }
        )

    widths, amplitudes = _qrs_widths_and_amplitudes(filtered, peaks, sample_rate_hz)
    row["qrs_width_mean"] = _safe_float(np.mean(widths)) if widths else 0.0
    row["qrs_width_std"] = _safe_float(np.std(widths)) if widths else 0.0
    row["r_amplitude_mean"] = _safe_float(np.mean(amplitudes)) if amplitudes else 0.0
    row["r_amplitude_std"] = _safe_float(np.std(amplitudes)) if amplitudes else 0.0
    return row


def extract_rhythm_feature_matrix(ecg_windows, sample_rate_hz=130, feature_columns=None):
    columns = list(feature_columns or RHYTHM_FEATURE_COLUMNS)
    rows = [extract_rhythm_feature_row(window, sample_rate_hz=sample_rate_hz) for window in ecg_windows]
    matrix = np.asarray([[row.get(column, 0.0) for column in columns] for row in rows], dtype=float)
    return matrix, rows
