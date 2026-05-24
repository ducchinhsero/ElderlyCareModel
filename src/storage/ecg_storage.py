import csv
import hashlib
import json
import os
import sqlite3
import struct
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.env_loader import load_env_file


load_env_file()

DB_PATH = "dataset/realtime_logs/ecg_monitor.db"
RAW_ECG_ROOT = "dataset/realtime_logs/raw_ecg"
RAW_ACC_ROOT = "dataset/realtime_logs/raw_acc"
DEFAULT_RAW_CHUNK_SECONDS = 5
ECG_CHUNK_ENCODING = "int32_le_zlib"
ACC_CHUNK_ENCODING = "float32x4_le_zlib"
SAVE_LEGACY_RAW_CSV = os.getenv("SAVE_LEGACY_RAW_CSV", "0").strip().lower() in {"1", "true", "yes"}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def timestamp_to_epoch(value):
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return float(dt.timestamp())


def _positive_float(value, name, allow_zero=False):
    number = float(value)
    if allow_zero:
        if number < 0:
            raise ValueError(f"{name} must be greater than or equal to 0.")
    elif number <= 0:
        raise ValueError(f"{name} must be positive.")
    return number


def _positive_int(value, name):
    number = int(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive.")
    return number


def get_connection(db_path=DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            prediction_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            patient_id TEXT,
            timestamp TEXT NOT NULL,
            sample_rate_hz REAL NOT NULL,
            window_count INTEGER NOT NULL,
            heart_rate_bpm REAL,
            emotion_json TEXT NOT NULL,
            stress_json TEXT NOT NULL DEFAULT '{}',
            anomaly_json TEXT NOT NULL,
            signal_quality_json TEXT NOT NULL,
            risk_json TEXT NOT NULL,
            alert_level TEXT NOT NULL,
            message TEXT NOT NULL,
            raw_ecg_path TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            prediction_id TEXT,
            session_id TEXT,
            patient_id TEXT,
            timestamp TEXT NOT NULL,
            timestamp_epoch REAL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            label TEXT,
            message TEXT,
            heart_rate_bpm REAL,
            activity_state TEXT,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS guided_baseline_sessions (
            session_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            day_index INTEGER NOT NULL,
            target_days INTEGER NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS guided_baseline_segments (
            segment_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            day_index INTEGER NOT NULL,
            segment_type TEXT NOT NULL,
            expected_activity TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            valid_window_count INTEGER NOT NULL DEFAULT 0,
            rejected_window_count INTEGER NOT NULL DEFAULT 0,
            rejection_reasons_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collection_sessions (
            collection_session_id TEXT PRIMARY KEY,
            patient_id TEXT,
            purpose TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_synced INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collection_segments (
            collection_segment_id TEXT PRIMARY KEY,
            collection_session_id TEXT,
            patient_id TEXT,
            segment_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_synced INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_signal_chunks (
            chunk_id TEXT PRIMARY KEY,
            patient_id TEXT,
            collection_session_id TEXT,
            guided_segment_id TEXT,
            prediction_id TEXT,
            signal_type TEXT NOT NULL,
            timestamp_start_unix REAL NOT NULL,
            timestamp_end_unix REAL NOT NULL,
            timestamp_start_str TEXT NOT NULL,
            sample_rate_hz REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            channel_count INTEGER NOT NULL DEFAULT 1,
            encoding TEXT NOT NULL,
            payload_blob BLOB NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            is_baseline_usable INTEGER NOT NULL DEFAULT 0,
            is_synced INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            patient_id TEXT,
            snapshot_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            timestamp_epoch REAL,
            period_json TEXT NOT NULL DEFAULT '{}',
            payload_json TEXT NOT NULL,
            is_synced INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(predictions)").fetchall()}
    if "sensor_context_json" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN sensor_context_json TEXT NOT NULL DEFAULT '{}'")
    if "raw_acc_path" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN raw_acc_path TEXT")
    if "rhythm_json" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN rhythm_json TEXT NOT NULL DEFAULT '{}'")
    if "ectopy_json" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN ectopy_json TEXT NOT NULL DEFAULT '{}'")
    if "hr_event_json" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN hr_event_json TEXT NOT NULL DEFAULT '{}'")
    if "af_episode_json" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN af_episode_json TEXT NOT NULL DEFAULT '{}'")
    if "rhythm_alert_json" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN rhythm_alert_json TEXT NOT NULL DEFAULT '{}'")
    if "timestamp_epoch" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN timestamp_epoch REAL")
    if "raw_ecg_chunk_ids_json" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN raw_ecg_chunk_ids_json TEXT NOT NULL DEFAULT '[]'")
    if "raw_acc_chunk_ids_json" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN raw_acc_chunk_ids_json TEXT NOT NULL DEFAULT '[]'")
    if "stress_json" not in columns:
        conn.execute("ALTER TABLE predictions ADD COLUMN stress_json TEXT NOT NULL DEFAULT '{}'")
    rows = conn.execute(
        "SELECT prediction_id, timestamp FROM predictions WHERE timestamp_epoch IS NULL"
    ).fetchall()
    for row in rows:
        epoch = timestamp_to_epoch(row[1])
        if epoch is not None:
            conn.execute(
                "UPDATE predictions SET timestamp_epoch = ? WHERE prediction_id = ?",
                (epoch, row[0]),
            )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_patient_time ON predictions(patient_id, timestamp)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_predictions_patient_epoch "
        "ON predictions(patient_id, timestamp_epoch)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_patient_epoch "
        "ON events(patient_id, timestamp_epoch)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_type_epoch "
        "ON events(event_type, timestamp_epoch)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_guided_baseline_sessions_patient "
        "ON guided_baseline_sessions(patient_id, started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_guided_baseline_segments_patient "
        "ON guided_baseline_segments(patient_id, segment_type, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_signal_chunks_patient_time "
        "ON raw_signal_chunks(patient_id, signal_type, timestamp_start_unix)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_signal_chunks_sync "
        "ON raw_signal_chunks(is_synced, timestamp_start_unix)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_collection_sessions_patient "
        "ON collection_sessions(patient_id, started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_assessment_snapshots_patient "
        "ON assessment_snapshots(patient_id, snapshot_type, timestamp_epoch)"
    )
    conn.commit()


def session_id_for_timestamp(timestamp):
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.now()
    patient_day = dt.strftime("%Y%m%d")
    return patient_day


def save_raw_ecg_csv(ecg_samples, sample_rate_hz, patient_id, timestamp, prediction_id, root=RAW_ECG_ROOT):
    session_id = session_id_for_timestamp(timestamp)
    safe_patient = patient_id or "unknown"
    safe_patient = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in safe_patient)
    out_dir = Path(root) / safe_patient / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{prediction_id}.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_index", "time_seconds", "ecg_uv"])
        for i, value in enumerate(ecg_samples):
            writer.writerow([i, i / float(sample_rate_hz), value])
    return str(path)


def save_raw_acc_csv(acc_samples, sample_rate_hz, patient_id, timestamp, prediction_id, root=RAW_ACC_ROOT):
    session_id = session_id_for_timestamp(timestamp)
    safe_patient = patient_id or "unknown"
    safe_patient = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in safe_patient)
    out_dir = Path(root) / safe_patient / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{prediction_id}.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_index", "time_seconds", "x_mg", "y_mg", "z_mg", "vm_mg"])
        for i, item in enumerate(acc_samples):
            if isinstance(item, dict):
                x = item.get("x_mg", item.get("x", item.get("acc_x_mg")))
                y = item.get("y_mg", item.get("y", item.get("acc_y_mg")))
                z = item.get("z_mg", item.get("z", item.get("acc_z_mg")))
                vm = item.get("vm_mg", item.get("vm"))
            else:
                values = list(item)
                if len(values) < 3:
                    continue
                x, y, z = values[:3]
                vm = values[3] if len(values) >= 4 else None
            if vm is None:
                vm = (float(x) ** 2 + float(y) ** 2 + float(z) ** 2) ** 0.5
            writer.writerow([i, i / float(sample_rate_hz), x, y, z, vm])
    return str(path)


def _timestamp_from_epoch(epoch):
    return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat()


def _encode_ecg_samples(samples):
    values = [int(round(float(value))) for value in samples]
    payload = struct.pack("<" + "i" * len(values), *values) if values else b""
    compressed = zlib.compress(payload)
    return compressed, hashlib.sha256(compressed).hexdigest(), ECG_CHUNK_ENCODING


def _decode_ecg_samples(payload_blob, sample_count, encoding=ECG_CHUNK_ENCODING):
    if encoding != ECG_CHUNK_ENCODING:
        raise ValueError(f"Unsupported ECG chunk encoding: {encoding}")
    raw = zlib.decompress(payload_blob)
    if not raw:
        return []
    return list(struct.unpack("<" + "i" * int(sample_count), raw))


def _acc_row(item):
    if isinstance(item, dict):
        x = item.get("x_mg", item.get("x", item.get("acc_x_mg", 0.0)))
        y = item.get("y_mg", item.get("y", item.get("acc_y_mg", 0.0)))
        z = item.get("z_mg", item.get("z", item.get("acc_z_mg", 0.0)))
        vm = item.get("vm_mg", item.get("vm"))
    else:
        values = list(item)
        x = values[0] if len(values) > 0 else 0.0
        y = values[1] if len(values) > 1 else 0.0
        z = values[2] if len(values) > 2 else 0.0
        vm = values[3] if len(values) > 3 else None
    if vm is None:
        vm = (float(x) ** 2 + float(y) ** 2 + float(z) ** 2) ** 0.5
    return float(x), float(y), float(z), float(vm)


def _encode_acc_samples(samples):
    rows = [_acc_row(item) for item in samples]
    flat = [value for row in rows for value in row]
    payload = struct.pack("<" + "f" * len(flat), *flat) if flat else b""
    compressed = zlib.compress(payload)
    return compressed, hashlib.sha256(compressed).hexdigest(), ACC_CHUNK_ENCODING


def _decode_acc_samples(payload_blob, sample_count, encoding=ACC_CHUNK_ENCODING):
    if encoding != ACC_CHUNK_ENCODING:
        raise ValueError(f"Unsupported ACC chunk encoding: {encoding}")
    raw = zlib.decompress(payload_blob)
    if not raw:
        return []
    values = struct.unpack("<" + "f" * (int(sample_count) * 4), raw)
    return [
        {
            "x_mg": values[i],
            "y_mg": values[i + 1],
            "z_mg": values[i + 2],
            "vm_mg": values[i + 3],
        }
        for i in range(0, len(values), 4)
    ]


def _chunk_ranges(sample_count, sample_rate_hz, chunk_seconds=DEFAULT_RAW_CHUNK_SECONDS):
    sample_rate_hz = _positive_float(sample_rate_hz, "sample_rate_hz")
    chunk_seconds = _positive_float(chunk_seconds, "chunk_seconds")
    chunk_size = max(1, int(round(sample_rate_hz * chunk_seconds)))
    for start in range(0, int(sample_count), chunk_size):
        end = min(start + chunk_size, int(sample_count))
        yield start, end


def _raw_chunk_row(row, include_payload=False):
    payload = {
        "chunk_id": row["chunk_id"],
        "patient_id": row["patient_id"],
        "collection_session_id": row["collection_session_id"],
        "guided_segment_id": row["guided_segment_id"],
        "prediction_id": row["prediction_id"],
        "signal_type": row["signal_type"],
        "timestamp_start_unix": row["timestamp_start_unix"],
        "timestamp_end_unix": row["timestamp_end_unix"],
        "timestamp_start_str": row["timestamp_start_str"],
        "sample_rate_hz": row["sample_rate_hz"],
        "sample_count": row["sample_count"],
        "channel_count": row["channel_count"],
        "encoding": row["encoding"],
        "checksum_sha256": row["checksum_sha256"],
        "is_baseline_usable": bool(row["is_baseline_usable"]),
        "is_synced": bool(row["is_synced"]),
        "synced_at": row["synced_at"],
        "created_at": row["created_at"],
    }
    if include_payload:
        payload["payload_blob"] = row["payload_blob"]
    return payload


def save_raw_signal_chunks(
    samples,
    sample_rate_hz,
    patient_id,
    timestamp,
    prediction_id=None,
    signal_type="ecg",
    collection_session_id=None,
    guided_segment_id=None,
    chunk_seconds=DEFAULT_RAW_CHUNK_SECONDS,
    db_path=DB_PATH,
):
    samples = list(samples or [])
    if not samples:
        return []
    signal_type = str(signal_type or "").lower()
    if signal_type not in {"ecg", "acc"}:
        raise ValueError("signal_type must be 'ecg' or 'acc'.")
    sample_rate_hz = _positive_float(sample_rate_hz, "sample_rate_hz")
    chunk_seconds = _positive_float(chunk_seconds, "chunk_seconds")
    start_epoch = timestamp_to_epoch(timestamp) or datetime.now(timezone.utc).timestamp()
    created_at = utc_now_iso()
    rows = []

    conn = get_connection(db_path)
    try:
        for start, end in _chunk_ranges(len(samples), sample_rate_hz, chunk_seconds=chunk_seconds):
            chunk_samples = samples[start:end]
            chunk_start_epoch = start_epoch + (start / sample_rate_hz)
            chunk_end_epoch = start_epoch + ((end - 1) / sample_rate_hz if end > start else start / sample_rate_hz)
            if signal_type == "ecg":
                payload_blob, checksum, encoding = _encode_ecg_samples(chunk_samples)
                channel_count = 1
            else:
                payload_blob, checksum, encoding = _encode_acc_samples(chunk_samples)
                channel_count = 4
            chunk_id = str(uuid.uuid4())
            row = {
                "chunk_id": chunk_id,
                "patient_id": patient_id,
                "collection_session_id": collection_session_id,
                "guided_segment_id": guided_segment_id,
                "prediction_id": prediction_id,
                "signal_type": signal_type,
                "timestamp_start_unix": chunk_start_epoch,
                "timestamp_end_unix": chunk_end_epoch,
                "timestamp_start_str": _timestamp_from_epoch(chunk_start_epoch),
                "sample_rate_hz": sample_rate_hz,
                "sample_count": len(chunk_samples),
                "channel_count": channel_count,
                "encoding": encoding,
                "payload_blob": payload_blob,
                "checksum_sha256": checksum,
                "created_at": created_at,
            }
            conn.execute(
                """
                INSERT INTO raw_signal_chunks (
                    chunk_id, patient_id, collection_session_id, guided_segment_id,
                    prediction_id, signal_type, timestamp_start_unix, timestamp_end_unix,
                    timestamp_start_str, sample_rate_hz, sample_count, channel_count,
                    encoding, payload_blob, checksum_sha256, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["chunk_id"],
                    row["patient_id"],
                    row["collection_session_id"],
                    row["guided_segment_id"],
                    row["prediction_id"],
                    row["signal_type"],
                    row["timestamp_start_unix"],
                    row["timestamp_end_unix"],
                    row["timestamp_start_str"],
                    row["sample_rate_hz"],
                    row["sample_count"],
                    row["channel_count"],
                    row["encoding"],
                    row["payload_blob"],
                    row["checksum_sha256"],
                    row["created_at"],
                ),
            )
            rows.append({key: value for key, value in row.items() if key != "payload_blob"})
        conn.commit()
    finally:
        conn.close()
    return rows


def upsert_collection_session(
    collection_session_id,
    patient_id,
    purpose="realtime_monitoring",
    status="in_progress",
    started_at=None,
    metadata=None,
    db_path=DB_PATH,
):
    now = utc_now_iso()
    started_at = started_at or now
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO collection_sessions (
                collection_session_id, patient_id, purpose, status,
                started_at, ended_at, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(collection_session_id) DO UPDATE SET
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                collection_session_id,
                patient_id,
                purpose,
                status,
                started_at,
                None,
                json.dumps(metadata or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return collection_session_id


def _safe_json(value, fallback=None):
    if fallback is None:
        fallback = {}
    try:
        parsed = json.loads(value or "{}")
        return parsed if parsed is not None else fallback
    except Exception:
        return fallback


def _stress_from_legacy_emotion(emotion):
    emotion = emotion or {}
    label = emotion.get("label")
    confidence = float(emotion.get("confidence") or 0.0)
    probabilities = emotion.get("probabilities") or {}
    stress_probability = float(probabilities.get("stress") or (confidence if label == "stress" else 0.0))
    if label == "stress":
        return {
            "label": "stress",
            "value": 1,
            "confidence": confidence or stress_probability,
            "probabilities": {
                "non_stress": max(0.0, 1.0 - stress_probability),
                "stress": stress_probability,
            },
            "model_version": "legacy_emotion_fallback",
            "window_seconds": None,
            "reason": "mapped_from_legacy_emotion",
        }
    if label in {"neutral", "relaxed"}:
        return {
            "label": "non_stress",
            "value": 0,
            "confidence": confidence,
            "probabilities": {
                "non_stress": confidence,
                "stress": stress_probability,
            },
            "model_version": "legacy_emotion_fallback",
            "window_seconds": None,
            "reason": "mapped_from_legacy_emotion",
        }
    return {
        "label": "unknown",
        "value": None,
        "confidence": 0.0,
        "probabilities": {"non_stress": 0.0, "stress": 0.0},
        "model_version": "legacy_emotion_fallback",
        "window_seconds": None,
        "reason": "legacy_emotion_missing_or_unknown",
    }


def _row_to_result(row):
    emotion = _safe_json(row["emotion_json"])
    stress = _safe_json(row["stress_json"])
    if not stress:
        stress = _stress_from_legacy_emotion(emotion)
    return {
        "prediction_id": row["prediction_id"],
        "session_id": row["session_id"],
        "patient_id": row["patient_id"],
        "timestamp": row["timestamp"],
        "timestamp_epoch": row["timestamp_epoch"],
        "sample_rate_hz": row["sample_rate_hz"],
        "window_count": row["window_count"],
        "heart_rate_bpm": row["heart_rate_bpm"],
        "stress": stress,
        "anomaly": _safe_json(row["anomaly_json"]),
        "rhythm": _safe_json(row["rhythm_json"]),
        "ectopy": _safe_json(row["ectopy_json"]),
        "hr_event": _safe_json(row["hr_event_json"]),
        "af_episode": _safe_json(row["af_episode_json"]),
        "rhythm_alert": _safe_json(row["rhythm_alert_json"]),
        "signal_quality": _safe_json(row["signal_quality_json"]),
        "risk": _safe_json(row["risk_json"]),
        "sensor_context": _safe_json(row["sensor_context_json"]),
        "alert_level": row["alert_level"],
        "message": row["message"],
        "raw_ecg_path": row["raw_ecg_path"],
        "raw_acc_path": row["raw_acc_path"],
        "raw_ecg_chunk_ids": _safe_json(row["raw_ecg_chunk_ids_json"], fallback=[]),
        "raw_acc_chunk_ids": _safe_json(row["raw_acc_chunk_ids_json"], fallback=[]),
    }


def _row_to_event(row):
    return {
        "event_id": row["event_id"],
        "prediction_id": row["prediction_id"],
        "session_id": row["session_id"],
        "patient_id": row["patient_id"],
        "timestamp": row["timestamp"],
        "timestamp_epoch": row["timestamp_epoch"],
        "event_type": row["event_type"],
        "severity": row["severity"],
        "label": row["label"],
        "message": row["message"],
        "heart_rate_bpm": row["heart_rate_bpm"],
        "activity_state": row["activity_state"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def _stable_event_id(event):
    payload = "|".join(
        str(event.get(key) or "")
        for key in (
            "prediction_id",
            "timestamp",
            "event_type",
            "severity",
            "label",
            "message",
            "activity_state",
        )
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _event_base(item):
    return {
        "prediction_id": item.get("prediction_id"),
        "session_id": item.get("session_id"),
        "patient_id": item.get("patient_id"),
        "timestamp": item.get("timestamp"),
        "timestamp_epoch": item.get("timestamp_epoch") or timestamp_to_epoch(item.get("timestamp")),
        "heart_rate_bpm": item.get("heart_rate_bpm"),
        "activity_state": (item.get("sensor_context") or {}).get("activity_state"),
    }


def _make_event(item, event_type, severity, label, message, metadata=None):
    event = {
        **_event_base(item),
        "event_type": event_type,
        "severity": severity or "unknown",
        "label": label,
        "message": message or "",
        "metadata": metadata or {},
    }
    event["event_id"] = _stable_event_id(event)
    return event


def build_events_for_prediction(item):
    events = []
    rhythm = item.get("rhythm") or {}
    rhythm_alert = item.get("rhythm_alert") or {}
    rhythm_label = rhythm.get("label")
    afib_probability = float(rhythm.get("possible_afib_probability") or 0.0)
    if rhythm_label == "possible_afib" or rhythm_alert.get("level") in {"medium", "high", "critical"}:
        events.append(
            _make_event(
                item,
                "af_suspicion",
                rhythm_alert.get("level") or "medium",
                rhythm_label or "possible_afib",
                rhythm_alert.get("message") or "Possible AFib rhythm pattern detected.",
                {
                    "possible_afib_probability": afib_probability,
                    "rhythm": rhythm,
                    "rhythm_alert": rhythm_alert,
                },
            )
        )

    hr_event = item.get("hr_event") or {}
    if hr_event.get("label") == "tachycardia_at_rest":
        events.append(
            _make_event(
                item,
                "tachycardia",
                "medium",
                hr_event.get("label"),
                hr_event.get("reason") or "Tachycardia at rest detected.",
                {"hr_event": hr_event},
            )
        )
    elif hr_event.get("label") == "bradycardia":
        events.append(
            _make_event(
                item,
                "bradycardia",
                "medium",
                hr_event.get("label"),
                hr_event.get("reason") or "Bradycardia detected.",
                {"hr_event": hr_event},
            )
        )

    ectopy = item.get("ectopy") or {}
    if ectopy.get("label") in {"pvc", "pac", "mixed_ectopic"}:
        events.append(
            _make_event(
                item,
                "ectopy_suspicion",
                "medium",
                ectopy.get("label"),
                f"Possible {ectopy.get('label')} activity detected.",
                {"ectopy": ectopy},
            )
        )

    stress = item.get("stress") or {}
    signal_quality = item.get("signal_quality") or {}
    activity_state = ((item.get("sensor_context") or {}).get("activity_state") or "unknown").upper()
    if (
        stress.get("label") == "stress"
        and signal_quality.get("label") in {"good", "fair"}
        and activity_state not in {"WALK", "ACTIVE"}
    ):
        events.append(
            _make_event(
                item,
                "stress_suspicion",
                "medium",
                "stress",
                "Stress-like physiological pattern detected in reliable ECG data.",
                {"stress": stress},
            )
        )

    hr_context = (item.get("sensor_context") or {}).get("hr_context_alert") or {}
    if hr_context.get("level") in {"WATCH", "ALERT", "CRITICAL"}:
        events.append(
            _make_event(
                item,
                "hr_context",
                "medium" if hr_context.get("level") == "WATCH" else "high",
                hr_context.get("level"),
                hr_context.get("reason") or "Heart-rate context requires monitoring.",
                {"hr_context_alert": hr_context},
            )
        )

    fall = (item.get("sensor_context") or {}).get("fall") or {}
    if fall.get("strong_fall") or fall.get("fall_candidate"):
        events.append(
            _make_event(
                item,
                "fall_candidate",
                "critical" if fall.get("strong_fall") else "high",
                "strong_fall" if fall.get("strong_fall") else "fall_candidate",
                fall.get("reason") or item.get("message") or "Fall candidate detected.",
                {"fall": fall},
            )
        )

    quality = signal_quality.get("label")
    if quality in {"poor", "noise", "poor_contact", "motion_artifact"}:
        events.append(
            _make_event(
                item,
                "poor_signal",
                "unknown",
                quality,
                "; ".join(signal_quality.get("reasons") or []) or "Poor ECG signal quality.",
                {"signal_quality": signal_quality},
            )
        )
    return events


def _insert_events(conn, events):
    now = utc_now_iso()
    for event in events:
        conn.execute(
            """
            INSERT OR REPLACE INTO events (
                event_id, prediction_id, session_id, patient_id, timestamp, timestamp_epoch,
                event_type, severity, label, message, heart_rate_bpm, activity_state,
                metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("event_id") or _stable_event_id(event),
                event.get("prediction_id"),
                event.get("session_id"),
                event.get("patient_id"),
                event.get("timestamp"),
                event.get("timestamp_epoch"),
                event.get("event_type"),
                event.get("severity") or "unknown",
                event.get("label"),
                event.get("message") or "",
                event.get("heart_rate_bpm"),
                event.get("activity_state"),
                json.dumps(event.get("metadata") or {}, ensure_ascii=False),
                now,
            ),
        )


def save_prediction(
    result,
    ecg_samples,
    sample_rate_hz,
    acc_samples=None,
    acc_sample_rate_hz=None,
    db_path=DB_PATH,
):
    result = dict(result)
    stress = result.get("stress") or _stress_from_legacy_emotion(result.get("emotion") or {})
    result["stress"] = stress
    prediction_id = result.get("prediction_id") or str(uuid.uuid4())
    result["prediction_id"] = prediction_id
    timestamp = result.get("timestamp") or utc_now_iso()
    result["timestamp"] = timestamp
    timestamp_epoch = timestamp_to_epoch(timestamp)
    session_id = result.get("session_id") or session_id_for_timestamp(timestamp)
    result["session_id"] = session_id
    collection_session_id = (
        result.get("collection_session_id")
        or f"{result.get('patient_id') or 'unknown'}:{session_id}"
    )
    result["collection_session_id"] = collection_session_id
    upsert_collection_session(
        collection_session_id,
        patient_id=result.get("patient_id"),
        purpose=result.get("collection_purpose") or "realtime_monitoring",
        started_at=timestamp,
        metadata={"prediction_session_id": session_id},
        db_path=db_path,
    )
    raw_path = None
    if SAVE_LEGACY_RAW_CSV:
        raw_path = save_raw_ecg_csv(
            ecg_samples,
            sample_rate_hz,
            result.get("patient_id"),
            timestamp,
            prediction_id,
        )
    result["raw_ecg_path"] = raw_path
    ecg_chunks = save_raw_signal_chunks(
        ecg_samples,
        sample_rate_hz,
        result.get("patient_id"),
        timestamp,
        prediction_id=prediction_id,
        signal_type="ecg",
        collection_session_id=collection_session_id,
        db_path=db_path,
    )
    raw_ecg_chunk_ids = [item["chunk_id"] for item in ecg_chunks]
    result["raw_ecg_chunk_ids"] = raw_ecg_chunk_ids
    raw_acc_path = None
    raw_acc_chunk_ids = []
    if acc_samples is not None and acc_sample_rate_hz is not None:
        if SAVE_LEGACY_RAW_CSV:
            raw_acc_path = save_raw_acc_csv(
                acc_samples,
                acc_sample_rate_hz,
                result.get("patient_id"),
                timestamp,
                prediction_id,
            )
        acc_chunks = save_raw_signal_chunks(
            acc_samples,
            acc_sample_rate_hz,
            result.get("patient_id"),
            timestamp,
            prediction_id=prediction_id,
            signal_type="acc",
            collection_session_id=collection_session_id,
            db_path=db_path,
        )
        raw_acc_chunk_ids = [item["chunk_id"] for item in acc_chunks]
    result["raw_acc_path"] = raw_acc_path
    result["raw_acc_chunk_ids"] = raw_acc_chunk_ids
    result["timestamp_epoch"] = timestamp_epoch

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO predictions (
                prediction_id, session_id, patient_id, timestamp, timestamp_epoch, sample_rate_hz,
                window_count, heart_rate_bpm, emotion_json, stress_json, anomaly_json,
                rhythm_json, ectopy_json, hr_event_json, af_episode_json, rhythm_alert_json, signal_quality_json,
                risk_json, sensor_context_json, alert_level, message, raw_ecg_path,
                raw_acc_path, raw_ecg_chunk_ids_json, raw_acc_chunk_ids_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction_id,
                session_id,
                result.get("patient_id"),
                timestamp,
                timestamp_epoch,
                float(sample_rate_hz),
                int(result.get("window_count") or 0),
                result.get("heart_rate_bpm"),
                json.dumps(result.get("emotion") or {}, ensure_ascii=False),
                json.dumps(stress, ensure_ascii=False),
                json.dumps(result.get("anomaly") or {}, ensure_ascii=False),
                json.dumps(result.get("rhythm") or {}, ensure_ascii=False),
                json.dumps(result.get("ectopy") or {}, ensure_ascii=False),
                json.dumps(result.get("hr_event") or {}, ensure_ascii=False),
                json.dumps(result.get("af_episode") or {}, ensure_ascii=False),
                json.dumps(result.get("rhythm_alert") or {}, ensure_ascii=False),
                json.dumps(result.get("signal_quality") or {}, ensure_ascii=False),
                json.dumps(result.get("risk") or {}, ensure_ascii=False),
                json.dumps(result.get("sensor_context") or {}, ensure_ascii=False),
                result.get("alert_level") or "unknown",
                result.get("message") or "",
                raw_path,
                raw_acc_path,
                json.dumps(raw_ecg_chunk_ids),
                json.dumps(raw_acc_chunk_ids),
                utc_now_iso(),
            ),
        )
        _insert_events(conn, build_events_for_prediction(result))
        conn.commit()
    finally:
        conn.close()
    return result


def get_history(patient_id=None, days=1, limit=100, db_path=DB_PATH):
    days = _positive_float(days, "days")
    limit = _positive_int(limit, "limit")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    params = [since.timestamp()]
    where = "timestamp_epoch >= ?"
    if patient_id:
        where += " AND patient_id = ?"
        params.append(patient_id)
    params.append(limit)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM predictions WHERE {where} "
            "ORDER BY timestamp_epoch DESC, timestamp DESC LIMIT ?",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_result(row) for row in rows]


def get_raw_chunks(
    patient_id=None,
    hours=24,
    signal_type=None,
    limit=1000,
    include_payload=False,
    unsynced_only=False,
    db_path=DB_PATH,
):
    hours = _positive_float(hours, "hours")
    limit = _positive_int(limit, "limit")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    params = [since.timestamp()]
    where = "timestamp_start_unix >= ?"
    if patient_id:
        where += " AND patient_id = ?"
        params.append(patient_id)
    if signal_type:
        where += " AND signal_type = ?"
        params.append(str(signal_type).lower())
    if unsynced_only:
        where += " AND is_synced = 0"
    params.append(limit)
    columns = "*" if include_payload else (
        "chunk_id, patient_id, collection_session_id, guided_segment_id, prediction_id, "
        "signal_type, timestamp_start_unix, timestamp_end_unix, timestamp_start_str, "
        "sample_rate_hz, sample_count, channel_count, encoding, checksum_sha256, "
        "is_baseline_usable, is_synced, synced_at, created_at"
    )
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT {columns} FROM raw_signal_chunks WHERE {where} "
            "ORDER BY timestamp_start_unix ASC LIMIT ?",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_raw_chunk_row(row, include_payload=include_payload) for row in rows]


def get_raw_chunk(chunk_id, include_payload=False, db_path=DB_PATH):
    columns = "*" if include_payload else (
        "chunk_id, patient_id, collection_session_id, guided_segment_id, prediction_id, "
        "signal_type, timestamp_start_unix, timestamp_end_unix, timestamp_start_str, "
        "sample_rate_hz, sample_count, channel_count, encoding, checksum_sha256, "
        "is_baseline_usable, is_synced, synced_at, created_at"
    )
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            f"SELECT {columns} FROM raw_signal_chunks WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _raw_chunk_row(row, include_payload=include_payload)


def decode_raw_chunk(chunk):
    if not chunk or "payload_blob" not in chunk:
        raise ValueError("chunk with payload_blob is required.")
    if chunk["signal_type"] == "ecg":
        return _decode_ecg_samples(
            chunk["payload_blob"],
            chunk["sample_count"],
            encoding=chunk["encoding"],
        )
    if chunk["signal_type"] == "acc":
        return _decode_acc_samples(
            chunk["payload_blob"],
            chunk["sample_count"],
            encoding=chunk["encoding"],
        )
    raise ValueError(f"Unsupported signal_type: {chunk['signal_type']}")


def _get_prediction_row_by_id(prediction_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM predictions WHERE prediction_id = ?",
            (prediction_id,),
        ).fetchone()
    finally:
        conn.close()
    return row


def get_latest_ecg(patient_id=None, max_samples=1000, db_path=DB_PATH):
    max_samples = _positive_int(max_samples, "max_samples")
    params = []
    where = ""
    if patient_id:
        where = "WHERE patient_id = ?"
        params.append(patient_id)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            f"SELECT * FROM predictions {where} ORDER BY timestamp_epoch DESC, timestamp DESC LIMIT 1",
            params,
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"prediction": None, "samples": []}

    prediction = _row_to_result(row)
    chunk_ids = prediction.get("raw_ecg_chunk_ids") or []
    samples = []
    for chunk_id in chunk_ids:
        chunk = get_raw_chunk(chunk_id, include_payload=True, db_path=db_path)
        if chunk is not None:
            samples.extend(decode_raw_chunk(chunk))

    if samples:
        if len(samples) > max_samples:
            step = max(1, len(samples) // max_samples)
            samples = samples[::step][:max_samples]
        return {"prediction": prediction, "samples": samples, "source": "raw_signal_chunks"}

    if not row["raw_ecg_path"] or not os.path.exists(row["raw_ecg_path"]):
        return {
            "prediction": prediction,
            "samples": [],
            "source": "missing_raw",
            "reason": "Raw ECG samples are not available locally. They may have been purged after sync.",
        }

    with open(row["raw_ecg_path"], "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for item in reader:
            samples.append(float(item["ecg_uv"]))

    if len(samples) > max_samples:
        step = max(1, len(samples) // max_samples)
        samples = samples[::step][:max_samples]

    return {"prediction": prediction, "samples": samples, "source": "legacy_csv"}


def get_predictions_for_session(patient_id, session_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM predictions
            WHERE patient_id = ? AND session_id = ?
            ORDER BY timestamp_epoch ASC, timestamp ASC
            """,
            (patient_id, session_id),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_result(row) for row in rows]


def mark_raw_chunks_for_segment(
    patient_id,
    start_timestamp,
    end_timestamp,
    guided_segment_id=None,
    collection_session_id=None,
    baseline_usable=True,
    db_path=DB_PATH,
):
    start_epoch = timestamp_to_epoch(start_timestamp)
    end_epoch = timestamp_to_epoch(end_timestamp)
    if start_epoch is None or end_epoch is None:
        return {"updated": 0}
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE raw_signal_chunks
            SET guided_segment_id = COALESCE(?, guided_segment_id),
                collection_session_id = COALESCE(?, collection_session_id),
                is_baseline_usable = ?
            WHERE patient_id = ?
              AND timestamp_start_unix <= ?
              AND timestamp_end_unix >= ?
            """,
            (
                guided_segment_id,
                collection_session_id,
                1 if baseline_usable else 0,
                patient_id,
                end_epoch,
                start_epoch,
            ),
        )
        conn.commit()
        updated = cursor.rowcount
    finally:
        conn.close()
    return {"updated": updated}


def get_collection_sessions(patient_id=None, hours=24, limit=200, db_path=DB_PATH):
    hours = _positive_float(hours, "hours")
    limit = _positive_int(limit, "limit")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    params = [since.isoformat()]
    where = "started_at >= ?"
    if patient_id:
        where += " AND patient_id = ?"
        params.append(patient_id)
    params.append(limit)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM collection_sessions WHERE {where} ORDER BY started_at DESC LIMIT ?",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "collection_session_id": row["collection_session_id"],
            "patient_id": row["patient_id"],
            "purpose": row["purpose"],
            "status": row["status"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "is_synced": bool(row["is_synced"]),
            "synced_at": row["synced_at"],
        }
        for row in rows
    ]


def get_collection_segments(patient_id=None, hours=24, limit=500, db_path=DB_PATH):
    hours = _positive_float(hours, "hours")
    limit = _positive_int(limit, "limit")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    params = [since.isoformat()]
    where = "created_at >= ?"
    if patient_id:
        where += " AND patient_id = ?"
        params.append(patient_id)
    params.append(limit)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM collection_segments WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "collection_segment_id": row["collection_segment_id"],
            "collection_session_id": row["collection_session_id"],
            "patient_id": row["patient_id"],
            "segment_type": row["segment_type"],
            "status": row["status"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "is_synced": bool(row["is_synced"]),
            "synced_at": row["synced_at"],
        }
        for row in rows
    ]


def save_assessment_snapshot(
    snapshot_type,
    payload,
    patient_id=None,
    period=None,
    timestamp=None,
    dedupe_seconds=300,
    db_path=DB_PATH,
):
    timestamp = timestamp or utc_now_iso()
    dedupe_seconds = _positive_float(dedupe_seconds, "dedupe_seconds", allow_zero=True)
    period_json = json.dumps(period or {}, sort_keys=True, ensure_ascii=False)
    snapshot_id = str(uuid.uuid4())
    conn = get_connection(db_path)
    try:
        if dedupe_seconds > 0:
            row = conn.execute(
                """
                SELECT snapshot_id, timestamp, timestamp_epoch FROM assessment_snapshots
                WHERE patient_id IS ?
                  AND snapshot_type = ?
                  AND period_json = ?
                ORDER BY timestamp_epoch DESC
                LIMIT 1
                """,
                (patient_id, snapshot_type, period_json),
            ).fetchone()
            if row is not None:
                latest_epoch = float(row["timestamp_epoch"] or 0)
                current_epoch = timestamp_to_epoch(timestamp) or datetime.now(timezone.utc).timestamp()
                if current_epoch - latest_epoch < dedupe_seconds:
                    return {
                        "snapshot_id": row["snapshot_id"],
                        "snapshot_type": snapshot_type,
                        "timestamp": row["timestamp"],
                        "deduped": True,
                    }
        conn.execute(
            """
            INSERT INTO assessment_snapshots (
                snapshot_id, patient_id, snapshot_type, timestamp, timestamp_epoch,
                period_json, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                patient_id,
                snapshot_type,
                timestamp,
                timestamp_to_epoch(timestamp),
                period_json,
                json.dumps(payload or {}, ensure_ascii=False),
                utc_now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"snapshot_id": snapshot_id, "snapshot_type": snapshot_type, "timestamp": timestamp, "deduped": False}


def get_assessment_snapshots(patient_id=None, hours=24, snapshot_type=None, limit=100, db_path=DB_PATH):
    hours = _positive_float(hours, "hours")
    limit = _positive_int(limit, "limit")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    params = [since.timestamp()]
    where = "timestamp_epoch >= ?"
    if patient_id:
        where += " AND patient_id = ?"
        params.append(patient_id)
    if snapshot_type:
        where += " AND snapshot_type = ?"
        params.append(snapshot_type)
    params.append(limit)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM assessment_snapshots WHERE {where} ORDER BY timestamp_epoch DESC LIMIT ?",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "snapshot_id": row["snapshot_id"],
            "patient_id": row["patient_id"],
            "snapshot_type": row["snapshot_type"],
            "timestamp": row["timestamp"],
            "timestamp_epoch": row["timestamp_epoch"],
            "period": json.loads(row["period_json"] or "{}"),
            "payload": json.loads(row["payload_json"] or "{}"),
            "is_synced": bool(row["is_synced"]),
            "synced_at": row["synced_at"],
        }
        for row in rows
    ]


def mark_raw_chunks_synced(chunk_ids, db_path=DB_PATH):
    chunk_ids = list(chunk_ids or [])
    if not chunk_ids:
        return {"updated": 0}
    placeholders = ",".join("?" for _ in chunk_ids)
    params = [utc_now_iso(), *chunk_ids]
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            f"UPDATE raw_signal_chunks SET is_synced = 1, synced_at = ? WHERE chunk_id IN ({placeholders})",
            params,
        )
        conn.commit()
        updated = cursor.rowcount
    finally:
        conn.close()
    return {"updated": updated}


def mark_collection_sessions_synced(ids, db_path=DB_PATH):
    ids = list(ids or [])
    if not ids:
        return {"updated": 0}
    placeholders = ",".join("?" for _ in ids)
    params = [utc_now_iso(), *ids]
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            f"UPDATE collection_sessions SET is_synced = 1, synced_at = ? WHERE collection_session_id IN ({placeholders})",
            params,
        )
        conn.commit()
        updated = cursor.rowcount
    finally:
        conn.close()
    return {"updated": updated}


def mark_collection_segments_synced(ids, db_path=DB_PATH):
    ids = list(ids or [])
    if not ids:
        return {"updated": 0}
    placeholders = ",".join("?" for _ in ids)
    params = [utc_now_iso(), *ids]
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            f"UPDATE collection_segments SET is_synced = 1, synced_at = ? WHERE collection_segment_id IN ({placeholders})",
            params,
        )
        conn.commit()
        updated = cursor.rowcount
    finally:
        conn.close()
    return {"updated": updated}


def mark_assessment_snapshots_synced(ids, db_path=DB_PATH):
    ids = list(ids or [])
    if not ids:
        return {"updated": 0}
    placeholders = ",".join("?" for _ in ids)
    params = [utc_now_iso(), *ids]
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            f"UPDATE assessment_snapshots SET is_synced = 1, synced_at = ? WHERE snapshot_id IN ({placeholders})",
            params,
        )
        conn.commit()
        updated = cursor.rowcount
    finally:
        conn.close()
    return {"updated": updated}


def purge_synced_raw_chunks(retention_hours=24, limit=10000, db_path=DB_PATH):
    retention_hours = _positive_float(retention_hours, "retention_hours", allow_zero=True)
    limit = _positive_int(limit, "limit")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT chunk_id FROM raw_signal_chunks
            WHERE is_synced = 1
              AND is_baseline_usable = 0
              AND timestamp_start_unix < ?
            ORDER BY timestamp_start_unix ASC
            LIMIT ?
            """,
            (cutoff.timestamp(), limit),
        ).fetchall()
        ids = [row["chunk_id"] for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM raw_signal_chunks WHERE chunk_id IN ({placeholders})", ids)
            conn.commit()
    finally:
        conn.close()
    return {"purged": len(ids), "retention_hours": retention_hours}


def storage_status(db_path=DB_PATH):
    conn = get_connection(db_path)
    try:
        counts = {}
        for table in (
            "predictions",
            "events",
            "raw_signal_chunks",
            "collection_sessions",
            "collection_segments",
            "guided_baseline_sessions",
            "guided_baseline_segments",
            "assessment_snapshots",
        ):
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        raw = conn.execute(
            """
            SELECT signal_type, COUNT(*) AS chunk_count, SUM(sample_count) AS sample_count,
                   SUM(LENGTH(payload_blob)) AS payload_bytes,
                   SUM(CASE WHEN is_synced = 0 THEN 1 ELSE 0 END) AS unsynced_count
            FROM raw_signal_chunks
            GROUP BY signal_type
            """
        ).fetchall()
    finally:
        conn.close()
    return {
        "db_path": db_path,
        "raw_chunk_seconds": DEFAULT_RAW_CHUNK_SECONDS,
        "counts": counts,
        "raw_signal_chunks": [
            {
                "signal_type": row["signal_type"],
                "chunk_count": row["chunk_count"],
                "sample_count": row["sample_count"] or 0,
                "payload_bytes": row["payload_bytes"] or 0,
                "unsynced_count": row["unsynced_count"] or 0,
            }
            for row in raw
        ],
    }


def get_events(
    patient_id=None,
    days=1,
    limit=200,
    event_type=None,
    severity=None,
    db_path=DB_PATH,
):
    since = datetime.now(timezone.utc) - timedelta(days=float(days))
    params = [since.timestamp()]
    where = "timestamp_epoch >= ?"
    if patient_id:
        where += " AND patient_id = ?"
        params.append(patient_id)
    if event_type:
        where += " AND event_type = ?"
        params.append(event_type)
    if severity:
        where += " AND severity = ?"
        params.append(severity)
    params.append(int(limit))

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM events WHERE {where} "
            "ORDER BY timestamp_epoch DESC, timestamp DESC LIMIT ?",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_event(row) for row in rows]


def rebuild_event_table(patient_id=None, days=30, limit=50000, db_path=DB_PATH):
    history = get_history(patient_id=patient_id, days=days, limit=limit, db_path=db_path)
    conn = get_connection(db_path)
    inserted = 0
    try:
        for item in history:
            events = build_events_for_prediction(item)
            _insert_events(conn, events)
            inserted += len(events)
        conn.commit()
    finally:
        conn.close()
    return {
        "status": "rebuilt",
        "prediction_count": len(history),
        "event_count": inserted,
        "patient_id": patient_id,
        "days": days,
    }


def compute_risk_summary(patient_id=None, days=1, db_path=DB_PATH):
    history = get_history(patient_id=patient_id, days=days, limit=1000, db_path=db_path)
    if not history:
        return {"level": "unknown", "score": 0.0, "reason": "No prediction history available."}

    quality_ok = [h for h in history if (h.get("signal_quality") or {}).get("label") in ("good", "fair")]
    if not quality_ok:
        return {"level": "unknown", "score": 0.0, "reason": "No reliable ECG segments in selected period."}

    recent = quality_ok[:10]
    abnormal_daily = sum(1 for h in quality_ok if (h.get("anomaly") or {}).get("value") == 1) / len(quality_ok)
    abnormal_recent = sum(1 for h in recent if (h.get("anomaly") or {}).get("value") == 1) / len(recent)
    stress_recent = sum(1 for h in recent if (h.get("stress") or {}).get("label") == "stress") / len(recent)

    score = min(1.0, 0.65 * abnormal_recent + 0.25 * abnormal_daily + 0.10 * stress_recent)
    if score >= 0.65:
        level = "high"
    elif score >= 0.35:
        level = "medium"
    else:
        level = "low"

    reason = (
        f"Recent abnormal ratio {abnormal_recent:.0%}, "
        f"daily abnormal ratio {abnormal_daily:.0%}, recent stress ratio {stress_recent:.0%}."
    )
    return {"level": level, "score": round(float(score), 3), "reason": reason}


def _count_items(history, getter):
    counts = {}
    for item in history:
        key = getter(item) or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _safe_dt(item):
    timestamp = item.get("timestamp")
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except Exception:
        epoch = item.get("timestamp_epoch")
        if epoch is None:
            return None
        dt = datetime.fromtimestamp(float(epoch), timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _duration_seconds(items):
    if len(items) < 2:
        return 0.0
    first = _safe_dt(items[0])
    last = _safe_dt(items[-1])
    if first is None or last is None:
        return 0.0
    return max(0.0, (last - first).total_seconds())


def _ratio(items, predicate):
    if not items:
        return 0.0
    return sum(1 for item in items if predicate(item)) / len(items)


def _af_suspicion(item):
    rhythm = item.get("rhythm") or {}
    rhythm_alert = item.get("rhythm_alert") or {}
    return (
        rhythm.get("label") == "possible_afib"
        or float(rhythm.get("possible_afib_probability") or 0.0) >= 0.05
        or rhythm_alert.get("level") in {"medium", "high", "critical"}
    )


def _summary_for_items(items):
    hr_values = [float(item["heart_rate_bpm"]) for item in items if item.get("heart_rate_bpm") is not None]
    afib_values = [
        float((item.get("rhythm") or {}).get("possible_afib_probability") or 0.0)
        for item in items
    ]
    af_burden_values = [
        float((item.get("af_episode") or {}).get("af_burden_percent") or 0.0)
        for item in items
    ]
    event_counts = _count_items(
        [event for item in items for event in build_events_for_prediction(item)],
        lambda event: event.get("event_type"),
    )
    return {
        "window_count": len(items),
        "duration_seconds": round(_duration_seconds(items), 2),
        "mean_heart_rate_bpm": round(sum(hr_values) / len(hr_values), 2) if hr_values else None,
        "min_heart_rate_bpm": round(min(hr_values), 2) if hr_values else None,
        "max_heart_rate_bpm": round(max(hr_values), 2) if hr_values else None,
        "mean_afib_probability": round(sum(afib_values) / len(afib_values), 4) if afib_values else 0.0,
        "max_afib_probability": round(max(afib_values), 4) if afib_values else 0.0,
        "max_af_burden_percent": round(max(af_burden_values), 2) if af_burden_values else 0.0,
        "af_suspicion_window_ratio": round(_ratio(items, _af_suspicion), 4),
        "good_signal_ratio": round(
            _ratio(items, lambda item: (item.get("signal_quality") or {}).get("label") in {"good", "fair"}),
            4,
        ),
        "poor_signal_count": sum(
            1
            for item in items
            if (item.get("signal_quality") or {}).get("label")
            in {"poor", "noise", "poor_contact", "motion_artifact"}
        ),
        "rhythm_counts": _count_items(items, lambda item: (item.get("rhythm") or {}).get("label")),
        "ectopy_counts": _count_items(items, lambda item: (item.get("ectopy") or {}).get("label")),
        "rhythm_alert_counts": _count_items(items, lambda item: (item.get("rhythm_alert") or {}).get("level")),
        "quality_counts": _count_items(items, lambda item: (item.get("signal_quality") or {}).get("label")),
        "activity_counts": _count_items(items, lambda item: (item.get("sensor_context") or {}).get("activity_state")),
        "hr_event_counts": _count_items(items, lambda item: (item.get("hr_event") or {}).get("label")),
        "stress_counts": _count_items(items, lambda item: (item.get("stress") or {}).get("label")),
        "alert_counts": _count_items(items, lambda item: item.get("alert_level")),
        "event_counts": event_counts,
    }


def compute_session_summary(patient_id=None, days=1, db_path=DB_PATH):
    history = list(reversed(get_history(patient_id=patient_id, days=days, limit=5000, db_path=db_path)))
    if not history:
        return {"session_count": 0, "window_count": 0, "sessions": [], "overall": {}}

    sessions = {}
    for item in history:
        key = (item.get("patient_id") or "unknown", item.get("session_id") or "unknown")
        sessions.setdefault(key, []).append(item)

    session_rows = []
    for (pid, session_id), items in sorted(sessions.items(), key=lambda pair: pair[0]):
        summary = _summary_for_items(items)
        session_rows.append(
            {
                "patient_id": pid,
                "session_id": session_id,
                "start_timestamp": items[0].get("timestamp"),
                "end_timestamp": items[-1].get("timestamp"),
                **summary,
            }
        )

    return {
        "session_count": len(session_rows),
        "window_count": len(history),
        "overall": _summary_for_items(history),
        "sessions": session_rows,
    }


def compute_daily_summary(patient_id=None, days=7, db_path=DB_PATH):
    history = list(reversed(get_history(patient_id=patient_id, days=days, limit=5000, db_path=db_path)))
    if not history:
        return {"day_count": 0, "window_count": 0, "days": [], "overall": {}}

    grouped = {}
    for item in history:
        dt = _safe_dt(item)
        day = dt.date().isoformat() if dt is not None else "unknown"
        grouped.setdefault(day, []).append(item)

    day_rows = []
    for day, items in sorted(grouped.items()):
        patients = sorted({item.get("patient_id") or "unknown" for item in items})
        sessions = sorted({item.get("session_id") or "unknown" for item in items})
        day_rows.append(
            {
                "day": day,
                "patient_ids": patients,
                "session_count": len(sessions),
                "session_ids": sessions,
                **_summary_for_items(items),
            }
        )

    return {
        "day_count": len(day_rows),
        "window_count": len(history),
        "overall": _summary_for_items(history),
        "days": day_rows,
    }


def _build_event_timeline_from_predictions(patient_id=None, days=1, limit=200, db_path=DB_PATH):
    history = list(reversed(get_history(patient_id=patient_id, days=days, limit=5000, db_path=db_path)))
    events = []
    for item in history:
        events.extend(build_events_for_prediction(item))
    return {"event_count": len(events[-int(limit) :]), "events": events[-int(limit) :]}


def build_event_timeline(patient_id=None, days=1, limit=200, db_path=DB_PATH):
    events = list(
        reversed(
            get_events(
                patient_id=patient_id,
                days=days,
                limit=limit,
                db_path=db_path,
            )
        )
    )
    if events:
        return {"event_count": len(events), "events": events}
    return _build_event_timeline_from_predictions(
        patient_id=patient_id,
        days=days,
        limit=limit,
        db_path=db_path,
    )
