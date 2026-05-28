import argparse
import json
import math
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_LOG_PATH = "logs/soak_test_runs.jsonl"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def generate_synthetic_ecg(
    sample_rate_hz=130,
    duration_seconds=30,
    heart_rate_bpm=72,
    noise_uv=25,
    seed=None,
):
    rng = random.Random(seed)
    sample_count = int(round(float(sample_rate_hz) * float(duration_seconds)))
    beat_period = 60.0 / float(heart_rate_bpm)
    samples = []
    for i in range(sample_count):
        t = i / float(sample_rate_hz)
        phase = (t % beat_period) / beat_period
        baseline = 60.0 * math.sin(2.0 * math.pi * 0.25 * t)
        p_wave = 80.0 * math.exp(-((phase - 0.18) / 0.035) ** 2)
        q_wave = -180.0 * math.exp(-((phase - 0.37) / 0.014) ** 2)
        r_wave = 1100.0 * math.exp(-((phase - 0.40) / 0.010) ** 2)
        s_wave = -250.0 * math.exp(-((phase - 0.43) / 0.018) ** 2)
        t_wave = 260.0 * math.exp(-((phase - 0.68) / 0.060) ** 2)
        noise = rng.uniform(-float(noise_uv), float(noise_uv))
        samples.append(int(round(baseline + p_wave + q_wave + r_wave + s_wave + t_wave + noise)))
    return samples


def generate_synthetic_acc(sample_rate_hz=200, duration_seconds=30, activity="REST", seed=None):
    rng = random.Random(seed)
    sample_count = int(round(float(sample_rate_hz) * float(duration_seconds)))
    activity = str(activity or "REST").upper()
    movement = {"REST": 8.0, "WALK": 85.0, "ACTIVE": 170.0}.get(activity, 20.0)
    rows = []
    for i in range(sample_count):
        t = i / float(sample_rate_hz)
        x = movement * math.sin(2.0 * math.pi * 1.3 * t) + rng.uniform(-5, 5)
        y = movement * math.cos(2.0 * math.pi * 1.1 * t) + rng.uniform(-5, 5)
        z = 1000.0 + movement * 0.35 * math.sin(2.0 * math.pi * 0.8 * t) + rng.uniform(-5, 5)
        vm = math.sqrt(x * x + y * y + z * z)
        rows.append({"x_mg": x, "y_mg": y, "z_mg": z, "vm_mg": vm})
    return rows


def build_ingest_payload(
    patient_id,
    sample_rate_hz=130,
    window_seconds=30,
    heart_rate_bpm=72,
    activity="REST",
    include_acc=True,
    seed=None,
):
    payload = {
        "patient_id": patient_id,
        "sample_rate_hz": float(sample_rate_hz),
        "timestamp": utc_now_iso(),
        "ecg_samples": generate_synthetic_ecg(
            sample_rate_hz=sample_rate_hz,
            duration_seconds=window_seconds,
            heart_rate_bpm=heart_rate_bpm,
            seed=seed,
        ),
    }
    if include_acc:
        payload["acc_sample_rate_hz"] = 200.0
        payload["acc_samples"] = generate_synthetic_acc(
            sample_rate_hz=200,
            duration_seconds=window_seconds,
            activity=activity,
            seed=seed,
        )
    return payload


def post_json(url, payload, timeout_seconds=30, api_key=None):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body) if body else {}


def get_json(url, timeout_seconds=30, api_key=None):
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body) if body else {}


def append_log(path, payload):
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def summarize_ingest_response(response):
    return {
        "patient_id": response.get("patient_id"),
        "timestamp": response.get("timestamp"),
        "heart_rate_bpm": response.get("heart_rate_bpm"),
        "alert_level": response.get("alert_level"),
        "message": response.get("message"),
        "signal_quality": (response.get("signal_quality") or {}).get("label"),
        "rhythm": (response.get("rhythm") or {}).get("label"),
        "risk": (response.get("risk") or {}).get("level"),
        "raw_ecg_chunk_count": len(response.get("raw_ecg_chunk_ids") or []),
        "raw_acc_chunk_count": len(response.get("raw_acc_chunk_ids") or []),
    }


