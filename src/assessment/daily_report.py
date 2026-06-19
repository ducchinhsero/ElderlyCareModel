"""Per-calendar-day statistical report built from cloud (MongoDB) data.

Powers the app's "chọn ngày xem báo cáo" feature: given a patient and a
calendar date, returns the same statistical breakdown rendered in the
standalone HTML report (HR stats, hourly trend, band distribution, per-minute
series, event/rhythm/ectopy/stress breakdowns, critical events, and a short
multi-day rest-HR trend).

Data source is MongoDB Atlas because the Pi's local SQLite is purged ~24h
after sync (MONGODB_SYNC_PURGE_AFTER_SYNC), so historical days only exist in
the cloud archive. Documents are grouped by ``session_id`` (YYYYMMDD in the
patient's local day), which is exactly how the collector tags each window.
"""
from datetime import datetime, timedelta

from src.storage.mongodb_sync import get_mongo_database, is_mongodb_configured

# Signal-quality labels we trust for clinical statistics. "poor" windows still
# produce an HR estimate but from unstable RR intervals, so they are excluded
# from every aggregate (matching the HTML report methodology).
RELIABLE_QUALITY = ["good", "fair"]
_RELIABLE_MATCH = {"signal_quality.label": {"$in": RELIABLE_QUALITY}}
_HR_OK = {"heart_rate_bpm": {"$ne": None}}

# HR band boundaries (bpm) and the labels each bucket maps to.
_BAND_BOUNDS = [0, 60, 100, 120, 150, 100000]
_BAND_LABELS = {0: "<60", 60: "60-99", 100: "100-119", 120: "120-149", 150: ">=150"}


def _date_to_session_id(date_str):
    """'2026-06-18' or '20260618' -> '20260618' (session_id format)."""
    raw = str(date_str).strip()
    if "-" in raw:
        dt = datetime.strptime(raw, "%Y-%m-%d")
        return dt.strftime("%Y%m%d")
    datetime.strptime(raw, "%Y%m%d")  # validate
    return raw


def _session_id_to_iso(session_id):
    return datetime.strptime(session_id, "%Y%m%d").strftime("%Y-%m-%d")


def _facet_counts(rows, default="none"):
    """Turn a [{_id: label, n: count}, ...] facet branch into {label: count}."""
    counts = {}
    for row in rows or []:
        key = row.get("_id")
        key = key if key else default
        counts[str(key)] = int(row.get("n") or 0)
    return counts


def _first(rows):
    return rows[0] if rows else None


def list_available_report_days(patient_id="polar_h10", limit=120):
    """Return calendar days that have any prediction data, newest first.

    Used by the app's date picker to enable/highlight days with data.
    """
    if not is_mongodb_configured():
        raise ValueError("MongoDB is not configured; cannot list report days.")
    _client, db = get_mongo_database()
    query = {"patient_id": patient_id} if patient_id else {}
    session_ids = [s for s in db.predictions.distinct("session_id", query) if s]
    session_ids.sort(reverse=True)
    session_ids = session_ids[:limit]
    return {
        "patient_id": patient_id,
        "days": [
            {"session_id": sid, "date": _session_id_to_iso(sid)}
            for sid in session_ids
        ],
    }


