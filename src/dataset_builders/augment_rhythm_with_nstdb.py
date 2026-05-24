import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.preprocessing import (
    RHYTHM_LABEL_MAP,
    TARGET_SAMPLE_RATE_HZ,
    normalize_ecg,
    resample_ecg,
    save_json,
    split_into_windows,
)


DEFAULT_INPUT_DIR = "data_processed/rhythm"
DEFAULT_NSTDB_DIR = "data_raw/nstdb"
DEFAULT_OUTPUT_DIR = "data_processed/rhythm_nstdb_augmented"
DEFAULT_NOISE_RECORDS = ("bw", "em", "ma")


def _load_wfdb():
    try:
        import wfdb
    except ImportError as exc:
        raise ImportError(
            "wfdb is required to read MIT-BIH Noise Stress Test Database files. "
            "Install dependencies with: python -m pip install -r requirements.txt"
        ) from exc
    return wfdb


def _read_wfdb_record(record_base_path):
    wfdb = _load_wfdb()
    record = wfdb.rdrecord(str(record_base_path))
    signal = np.asarray(record.p_signal, dtype=float)
    if signal.ndim == 2:
        signal = signal[:, 0]
    return signal.flatten(), float(record.fs)


def _load_noise_windows(nstdb_dir, noise_records, target_sample_rate_hz, samples_per_window):
    windows = []
    metadata = []
    for record_name in noise_records:
        record_base = Path(nstdb_dir) / record_name
        if not (record_base.with_suffix(".dat").exists() and record_base.with_suffix(".hea").exists()):
            continue
        signal, source_rate_hz = _read_wfdb_record(record_base)
        resampled = resample_ecg(signal, source_rate_hz=source_rate_hz, target_rate_hz=target_sample_rate_hz)
        normalized = normalize_ecg(resampled)
        for window_index, (start_sample, window, padded) in enumerate(
            split_into_windows(normalized, samples_per_window=samples_per_window, include_partial=False)
        ):
            windows.append(window.astype(np.float32))
            metadata.append(
                {
                    "noise_record": record_name,
                    "noise_window_index": int(window_index),
                    "noise_start_sample": int(start_sample),
                    "noise_source_sample_rate_hz": float(source_rate_hz),
                    "noise_padded": bool(padded),
                }
            )
    if not windows:
        raise ValueError(
            f"No NSTDB noise windows generated from {nstdb_dir}. "
            "Expected records such as bw.dat/bw.hea, em.dat/em.hea, ma.dat/ma.hea."
        )
    return np.asarray(windows, dtype=np.float32), metadata


def _mix_at_snr(clean_window, noise_window, snr_db):
    clean = np.asarray(clean_window, dtype=float)
    noise = np.asarray(noise_window, dtype=float)
    clean_power = float(np.mean(clean**2))
    noise_power = float(np.mean(noise**2))
    if noise_power <= 1e-12:
        return clean.astype(np.float32)
    target_noise_power = clean_power / (10.0 ** (float(snr_db) / 10.0))
    scaled_noise = noise * np.sqrt(target_noise_power / noise_power)
    return normalize_ecg(clean + scaled_noise).astype(np.float32)


