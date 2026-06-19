"""Minimal read-only cloud API.

Serves the MongoDB-backed historical/report endpoints WITHOUT the Raspberry
Pi, so a remote caregiver can view previously-collected data even while the Pi
is offline. It reads only from MongoDB Atlas (the cloud archive the Pi syncs
to) — it never touches the Pi's local SQLite, Polar BLE, or ML models, so it
stays light enough to run on a free PaaS dyno.

Deploy (e.g. Render/Railway/Fly) with these env vars:
    MONGODB_URI            (required) — same Atlas URI the Pi syncs to
    MONGODB_DB             (optional, default "elderly_care")
    CLOUD_API_KEY          (recommended) — shared secret; the Flutter app sends
                           it as the X-API-Key header. Falls back to API_KEY.
    CLOUD_API_AUTH_ENABLED (optional, default "1") — set "0" only for local tests

Run: uvicorn src.api.cloud_reader:app --host 0.0.0.0 --port $PORT

Realtime live vitals are NOT served here — those require the Pi (Tailscale).
This service is the "previous days / reports" data path.
"""
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config.env_loader import load_env_file
from src.assessment.daily_report import (
    compute_daily_report,
    list_available_report_days,
)
from src.storage.mongodb_sync import get_mongo_database, is_mongodb_configured

load_env_file()


def _env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Public internet by default -> auth ON unless explicitly disabled for tests.
API_AUTH_ENABLED = _env_bool("CLOUD_API_AUTH_ENABLED", default=True)
API_KEY = (os.getenv("CLOUD_API_KEY") or os.getenv("API_KEY") or "").strip()
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
PUBLIC_PATHS = {"/health", "/", "/docs", "/openapi.json"}

app = FastAPI(title="Elderly Care Cloud Reader", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if not API_AUTH_ENABLED or request.method.upper() == "OPTIONS":
        return await call_next(request)
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    if not API_KEY:
        return JSONResponse(
            status_code=503,
            content={"detail": "Cloud auth is enabled but CLOUD_API_KEY is not set."},
        )
    supplied = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if supplied != API_KEY:
        return JSONResponse(
            status_code=401, content={"detail": "Invalid or missing API key."}
        )
    return await call_next(request)


@app.get("/")
def root():
    return {
        "service": "elderly_care_cloud_reader",
        "endpoints": [
            "/health",
            "/daily-report?date=YYYY-MM-DD&patient_id=",
            "/daily-report/available-days?patient_id=",
        ],
        "note": "Read-only MongoDB-backed historical data. Realtime vitals require the Pi.",
    }


@app.get("/health")
def health():
    """Liveness + MongoDB reachability (used by PaaS health checks)."""
    configured = is_mongodb_configured()
    mongo_ok = False
    error = None
    if configured:
        try:
            client, _db = get_mongo_database()
            client.admin.command("ping")
            mongo_ok = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if mongo_ok else "degraded",
        "mongodb_configured": configured,
        "mongodb_reachable": mongo_ok,
        "auth_enabled": API_AUTH_ENABLED,
        "error": error,
    }


@app.get("/daily-report/available-days")
def daily_report_available_days(patient_id: str = "polar_h10"):
    try:
        return list_available_report_days(patient_id=patient_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/daily-report")
def daily_report(date: str, patient_id: str = "polar_h10"):
    try:
        return compute_daily_report(patient_id=patient_id, date=date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
