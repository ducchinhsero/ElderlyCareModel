import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


DEFAULT_INPUT = "logs/pi_soak_24h.jsonl"
DEFAULT_SUMMARY = "logs/pi_soak_24h_summary.json"
DEFAULT_REPORT = "logs/pi_soak_24h_report.md"


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _payload(sample, key):
    data = sample.get(key) or {}
    if not data.get("ok"):
        return None
    return data.get("payload") or {}


def _nested(payload, *keys, default=None):
    value = payload
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def _stat(values):
    values = [float(value) for value in values if value is not None]
    if not values:
        return {"min": None, "avg": None, "max": None}
    return {
        "min": round(min(values), 3),
        "avg": round(sum(values) / len(values), 3),
        "max": round(max(values), 3),
    }


def _load_alert_review(path):
    review_path = Path(path)
    if not review_path.exists():
        return {
            "status": "not_reviewed",
            "reviewed_count": 0,
            "false_alert_count": None,
            "false_alert_by_type": {},
        }

    false_by_type = Counter()
    reviewed = 0
    false_total = 0
    with review_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            reviewed += 1
            is_false = str(row.get("is_false_alert") or "").strip().lower() in {"1", "true", "yes", "y"}
            if is_false:
                false_total += 1
                false_by_type[row.get("event_type") or "unknown"] += 1
    return {
        "status": "reviewed",
        "reviewed_count": reviewed,
        "false_alert_count": false_total,
        "false_alert_by_type": dict(false_by_type),
    }


def summarize(rows, alert_review_path):
    samples = [row for row in rows if row.get("type") == "pi_runtime_monitor_sample"]
    endpoint_failures = Counter()
    event_by_id = {}
    alert_counts = Counter()
    prediction_counts = []
    db_sizes = []
    unsynced_counts = []
    reconnect_counts = []
    mqtt_connected = []
    latest_prediction_times = []
    process_cpu = []
    process_ram = []
    system_cpu = []
    system_ram = []
    sync_statuses = Counter()

    for sample in samples:
        for key in ("health", "latest_result", "storage", "sync_scheduler", "events"):
            if not (sample.get(key) or {}).get("ok"):
                endpoint_failures[key] += 1

        health = _payload(sample, "health") or {}
        polar = health.get("polar") or {}
        reconnect_counts.append(polar.get("reconnect_count"))
        mqtt_connected.append(bool(health.get("mqtt_connected")))

        latest = _payload(sample, "latest_result") or {}
        latest_result = latest.get("latest_result") or {}
        latest_ts = _parse_iso(latest_result.get("timestamp"))
        if latest_ts:
            latest_prediction_times.append(latest_ts)

        storage = _payload(sample, "storage") or {}
        counts = storage.get("counts") or {}
        if counts.get("predictions") is not None:
            prediction_counts.append(int(counts.get("predictions") or 0))
        if storage.get("db_total_bytes") is not None:
            db_sizes.append(int(storage.get("db_total_bytes") or 0))
        raw_chunks = storage.get("raw_signal_chunks") or []
        unsynced_counts.append(sum(int(item.get("unsynced_count") or 0) for item in raw_chunks))

        scheduler = _payload(sample, "sync_scheduler") or {}
        status = _nested(scheduler, "last_result", "status")
        if status:
            sync_statuses[str(status)] += 1

        events_payload = _payload(sample, "events") or {}
        for event in events_payload.get("events") or []:
            event_id = event.get("event_id") or f"{event.get('timestamp')}:{event.get('event_type')}:{event.get('label')}"
            event_by_id[event_id] = event

        resources = sample.get("resources") or {}
        process_cpu.append(resources.get("process_cpu_percent"))
        process_ram.append(resources.get("process_rss_bytes"))
        system_cpu.append(resources.get("system_cpu_percent"))
        system_ram.append(resources.get("system_memory_percent"))

    for event in event_by_id.values():
        alert_counts[event.get("event_type") or "unknown"] += 1

    gaps = []
    latest_prediction_times = sorted(set(latest_prediction_times))
    for before, after in zip(latest_prediction_times, latest_prediction_times[1:]):
        gaps.append((after - before).total_seconds())

    started_at = rows[0].get("started_at") or rows[0].get("timestamp") if rows else None
    finished_at = rows[-1].get("finished_at") or rows[-1].get("timestamp") if rows else None
    prediction_delta = None
    if prediction_counts:
        prediction_delta = max(prediction_counts) - min(prediction_counts)

    summary = {
        "started_at": started_at,
        "finished_at": finished_at,
        "sample_count": len(samples),
        "endpoint_failures": dict(endpoint_failures),
        "prediction_count_start": min(prediction_counts) if prediction_counts else None,
        "prediction_count_end": max(prediction_counts) if prediction_counts else None,
        "prediction_delta": prediction_delta,
        "max_prediction_gap_seconds": round(max(gaps), 3) if gaps else None,
        "reconnect_count": max([int(value or 0) for value in reconnect_counts], default=0),
        "mqtt_connected_samples": sum(1 for value in mqtt_connected if value),
        "mqtt_sample_count": len(mqtt_connected),
        "db_size_start_bytes": db_sizes[0] if db_sizes else None,
        "db_size_end_bytes": db_sizes[-1] if db_sizes else None,
        "db_size_max_bytes": max(db_sizes) if db_sizes else None,
        "unsynced_raw_chunks_max": max(unsynced_counts) if unsynced_counts else None,
        "cpu_process_percent": _stat(process_cpu),
        "ram_process_rss_bytes": _stat(process_ram),
        "cpu_system_percent": _stat(system_cpu),
        "ram_system_percent": _stat(system_ram),
        "sync_status_counts": dict(sync_statuses),
        "alert_counts": dict(alert_counts),
        "alert_review": _load_alert_review(alert_review_path),
    }
    return summary


