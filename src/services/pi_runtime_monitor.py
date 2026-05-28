import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_LOG_PATH = "logs/pi_soak_24h.jsonl"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_json(url, timeout_seconds=20, api_key=None):
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


def _load_psutil():
    try:
        import psutil  # noqa: PLC0415
    except ImportError:
        return None
    return psutil


def _find_process(psutil, process_name):
    if psutil is None or not process_name:
        return None
    needle = str(process_name).lower()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if needle in name or needle in cmdline:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def collect_resource_stats(psutil, process_name=None):
    if psutil is None:
        return {"available": False, "reason": "psutil_not_installed"}

    stats = {
        "available": True,
        "system_cpu_percent": psutil.cpu_percent(interval=0.1),
        "system_memory_percent": psutil.virtual_memory().percent,
    }
    proc = _find_process(psutil, process_name)
    if proc is None:
        stats["process_found"] = False
        return stats

    try:
        memory = proc.memory_info()
        stats.update(
            {
                "process_found": True,
                "pid": proc.pid,
                "process_name": proc.name(),
                "process_cpu_percent": proc.cpu_percent(interval=0.1),
                "process_rss_bytes": int(memory.rss),
                "process_vms_bytes": int(memory.vms),
            }
        )
    except Exception as exc:  # noqa: BLE001
        stats.update({"process_found": False, "process_error": str(exc)})
    return stats


def _safe_get(endpoint, base_url, timeout_seconds, api_key=None):
    url = f"{base_url.rstrip('/')}{endpoint}"
    try:
        status, payload = get_json(url, timeout_seconds=timeout_seconds, api_key=api_key)
        return {"ok": True, "status": status, "payload": payload}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def build_monitor_sample(args, psutil):
    base_url = args.base_url.rstrip("/")
    patient_id = args.patient_id
    sample = {
        "type": "pi_runtime_monitor_sample",
        "timestamp": utc_now_iso(),
        "base_url": base_url,
        "patient_id": patient_id,
        "resources": collect_resource_stats(psutil, process_name=args.process_name),
    }

    sample["health"] = _safe_get("/health", base_url, args.timeout_seconds, args.api_key)
    sample["latest_result"] = _safe_get("/latest-result", base_url, args.timeout_seconds, args.api_key)
    sample["storage"] = _safe_get("/storage/status", base_url, args.timeout_seconds, args.api_key)
    sample["sync_scheduler"] = _safe_get(
        "/storage/sync-scheduler/status",
        base_url,
        args.timeout_seconds,
        args.api_key,
    )
    sample["events"] = _safe_get(
        f"/events?patient_id={patient_id}&days={args.event_days}&limit={args.event_limit}",
        base_url,
        args.timeout_seconds,
        args.api_key,
    )
    return sample


def run_monitor(args):
    psutil = _load_psutil()
    end_at = time.monotonic() + (float(args.duration_hours) * 3600.0)
    started_at = utc_now_iso()
    start = {
        "type": "pi_runtime_monitor_start",
        "started_at": started_at,
        "base_url": args.base_url,
        "patient_id": args.patient_id,
        "duration_hours": args.duration_hours,
        "interval_seconds": args.interval_seconds,
        "psutil_available": psutil is not None,
    }
    append_log(args.output, start)
    print(json.dumps(start, ensure_ascii=False))

    iteration = 0
    failures = 0
    while time.monotonic() < end_at:
        iteration += 1
        sample = build_monitor_sample(args, psutil)
        failures += sum(1 for key in ("health", "latest_result", "storage", "sync_scheduler", "events") if not sample[key]["ok"])
        sample["iteration"] = iteration
        append_log(args.output, sample)
        print(json.dumps(sample, ensure_ascii=False))
        time.sleep(float(args.interval_seconds))

    finish = {
        "type": "pi_runtime_monitor_finish",
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "iterations": iteration,
        "endpoint_failures": failures,
        "output": args.output,
    }
    append_log(args.output, finish)
    return finish


def parse_args():
    parser = argparse.ArgumentParser(description="Monitor a real Raspberry Pi + Polar H10 runtime for long soak tests.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--patient-id", default="polar_h10")
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--event-days", type=float, default=1.0)
    parser.add_argument("--event-limit", type=int, default=10000)
    parser.add_argument("--process-name", default=os.getenv("PI_MONITOR_PROCESS_NAME", "uvicorn"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--output", default=DEFAULT_LOG_PATH)
    return parser.parse_args()


def main():
    result = run_monitor(parse_args())
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