def run_soak_test(args):
    base_url = args.base_url.rstrip("/")
    end_at = time.monotonic() + (float(args.duration_minutes) * 60.0)
    iteration = 0
    failures = 0
    started_at = utc_now_iso()
    append_log(
        args.log_path,
        {
            "type": "soak_start",
            "started_at": started_at,
            "base_url": base_url,
            "patient_id": args.patient_id,
            "duration_minutes": args.duration_minutes,
        },
    )

    while time.monotonic() < end_at:
        iteration += 1
        event = {
            "type": "soak_iteration",
            "iteration": iteration,
            "timestamp": utc_now_iso(),
        }
        try:
            payload = build_ingest_payload(
                patient_id=args.patient_id,
                sample_rate_hz=args.sample_rate_hz,
                window_seconds=args.window_seconds,
                heart_rate_bpm=args.heart_rate_bpm,
                activity=args.activity,
                include_acc=not args.no_acc,
                seed=iteration,
            )
            status, response = post_json(
                f"{base_url}/ingest-ecg",
                payload,
                timeout_seconds=args.timeout_seconds,
                api_key=args.api_key,
            )
            event["ingest_status"] = status
            event["ingest"] = summarize_ingest_response(response)

            if args.check_storage:
                storage_status_code, storage = get_json(
                    f"{base_url}/storage/status",
                    timeout_seconds=args.timeout_seconds,
                    api_key=args.api_key,
                )
                event["storage_status"] = storage_status_code
                event["storage"] = {
                    "counts": storage.get("counts"),
                    "raw_signal_chunks": storage.get("raw_signal_chunks"),
                    "mongodb_sync_configured": storage.get("mongodb_sync_configured"),
                }

            if args.sync_every and iteration % int(args.sync_every) == 0:
                sync_payload = {
                    "patient_id": args.patient_id,
                    "days": args.sync_days,
                    "limit": args.sync_limit,
                    "purge_after_sync": args.purge_after_sync,
                    "purge_retention_hours": args.purge_retention_hours,
                }
                sync_status, sync_response = post_json(
                    f"{base_url}/storage/sync-scheduler/run-once",
                    sync_payload,
                    timeout_seconds=max(args.timeout_seconds, 60),
                    api_key=args.api_key,
                )
                event["sync_status"] = sync_status
                event["sync"] = sync_response
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            failures += 1
            event["error"] = str(exc)
        append_log(args.log_path, event)
        print(json.dumps(event, ensure_ascii=False))
        time.sleep(float(args.interval_seconds))

    result = {
        "type": "soak_finish",
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "iterations": iteration,
        "failures": failures,
        "log_path": args.log_path,
    }
    append_log(args.log_path, result)
    return result


def parse_args():
    parser = argparse.ArgumentParser(description="Run a long-running ECG API soak test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--patient-id", default="soak_test")
    parser.add_argument("--duration-minutes", type=float, default=10)
    parser.add_argument("--interval-seconds", type=float, default=30)
    parser.add_argument("--window-seconds", type=float, default=30)
    parser.add_argument("--sample-rate-hz", type=float, default=130)
    parser.add_argument("--heart-rate-bpm", type=float, default=72)
    parser.add_argument("--activity", default="REST", choices=["REST", "WALK", "ACTIVE"])
    parser.add_argument("--no-acc", action="store_true")
    parser.add_argument("--check-storage", action="store_true")
    parser.add_argument("--sync-every", type=int, default=0, help="Run sync every N iterations. 0 disables manual sync.")
    parser.add_argument("--sync-days", type=float, default=1)
    parser.add_argument("--sync-limit", type=int, default=5000)
    parser.add_argument("--purge-after-sync", action="store_true")
    parser.add_argument("--purge-retention-hours", type=float, default=24)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--log-path", default=DEFAULT_LOG_PATH)
    return parser.parse_args()


def main():
    result = run_soak_test(parse_args())
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
