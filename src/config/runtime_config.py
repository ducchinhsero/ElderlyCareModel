import json
import os
from pathlib import Path


DEFAULT_SENSOR_CONTEXT_CONFIG_PATH = "models/runtime/sensor_context_config.json"
_CONFIG_CACHE = {"path": None, "mtime": None, "payload": {}}


def sensor_context_config_path():
    return os.getenv("SENSOR_CONTEXT_CONFIG_PATH", DEFAULT_SENSOR_CONTEXT_CONFIG_PATH)


def clear_runtime_config_cache():
    _CONFIG_CACHE.update({"path": None, "mtime": None, "payload": {}})


def load_sensor_context_config(force=False):
    if os.getenv("SENSOR_CONTEXT_CONFIG_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return {}

    path = Path(sensor_context_config_path())
    if not path.exists():
        clear_runtime_config_cache()
        return {}

    mtime = path.stat().st_mtime
    cache_valid = (
        not force
        and _CONFIG_CACHE["path"] == str(path)
        and _CONFIG_CACHE["mtime"] == mtime
    )
    if cache_valid:
        return dict(_CONFIG_CACHE["payload"])

    payload = json.loads(path.read_text(encoding="utf-8"))
    _CONFIG_CACHE.update({"path": str(path), "mtime": mtime, "payload": payload})
    return dict(payload)


def get_config_section(section_name, default=None):
    payload = load_sensor_context_config()
    section = payload.get(section_name)
    if isinstance(section, dict):
        return dict(section)
    return {} if default is None else default