def _fmt(value, suffix=""):
    if value is None:
        return "not available"
    return f"{value}{suffix}"


def render_markdown(summary):
    alert_lines = "\n".join(
        f"- `{key}`: {value}" for key, value in sorted((summary.get("alert_counts") or {}).items())
    ) or "- No events captured."
    review = summary.get("alert_review") or {}
    return f"""# Raspberry Pi 24h Soak Test Report

## Summary

- Started: {_fmt(summary.get("started_at"))}
- Finished: {_fmt(summary.get("finished_at"))}
- Monitor samples: {_fmt(summary.get("sample_count"))}
- Prediction delta: {_fmt(summary.get("prediction_delta"))}
- Max prediction gap: {_fmt(summary.get("max_prediction_gap_seconds"), "s")}
- Polar reconnect count: {_fmt(summary.get("reconnect_count"))}
- Max unsynced raw chunks: {_fmt(summary.get("unsynced_raw_chunks_max"))}
- DB size start: {_fmt(summary.get("db_size_start_bytes"), " bytes")}
- DB size end: {_fmt(summary.get("db_size_end_bytes"), " bytes")}

## CPU/RAM

- Process CPU percent: {summary.get("cpu_process_percent")}
- Process RSS bytes: {summary.get("ram_process_rss_bytes")}
- System CPU percent: {summary.get("cpu_system_percent")}
- System RAM percent: {summary.get("ram_system_percent")}

## Endpoint Failures

```json
{json.dumps(summary.get("endpoint_failures") or {}, indent=2, ensure_ascii=False)}
```

## MongoDB Sync

```json
{json.dumps(summary.get("sync_status_counts") or {}, indent=2, ensure_ascii=False)}
```

## Alert Counts

{alert_lines}

## False Alert Review

- Status: {review.get("status")}
- Reviewed alerts: {review.get("reviewed_count")}
- False alerts: {review.get("false_alert_count")}

```json
{json.dumps(review.get("false_alert_by_type") or {}, indent=2, ensure_ascii=False)}
```

## Notes

False-alert accuracy requires manual review because the monitor cannot know whether an alert is clinically correct without ground-truth labels.
"""


def write_json(path, payload):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Build a markdown/json report from pi_runtime_monitor JSONL logs.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--alert-review", default="logs/alert_review.csv")
    parser.add_argument("--summary-output", default=DEFAULT_SUMMARY)
    parser.add_argument("--report-output", default=DEFAULT_REPORT)
    return parser.parse_args()


def main():
    args = parse_args()
    rows = _load_jsonl(args.input)
    summary = summarize(rows, args.alert_review)
    write_json(args.summary_output, summary)
    report = render_markdown(summary)
    output = Path(args.report_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(json.dumps({"summary_output": args.summary_output, "report_output": args.report_output}, indent=2))


if __name__ == "__main__":
    main()
