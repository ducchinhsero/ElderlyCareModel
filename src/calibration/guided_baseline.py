import json
import uuid
from datetime import datetime, timezone

from src.calibration.personal_baseline import update_progressive_personal_baseline
from src.storage.ecg_storage import (
    DB_PATH,
    get_connection,
    get_history,
    mark_raw_chunks_for_segment,
    timestamp_to_epoch,
    utc_now_iso,
)


SEGMENT_PLAN = [
    {
        "segment_type": "REST",
        "expected_activity": "REST",
        "duration_seconds": 300,
        "min_valid_windows": 2,
        "instruction": "Sit or lie down quietly and keep the Polar H10 strap stable.",
    },
    {
        "segment_type": "WALK",
        "expected_activity": "WALK",
        "duration_seconds": 300,
        "min_valid_windows": 2,
        "instruction": "Walk slowly in a safe area.",
    },
    {
        "segment_type": "ACTIVE",
        "expected_activity": "ACTIVE",
        "duration_seconds": 180,
        "min_valid_windows": 1,
        "instruction": "Do light daily movement. Do not run or jump.",
        "skippable": True,
    },
]

RELIABLE_SIGNAL_LABELS = {"good", "fair"}
VALID_SEGMENT_STATUSES = {"completed", "skipped"}


def _safe_patient_id(patient_id):
    patient_id = patient_id or "polar_h10"
    return str(patient_id)


def _safe_dt(value):
    if not value:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _segment_config(segment_type):
    segment_type = str(segment_type or "").upper()
    for item in SEGMENT_PLAN:
        if item["segment_type"] == segment_type:
            return item
    raise ValueError(f"Unsupported guided baseline segment: {segment_type}")


