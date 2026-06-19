import argparse
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from src.config.env_loader import load_env_file
from src.storage.ecg_storage import (
    build_event_timeline,
    compute_risk_summary,
    compute_session_summary,
    get_assessment_snapshots,
    get_collection_segments,
    get_collection_sessions,
    get_history,
    get_raw_chunks,
    get_unsynced_daily_rollups,
    mark_assessment_snapshots_synced,
    mark_daily_rollups_synced,
    mark_collection_segments_synced,
    mark_collection_sessions_synced,
    mark_raw_chunks_synced,
)
from src.calibration.personal_baseline import load_personal_baseline


load_env_file()

_logger = logging.getLogger("elderly_care.mongodb_sync")

DEFAULT_MONGODB_URI = os.getenv("MONGODB_URI")
DEFAULT_MONGODB_DB = os.getenv("MONGODB_DB", "elderly_care")
BULK_BATCH_SIZE = int(os.getenv("MONGODB_BULK_BATCH_SIZE", "200"))

# Module-level MongoClient cache. MongoClient builds a connection pool
# (~1-3s over Wi-Fi on Pi) so reusing across sync cycles dramatically
# cuts per-cycle overhead. Keyed by (uri, db_name).
_CLIENT_LOCK = threading.Lock()
_CLIENT_CACHE = {}
_INDEXES_ENSURED = set()


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_mongodb_configured(uri=None):
    load_env_file()
    return bool(uri or os.getenv("MONGODB_URI") or DEFAULT_MONGODB_URI)