def augment_rhythm_with_nstdb(
    input_dir=DEFAULT_INPUT_DIR,
    nstdb_dir=DEFAULT_NSTDB_DIR,
    output_dir=DEFAULT_OUTPUT_DIR,
    noise_records=DEFAULT_NOISE_RECORDS,
    augmented_count=1600,
    snr_db_values=(-3.0, 0.0, 3.0),
    random_state=42,
    target_sample_rate_hz=TARGET_SAMPLE_RATE_HZ,
):
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    X_path = input_path / "X.npy"
    y_path = input_path / "y.npy"
    metadata_path = input_path / "metadata.csv"
    if not X_path.exists() or not y_path.exists():
        raise FileNotFoundError(f"Missing {X_path} or {y_path}. Build CinC 2017 dataset first.")

    X = np.load(X_path)
    y = np.load(y_path)
    metadata = pd.read_csv(metadata_path) if metadata_path.exists() else pd.DataFrame(index=np.arange(len(y)))
    samples_per_window = int(X.shape[1])
    noise_windows, noise_metadata = _load_noise_windows(
        nstdb_dir,
        noise_records=noise_records,
        target_sample_rate_hz=target_sample_rate_hz,
        samples_per_window=samples_per_window,
    )

    rng = np.random.default_rng(random_state)
    clean_indices = np.where(y != RHYTHM_LABEL_MAP["noise"])[0]
    if clean_indices.size == 0:
        raise ValueError("No clean source windows available for NSTDB augmentation.")

    augmented_windows = []
    augmented_rows = []
    snr_values = list(float(value) for value in snr_db_values)
    for index in range(int(augmented_count)):
        clean_index = int(rng.choice(clean_indices))
        noise_index = int(rng.integers(0, len(noise_windows)))
        snr_db = float(rng.choice(snr_values))
        mixed = _mix_at_snr(X[clean_index], noise_windows[noise_index], snr_db=snr_db)
        augmented_windows.append(mixed)
        source_row = metadata.iloc[clean_index].to_dict() if len(metadata) == len(y) else {}
        noise_row = noise_metadata[noise_index]
        augmented_rows.append(
            {
                "record_id": f"nstdb_aug_{index:06d}",
                "raw_label": "~",
                "class_id": RHYTHM_LABEL_MAP["noise"],
                "label": "noise",
                "window_index": 0,
                "target_start_sample": 0,
                "target_start_seconds": 0.0,
                "target_sample_rate_hz": float(target_sample_rate_hz),
                "source_sample_rate_hz": float(target_sample_rate_hz),
                "source_sample_count": int(samples_per_window),
                "target_sample_count": int(samples_per_window),
                "samples_per_window": int(samples_per_window),
                "padded": False,
                "augmentation": "nstdb_noise_mix",
                "snr_db": snr_db,
                "source_record_id": source_row.get("record_id"),
                "source_label": source_row.get("label"),
                **noise_row,
            }
        )

    X_aug = np.vstack([X, np.asarray(augmented_windows, dtype=np.float32)])
    y_aug = np.concatenate([y, np.full(len(augmented_windows), RHYTHM_LABEL_MAP["noise"], dtype=y.dtype)])
    metadata_aug = pd.concat([metadata, pd.DataFrame(augmented_rows)], ignore_index=True)

    output_path.mkdir(parents=True, exist_ok=True)
    np.save(output_path / "X.npy", X_aug.astype(np.float32))
    np.save(output_path / "y.npy", y_aug)
    metadata_aug.to_csv(output_path / "metadata.csv", index=False)

    labels, counts = np.unique(y_aug, return_counts=True)
    summary = {
        "input_dir": str(input_path),
        "nstdb_dir": str(nstdb_dir),
        "output_dir": str(output_path),
        "X_shape": list(X_aug.shape),
        "y_shape": list(y_aug.shape),
        "augmented_noise_windows": int(len(augmented_windows)),
        "noise_records": list(noise_records),
        "snr_db_values": snr_values,
        "label_distribution": {
            str(int(label)): int(count) for label, count in zip(labels, counts)
        },
    }
    save_json(output_path / "augmentation_summary.json", summary)
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="Augment rhythm dataset with NSTDB noise windows.")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--nstdb-dir", default=DEFAULT_NSTDB_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--augmented-count", type=int, default=1600)
    parser.add_argument("--snr-db", type=float, nargs="+", default=[-3.0, 0.0, 3.0])
    parser.add_argument("--noise-records", nargs="+", default=list(DEFAULT_NOISE_RECORDS))
    return parser.parse_args()


def main():
    args = parse_args()
    summary = augment_rhythm_with_nstdb(
        input_dir=args.input_dir,
        nstdb_dir=args.nstdb_dir,
        output_dir=args.output_dir,
        noise_records=args.noise_records,
        augmented_count=args.augmented_count,
        snr_db_values=args.snr_db,
    )
    print("NSTDB augmentation complete.")
    print(summary)


if __name__ == "__main__":
    main()
