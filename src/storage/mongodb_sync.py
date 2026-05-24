import argparse
import hashlib
import json
import os
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
    mark_assessment_snapshots_synced,
    mark_collection_segments_synced,
    mark_collection_sessions_synced,
    mark_raw_chunks_synced,
)
from src.calibration.personal_baseline import load_personal_baseline


load_env_file()

DEFAULT_MONGODB_URI = os.getenv("MONGODB_URI")
DEFAULT_MONGODB_DB = os.getenv("MONGODB_DB", "elderly_care")


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_mongodb_configured(uri=None):
    load_env_file()
    return bool(uri or os.getenv("MONGODB_URI") or DEFAULT_MONGODB_URI)


def _load_pymongo():
    try:
        from pymongo import ASCENDING, MongoClient
    except ImportError as exc:
        raise ImportError(
            "pymongo is required for MongoDB sync. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc
    return MongoClient, ASCENDING


def get_mongo_database(uri=None, db_name=None):
    load_env_file()
    uri = uri or os.getenv("MONGODB_URI") or DEFAULT_MONGODB_URI
    if not uri:
        raise ValueError("MONGODB_URI is not configured.")
    MongoClient, _ = _load_pymongo()
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client[db_name or os.getenv("MONGODB_DB") or DEFAULT_MONGODB_DB]
    return client, db


def ensure_indexes(db):
    _, ASCENDING = _load_pymongo()
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
    db.sync_runs.create_index([("synced_at", ASCENDING)])


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
    client, db = get_mongo_database(uri=uri, db_name=db_name)
    try:
        # Force a quick connectivity check before any write.
        client.admin.command("ping")
        ensure_indexes(db)

        history = get_history(patient_id=patient_id, days=days, limit=limit)
        prediction_upserts = 0
        for prediction in history:
            doc = _prediction_doc(prediction, include_raw_samples=include_raw_samples)
            result = db.predictions.update_one(
                {"prediction_id": doc["prediction_id"]},
                {"$set": doc},
                upsert=True,
            )
            if result.upserted_id is not None or result.modified_count:
                prediction_upserts += 1

        events_payload = build_event_timeline(patient_id=patient_id, days=days, limit=limit)
        event_upserts = 0
        for event in events_payload.get("events") or []:
            doc = _json_safe(dict(event))
            doc["event_id"] = event_id_for(doc)
            doc["synced_at"] = utc_now_iso()
            result = db.events.update_one(
                {"event_id": doc["event_id"]},
                {"$set": doc},
                upsert=True,
            )
            if result.upserted_id is not None or result.modified_count:
                event_upserts += 1

        session_summary = compute_session_summary(patient_id=patient_id, days=days)
        session_summary_upserts = 0
        for doc in _session_summary_docs(session_summary, days=days, patient_id=patient_id):
            result = db.session_summaries.update_one(
                {"summary_id": doc["summary_id"]},
                {"$set": doc},
                upsert=True,
            )
            if result.upserted_id is not None or result.modified_count:
                session_summary_upserts += 1

        risk = compute_risk_summary(patient_id=patient_id, days=days)
        risk_doc = {
            "summary_id": f"{patient_id or 'all'}:risk:{float(days)}d",
            "patient_id": patient_id,
            "source_days": float(days),
            "risk": _json_safe(risk),
            "synced_at": utc_now_iso(),
        }
        risk_result = db.risk_summaries.update_one(
            {"summary_id": risk_doc["summary_id"]},
            {"$set": risk_doc},
            upsert=True,
        )

        raw_chunks = get_raw_chunks(
            patient_id=patient_id,
            hours=float(days) * 24.0,
            limit=limit,
            include_payload=True,
            unsynced_only=True,
        )
        raw_chunk_upserts = 0
        raw_chunk_ids = []
        for chunk in raw_chunks:
            doc = _raw_chunk_doc(chunk)
            result = db.raw_signal_chunks.update_one(
                {"chunk_id": doc["chunk_id"]},
                {"$set": doc},
                upsert=True,
            )
            raw_chunk_ids.append(doc["chunk_id"])
            if result.upserted_id is not None or result.modified_count:
                raw_chunk_upserts += 1
        mark_raw_chunks_synced(raw_chunk_ids)

        collection_sessions = [
            item
            for item in get_collection_sessions(patient_id=patient_id, hours=float(days) * 24.0, limit=limit)
            if not item.get("is_synced")
        ]
        collection_session_upserts = 0
        collection_session_ids = []
        for item in collection_sessions:
            doc = _json_safe(dict(item))
            doc["synced_at"] = utc_now_iso()
            result = db.collection_sessions.update_one(
                {"collection_session_id": doc["collection_session_id"]},
                {"$set": doc},
                upsert=True,
            )
            collection_session_ids.append(doc["collection_session_id"])
            if result.upserted_id is not None or result.modified_count:
                collection_session_upserts += 1
        mark_collection_sessions_synced(collection_session_ids)

        collection_segments = [
            item
            for item in get_collection_segments(patient_id=patient_id, hours=float(days) * 24.0, limit=limit)
            if not item.get("is_synced")
        ]
        collection_segment_upserts = 0
        collection_segment_ids = []
        for item in collection_segments:
            doc = _json_safe(dict(item))
            doc["synced_at"] = utc_now_iso()
            result = db.collection_segments.update_one(
                {"collection_segment_id": doc["collection_segment_id"]},
                {"$set": doc},
                upsert=True,
            )
            collection_segment_ids.append(doc["collection_segment_id"])
            if result.upserted_id is not None or result.modified_count:
                collection_segment_upserts += 1
        mark_collection_segments_synced(collection_segment_ids)

        assessment_snapshots = [
            item
            for item in get_assessment_snapshots(patient_id=patient_id, hours=float(days) * 24.0, limit=limit)
            if not item.get("is_synced")
        ]
        assessment_snapshot_upserts = 0
        assessment_snapshot_ids = []
        for item in assessment_snapshots:
            doc = _json_safe(dict(item))
            doc["synced_at"] = utc_now_iso()
            result = db.assessment_snapshots.update_one(
                {"snapshot_id": doc["snapshot_id"]},
                {"$set": doc},
                upsert=True,
            )
            assessment_snapshot_ids.append(doc["snapshot_id"])
            if result.upserted_id is not None or result.modified_count:
                assessment_snapshot_upserts += 1
        mark_assessment_snapshots_synced(assessment_snapshot_ids)

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
            "risk_summary_upserted": bool(risk_result.upserted_id is not None or risk_result.modified_count),
            "raw_chunk_count": len(raw_chunks),
            "raw_chunk_upserts": raw_chunk_upserts,
            "collection_session_upserts": collection_session_upserts,
            "collection_segment_upserts": collection_segment_upserts,
            "assessment_snapshot_upserts": assessment_snapshot_upserts,
            "personal_baseline_upserted": personal_baseline_upserted,
            "raw_storage": "blob_chunks" if raw_chunks else "no_unsynced_chunks",
        }
    finally:
        client.close()


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
