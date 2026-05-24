import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.features.ectopy_features import ECTOPY_LABELS, label_window_from_symbols
from src.preprocessing import TARGET_SAMPLE_RATE_HZ, WINDOW_SECONDS, normalize_ecg, resample_ecg, save_json, split_into_windows


DEFAULT_INPUT_DIR = "data_raw/mitdb"
DEFAULT_OUTPUT_DIR = "data_processed/mitdb_ectopy"


def _load_wfdb():
    try:
        import wfdb
    except ImportError as exc:
        raise ImportError(
            "wfdb is required to read MIT-BIH Arrhythmia files. "
            "Install dependencies with: python -m pip install -r requirements.txt"
        ) from exc
    return wfdb


def _read_records(input_dir):
    input_path = Path(input_dir)
    records_path = input_path / "RECORDS"
    if records_path.exists():
        return [
            line.strip()
            for line in records_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    return sorted(
        path.stem
        for path in input_path.glob("*.hea")
        if (input_path / f"{path.stem}.dat").exists()
    )


def _annotation_symbols_in_window(annotation, source_sample_rate_hz, start_seconds, end_seconds):
    samples = np.asarray(annotation.sample, dtype=float)
    symbols = np.asarray(annotation.symbol, dtype=str)
    seconds = samples / float(source_sample_rate_hz)
    mask = (seconds >= float(start_seconds)) & (seconds < float(end_seconds))
    return symbols[mask].tolist()


def build_mitdb_ectopy_dataset(
    input_dir=DEFAULT_INPUT_DIR,
    output_dir=DEFAULT_OUTPUT_DIR,
    target_sample_rate_hz=TARGET_SAMPLE_RATE_HZ,
    window_seconds=WINDOW_SECONDS,
    max_records=None,
    include_other=True,
):
    wfdb = _load_wfdb()
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    records = _read_records(input_path)
    if max_records is not None:
        records = records[: int(max_records)]

    samples_per_window = int(round(float(target_sample_rate_hz) * float(window_seconds)))
    X = []
    y = []
    metadata_rows = []
    skipped = []

    for record_id in records:
        record_base = input_path / record_id
        if not record_base.with_suffix(".dat").exists():
            skipped.append({"record_id": record_id, "reason": "missing .dat file"})
            continue
        try:
            record = wfdb.rdrecord(str(record_base))
            annotation = wfdb.rdann(str(record_base), "atr")
        except Exception as exc:
            skipped.append({"record_id": record_id, "reason": str(exc)})
            continue

        signal = np.asarray(record.p_signal, dtype=float)
        if signal.ndim == 2:
            signal = signal[:, 0]
        source_sample_rate_hz = float(record.fs)
        resampled = resample_ecg(signal, source_sample_rate_hz, target_sample_rate_hz)
        normalized = normalize_ecg(resampled)

        for window_index, (start_sample, window, padded) in enumerate(
            split_into_windows(normalized, samples_per_window=samples_per_window, include_partial=False)
        ):
            start_seconds = float(start_sample / float(target_sample_rate_hz))
            end_seconds = start_seconds + float(window_seconds)
            symbols = _annotation_symbols_in_window(
                annotation,
                source_sample_rate_hz,
                start_seconds,
                end_seconds,
            )
            class_id, label, counts = label_window_from_symbols(symbols)
            if label == "other" and not include_other:
                continue
            X.append(window.astype(np.float32))
            y.append(class_id)
            metadata_rows.append(
                {
                    "record_id": record_id,
                    "window_index": int(window_index),
                    "class_id": int(class_id),
                    "label": label,
                    "normal_count": int(counts.get("normal", 0)),
                    "pvc_count": int(counts.get("pvc", 0)),
                    "pac_count": int(counts.get("pac", 0)),
                    "other_count": int(counts.get("other", 0)),
                    "ignored_count": int(counts.get("ignored", 0)),
                    "beat_count": int(len(symbols)),
                    "target_start_sample": int(start_sample),
                    "target_start_seconds": start_seconds,
                    "target_sample_rate_hz": float(target_sample_rate_hz),
                    "source_sample_rate_hz": source_sample_rate_hz,
                    "samples_per_window": int(samples_per_window),
                    "padded": bool(padded),
                }
            )

    if not X:
        raise ValueError(f"No MITDB ectopy windows generated from {input_path}. Skipped: {skipped[:5]}")

    output_path.mkdir(parents=True, exist_ok=True)
    X_array = np.vstack([window.reshape(1, -1) for window in X]).astype(np.float32)
    y_array = np.asarray(y, dtype=np.int64)
    metadata = pd.DataFrame(metadata_rows)
    np.save(output_path / "X.npy", X_array)
    np.save(output_path / "y.npy", y_array)
    metadata.to_csv(output_path / "metadata.csv", index=False)

    labels, counts = np.unique(y_array, return_counts=True)
    summary = {
        "input_dir": str(input_path),
        "output_dir": str(output_path),
        "records_requested": len(records),
        "records_skipped": skipped,
        "X_shape": list(X_array.shape),
        "y_shape": list(y_array.shape),
        "label_distribution": {
            ECTOPY_LABELS[int(label)]: int(count)
            for label, count in zip(labels, counts)
        },
        "target_sample_rate_hz": float(target_sample_rate_hz),
        "window_seconds": float(window_seconds),
        "samples_per_window": int(samples_per_window),
        "include_other": bool(include_other),
    }
    save_json(output_path / "label_map.json", {"labels": {str(k): v for k, v in ECTOPY_LABELS.items()}})
    save_json(output_path / "build_summary.json", summary)
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="Build MIT-BIH Arrhythmia PVC/PAC window dataset.")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-sample-rate-hz", type=float, default=TARGET_SAMPLE_RATE_HZ)
    parser.add_argument("--window-seconds", type=float, default=WINDOW_SECONDS)
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--exclude-other", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    summary = build_mitdb_ectopy_dataset(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        target_sample_rate_hz=args.target_sample_rate_hz,
        window_seconds=args.window_seconds,
        max_records=args.max_records,
        include_other=not args.exclude_other,
    )
    print("MITDB ectopy dataset built.")
    print(summary)


if __name__ == "__main__":
    main()
