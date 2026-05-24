import numpy as np

from src.features.ecg_features import bandpass_filter, detect_r_peaks, rr_intervals_ms_from_peaks
from src.features.rhythm_features import RHYTHM_FEATURE_COLUMNS, extract_rhythm_feature_row


ECTOPY_LABELS = {
    0: "normal",
    1: "pvc",
    2: "pac",
    3: "mixed_ectopic",
    4: "other",
}
ECTOPY_LABEL_MAP = {label: class_id for class_id, label in ECTOPY_LABELS.items()}

PVC_SYMBOLS = {"V", "E"}
PAC_SYMBOLS = {"A", "a", "J", "S"}
NORMAL_SYMBOLS = {"N", "L", "R", "e", "j"}
IGNORED_SYMBOLS = {"+", "~", "|", "x", "[", "]", "!", '"', "(", ")"}

ECTOPY_FEATURE_COLUMNS = list(RHYTHM_FEATURE_COLUMNS) + [
    "premature_rr_ratio",
    "compensatory_pause_ratio",
    "short_long_rr_pair_ratio",
    "qrs_width_outlier_ratio",
    "r_amplitude_outlier_ratio",
    "pvc_like_ratio",
    "pac_like_ratio",
]


def classify_beat_symbol(symbol):
    symbol = str(symbol).strip()
    if symbol in PVC_SYMBOLS:
        return "pvc"
    if symbol in PAC_SYMBOLS:
        return "pac"
    if symbol in NORMAL_SYMBOLS:
        return "normal"
    if symbol in IGNORED_SYMBOLS or not symbol:
        return "ignored"
    return "other"


def label_window_from_symbols(symbols):
    counts = {"normal": 0, "pvc": 0, "pac": 0, "other": 0, "ignored": 0}
    for symbol in symbols:
        category = classify_beat_symbol(symbol)
        counts[category] = counts.get(category, 0) + 1

    if counts["pvc"] > 0 and counts["pac"] > 0:
        label = "mixed_ectopic"
    elif counts["pvc"] > 0:
        label = "pvc"
    elif counts["pac"] > 0:
        label = "pac"
    elif counts["other"] > 0:
        label = "other"
    else:
        label = "normal"
    return ECTOPY_LABEL_MAP[label], label, counts


def _safe_ratio(mask):
    mask = np.asarray(mask, dtype=bool)
    if mask.size == 0:
        return 0.0
    return float(np.mean(mask))


def _qrs_widths_and_amplitudes(filtered_ecg, peaks, sample_rate_hz):
    ecg = np.asarray(filtered_ecg, dtype=float).flatten()
    widths = []
    amplitudes = []
    half_window = int(0.12 * float(sample_rate_hz))
    for peak in np.asarray(peaks, dtype=int).flatten():
        start = max(0, peak - half_window)
        end = min(ecg.size, peak + half_window + 1)
        segment = ecg[start:end]
        if segment.size < 3:
            continue
        baseline = float(np.median(segment))
        peak_value = float(ecg[peak])
        amplitude = abs(peak_value - baseline)
        if amplitude <= 1e-12:
            continue
        threshold = baseline + 0.5 * (peak_value - baseline)
        above = segment >= threshold if peak_value >= baseline else segment <= threshold
        indices = np.where(above)[0]
        if indices.size:
            widths.append((indices[-1] - indices[0] + 1) * 1000.0 / float(sample_rate_hz))
        amplitudes.append(amplitude)
    return np.asarray(widths, dtype=float), np.asarray(amplitudes, dtype=float)


def extract_ectopy_feature_row(ecg_signal, sample_rate_hz=130):
    row = extract_rhythm_feature_row(ecg_signal, sample_rate_hz=sample_rate_hz)
    for column in ECTOPY_FEATURE_COLUMNS:
        row.setdefault(column, 0.0)

    ecg = np.asarray(ecg_signal, dtype=float).flatten()
    if ecg.size < 3:
        return row

    filtered = bandpass_filter(ecg, sample_rate_hz)
    peaks = detect_r_peaks(filtered, sample_rate_hz)
    rr_ms = rr_intervals_ms_from_peaks(peaks, sample_rate_hz)
    valid_rr = rr_ms[(rr_ms >= 300) & (rr_ms <= 2000)]
    if valid_rr.size >= 3:
        median_rr = float(np.median(valid_rr))
        premature = valid_rr < 0.80 * median_rr
        compensatory = valid_rr > 1.20 * median_rr
        short_long_pairs = premature[:-1] & compensatory[1:]
        row["premature_rr_ratio"] = _safe_ratio(premature)
        row["compensatory_pause_ratio"] = _safe_ratio(compensatory)
        row["short_long_rr_pair_ratio"] = _safe_ratio(short_long_pairs)

    widths, amplitudes = _qrs_widths_and_amplitudes(filtered, peaks, sample_rate_hz)
    width_outliers = np.asarray([], dtype=bool)
    amp_outliers = np.asarray([], dtype=bool)
    if widths.size >= 3:
        median_width = float(np.median(widths))
        width_outliers = widths > max(110.0, 1.35 * median_width)
        row["qrs_width_outlier_ratio"] = _safe_ratio(width_outliers)
    if amplitudes.size >= 3:
        median_amp = float(np.median(amplitudes))
        amp_outliers = np.abs(amplitudes - median_amp) > 0.45 * max(abs(median_amp), 1e-9)
        row["r_amplitude_outlier_ratio"] = _safe_ratio(amp_outliers)

    premature_ratio = float(row.get("premature_rr_ratio") or 0.0)
    wide_ratio = float(row.get("qrs_width_outlier_ratio") or 0.0)
    amp_ratio = float(row.get("r_amplitude_outlier_ratio") or 0.0)
    pause_ratio = float(row.get("compensatory_pause_ratio") or 0.0)
    row["pvc_like_ratio"] = float(min(1.0, 0.45 * premature_ratio + 0.25 * wide_ratio + 0.2 * pause_ratio + 0.1 * amp_ratio))
    row["pac_like_ratio"] = float(min(1.0, 0.65 * premature_ratio + 0.2 * (1.0 - wide_ratio) + 0.15 * amp_ratio))
    return row


def extract_ectopy_feature_matrix(ecg_windows, sample_rate_hz=130, feature_columns=None):
    columns = list(feature_columns or ECTOPY_FEATURE_COLUMNS)
    rows = [extract_ectopy_feature_row(window, sample_rate_hz=sample_rate_hz) for window in ecg_windows]
    matrix = np.asarray([[row.get(column, 0.0) for column in columns] for row in rows], dtype=float)
    return matrix, rows