def _load_pymongo():
    try:
        from pymongo import ASCENDING, MongoClient, UpdateOne
    except ImportError as exc:
        raise ImportError(
            "pymongo is required for MongoDB sync. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc
    return MongoClient, ASCENDING, UpdateOne


def _make_client(uri):
    """Build a MongoClient tuned for an edge device on flaky Wi-Fi.

    Timeouts widened from the pymongo defaults because Atlas DNS SRV
    resolution + TLS handshake can take 5-10s over a weak link.
    retryWrites=True is critical: bulk_write batches will be retried
    once on transient network errors instead of throwing.
    """
    MongoClient, _, _ = _load_pymongo()
    return MongoClient(
        uri,
        serverSelectionTimeoutMS=15000,
        connectTimeoutMS=20000,
        socketTimeoutMS=60000,
        retryWrites=True,
        w="majority",
        appname="elderly_care_pi",
    )


def get_mongo_database(uri=None, db_name=None):
    """Return (client, db). Reuses a cached MongoClient when possible.

    The caller MUST NOT call client.close() — closing kills the cached pool
    and forces every subsequent cycle to rebuild it. Use close_all_clients()
    on graceful shutdown only.
    """
    load_env_file()
    uri = uri or os.getenv("MONGODB_URI") or DEFAULT_MONGODB_URI
    if not uri:
        raise ValueError("MONGODB_URI is not configured.")
    db_name = db_name or os.getenv("MONGODB_DB") or DEFAULT_MONGODB_DB
    cache_key = (uri, db_name)
    with _CLIENT_LOCK:
        client = _CLIENT_CACHE.get(cache_key)
        if client is None:
            client = _make_client(uri)
            _CLIENT_CACHE[cache_key] = client
    return client, client[db_name]


def close_all_clients():
    """Tear down every cached MongoClient. Call on app shutdown."""
    with _CLIENT_LOCK:
        for client in _CLIENT_CACHE.values():
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        _CLIENT_CACHE.clear()
        _INDEXES_ENSURED.clear()


def _bulk_upsert(collection, key_field, docs, batch_size=BULK_BATCH_SIZE):
    """Upsert docs by key_field in batches. Returns (count_written, ids).

    Uses bulk_write(ordered=False) so one bad doc doesn't abort the batch.
    Much faster than per-doc update_one over slow links (1 round-trip per
    batch instead of per doc).
    """
    if not docs:
        return 0, []
    _, _, UpdateOne = _load_pymongo()
    written = 0
    ids = []
    for start in range(0, len(docs), batch_size):
        batch = docs[start : start + batch_size]
        ops = [
            UpdateOne({key_field: doc[key_field]}, {"$set": doc}, upsert=True)
            for doc in batch
        ]
        result = collection.bulk_write(ops, ordered=False)
        written += int(result.upserted_count or 0) + int(result.modified_count or 0)
        ids.extend(doc[key_field] for doc in batch)
    return written, ids


def ensure_indexes(db):
    """Idempotent index creation; cached per (db.name) so we don't
    re-send 13 create_index round-trips on every sync cycle.
    """
    cache_key = getattr(db, "name", str(db))
    with _CLIENT_LOCK:
        if cache_key in _INDEXES_ENSURED:
            return
    _, ASCENDING, _ = _load_pymongo()
    db.predictions.create_index([("prediction_id", ASCENDING)], unique=True)
    db.predictions.create_index([("patient_id", ASCENDING), ("timestamp_epoch", ASCENDING)])
    db.events.create_index([("event_id", ASCENDING)], unique=True)
    db.events.create_index([("patient_id", ASCENDING), ("timestamp", ASCENDING)])
    db.session_summaries.create_index([("summary_id", ASCENDING)], unique=True)
    db.risk_summaries.create_index([("summary_id", ASCENDING)], unique=True)
    db.raw_signal_chunks.create_index([("chunk_id", ASCENDING)], unique=True)
    db.raw_signal_chunks.create_index([("patient_id", ASCENDING), ("timestamp_start_unix", ASCENDING)])
    db.collection_sessions.create_index([("collection_session_id", ASCENDING)], unique=True)
    db.collection_segments.create_index([("collection_segment_id", ASCENDING)], unique=True)
    db.assessment_snapshots.create_index([("snapshot_id", ASCENDING)], unique=True)
    db.personal_baselines.create_index([("patient_id", ASCENDING)], unique=True)
    db.daily_rollups.create_index([("rollup_id", ASCENDING)], unique=True)
    db.daily_rollups.create_index([("patient_id", ASCENDING), ("day", ASCENDING)])
    db.sync_runs.create_index([("synced_at", ASCENDING)])
    with _CLIENT_LOCK:
        _INDEXES_ENSURED.add(cache_key)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def event_id_for(event):
    payload = {
        "patient_id": event.get("patient_id"),
        "session_id": event.get("session_id"),
        "timestamp": event.get("timestamp"),
        "event_type": event.get("event_type"),
        "severity": event.get("severity"),
        "label": event.get("label"),
        "message": event.get("message"),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _prediction_doc(prediction, include_raw_samples=False):
    doc = _json_safe(dict(prediction))
    doc["synced_at"] = utc_now_iso()
    doc["storage_strategy"] = {
        "raw_ecg": "file_path",
        "raw_acc": "file_path",
        "include_raw_samples": bool(include_raw_samples),
    }
    if not include_raw_samples:
        doc.pop("ecg_samples", None)
        doc.pop("acc_samples", None)
    return doc


def _raw_chunk_doc(chunk):
    try:
        from bson.binary import Binary
    except ImportError:
        Binary = None
    doc = _json_safe({key: value for key, value in chunk.items() if key != "payload_blob"})
    if "payload_blob" in chunk:
        doc["payload_blob"] = Binary(chunk["payload_blob"]) if Binary else chunk["payload_blob"]
    doc["synced_at"] = utc_now_iso()
    return doc


def _session_summary_docs(summary, days, patient_id=None):
    docs = []
    for session in summary.get("sessions") or []:
        patient_id = session.get("patient_id") or "unknown"
        session_id = session.get("session_id") or "unknown"
        doc = _json_safe(dict(session))
        doc["summary_id"] = f"{patient_id}:{session_id}"
        doc["summary_type"] = "session"
        doc["source_days"] = float(days)
        doc["synced_at"] = utc_now_iso()
        docs.append(doc)

    overall = _json_safe(dict(summary.get("overall") or {}))
    overall_patient = patient_id or "all"
    doc = {
        "summary_id": f"{overall_patient}:overall:{float(days)}d",
        "summary_type": "overall_window",
        "patient_id": overall_patient,
        "source_days": float(days),
        "session_count": int(summary.get("session_count") or 0),
        "window_count": int(summary.get("window_count") or 0),
        "overall": overall,
        "synced_at": utc_now_iso(),
    }
    docs.append(doc)
    return docs


def sync_to_mongodb(
    patient_id=None,
    days=1,
    limit=5000,
    uri=None,
    db_name=None,
    include_raw_samples=False,
):
    """Sync local SQLite tables to MongoDB Atlas.

    Uses bulk_write batches (BULK_BATCH_SIZE=200) instead of per-doc
    update_one — over a slow Wi-Fi link this drops cycle time from minutes
    to seconds for a typical 5000-prediction batch.

    Idempotent: all upserts keyed by stable ids (prediction_id, event_id,
    chunk_id, ...) so re-running a failed sync does not duplicate data.
    mark_*_synced is called PER COLLECTION after that collection's bulk
    completes — if a later collection fails, earlier ones stay marked
    synced and won't be re-uploaded.
    """
    client, db = get_mongo_database(uri=uri, db_name=db_name)
    # Liveness check before any write. Cheap (~1 round-trip) and surfaces
    # network/auth errors as a clean exception rather than mid-bulk fail.
    client.admin.command("ping")
    ensure_indexes(db)

    # --- predictions ---
    history = get_history(patient_id=patient_id, days=days, limit=limit)
    prediction_docs = [
        _prediction_doc(p, include_raw_samples=include_raw_samples)
        for p in history
    ]
    prediction_upserts, _ = _bulk_upsert(
        db.predictions, "prediction_id", prediction_docs
    )

    # --- events ---
    events_payload = build_event_timeline(patient_id=patient_id, days=days, limit=limit)
    event_docs = []
    for event in events_payload.get("events") or []:
        doc = _json_safe(dict(event))
        doc["event_id"] = event_id_for(doc)
        doc["synced_at"] = utc_now_iso()
        event_docs.append(doc)
    event_upserts, _ = _bulk_upsert(db.events, "event_id", event_docs)

    # --- session summaries ---
    session_summary = compute_session_summary(patient_id=patient_id, days=days)
    session_summary_docs_list = _session_summary_docs(
        session_summary, days=days, patient_id=patient_id
    )
    session_summary_upserts, _ = _bulk_upsert(
        db.session_summaries, "summary_id", session_summary_docs_list
    )

    # --- risk summary (single doc) ---
    risk = compute_risk_summary(patient_id=patient_id, days=days)
    risk_doc = {
        "summary_id": f"{patient_id or 'all'}:risk:{float(days)}d",
        "patient_id": patient_id,
        "source_days": float(days),
        "risk": _json_safe(risk),
        "synced_at": utc_now_iso(),
    }
    risk_result = db.risk_summaries.update_one(
        {"summary_id": risk_doc["summary_id"]}, {"$set": risk_doc}, upsert=True
    )

    # --- raw chunks (BLOBs) ---
    raw_chunks = get_raw_chunks(
        patient_id=patient_id,
        hours=float(days) * 24.0,
        limit=limit,
        include_payload=True,
        unsynced_only=True,
    )
    raw_chunk_docs = [_raw_chunk_doc(c) for c in raw_chunks]
    raw_chunk_upserts, raw_chunk_ids = _bulk_upsert(
        db.raw_signal_chunks, "chunk_id", raw_chunk_docs
    )
    # Only mark synced AFTER the bulk completes — if bulk_write raised,
    # we never reach here, and is_synced stays 0 so next cycle retries.
    mark_raw_chunks_synced(raw_chunk_ids)

    # --- collection sessions ---
    collection_sessions = [
        item
        for item in get_collection_sessions(
            patient_id=patient_id, hours=float(days) * 24.0, limit=limit
        )
        if not item.get("is_synced")
    ]
    collection_session_docs = []
    for item in collection_sessions:
        doc = _json_safe(dict(item))
        doc["synced_at"] = utc_now_iso()
        collection_session_docs.append(doc)
    collection_session_upserts, collection_session_ids = _bulk_upsert(
        db.collection_sessions, "collection_session_id", collection_session_docs
    )
    mark_collection_sessions_synced(collection_session_ids)

    # --- collection segments ---
    collection_segments = [
        item
        for item in get_collection_segments(
            patient_id=patient_id, hours=float(days) * 24.0, limit=limit
        )
        if not item.get("is_synced")
    ]
    collection_segment_docs = []
    for item in collection_segments:
        doc = _json_safe(dict(item))
        doc["synced_at"] = utc_now_iso()
        collection_segment_docs.append(doc)
    collection_segment_upserts, collection_segment_ids = _bulk_upsert(
        db.collection_segments, "collection_segment_id", collection_segment_docs
    )
    mark_collection_segments_synced(collection_segment_ids)

    # --- assessment snapshots ---
    assessment_snapshots = [
        item
        for item in get_assessment_snapshots(
            patient_id=patient_id, hours=float(days) * 24.0, limit=limit
        )
        if not item.get("is_synced")
    ]
    assessment_snapshot_docs = []
    for item in assessment_snapshots:
        doc = _json_safe(dict(item))
        doc["synced_at"] = utc_now_iso()
        assessment_snapshot_docs.append(doc)
    assessment_snapshot_upserts, assessment_snapshot_ids = _bulk_upsert(
        db.assessment_snapshots, "snapshot_id", assessment_snapshot_docs
    )
    mark_assessment_snapshots_synced(assessment_snapshot_ids)

    # --- daily rollups (pre-aggregated per-day metrics) ---
    daily_rollups = get_unsynced_daily_rollups(patient_id=patient_id, limit=limit)
    daily_rollup_docs = []
    for item in daily_rollups:
        doc = _json_safe({k: v for k, v in item.items() if k != "metrics_json"})
        doc["synced_at"] = utc_now_iso()
        daily_rollup_docs.append(doc)
    daily_rollup_upserts, daily_rollup_ids = _bulk_upsert(
        db.daily_rollups, "rollup_id", daily_rollup_docs
    )
    mark_daily_rollups_synced([d["rollup_id"] for d in daily_rollup_docs])

    # --- personal baseline (single doc per patient) ---
    personal_baseline_upserted = False
    if patient_id:
        baseline = load_personal_baseline(patient_id)
        if baseline:
            baseline_doc = _json_safe(dict(baseline))
            baseline_doc["synced_at"] = utc_now_iso()
            baseline_result = db.personal_baselines.update_one(
                {"patient_id": patient_id},
                {"$set": baseline_doc},
                upsert=True,
            )
            personal_baseline_upserted = bool(
                baseline_result.upserted_id is not None or baseline_result.modified_count
            )

    sync_run = {
        "patient_id": patient_id,
        "days": float(days),
        "limit": int(limit),
        "prediction_count": len(history),
        "event_count": len(events_payload.get("events") or []),
        "session_summary_count": len(session_summary.get("sessions") or []),
        "raw_chunk_count": len(raw_chunks),
        "collection_session_count": len(collection_sessions),
        "collection_segment_count": len(collection_segments),
        "assessment_snapshot_count": len(assessment_snapshots),
        "daily_rollup_count": len(daily_rollups),
        "include_raw_samples": bool(include_raw_samples),
        "synced_at": utc_now_iso(),
    }
    db.sync_runs.insert_one(sync_run)

    return {
        "status": "synced",
        "database": db.name,
        "patient_id": patient_id,
        "days": float(days),
        "limit": int(limit),
        "prediction_count": len(history),
        "prediction_upserts": prediction_upserts,
        "event_count": len(events_payload.get("events") or []),
        "event_upserts": event_upserts,
        "session_summary_upserts": session_summary_upserts,
        "risk_summary_upserted": bool(
            risk_result.upserted_id is not None or risk_result.modified_count
        ),
        "raw_chunk_count": len(raw_chunks),
        "raw_chunk_upserts": raw_chunk_upserts,
        "collection_session_upserts": collection_session_upserts,
        "collection_segment_upserts": collection_segment_upserts,
        "assessment_snapshot_upserts": assessment_snapshot_upserts,
        "daily_rollup_count": len(daily_rollups),
        "daily_rollup_upserts": daily_rollup_upserts,
        "personal_baseline_upserted": personal_baseline_upserted,
        "raw_storage": "blob_chunks" if raw_chunks else "no_unsynced_chunks",
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Sync local SQLite ECG monitor data to MongoDB.")
    parser.add_argument("--patient-id", default=None)
    parser.add_argument("--days", type=float, default=1)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--uri", default=None, help="MongoDB URI. Defaults to MONGODB_URI.")
    parser.add_argument("--db-name", default=None, help="MongoDB database. Defaults to MONGODB_DB or elderly_care.")
    parser.add_argument("--include-raw-samples", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    result = sync_to_mongodb(
        patient_id=args.patient_id,
        days=args.days,
        limit=args.limit,
        uri=args.uri,
        db_name=args.db_name,
        include_raw_samples=args.include_raw_samples,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