def compute_daily_report(patient_id="polar_h10", date=None):
    """Build the full per-day statistical report from MongoDB.

    ``date`` accepts 'YYYY-MM-DD' or 'YYYYMMDD'. Returns a JSON-serializable
    dict with the same shape the HTML report consumes.
    """
    if not is_mongodb_configured():
        raise ValueError("MongoDB is not configured; cannot build daily report.")
    if not date:
        raise ValueError("date is required (YYYY-MM-DD).")
    session_id = _date_to_session_id(date)
    _client, db = get_mongo_database()

    out = {
        "patient_id": patient_id,
        "date": _session_id_to_iso(session_id),
        "session_id": session_id,
    }

    # All per-window aggregates computed server-side in ONE round-trip via
    # $facet, so we transfer a few KB of grouped results instead of pulling
    # thousands of documents over the (slow) Atlas link.
    pred = _first(list(db.predictions.aggregate([
        {"$match": {"patient_id": patient_id, "session_id": session_id}},
        {"$facet": {
            "total": [{"$count": "n"}],
            "trange": [{"$group": {"_id": None,
                                   "tmin": {"$min": "$timestamp"},
                                   "tmax": {"$max": "$timestamp"}}}],
            "signal_quality": [{"$group": {"_id": "$signal_quality.label",
                                           "n": {"$sum": 1}}}],
            "activity": [{"$group": {"_id": "$sensor_context.activity_state",
                                     "n": {"$sum": 1}}}],
            "reliable": [{"$match": _RELIABLE_MATCH}, {"$count": "n"}],
            "hr_stats": [
                {"$match": {**_RELIABLE_MATCH, **_HR_OK}},
                {"$group": {"_id": None, "n": {"$sum": 1},
                            "mean": {"$avg": "$heart_rate_bpm"},
                            "min": {"$min": "$heart_rate_bpm"},
                            "max": {"$max": "$heart_rate_bpm"},
                            "std": {"$stdDevPop": "$heart_rate_bpm"}}},
            ],
            "bands": [
                {"$match": {**_RELIABLE_MATCH, **_HR_OK}},
                {"$bucket": {"groupBy": "$heart_rate_bpm",
                             "boundaries": _BAND_BOUNDS, "default": "other",
                             "output": {"n": {"$sum": 1}}}},
            ],
            "hourly": [
                {"$match": {**_RELIABLE_MATCH, **_HR_OK}},
                {"$group": {"_id": {"$substrBytes": ["$timestamp", 11, 2]},
                            "n": {"$sum": 1},
                            "mean": {"$avg": "$heart_rate_bpm"},
                            "min": {"$min": "$heart_rate_bpm"},
                            "max": {"$max": "$heart_rate_bpm"}}},
                {"$sort": {"_id": 1}},
            ],
            "series": [
                {"$match": {**_RELIABLE_MATCH, **_HR_OK}},
                {"$group": {"_id": {"$substrBytes": ["$timestamp", 11, 5]},
                            "hr": {"$avg": "$heart_rate_bpm"}}},
                {"$sort": {"_id": 1}},
            ],
            "rhythm": [{"$match": _RELIABLE_MATCH},
                       {"$group": {"_id": "$rhythm.label", "n": {"$sum": 1}}}],
            "ectopy": [{"$match": _RELIABLE_MATCH},
                       {"$group": {"_id": "$ectopy.label", "n": {"$sum": 1}}}],
            "afib": [
                {"$match": _RELIABLE_MATCH},
                {"$group": {"_id": None,
                            "mean": {"$avg": "$rhythm.possible_afib_probability"},
                            "max": {"$max": "$rhythm.possible_afib_probability"}}},
            ],
            "afib_over03": [
                {"$match": {**_RELIABLE_MATCH,
                            "rhythm.possible_afib_probability": {"$gt": 0.3}}},
                {"$count": "n"},
            ],
            "stress_counts": [
                {"$match": {**_RELIABLE_MATCH,
                            "stress.label": {"$in": ["stress", "non_stress"]}}},
                {"$group": {"_id": "$stress.label", "n": {"$sum": 1}}},
            ],
            "stress_prob": [
                {"$match": {**_RELIABLE_MATCH,
                            "stress.label": {"$in": ["stress", "non_stress"]}}},
                {"$group": {"_id": None,
                            "mean": {"$avg": "$stress.probabilities.stress"},
                            "max": {"$max": "$stress.probabilities.stress"}}},
            ],
            "stress_hourly": [
                {"$match": {**_RELIABLE_MATCH,
                            "stress.label": {"$in": ["stress", "non_stress"]}}},
                {"$group": {"_id": {"$substrBytes": ["$timestamp", 11, 2]},
                            "total": {"$sum": 1},
                            "stress": {"$sum": {"$cond": [
                                {"$eq": ["$stress.label", "stress"]}, 1, 0]}}}},
                {"$sort": {"_id": 1}},
            ],
        }},
    ])))

    total = (_first(pred.get("total")) or {}).get("n", 0) if pred else 0
    out["total_windows"] = int(total)
    if not total:
        out["has_data"] = False
        out["reliable_windows"] = 0
        return out

    out["has_data"] = True
    trange = _first(pred.get("trange")) or {}
    out["t_start"] = trange.get("tmin")
    out["t_end"] = trange.get("tmax")
    out["reliable_windows"] = int((_first(pred.get("reliable")) or {}).get("n", 0))
    out["signal_quality"] = _facet_counts(pred.get("signal_quality"))
    out["activity"] = _facet_counts(pred.get("activity"))

    hr_stats = _first(pred.get("hr_stats"))
    if hr_stats:
        out["hr_stats"] = {
            "n": int(hr_stats.get("n") or 0),
            "mean": hr_stats.get("mean"),
            "median": hr_stats.get("mean"),  # median dropped server-side
            "min": hr_stats.get("min"),
            "max": hr_stats.get("max"),
            "std": hr_stats.get("std"),
        }
        out["hr_bands"] = {
            label: 0 for label in _BAND_LABELS.values()
        }
        for row in pred.get("bands") or []:
            label = _BAND_LABELS.get(row.get("_id"))
            if label:
                out["hr_bands"][label] = int(row.get("n") or 0)
        out["hourly"] = [
            {"hour": r["_id"], "n": int(r.get("n") or 0),
             "mean": r.get("mean"), "min": r.get("min"), "max": r.get("max")}
            for r in pred.get("hourly") or []
        ]
        out["series"] = [
            {"t": r["_id"], "hr": round(r.get("hr") or 0, 1)}
            for r in pred.get("series") or []
        ]

    out["rhythm"] = _facet_counts(pred.get("rhythm"))
    out["ectopy"] = _facet_counts(pred.get("ectopy"))
    afib = _first(pred.get("afib"))
    if afib and afib.get("max") is not None:
        out["afib"] = {
            "mean": afib.get("mean"),
            "max": afib.get("max"),
            "over03": int((_first(pred.get("afib_over03")) or {}).get("n", 0)),
        }

    stress_counts = _facet_counts(pred.get("stress_counts"))
    valid = sum(stress_counts.values())
    if valid:
        stress_n = stress_counts.get("stress", 0)
        prob = _first(pred.get("stress_prob")) or {}
        out["stress_stats"] = {
            "valid": valid,
            "unknown": out["reliable_windows"] - valid,
            "stress": stress_n,
            "non_stress": stress_counts.get("non_stress", 0),
            "pct_stress": stress_n / valid * 100.0,
            "mean_prob": prob.get("mean"),
            "max_prob": prob.get("max"),
            "hourly": [
                {"hour": r["_id"], "stress": int(r.get("stress") or 0),
                 "total": int(r.get("total") or 0),
                 "pct": (int(r.get("stress") or 0) / int(r["total"]) * 100.0)
                 if r.get("total") else 0.0}
                for r in pred.get("stress_hourly") or []
            ],
        }

    # --- events (separate collection, one $facet round-trip) ---
    ev = _first(list(db.events.aggregate([
        {"$match": {"patient_id": patient_id, "session_id": session_id}},
        {"$facet": {
            "total": [{"$count": "n"}],
            "by_type": [{"$group": {"_id": "$event_type", "n": {"$sum": 1}}}],
            "by_severity": [{"$group": {"_id": "$severity", "n": {"$sum": 1}}}],
            "critical": [
                {"$match": {"severity": "critical"}},
                {"$sort": {"timestamp": 1}},
                {"$project": {"_id": 0,
                              "t": {"$substrBytes": ["$timestamp", 11, 8]},
                              "type": "$event_type", "hr": "$heart_rate_bpm"}},
            ],
            "falls": [
                {"$match": {"event_type": "fall_candidate"}},
                {"$sort": {"timestamp": 1}},
                {"$project": {"_id": 0,
                              "t": {"$substrBytes": ["$timestamp", 11, 8]},
                              "conf": "$metadata.fall.confidence",
                              "msg": {"$substrBytes": ["$message", 0, 80]}}},
            ],
        }},
    ]))) or {}
    out["total_events"] = int((_first(ev.get("total")) or {}).get("n", 0))
    out["event_types"] = _facet_counts(ev.get("by_type"))
    out["event_severity"] = _facet_counts(ev.get("by_severity"))
    out["critical_events"] = ev.get("critical") or []
    out["fall_events"] = ev.get("falls") or []

    # --- short multi-day rest-HR trend (selected day + 2 prior days) ---
    base = datetime.strptime(session_id, "%Y%m%d")
    trend_ids = [(base - timedelta(days=d)).strftime("%Y%m%d") for d in (2, 1, 0)]
    trend_rows = {
        r["_id"]: r
        for r in db.predictions.aggregate([
            {"$match": {"patient_id": patient_id,
                        "session_id": {"$in": trend_ids},
                        **_RELIABLE_MATCH, **_HR_OK,
                        "sensor_context.activity_state": "REST"}},
            {"$group": {"_id": "$session_id", "n": {"$sum": 1},
                        "mean": {"$avg": "$heart_rate_bpm"},
                        "max": {"$max": "$heart_rate_bpm"},
                        "over100": {"$sum": {"$cond": [
                            {"$gt": ["$heart_rate_bpm", 100]}, 1, 0]}}}},
        ])
    }
    days = []
    for sid in trend_ids:
        row = trend_rows.get(sid)
        if not row or not row.get("n"):
            continue
        n = int(row["n"])
        days.append({
            "day": sid,
            "date": _session_id_to_iso(sid),
            "n": n,
            "mean": row.get("mean"),
            "median": row.get("mean"),
            "max": row.get("max"),
            "pct_over100": int(row.get("over100") or 0) / n * 100.0,
        })
    out["days"] = days

    return out
