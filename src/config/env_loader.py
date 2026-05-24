import os
from pathlib import Path


_LOADED = False


def load_env_file(path=".env"):
    global _LOADED
    if _LOADED:
        return

    env_path = _resolve_env_path(path)
    if env_path is None:
        return

    with open(env_path, "r", encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lstrip("\ufeff")
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    _LOADED = True


def _resolve_env_path(path):
    requested = Path(path)
    if requested.is_absolute():
        return requested if requested.exists() else None

    candidates = [Path.cwd() / requested]
    # src/config/env_loader.py -> project root is parents[2].
    candidates.append(Path(__file__).resolve().parents[2] / requested)
    candidates.extend(parent / requested for parent in Path.cwd().resolve().parents)

    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved
    return None
