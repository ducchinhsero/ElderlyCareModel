import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.preprocessing import (
    RHYTHM_LABEL_MAP,
    SAMPLES_PER_WINDOW,
    TARGET_SAMPLE_RATE_HZ,
    normalize_ecg,
    resample_ecg,
    save_json,
    split_into_windows,
)


DEFAULT_INPUT_DIR = "data_raw/afdb"
DEFAULT_OUTPUT_DIR = "data_processed/afdb_windows"


def _load_wfdb():
    try:
        import wfdb
    except ImportError as exc:
        raise ImportError(
            "wfdb is required to read AFDB files. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc
    return wfdb


def _read_records_file(input_dir):
    records_path = Path(input_dir) / "RECORDS"
    if not records_path.exists():
        return sorted(path.stem for path in Path(input_dir).glob("*.hea") if (Path(input_dir) / f"{path.stem}.dat").exists())
    return [
        line.strip()
        for line in records_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _is_afib_note(note):
    note = (note or "").upper()
    return "AFIB" in note


def _rhythm_intervals_seconds(annotation, record_duration_seconds, sample_rate_hz):
    intervals = []
    samples = np.asarray(annotation.sample, dtype=int)
    notes = list(getattr(annotation, "aux_note", []) or [])
    for index, note in enumerate(notes):
        if not str(note).startswith("("):
            continue
        start = float(samples[index] / sample_rate_hz)
        end = (
            float(samples[index + 1] / sample_rate_hz)
            if index + 1 < len(samples)
            else float(record_duration_seconds)
        )
        if end <= start:
            continue
        intervals.append(
            {
                "start_seconds": start,
                "end_seconds": end,
                "rhythm_note": str(note),
                "is_afib": _is_afib_note(note),
            }
        )
    return intervals


def _afib_fraction_for_window(start_seconds, end_seconds, intervals):
    duration = max(float(end_seconds) - float(start_seconds), 1e-9)
    overlap = 0.0
    for interval in intervals:
        if not interval["is_afib"]:
            continue
        overlap_start = max(float(start_seconds), float(interval["start_seconds"]))
        overlap_end = min(float(end_seconds), float(interval["end_seconds"]))
        if overlap_end > overlap_start:
            overlap += overlap_end - overlap_start
    return float(overlap / duration)


def build_afdb_dataset(
    input_dir=DEFAULT_INPUT_DIR,
    output_dir=DEFAULT_OUTPUT_DIR,
    target_sample_rate_hz=TARGET_SAMPLE_RATE_HZ,
    window_seconds=30.0,
    afib_fraction_threshold=0.5,
    max_records=None,
):
    wfdb = _load_wfdb()
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    records = _read_records_file(input_path)
    if max_records is not None:
        records = records[: int(max_records)]

    samples_per_window = int(round(float(target_sample_rate_hz) * float(window_seconds)))
    X = []
    y = []
    metadata_rows = []
    episode_rows = []
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
        duration_seconds = float(len(signal) / source_sample_rate_hz)
        intervals = _rhythm_intervals_seconds(annotation, duration_seconds, source_sample_rate_hz)
        for interval_index, interval in enumerate(intervals):
            if interval["is_afib"]:
                episode_rows.append(
                    {
                        "record_id": record_id,
                        "episode_index": int(interval_index),
                        "start_seconds": interval["start_seconds"],
                        "end_seconds": interval["end_seconds"],
                        "duration_seconds": interval["end_seconds"] - interval["start_seconds"],
                        "rhythm_note": interval["rhythm_note"],
                    }
                )

        resampled = resample_ecg(signal, source_sample_rate_hz, target_sample_rate_hz)
        normalized = normalize_ecg(resampled)
        for window_index, (start_sample, window, padded) in enumerate(
            split_into_windows(normalized, samples_per_window=samples_per_window, include_partial=False)
        ):
            start_seconds = float(start_sample / float(target_sample_rate_hz))
            end_seconds = start_seconds + float(window_seconds)
            afib_fraction = _afib_fraction_for_window(start_seconds, end_seconds, intervals)
            class_id = (
                RHYTHM_LABEL_MAP["possible_afib"]
                if afib_fraction >= float(afib_fraction_threshold)
                else RHYTHM_LABEL_MAP["normal"]
            )
            X.append(window.astype(np.float32))
            y.append(class_id)
            metadata_rows.append(
                {
                    "record_id": record_id,
                    "window_index": int(window_index),
                    "class_id": int(class_id),
                    "label": "possible_afib" if class_id == RHYTHM_LABEL_MAP["possible_afib"] else "normal",
                    "afib_fraction": float(afib_fraction),
                    "target_start_sample": int(start_sample),
                    "target_start_seconds": start_seconds,
                    "target_sample_rate_hz": float(target_sample_rate_hz),
                    "source_sample_rate_hz": source_sample_rate_hz,
                    "samples_per_window": int(samples_per_window),
                    "padded": bool(padded),
                }
            )

    if not X:
        raise ValueError(f"No AFDB windows generated from {input_path}. Skipped: {skipped[:5]}")

    output_path.mkdir(parents=True, exist_ok=True)
    X_array = np.vstack([window.reshape(1, -1) for window in X]).astype(np.float32)
    y_array = np.asarray(y, dtype=np.int64)
    metadata = pd.DataFrame(metadata_rows)
    episodes = pd.DataFrame(episode_rows)
    np.save(output_path / "X_windows.npy", X_array)
    np.save(output_path / "y_windows.npy", y_array)
    metadata.to_csv(output_path / "metadata.csv", index=False)
    episodes.to_csv(output_path / "episode_metadata.csv", index=False)

    labels, counts = np.unique(y_array, return_counts=True)
    summary = {
        "input_dir": str(input_path),
        "output_dir": str(output_path),
        "records_requested": len(records),
        "records_skipped": skipped,
        "X_shape": list(X_array.shape),
        "y_shape": list(y_array.shape),
        "episode_count": int(len(episodes)),
        "label_distribution": {str(int(label)): int(count) for label, count in zip(labels, counts)},
        "target_sample_rate_hz": float(target_sample_rate_hz),
        "window_seconds": float(window_seconds),
        "samples_per_window": int(samples_per_window),
        "afib_fraction_threshold": float(afib_fraction_threshold),
    }
    save_json(output_path / "build_summary.json", summary)
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="Build AFDB 30s windows for long-term AF evaluation.")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-sample-rate-hz", type=float, default=TARGET_SAMPLE_RATE_HZ)
    parser.add_argument("--window-seconds", type=float, default=30.0)
    parser.add_argument("--afib-fraction-threshold", type=float, default=0.5)
    parser.add_argument("--max-records", type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    summary = build_afdb_dataset(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        target_sample_rate_hz=args.target_sample_rate_hz,
        window_seconds=args.window_seconds,
        afib_fraction_threshold=args.afib_fraction_threshold,
        max_records=args.max_records,
    )
    print("AFDB dataset built.")
    print(summary)


if __name__ == "__main__":
    main()
