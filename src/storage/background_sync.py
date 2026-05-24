import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config.env_loader import load_env_file
from src.storage.ecg_storage import purge_synced_raw_chunks, storage_status
from src.storage.mongodb_sync import is_mongodb_configured, sync_to_mongodb


load_env_file()

DEFAULT_SYNC_LOG_PATH = "logs/background_sync.log"
DEFAULT_SYNC_RUN_LOG_PATH = "logs/background_sync_runs.jsonl"

_scheduler_task = None
_scheduler_config = None
_scheduler_state = {
    "running": False,
    "started_at": None,
    "stopped_at": None,
    "cycle_count": 0,
    "last_run_at": None,
    "last_result": None,
    "last_error": None,
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


@dataclass
class BackgroundSyncConfig:
    enabled: bool = False
    interval_seconds: float = 300.0
    patient_id: str | None = None
    days: float = 1.0
    limit: int = 5000
    include_raw_samples: bool = False
    purge_after_sync: bool = True
    purge_retention_hours: float = 24.0
    purge_limit: int = 10000
    run_immediately: bool = True
    log_path: str = DEFAULT_SYNC_LOG_PATH
    run_log_path: str = DEFAULT_SYNC_RUN_LOG_PATH

    def validate(self):
        self.interval_seconds = _positive_float(self.interval_seconds, "interval_seconds")
        self.days = _positive_float(self.days, "days")
        self.limit = _positive_int(self.limit, "limit")
        self.purge_retention_hours = _positive_float(
            self.purge_retention_hours,
            "purge_retention_hours",
            allow_zero=True,
        )
        self.purge_limit = _positive_int(self.purge_limit, "purge_limit")
        if self.patient_id == "":
            self.patient_id = None
        return self

    @classmethod
    def from_env(cls):
        load_env_file()
        return cls(
            enabled=_parse_bool(os.getenv("MONGODB_SYNC_ENABLED"), default=False),
            interval_seconds=float(os.getenv("MONGODB_SYNC_INTERVAL_SECONDS", "300")),
            patient_id=os.getenv("MONGODB_SYNC_PATIENT_ID") or None,
            days=float(os.getenv("MONGODB_SYNC_DAYS", "1")),
            limit=int(os.getenv("MONGODB_SYNC_LIMIT", "5000")),
            include_raw_samples=_parse_bool(os.getenv("MONGODB_SYNC_INCLUDE_RAW_SAMPLES"), default=False),
            purge_after_sync=_parse_bool(os.getenv("MONGODB_SYNC_PURGE_AFTER_SYNC"), default=True),
            purge_retention_hours=float(os.getenv("MONGODB_SYNC_PURGE_RETENTION_HOURS", "24")),
            purge_limit=int(os.getenv("MONGODB_SYNC_PURGE_LIMIT", "10000")),
            run_immediately=_parse_bool(os.getenv("MONGODB_SYNC_RUN_IMMEDIATELY"), default=True),
            log_path=os.getenv("MONGODB_SYNC_LOG_PATH", DEFAULT_SYNC_LOG_PATH),
            run_log_path=os.getenv("MONGODB_SYNC_RUN_LOG_PATH", DEFAULT_SYNC_RUN_LOG_PATH),
        ).validate()


def get_background_sync_logger(log_path=DEFAULT_SYNC_LOG_PATH):
    logger = logging.getLogger("elderly_care.background_sync")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved = str(path.resolve())
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == resolved:
            return logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(resolved, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def close_background_sync_logger():
    logger = logging.getLogger("elderly_care.background_sync")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def append_sync_run_log(path, payload):
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def run_background_sync_once(
    config=None,
    sync_func=sync_to_mongodb,
    purge_func=purge_synced_raw_chunks,
    configured_func=is_mongodb_configured,
    storage_status_func=storage_status,
):
    config = (config or BackgroundSyncConfig.from_env()).validate()
    logger = get_background_sync_logger(config.log_path)
    started = time.time()
    result = {
        "status": "started",
        "started_at": utc_now_iso(),
        "patient_id": config.patient_id,
        "days": config.days,
        "limit": config.limit,
    }

    if not configured_func():
        result.update(
            {
                "status": "skipped",
                "reason": "MONGODB_URI is not configured.",
                "duration_seconds": round(time.time() - started, 3),
            }
        )
        logger.warning("MongoDB sync skipped: MONGODB_URI is not configured.")
        append_sync_run_log(config.run_log_path, result)
        return result

    try:
        sync_result = sync_func(
            patient_id=config.patient_id,
            days=config.days,
            limit=config.limit,
            include_raw_samples=config.include_raw_samples,
        )
        purge_result = None
        if config.purge_after_sync:
            purge_result = purge_func(
                retention_hours=config.purge_retention_hours,
                limit=config.purge_limit,
            )
        current_storage = storage_status_func()
        result.update(
            {
                "status": "ok",
                "sync": sync_result,
                "purge": purge_result,
                "storage": current_storage,
                "duration_seconds": round(time.time() - started, 3),
                "finished_at": utc_now_iso(),
            }
        )
        logger.info(
            "MongoDB sync ok: raw_chunks=%s purged=%s duration=%ss",
            (sync_result or {}).get("raw_chunk_count"),
            (purge_result or {}).get("purged"),
            result["duration_seconds"],
        )
        append_sync_run_log(config.run_log_path, result)
        return result
    except Exception as exc:
        result.update(
            {
                "status": "error",
                "error": str(exc),
                "duration_seconds": round(time.time() - started, 3),
                "finished_at": utc_now_iso(),
            }
        )
        logger.exception("MongoDB sync failed: %s", exc)
        append_sync_run_log(config.run_log_path, result)
        return result


async def _scheduler_loop(config):
    global _scheduler_state
    logger = get_background_sync_logger(config.log_path)
    _scheduler_state.update(
        {
            "running": True,
            "started_at": utc_now_iso(),
            "stopped_at": None,
            "cycle_count": 0,
            "last_error": None,
            "config": asdict(config),
        }
    )
    logger.info("Background MongoDB sync scheduler started.")
    try:
        if not config.run_immediately:
            await asyncio.sleep(config.interval_seconds)
        while True:
            result = await asyncio.to_thread(run_background_sync_once, config)
            _scheduler_state["cycle_count"] = int(_scheduler_state.get("cycle_count") or 0) + 1
            _scheduler_state["last_run_at"] = utc_now_iso()
            _scheduler_state["last_result"] = result
            _scheduler_state["last_error"] = result.get("error")
            await asyncio.sleep(config.interval_seconds)
    except asyncio.CancelledError:
        logger.info("Background MongoDB sync scheduler stopped.")
        raise
    finally:
        _scheduler_state["running"] = False
        _scheduler_state["stopped_at"] = utc_now_iso()


async def start_background_sync_scheduler(config=None):
    global _scheduler_task, _scheduler_config
    config = (config or BackgroundSyncConfig.from_env()).validate()
    if _scheduler_task is not None and not _scheduler_task.done():
        return {"status": "already_running", "scheduler": get_background_sync_status()}
    _scheduler_config = config
    _scheduler_task = asyncio.create_task(_scheduler_loop(config))
    return {"status": "started", "scheduler": get_background_sync_status()}


async def stop_background_sync_scheduler():
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        return {"status": "not_running", "scheduler": get_background_sync_status()}
    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    return {"status": "stopped", "scheduler": get_background_sync_status()}


def get_background_sync_status():
    config = _scheduler_config or BackgroundSyncConfig.from_env()
    status = dict(_scheduler_state)
    status["task_active"] = bool(_scheduler_task is not None and not _scheduler_task.done())
    status["configured"] = is_mongodb_configured()
    status["config"] = asdict(config)
    return status
