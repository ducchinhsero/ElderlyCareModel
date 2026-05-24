import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.io import loadmat

from src.preprocessing import (
    RHYTHM_LABELS,
    SAMPLES_PER_WINDOW,
    TARGET_SAMPLE_RATE_HZ,
    WINDOW_SECONDS,
    encode_rhythm_label,
    normalize_ecg,
    resample_ecg,
    save_json,
    split_into_windows,
)


DEFAULT_INPUT_DIR = "data_raw/cinc2017"
DEFAULT_OUTPUT_DIR = "data_processed/rhythm"
DEFAULT_REFERENCE_CANDIDATES = (
    "REFERENCE-v3.csv",
    "REFERENCE-v2.csv",
    "REFERENCE-v1.csv",
    "REFERENCE.csv",
    "REFERENCE-original.csv",
)


def find_reference_file(input_dir):
    input_path = Path(input_dir)
    for candidate in DEFAULT_REFERENCE_CANDIDATES:
        path = input_path / candidate
        if path.exists():
            return path
    matches = sorted(input_path.glob("REFERENCE*.csv"))
    if matches:
        return matches[0]
    raise FileNotFoundError(
        f"No REFERENCE*.csv file found in {input_path}. "
        "Place PhysioNet/CinC 2017 files under data_raw/cinc2017."
    )


def read_reference(reference_path):
    df = pd.read_csv(reference_path, header=None, names=["record_id", "raw_label"])
    df = df.dropna(subset=["record_id", "raw_label"])
    df["record_id"] = df["record_id"].astype(str).str.strip()
    df["raw_label"] = df["raw_label"].astype(str).str.strip()
    df = df[df["record_id"].str.len() > 0]
    return df.reset_index(drop=True)


def read_source_sample_rate(header_path, default_rate_hz=300):
    if not Path(header_path).exists():
        return float(default_rate_hz)
    first_line = Path(header_path).read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    parts = first_line.split()
    if len(parts) >= 3:
        try:
            return float(parts[2])
        except ValueError:
            return float(default_rate_hz)
    return float(default_rate_hz)


def read_mat_ecg(mat_path):
    payload = loadmat(mat_path)
    if "val" in payload:
        values = payload["val"]
    else:
        candidates = [
            value
            for key, value in payload.items()
            if not key.startswith("__") and isinstance(value, np.ndarray) and value.size > 0
        ]
        if not candidates:
            raise ValueError(f"No ECG array found in {mat_path}")
        values = candidates[0]

    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        return values
    return values[0].flatten()


def build_cinc2017_dataset(
    input_dir=DEFAULT_INPUT_DIR,
    output_dir=DEFAULT_OUTPUT_DIR,
    reference_file=None,
    target_sample_rate_hz=TARGET_SAMPLE_RATE_HZ,
    window_seconds=WINDOW_SECONDS,
):
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    reference_path = Path(reference_file) if reference_file else find_reference_file(input_path)
    records = read_reference(reference_path)
    samples_per_window = int(round(float(target_sample_rate_hz) * float(window_seconds)))

    X = []
    y = []
    metadata_rows = []
    missing_records = []

    for _, row in records.iterrows():
        record_id = row["record_id"]
        raw_label = row["raw_label"]
        mat_path = input_path / f"{record_id}.mat"
        header_path = input_path / f"{record_id}.hea"
        if not mat_path.exists():
            missing_records.append(record_id)
            continue

        class_id = encode_rhythm_label(raw_label)
        source_sample_rate_hz = read_source_sample_rate(header_path)
        source_ecg = read_mat_ecg(mat_path)
        resampled = resample_ecg(source_ecg, source_sample_rate_hz, target_sample_rate_hz)
        normalized = normalize_ecg(resampled)

        for window_index, (start_sample, window, padded) in enumerate(
            split_into_windows(normalized, samples_per_window=samples_per_window, include_partial=True)
        ):
            X.append(window.astype(np.float32))
            y.append(class_id)
            metadata_rows.append(
                {
                    "record_id": record_id,
                    "raw_label": raw_label,
                    "class_id": int(class_id),
                    "label": RHYTHM_LABELS[int(class_id)],
                    "window_index": int(window_index),
                    "target_start_sample": int(start_sample),
                    "target_start_seconds": float(start_sample / float(target_sample_rate_hz)),
                    "target_sample_rate_hz": float(target_sample_rate_hz),
                    "source_sample_rate_hz": float(source_sample_rate_hz),
                    "source_sample_count": int(len(source_ecg)),
                    "target_sample_count": int(len(resampled)),
                    "samples_per_window": int(samples_per_window),
                    "padded": bool(padded),
                }
            )

    if not X:
        raise ValueError(
            f"No CinC 2017 windows were generated from {input_path}. "
            "Check that .mat/.hea files and REFERENCE.csv are present."
        )

    output_path.mkdir(parents=True, exist_ok=True)
    X_array = np.vstack([window.reshape(1, -1) for window in X]).astype(np.float32)
    y_array = np.asarray(y, dtype=np.int64)
    metadata = pd.DataFrame(metadata_rows)

    np.save(output_path / "X.npy", X_array)
    np.save(output_path / "y.npy", y_array)
    metadata.to_csv(output_path / "metadata.csv", index=False)
    save_json(
        output_path / "label_map.json",
        {
            "labels": {str(key): value for key, value in RHYTHM_LABELS.items()},
            "target_sample_rate_hz": float(target_sample_rate_hz),
            "window_seconds": float(window_seconds),
            "samples_per_window": int(samples_per_window),
            "source": "PhysioNet/CinC Challenge 2017",
        },
    )

    summary = {
        "output_dir": str(output_path),
        "X_shape": list(X_array.shape),
        "y_shape": list(y_array.shape),
        "label_distribution": {
            RHYTHM_LABELS[int(class_id)]: int(count)
            for class_id, count in zip(*np.unique(y_array, return_counts=True))
        },
        "missing_record_count": len(missing_records),
        "missing_records_preview": missing_records[:10],
    }
    save_json(output_path / "build_summary.json", summary)
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="Build 130 Hz / 30s rhythm windows from CinC 2017.")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reference-file", default=None)
    parser.add_argument("--target-sample-rate-hz", type=float, default=TARGET_SAMPLE_RATE_HZ)
    parser.add_argument("--window-seconds", type=float, default=WINDOW_SECONDS)
    return parser.parse_args()


def main():
    args = parse_args()
    summary = build_cinc2017_dataset(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        reference_file=args.reference_file,
        target_sample_rate_hz=args.target_sample_rate_hz,
        window_seconds=args.window_seconds,
    )
    print("CinC 2017 rhythm dataset built.")
    print(summary)


if __name__ == "__main__":
    main()
