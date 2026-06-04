import argparse
import asyncio
import csv
import json
import math
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from src.features.acc_features import TYPE_ACC, parse_acc_packet
from src.services.collect_real_data import (
    ACC_STOP_CMD,
    DEFAULT_ACC_RANGE_G,
    DEFAULT_ACC_SAMPLE_RATE_HZ,
    ECG_START_CMD,
    ECG_STOP_CMD,
    HR_UUID,
    PMD_CONTROL,
    PMD_DATA,
    POLAR_DEVICE_NAME,
    REALTIME_ECG_SAMPLE_RATE_HZ,
    SUPPORTED_ACC_RANGES_G,
    SUPPORTED_ACC_SAMPLE_RATES_HZ,
    TYPE_ECG,
    build_acc_start_cmd,
    find_polar_h10,
    parse_ecg_packet,
    parse_rr_packet,
)
from src.services.soak_test import generate_synthetic_acc, generate_synthetic_ecg

try:
    from bleak import BleakClient
except ImportError:
    BleakClient = None


DEFAULT_OUTPUT_ROOT = "data_raw/clinical_arrhythmia"
DEFAULT_DURATION_MINUTES = 60.0
DEFAULT_WINDOW_SECONDS = 30.0
DEFAULT_WARMUP_SECONDS = 60.0
MIN_CLINICAL_DURATION_MINUTES = 30.0
MAX_CLINICAL_DURATION_MINUTES = 120.0

CONDITION_GROUPS = (
    "confirmed_afib",
    "suspected_afib",
    "other_cardiac",
    "control",
    "unknown",
)
CLINICAL_SOURCES = (
    "doctor_confirmed",
    "holter_report",
    "ecg_12lead",
    "self_reported",
    "unknown",
)
WINDOW_RHYTHM_LABELS = (
    "unlabeled",
    "afib",
    "normal",
    "other_rhythm",
    "noise",
)
SESSION_CONTEXTS = ("rest_observation",)


def _safe_name(value):
    value = str(value or "unknown").strip()
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in value)


def _now_iso():
    return datetime.now().astimezone().isoformat()


def _visit_timestamp():
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def _format_exception(exc):
    text = str(exc)
    return f"{exc.__class__.__name__}({text})" if text else f"{exc.__class__.__name__}()"


@dataclass
class ClinicalCollectionConfig:
    participant_id: str
    condition_group: str
    clinical_source: str
    duration_minutes: float = DEFAULT_DURATION_MINUTES
    address: str | None = None
    scan_timeout: float = 20.0
    output_root: str = DEFAULT_OUTPUT_ROOT
    visit_id: str | None = None
    session_context: str = "rest_observation"
    window_rhythm_label: str = "unlabeled"
    condition_detail: str = ""
    operator_id: str = ""
    acc_sample_rate_hz: int = DEFAULT_ACC_SAMPLE_RATE_HZ
    acc_range_g: int = DEFAULT_ACC_RANGE_G
    warmup_seconds: float = DEFAULT_WARMUP_SECONDS
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    dry_run: bool = False
    allow_short_test: bool = False
    no_interactive_events: bool = False
    skip_quality_report: bool = False

    @property
    def duration_seconds(self):
        return float(self.duration_minutes) * 60.0

    @property
    def resolved_visit_id(self):
        return self.visit_id or f"visit_{_visit_timestamp()}"


def validate_duration_minutes(duration_minutes, allow_short_test=False):
    duration = float(duration_minutes)
    if duration <= 0:
        raise ValueError("duration-minutes must be positive.")
    if allow_short_test:
        return duration
    if duration < MIN_CLINICAL_DURATION_MINUTES or duration > MAX_CLINICAL_DURATION_MINUTES:
        raise ValueError(
            "duration-minutes must be between "
            f"{MIN_CLINICAL_DURATION_MINUTES:.0f} and {MAX_CLINICAL_DURATION_MINUTES:.0f}. "
            "Use --allow-short-test only for local dry runs."
        )
    return duration