def _json_loads(value, fallback):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _row_to_session(row, segments=None):
    return {
        "session_id": row["session_id"],
        "patient_id": row["patient_id"],
        "day_index": row["day_index"],
        "target_days": row["target_days"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "metadata": _json_loads(row["metadata_json"], {}),
        "segments": segments or [],
    }


def _row_to_segment(row):
    return {
        "segment_id": row["segment_id"],
        "session_id": row["session_id"],
        "patient_id": row["patient_id"],
        "day_index": row["day_index"],
        "segment_type": row["segment_type"],
        "expected_activity": row["expected_activity"],
        "duration_seconds": row["duration_seconds"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "valid_window_count": row["valid_window_count"],
        "rejected_window_count": row["rejected_window_count"],
        "rejection_reasons": _json_loads(row["rejection_reasons_json"], []),
        "status": row["status"],
    }


def _completed_day_count(conn, patient_id):
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT day_index) AS count
        FROM guided_baseline_sessions
        WHERE patient_id = ? AND status IN ('completed', 'partial')
        """,
        (patient_id,),
    ).fetchone()
    return int(row["count"] or 0)


def _latest_session(conn, patient_id):
    session = conn.execute(
        """
        SELECT * FROM guided_baseline_sessions
        WHERE patient_id = ?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if session is None:
        return None
    segments = conn.execute(
        """
        SELECT * FROM guided_baseline_segments
        WHERE session_id = ?
        ORDER BY CASE segment_type WHEN 'REST' THEN 1 WHEN 'WALK' THEN 2 WHEN 'ACTIVE' THEN 3 ELSE 4 END
        """,
        (session["session_id"],),
    ).fetchall()
    return _row_to_session(session, [_row_to_segment(row) for row in segments])


def get_guided_baseline_status(patient_id="polar_h10", target_days=7, db_path=DB_PATH):
    patient_id = _safe_patient_id(patient_id)
    conn = get_connection(db_path)
    try:
        completed_days = _completed_day_count(conn, patient_id)
        latest = _latest_session(conn, patient_id)
    finally:
        conn.close()

    status = "not_ready"
    if completed_days >= int(target_days):
        status = "ready"
    elif completed_days > 0:
        status = "warming_up"

    return {
        "patient_id": patient_id,
        "status": status,
        "day_count": completed_days,
        "target_days": int(target_days),
        "progress_ratio": round(min(1.0, completed_days / float(target_days)), 4),
        "segment_plan": SEGMENT_PLAN,
        "latest_session": latest,
    }


def start_guided_baseline_session(patient_id="polar_h10", target_days=7, db_path=DB_PATH):
    patient_id = _safe_patient_id(patient_id)
    now = utc_now_iso()
    session_id = str(uuid.uuid4())
    conn = get_connection(db_path)
    try:
        day_index = min(_completed_day_count(conn, patient_id) + 1, int(target_days))
        conn.execute(
            """
            INSERT INTO guided_baseline_sessions (
                session_id, patient_id, day_index, target_days, status,
                started_at, completed_at, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                patient_id,
                day_index,
                int(target_days),
                "in_progress",
                now,
                None,
                json.dumps({"mode": "guided_7_day", "warmup_seconds": 60}, ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO collection_sessions (
                collection_session_id, patient_id, purpose, status,
                started_at, ended_at, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                patient_id,
                "guided_baseline",
                "in_progress",
                now,
                None,
                json.dumps({"target_days": int(target_days), "day_index": day_index}, ensure_ascii=False),
                now,
                now,
            ),
        )
        for item in SEGMENT_PLAN:
            segment_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO guided_baseline_segments (
                    segment_id, session_id, patient_id, day_index, segment_type,
                    expected_activity, duration_seconds, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment_id,
                    session_id,
                    patient_id,
                    day_index,
                    item["segment_type"],
                    item["expected_activity"],
                    int(item["duration_seconds"]),
                    "pending",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO collection_segments (
                    collection_segment_id, collection_session_id, patient_id,
                    segment_type, status, started_at, ended_at,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment_id,
                    session_id,
                    patient_id,
                    item["segment_type"],
                    "pending",
                    None,
                    None,
                    json.dumps(
                        {
                            "expected_activity": item["expected_activity"],
                            "duration_seconds": int(item["duration_seconds"]),
                            "min_valid_windows": int(item.get("min_valid_windows") or 1),
                        },
                        ensure_ascii=False,
                    ),
                    now,
                    now,
                ),
            )
        conn.commit()
        latest = _latest_session(conn, patient_id)
    finally:
        conn.close()
    return {"status": "started", "session": latest, **get_guided_baseline_status(patient_id, target_days, db_path)}


def _activity_matches(actual, expected):
    actual = str(actual or "UNKNOWN").upper()
    expected = str(expected or "UNKNOWN").upper()
    if expected == "ACTIVE":
        return actual in {"ACTIVE", "WALK"}
    return actual == expected


def _validate_segment_windows(history, expected_activity):
    valid = []
    rejected = []
    reasons = {}
    for item in history:
        quality = ((item.get("signal_quality") or {}).get("label") or "unknown").lower()
        activity = ((item.get("sensor_context") or {}).get("activity_state") or "UNKNOWN").upper()
        item_reasons = []
        if quality not in RELIABLE_SIGNAL_LABELS:
            item_reasons.append(f"signal_quality:{quality}")
        if not _activity_matches(activity, expected_activity):
            item_reasons.append(f"activity:{activity}")
        if item_reasons:
            rejected.append(item)
            for reason in item_reasons:
                reasons[reason] = reasons.get(reason, 0) + 1
        else:
            valid.append(item)
    return valid, rejected, reasons


def complete_guided_baseline_segment(
    patient_id="polar_h10",
    session_id=None,
    segment_type=None,
    started_at=None,
    ended_at=None,
    allow_skip=False,
    db_path=DB_PATH,
):
    patient_id = _safe_patient_id(patient_id)
    if not session_id:
        raise ValueError("session_id is required.")
    config = _segment_config(segment_type)
    segment_type = config["segment_type"]
    now = utc_now_iso()

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM guided_baseline_segments
            WHERE session_id = ? AND patient_id = ? AND segment_type = ?
            """,
            (session_id, patient_id, segment_type),
        ).fetchone()
        if row is None:
            raise ValueError("Guided baseline segment was not found.")

        if allow_skip and config.get("skippable"):
            conn.execute(
                """
                UPDATE guided_baseline_segments
                SET started_at = ?, ended_at = ?, valid_window_count = 0,
                    rejected_window_count = 0, rejection_reasons_json = ?,
                    status = 'skipped', updated_at = ?
                WHERE segment_id = ?
                """,
                (
                    started_at or now,
                    ended_at or now,
                    json.dumps(["skipped_by_user"], ensure_ascii=False),
                    now,
                    row["segment_id"],
                ),
            )
            conn.execute(
                """
                UPDATE collection_segments
                SET started_at = ?, ended_at = ?, status = 'skipped', updated_at = ?
                WHERE collection_segment_id = ?
                """,
                (started_at or now, ended_at or now, now, row["segment_id"]),
            )
            conn.commit()
            return {"status": "skipped", "segment": _row_to_segment(conn.execute("SELECT * FROM guided_baseline_segments WHERE segment_id = ?", (row["segment_id"],)).fetchone())}

        start_dt = _safe_dt(started_at or row["started_at"])
        end_dt = _safe_dt(ended_at or now)
        if end_dt <= start_dt:
            raise ValueError("ended_at must be after started_at.")

        days = max(1.0, (datetime.now(timezone.utc) - start_dt).total_seconds() / 86400.0 + 1.0)
        history = get_history(patient_id=patient_id, days=days, limit=50000, db_path=db_path)
        start_epoch = start_dt.timestamp()
        end_epoch = end_dt.timestamp()
        segment_history = [
            item
            for item in history
            if (item.get("timestamp_epoch") or timestamp_to_epoch(item.get("timestamp")) or 0) >= start_epoch
            and (item.get("timestamp_epoch") or timestamp_to_epoch(item.get("timestamp")) or 0) <= end_epoch
        ]
        valid, rejected, reasons = _validate_segment_windows(segment_history, config["expected_activity"])
        min_valid = int(config.get("min_valid_windows") or 1)
        if len(valid) >= min_valid:
            status = "completed"
            reason_list = []
        else:
            status = "failed"
            reason_list = [
                f"Need at least {min_valid} valid windows, got {len(valid)}.",
                *[f"{key} x{count}" for key, count in sorted(reasons.items())],
            ]
            if not segment_history:
                reason_list.append("No predictions found in this segment time range.")

        conn.execute(
            """
            UPDATE guided_baseline_segments
            SET started_at = ?, ended_at = ?, valid_window_count = ?,
                rejected_window_count = ?, rejection_reasons_json = ?,
                status = ?, updated_at = ?
            WHERE segment_id = ?
            """,
            (
                start_dt.isoformat(),
                end_dt.isoformat(),
                len(valid),
                len(rejected),
                json.dumps(reason_list, ensure_ascii=False),
                status,
                now,
                row["segment_id"],
            ),
        )
        conn.execute(
            """
            UPDATE collection_segments
            SET started_at = ?, ended_at = ?, status = ?, updated_at = ?
            WHERE collection_segment_id = ?
            """,
            (
                start_dt.isoformat(),
                end_dt.isoformat(),
                status,
                now,
                row["segment_id"],
            ),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM guided_baseline_segments WHERE segment_id = ?",
            (row["segment_id"],),
        ).fetchone()
    finally:
        conn.close()

    if status == "completed":
        mark_raw_chunks_for_segment(
            patient_id=patient_id,
            start_timestamp=start_dt.isoformat(),
            end_timestamp=end_dt.isoformat(),
            guided_segment_id=row["segment_id"],
            collection_session_id=session_id,
            baseline_usable=True,
            db_path=db_path,
        )

    return {"status": status, "segment": _row_to_segment(updated)}


def _accepted_guided_ranges(conn, patient_id, target_days):
    rows = conn.execute(
        """
        SELECT started_at, ended_at FROM guided_baseline_segments
        WHERE patient_id = ?
          AND status = 'completed'
          AND started_at IS NOT NULL
          AND ended_at IS NOT NULL
        ORDER BY ended_at DESC
        """,
        (patient_id,),
    ).fetchall()
    ranges = []
    cutoff_count = int(target_days) * len(SEGMENT_PLAN)
    for row in rows[:cutoff_count]:
        start_epoch = timestamp_to_epoch(row["started_at"])
        end_epoch = timestamp_to_epoch(row["ended_at"])
        if start_epoch is not None and end_epoch is not None:
            ranges.append((start_epoch, end_epoch))
    return ranges


def get_guided_baseline_history(patient_id, target_days=7, db_path=DB_PATH):
    patient_id = _safe_patient_id(patient_id)
    conn = get_connection(db_path)
    try:
        ranges = _accepted_guided_ranges(conn, patient_id, target_days)
    finally:
        conn.close()
    if not ranges:
        return [], {"guided_segment_count": 0, "guided_prediction_count": 0}

    history = get_history(patient_id=patient_id, days=target_days, limit=50000, db_path=db_path)
    guided = []
    for item in history:
        epoch = item.get("timestamp_epoch") or timestamp_to_epoch(item.get("timestamp"))
        if epoch is None:
            continue
        if any(start <= epoch <= end for start, end in ranges):
            guided.append(item)
    return guided, {
        "guided_segment_count": len(ranges),
        "guided_prediction_count": len(guided),
        "guided_only": True,
    }


def complete_guided_baseline_day(
    patient_id="polar_h10",
    session_id=None,
    target_days=7,
    db_path=DB_PATH,
    baseline_root=None,
):
    patient_id = _safe_patient_id(patient_id)
    if not session_id:
        raise ValueError("session_id is required.")
    now = utc_now_iso()
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM guided_baseline_segments WHERE session_id = ? AND patient_id = ?",
            (session_id, patient_id),
        ).fetchall()
        if not rows:
            raise ValueError("No guided baseline segments found for this session.")
        statuses = {row["status"] for row in rows}
        if all(status == "completed" for status in statuses):
            session_status = "completed"
        elif all(status in VALID_SEGMENT_STATUSES for status in statuses):
            session_status = "partial"
        else:
            session_status = "failed"
        conn.execute(
            """
            UPDATE guided_baseline_sessions
            SET status = ?, completed_at = ?, updated_at = ?
            WHERE session_id = ? AND patient_id = ?
            """,
            (session_status, now, now, session_id, patient_id),
        )
        conn.execute(
            """
            UPDATE collection_sessions
            SET status = ?, ended_at = ?, updated_at = ?
            WHERE collection_session_id = ? AND patient_id = ?
            """,
            (session_status, now, now, session_id, patient_id),
        )
        conn.commit()
    finally:
        conn.close()

    guided_history, source_metadata = get_guided_baseline_history(patient_id, target_days, db_path=db_path)
    if guided_history:
        baseline_result = update_progressive_personal_baseline(
            patient_id=patient_id,
            target_days=target_days,
            min_predictions=1,
            include_alert_windows=False,
            db_path=db_path,
            history=guided_history,
            source_metadata=source_metadata,
            **({"root": baseline_root} if baseline_root else {}),
        )
    else:
        baseline_result = None

    status_payload = get_guided_baseline_status(patient_id, target_days, db_path)
    return {
        **status_payload,
        "status": session_status,
        "baseline_status": status_payload.get("status"),
        "baseline": baseline_result,
    }