def parse_event_command(command):
    text = str(command or "").strip()
    if not text:
        return None, None

    lower = text.lower()
    if lower == "stop":
        return "stop", None
    if lower.startswith("symptom "):
        label = _safe_name(text.split(" ", 1)[1].strip().lower())
        return None, {"event_type": "symptom", "label": label, "note": ""}
    if lower.startswith("activity "):
        label = _safe_name(text.split(" ", 1)[1].strip().lower())
        return None, {"event_type": "activity", "label": label, "note": ""}
    if lower.startswith("note "):
        note = text.split(" ", 1)[1].strip()
        return None, {"event_type": "note", "label": "operator_note", "note": note}
    return None, {"event_type": "note", "label": "unstructured", "note": text}


class ClinicalSessionWriter:
    def __init__(self, config: ClinicalCollectionConfig):
        self.config = config
        self.participant_id = _safe_name(config.participant_id)
        self.visit_id = _safe_name(config.resolved_visit_id)
        self.session_dir = Path(config.output_root) / self.participant_id / self.visit_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.started_unix = time.time()
        self.started_iso = _now_iso()
        self.ended_unix = None
        self.ended_iso = None
        self.ecg_sample_index = 0
        self.acc_sample_index = 0
        self.rr_index = 0
        self.event_index = 0
        self.last_flush_unix = self.started_unix
        self.lock = threading.Lock()

        self.ecg_file = (self.session_dir / "ecg.csv").open("w", newline="", encoding="utf-8")
        self.acc_file = (self.session_dir / "acc.csv").open("w", newline="", encoding="utf-8")
        self.rr_file = (self.session_dir / "rr.csv").open("w", newline="", encoding="utf-8")
        self.events_file = (self.session_dir / "events.csv").open("w", newline="", encoding="utf-8")

        self.ecg_writer = csv.writer(self.ecg_file)
        self.acc_writer = csv.writer(self.acc_file)
        self.rr_writer = csv.writer(self.rr_file)
        self.events_writer = csv.writer(self.events_file)
        self.ecg_writer.writerow(["sample_index", "timestamp_unix", "elapsed_seconds", "ecg_uv"])
        self.acc_writer.writerow(["sample_index", "timestamp_unix", "elapsed_seconds", "x_mg", "y_mg", "z_mg", "vm_mg"])
        self.rr_writer.writerow(["rr_index", "timestamp_unix", "elapsed_seconds", "rr_interval_ms"])
        self.events_writer.writerow(["event_id", "timestamp_unix", "elapsed_seconds", "event_type", "label", "note"])

    def _sample_timestamp(self, sample_index, sample_rate_hz):
        elapsed = float(sample_index) / float(sample_rate_hz)
        return self.started_unix + elapsed, elapsed

    def maybe_flush(self, force=False):
        now = time.time()
        if force or (now - self.last_flush_unix) >= 2.0:
            self.ecg_file.flush()
            self.acc_file.flush()
            self.rr_file.flush()
            self.events_file.flush()
            self.last_flush_unix = now

    def write_ecg_samples(self, samples):
        if not samples:
            return
        with self.lock:
            for value in samples:
                timestamp_unix, elapsed = self._sample_timestamp(
                    self.ecg_sample_index,
                    REALTIME_ECG_SAMPLE_RATE_HZ,
                )
                self.ecg_writer.writerow(
                    [self.ecg_sample_index, f"{timestamp_unix:.6f}", f"{elapsed:.6f}", int(value)]
                )
                self.ecg_sample_index += 1
            self.maybe_flush()

    def write_acc_samples(self, samples):
        if not samples:
            return
        with self.lock:
            for sample in samples:
                x, y, z, vm = sample
                timestamp_unix, elapsed = self._sample_timestamp(
                    self.acc_sample_index,
                    self.config.acc_sample_rate_hz,
                )
                self.acc_writer.writerow(
                    [
                        self.acc_sample_index,
                        f"{timestamp_unix:.6f}",
                        f"{elapsed:.6f}",
                        f"{float(x):.6f}",
                        f"{float(y):.6f}",
                        f"{float(z):.6f}",
                        f"{float(vm):.6f}",
                    ]
                )
                self.acc_sample_index += 1
            self.maybe_flush()

    def write_rr_intervals(self, intervals_ms):
        if not intervals_ms:
            return
        with self.lock:
            packet_unix = time.time()
            elapsed = packet_unix - self.started_unix
            for value in intervals_ms:
                self.rr_writer.writerow(
                    [self.rr_index, f"{packet_unix:.6f}", f"{elapsed:.6f}", f"{float(value):.6f}"]
                )
                self.rr_index += 1
            self.maybe_flush()

    def record_event(self, event_type, label, note=""):
        with self.lock:
            event_unix = time.time()
            elapsed = event_unix - self.started_unix
            event_id = f"evt_{self.event_index:05d}"
            self.events_writer.writerow(
                [
                    event_id,
                    f"{event_unix:.6f}",
                    f"{elapsed:.6f}",
                    str(event_type or "note"),
                    str(label or "unknown"),
                    str(note or ""),
                ]
            )
            self.event_index += 1
            self.maybe_flush(force=True)
            return event_id

    def write_segments(self):
        path = self.session_dir / "segments.csv"
        warmup_end = min(float(self.config.warmup_seconds), float(self.config.duration_seconds))
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["segment_id", "start_seconds", "end_seconds", "segment_type", "window_rhythm_label"])
            writer.writerow(["segment_000", "0.000", f"{warmup_end:.3f}", "warmup", "unlabeled"])
            if float(self.config.duration_seconds) > warmup_end:
                writer.writerow(
                    [
                        "segment_001",
                        f"{warmup_end:.3f}",
                        f"{float(self.config.duration_seconds):.3f}",
                        self.config.session_context,
                        self.config.window_rhythm_label,
                    ]
                )

    def write_metadata(self, status, stats, error=None):
        self.ended_unix = self.ended_unix or time.time()
        self.ended_iso = self.ended_iso or _now_iso()
        requested_duration = float(self.config.duration_seconds)
        actual_elapsed = max(0.0, self.ended_unix - self.started_unix)
        expected_ecg = max(1, int(round(requested_duration * REALTIME_ECG_SAMPLE_RATE_HZ)))
        expected_acc = max(1, int(round(requested_duration * int(self.config.acc_sample_rate_hz))))
        ecg_duration = self.ecg_sample_index / float(REALTIME_ECG_SAMPLE_RATE_HZ)
        acc_duration = self.acc_sample_index / float(self.config.acc_sample_rate_hz)
        metadata = {
            "participant_id": self.config.participant_id,
            "visit_id": self.visit_id,
            "condition_group": self.config.condition_group,
            "clinical_source": self.config.clinical_source,
            "condition_detail": self.config.condition_detail,
            "operator_id": self.config.operator_id,
            "session_context": self.config.session_context,
            "window_rhythm_label": self.config.window_rhythm_label,
            "status": status,
            "error": error,
            "device": POLAR_DEVICE_NAME,
            "device_address": self.config.address,
            "created_at": self.started_iso,
            "ended_at": self.ended_iso,
            "requested_duration_seconds": requested_duration,
            "actual_elapsed_seconds": actual_elapsed,
            "warmup_seconds": float(self.config.warmup_seconds),
            "ecg_sample_rate_hz": REALTIME_ECG_SAMPLE_RATE_HZ,
            "acc_sample_rate_hz": int(self.config.acc_sample_rate_hz),
            "acc_range_g": int(self.config.acc_range_g),
            "ecg_sample_count": int(self.ecg_sample_index),
            "acc_sample_count": int(self.acc_sample_index),
            "rr_interval_count": int(self.rr_index),
            "event_count": int(self.event_index),
            "ecg_duration_seconds": ecg_duration,
            "acc_duration_seconds": acc_duration,
            "ecg_sample_loss_ratio": max(0.0, 1.0 - (self.ecg_sample_index / expected_ecg)),
            "acc_sample_loss_ratio": max(0.0, 1.0 - (self.acc_sample_index / expected_acc)),
            "dry_run": bool(self.config.dry_run),
            "classification_guidance": {
                "session_condition_is_not_window_label": True,
                "do_not_label_entire_confirmed_afib_session_as_afib": True,
                "window_label_requires_time_aligned_clinical_annotation": True,
            },
            "files": {
                "ecg": str(self.session_dir / "ecg.csv"),
                "acc": str(self.session_dir / "acc.csv"),
                "rr": str(self.session_dir / "rr.csv"),
                "events": str(self.session_dir / "events.csv"),
                "segments": str(self.session_dir / "segments.csv"),
                "quality_report": str(self.session_dir / "quality_report.json"),
                "predictions_preview": str(self.session_dir / "predictions_preview.csv"),
            },
            "stats": stats,
            "notes": [
                "Use participant_id as an anonymous code, not a real name.",
                "This dataset is for screening/research analysis, not a standalone medical diagnosis.",
                "Window rhythm labels must remain unlabeled unless a time-aligned clinical source is available.",
            ],
        }
        (self.session_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return metadata

    def close(self):
        self.maybe_flush(force=True)
        self.ecg_file.close()
        self.acc_file.close()
        self.rr_file.close()
        self.events_file.close()


def _event_input_loop(writer: ClinicalSessionWriter, stop_requested: threading.Event):
    print("Event marker commands: symptom <label>, activity <label>, note <text>, stop")
    while not stop_requested.is_set():
        try:
            command = input("> ")
        except EOFError:
            return
        action, event = parse_event_command(command)
        if action == "stop":
            writer.record_event("operator", "stop_requested", "Collection stop requested by operator.")
            stop_requested.set()
            return
        if event:
            event_id = writer.record_event(event["event_type"], event["label"], event.get("note", ""))
            print(f"Recorded event {event_id}: {event['event_type']} {event['label']}")


async def collect_ble_session(config: ClinicalCollectionConfig):
    if BleakClient is None:
        raise RuntimeError("bleak is not installed. Run: python -m pip install -r requirements.txt")

    address = config.address or await find_polar_h10(timeout=config.scan_timeout)
    config.address = address
    writer = ClinicalSessionWriter(config)
    stop_requested = threading.Event()
    input_thread = None
    stats = {
        "pmd_packets_seen": 0,
        "pmd_ecg_packets_seen": 0,
        "pmd_acc_packets_seen": 0,
        "hr_packets_seen": 0,
        "disconnect_count": 0,
        "acc_stream_started": False,
        "hr_stream_started": False,
    }
    status = "completed"
    error = None

    if not config.no_interactive_events:
        input_thread = threading.Thread(
            target=_event_input_loop,
            args=(writer, stop_requested),
            daemon=True,
        )
        input_thread.start()

    def hr_callback(sender, data):
        stats["hr_packets_seen"] += 1
        writer.write_rr_intervals(parse_rr_packet(bytes(data)))

    def pmd_callback(sender, data):
        payload = bytes(data)
        stats["pmd_packets_seen"] += 1
        if len(payload) < 10:
            return

        data_type = payload[0] & 0x3F
        if data_type == TYPE_ECG:
            samples = parse_ecg_packet(payload)
            if samples:
                stats["pmd_ecg_packets_seen"] += 1
                writer.write_ecg_samples(samples)
        elif data_type == TYPE_ACC:
            _, samples = parse_acc_packet(payload)
            if samples:
                stats["pmd_acc_packets_seen"] += 1
                writer.write_acc_samples(samples)

    def disconnected_callback(_client):
        stats["disconnect_count"] += 1
        writer.record_event("system", "ble_disconnected", "Polar H10 BLE disconnected.")
        stop_requested.set()

    try:
        print(f"Connecting to Polar H10 at {address}...")
        async with BleakClient(
            address,
            timeout=20,
            disconnected_callback=disconnected_callback,
        ) as client:
            if not client.is_connected:
                raise RuntimeError("Unable to connect to Polar H10.")

            hr_notify_started = False
            try:
                await client.start_notify(HR_UUID, hr_callback)
                hr_notify_started = True
                stats["hr_stream_started"] = True
                print("HR/RR stream enabled.")
            except Exception as exc:
                writer.record_event("system", "hr_stream_unavailable", _format_exception(exc))
                print(f"HR/RR stream unavailable, continuing with ECG/ACC: {_format_exception(exc)}")

            await client.write_gatt_char(PMD_CONTROL, ECG_START_CMD, response=True)
            await asyncio.sleep(0.3)
            print("ECG stream enabled.")
            await client.start_notify(PMD_DATA, pmd_callback)
            print("PMD data notifications enabled.")

            try:
                await client.write_gatt_char(
                    PMD_CONTROL,
                    build_acc_start_cmd(
                        sample_rate_hz=config.acc_sample_rate_hz,
                        range_g=config.acc_range_g,
                    ),
                    response=True,
                )
                await asyncio.sleep(0.3)
                stats["acc_stream_started"] = True
                print(f"ACC stream enabled at {config.acc_sample_rate_hz}Hz, range {config.acc_range_g}G.")
            except Exception as exc:
                writer.record_event("system", "acc_stream_unavailable", _format_exception(exc))
                print(f"ACC stream unavailable, continuing ECG-only: {_format_exception(exc)}")

            start_loop = asyncio.get_running_loop().time()
            while not stop_requested.is_set():
                elapsed = asyncio.get_running_loop().time() - start_loop
                if elapsed >= config.duration_seconds:
                    break
                await asyncio.sleep(1.0)

            if stop_requested.is_set():
                status = "interrupted"

            try:
                await client.write_gatt_char(PMD_CONTROL, ACC_STOP_CMD, response=True)
            except Exception:
                pass
            try:
                await client.write_gatt_char(PMD_CONTROL, ECG_STOP_CMD, response=True)
            except Exception:
                pass
            try:
                await client.stop_notify(PMD_DATA)
            except Exception:
                pass
            if hr_notify_started:
                try:
                    await client.stop_notify(HR_UUID)
                except Exception:
                    pass
    except asyncio.CancelledError:
        status = "interrupted"
        error = "CancelledError"
    except KeyboardInterrupt:
        status = "interrupted"
        error = "KeyboardInterrupt"
    except Exception as exc:
        status = "failed"
        error = _format_exception(exc)
    finally:
        stop_requested.set()
        writer.ended_unix = time.time()
        writer.ended_iso = _now_iso()
        writer.write_segments()
        writer.close()

    metadata = writer.write_metadata(status=status, stats=stats, error=error)
    if not config.skip_quality_report:
        write_quality_outputs(writer.session_dir, metadata, window_seconds=config.window_seconds)

    print(f"Saved clinical arrhythmia session: {writer.session_dir}")
    print(f"Samples: ECG={metadata['ecg_sample_count']} ACC={metadata['acc_sample_count']} RR={metadata['rr_interval_count']}")
    if error:
        print(f"Collection ended with status={status}: {error}")
    return writer.session_dir, metadata


def _dict_acc_to_tuple(row):
    return (row["x_mg"], row["y_mg"], row["z_mg"], row["vm_mg"])


def collect_dry_run_session(config: ClinicalCollectionConfig):
    config.dry_run = True
    writer = ClinicalSessionWriter(config)
    stats = {
        "pmd_packets_seen": 0,
        "pmd_ecg_packets_seen": 0,
        "pmd_acc_packets_seen": 0,
        "hr_packets_seen": 0,
        "disconnect_count": 0,
        "acc_stream_started": True,
        "hr_stream_started": True,
        "synthetic": True,
    }
    try:
        duration = config.duration_seconds
        ecg = generate_synthetic_ecg(
            sample_rate_hz=REALTIME_ECG_SAMPLE_RATE_HZ,
            duration_seconds=duration,
            heart_rate_bpm=78,
            seed=1,
        )
        acc = [
            _dict_acc_to_tuple(row)
            for row in generate_synthetic_acc(
                sample_rate_hz=config.acc_sample_rate_hz,
                duration_seconds=duration,
                activity="REST",
                seed=1,
            )
        ]
        rr_count = int(max(0, duration // (60.0 / 78.0)))
        rr_intervals = [60000.0 / 78.0 for _ in range(rr_count)]
        writer.write_ecg_samples(ecg)
        writer.write_acc_samples(acc)
        writer.write_rr_intervals(rr_intervals)
        writer.record_event("note", "dry_run", "Synthetic dry-run session.")
        status = "completed"
        error = None
    except Exception as exc:
        status = "failed"
        error = _format_exception(exc)
    finally:
        writer.ended_unix = time.time()
        writer.ended_iso = _now_iso()
        writer.write_segments()
        writer.close()

    metadata = writer.write_metadata(status=status, stats=stats, error=error)
    if not config.skip_quality_report:
        write_quality_outputs(writer.session_dir, metadata, window_seconds=config.window_seconds)
    print(f"Saved dry-run clinical arrhythmia session: {writer.session_dir}")
    return writer.session_dir, metadata


def _read_ecg(path):
    rows = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(float(row["ecg_uv"]))
    return np.asarray(rows, dtype=float)


def _read_acc(path):
    samples = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            samples.append((float(row["x_mg"]), float(row["y_mg"]), float(row["z_mg"]), float(row["vm_mg"])))
    return samples


def _slice_list(values, start, end):
    return values[int(start): int(end)]


def _prediction_row(result, window_index, start_seconds, end_seconds):
    rhythm = result.get("rhythm") or {}
    signal_quality = result.get("signal_quality") or {}
    hr_event = result.get("hr_event") or {}
    return {
        "window_index": window_index,
        "start_seconds": round(float(start_seconds), 3),
        "end_seconds": round(float(end_seconds), 3),
        "heart_rate_bpm": result.get("heart_rate_bpm"),
        "signal_quality_label": signal_quality.get("label"),
        "signal_quality_score": signal_quality.get("score"),
        "rhythm_label": rhythm.get("label"),
        "rhythm_confidence": rhythm.get("confidence"),
        "possible_afib_probability": rhythm.get("possible_afib_probability"),
        "hr_event_label": hr_event.get("label"),
        "alert_level": result.get("alert_level"),
        "message": result.get("message"),
    }


def _preview_event_counts(rows):
    counts = Counter()
    for row in rows:
        quality = row.get("signal_quality_label")
        if quality == "poor":
            counts["poor_signal"] += 1
        hr_event = row.get("hr_event_label")
        if hr_event == "tachycardia_at_rest":
            counts["tachycardia"] += 1
        elif hr_event == "bradycardia":
            counts["bradycardia"] += 1
        rhythm_label = row.get("rhythm_label")
        afib_probability = float(row.get("possible_afib_probability") or 0.0)
        if rhythm_label == "possible_afib" or afib_probability >= 0.28:
            counts["af_suspicion"] += 1
    return dict(counts)


def _write_predictions_preview(path, rows):
    fieldnames = [
        "window_index",
        "start_seconds",
        "end_seconds",
        "heart_rate_bpm",
        "signal_quality_label",
        "signal_quality_score",
        "rhythm_label",
        "rhythm_confidence",
        "possible_afib_probability",
        "hr_event_label",
        "alert_level",
        "message",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_quality_outputs(session_dir, metadata, window_seconds=DEFAULT_WINDOW_SECONDS):
    from src.api import pipeline

    session_path = Path(session_dir)
    ecg = _read_ecg(session_path / "ecg.csv")
    acc = _read_acc(session_path / "acc.csv")
    ecg_rate = float(metadata.get("ecg_sample_rate_hz") or REALTIME_ECG_SAMPLE_RATE_HZ)
    acc_rate = float(metadata.get("acc_sample_rate_hz") or DEFAULT_ACC_SAMPLE_RATE_HZ)
    sample_count_per_window = int(round(float(window_seconds) * ecg_rate))
    acc_count_per_window = int(round(float(window_seconds) * acc_rate))
    total_windows = int(len(ecg) // sample_count_per_window) if sample_count_per_window > 0 else 0
    rows = []

    pipeline.af_episode_trackers.pop(metadata.get("participant_id"), None)
    for window_index in range(total_windows):
        ecg_start = window_index * sample_count_per_window
        ecg_end = ecg_start + sample_count_per_window
        acc_start = window_index * acc_count_per_window
        acc_end = acc_start + acc_count_per_window
        start_seconds = window_index * float(window_seconds)
        result = pipeline.predict_ecg(
            ecg[ecg_start:ecg_end],
            sample_rate_hz=ecg_rate,
            patient_id=metadata.get("participant_id"),
            acc_samples=_slice_list(acc, acc_start, acc_end),
            acc_sample_rate_hz=acc_rate,
        )
        rows.append(
            _prediction_row(
                result,
                window_index=window_index,
                start_seconds=start_seconds,
                end_seconds=start_seconds + float(window_seconds),
            )
        )

    _write_predictions_preview(session_path / "predictions_preview.csv", rows)

    quality_counts = Counter(row.get("signal_quality_label") or "unknown" for row in rows)
    valid_signal_count = sum(quality_counts.get(label, 0) for label in ("good", "fair"))
    valid_signal_ratio = (valid_signal_count / len(rows)) if rows else 0.0
    hr_values = [float(row["heart_rate_bpm"]) for row in rows if row.get("heart_rate_bpm") is not None]
    afib_values = [
        float(row["possible_afib_probability"])
        for row in rows
        if row.get("possible_afib_probability") is not None
    ]

    requested_minutes = float(metadata.get("requested_duration_seconds") or 0.0) / 60.0
    if requested_minutes >= 110:
        required_ecg_seconds = 110.0 * 60.0
    elif requested_minutes >= 60:
        required_ecg_seconds = 55.0 * 60.0
    else:
        required_ecg_seconds = max(0.0, 0.9 * float(metadata.get("requested_duration_seconds") or 0.0))

    metadata_complete = (
        bool(metadata.get("participant_id"))
        and metadata.get("condition_group") != "unknown"
        and metadata.get("clinical_source") != "unknown"
    )
    usable_for_analysis = (
        float(metadata.get("ecg_duration_seconds") or 0.0) >= required_ecg_seconds
        and valid_signal_ratio >= 0.70
        and float(metadata.get("ecg_sample_loss_ratio") or 1.0) <= 0.10
        and metadata_complete
    )
    report = {
        "participant_id": metadata.get("participant_id"),
        "visit_id": metadata.get("visit_id"),
        "generated_at": _now_iso(),
        "window_seconds": float(window_seconds),
        "window_count": len(rows),
        "quality_counts": dict(quality_counts),
        "valid_signal_ratio": round(valid_signal_ratio, 4),
        "ecg_duration_seconds": metadata.get("ecg_duration_seconds"),
        "acc_duration_seconds": metadata.get("acc_duration_seconds"),
        "ecg_sample_loss_ratio": metadata.get("ecg_sample_loss_ratio"),
        "acc_sample_loss_ratio": metadata.get("acc_sample_loss_ratio"),
        "heart_rate_bpm": {
            "min": round(min(hr_values), 2) if hr_values else None,
            "mean": round(sum(hr_values) / len(hr_values), 2) if hr_values else None,
            "max": round(max(hr_values), 2) if hr_values else None,
        },
        "possible_afib_probability": {
            "min": round(min(afib_values), 4) if afib_values else None,
            "mean": round(sum(afib_values) / len(afib_values), 4) if afib_values else None,
            "max": round(max(afib_values), 4) if afib_values else None,
        },
        "preview_event_counts": _preview_event_counts(rows),
        "metadata_complete": metadata_complete,
        "usable_for_analysis": usable_for_analysis,
        "decision_reasons": {
            "required_ecg_seconds": required_ecg_seconds,
            "valid_signal_ratio_min": 0.70,
            "ecg_sample_loss_ratio_max": 0.10,
            "clinical_metadata_required": True,
        },
        "warning": "This quality report is for screening dataset triage, not a medical diagnosis.",
    }
    (session_path / "quality_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Collect 1-2 hour Polar H10 ECG/ACC sessions for clinical arrhythmia screening datasets."
    )
    parser.add_argument("--participant-id", required=True, help="Anonymous participant code, e.g. p001.")
    parser.add_argument("--condition-group", required=True, choices=CONDITION_GROUPS)
    parser.add_argument("--clinical-source", required=True, choices=CLINICAL_SOURCES)
    parser.add_argument("--duration-minutes", type=float, default=DEFAULT_DURATION_MINUTES)
    parser.add_argument("--address", default=None, help="Polar H10 BLE address. If omitted, scan by name.")
    parser.add_argument("--scan-timeout", type=float, default=20.0)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--visit-id", default=None)
    parser.add_argument("--session-context", choices=SESSION_CONTEXTS, default="rest_observation")
    parser.add_argument("--window-rhythm-label", choices=WINDOW_RHYTHM_LABELS, default="unlabeled")
    parser.add_argument("--condition-detail", default="", help="Non-identifying clinical detail, e.g. hypertension.")
    parser.add_argument("--operator-id", default="", help="Anonymous operator code.")
    parser.add_argument("--acc-sample-rate-hz", type=int, choices=SUPPORTED_ACC_SAMPLE_RATES_HZ, default=DEFAULT_ACC_SAMPLE_RATE_HZ)
    parser.add_argument("--acc-range-g", type=int, choices=SUPPORTED_ACC_RANGES_G, default=DEFAULT_ACC_RANGE_G)
    parser.add_argument("--warmup-seconds", type=float, default=DEFAULT_WARMUP_SECONDS)
    parser.add_argument("--window-seconds", type=float, default=DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--dry-run", action="store_true", help="Generate synthetic data instead of connecting to BLE.")
    parser.add_argument("--allow-short-test", action="store_true", help="Allow duration below 30 minutes for local tests.")
    parser.add_argument("--no-interactive-events", action="store_true", help="Disable operator event marker input.")
    parser.add_argument("--skip-quality-report", action="store_true")
    args = parser.parse_args(argv)
    try:
        args.duration_minutes = validate_duration_minutes(args.duration_minutes, args.allow_short_test)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def config_from_args(args):
    return ClinicalCollectionConfig(
        participant_id=args.participant_id,
        condition_group=args.condition_group,
        clinical_source=args.clinical_source,
        duration_minutes=args.duration_minutes,
        address=args.address,
        scan_timeout=args.scan_timeout,
        output_root=args.output_root,
        visit_id=args.visit_id,
        session_context=args.session_context,
        window_rhythm_label=args.window_rhythm_label,
        condition_detail=args.condition_detail,
        operator_id=args.operator_id,
        acc_sample_rate_hz=args.acc_sample_rate_hz,
        acc_range_g=args.acc_range_g,
        warmup_seconds=args.warmup_seconds,
        window_seconds=args.window_seconds,
        dry_run=args.dry_run,
        allow_short_test=args.allow_short_test,
        no_interactive_events=args.no_interactive_events,
        skip_quality_report=args.skip_quality_report,
    )


async def async_main(argv=None):
    args = parse_args(argv)
    config = config_from_args(args)
    if config.window_rhythm_label != "unlabeled":
        print(
            "Warning: window rhythm labels should only be set when a time-aligned clinical annotation exists."
        )
    if config.dry_run:
        return collect_dry_run_session(config)
    return await collect_ble_session(config)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
