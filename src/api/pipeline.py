import argparse
import asyncio
import json
import os
import threading
import time
import urllib.request
from datetime import datetime

import joblib
import numpy as np
import pandas as pd

from src.assessment.daily_health_assessment import compute_daily_health_assessment
from src.assessment.temporal_health_report import compute_temporal_health_report
from src.config.runtime_config import load_sensor_context_config, sensor_context_config_path
from src.features.acc_features import (
    FS_ACC_HZ,
    TYPE_ACC,
    parse_acc_packet,
    summarize_acc_window,
)
from src.calibration.anomaly_calibration import (
    has_calibration,
    load_calibrated_anomaly,
    train_calibration_from_real_data,
    train_calibration_from_session,
)
from src.calibration.personal_baseline import (
    calibrate_personal_baseline,
    get_personal_baseline_status,
    update_progressive_personal_baseline,
)
from src.calibration.guided_baseline import (
    complete_guided_baseline_day,
    complete_guided_baseline_segment,
    get_guided_baseline_status,
    start_guided_baseline_session,
)
from src.features.ecg_features import (
    ANOMALY_FEATURE_COLUMNS,
    bandpass_filter,
    detect_r_peaks,
    evaluate_signal_quality,
    estimate_heart_rate_bpm,
    extract_anomaly_feature_rows,
    load_feature_schema,
    rr_intervals_ms_from_peaks,
    rows_to_matrix,
)
from src.features.stress_features import STRESS_WINDOW_SECONDS
from src.inference.stress_inference import RollingRRBuffer, StressPredictor, unknown_stress
from src.network.provisioning import read_network_status
from src.storage.ecg_storage import (
    build_event_timeline,
    build_events_for_prediction,
    acknowledge_alert,
    alert_delivery_status,
    compute_daily_summary,
    compute_risk_summary,
    compute_session_summary,
    enqueue_alert_webhook,
    get_assessment_snapshots,
    get_history,
    get_pending_alert_webhooks,
    get_latest_ecg,
    get_realtime_alerts,
    get_raw_chunk,
    get_raw_chunks,
    get_collection_sessions,
    mark_alert_webhook_delivered,
    mark_alert_webhook_failed,
    purge_synced_raw_chunks,
    rebuild_event_table,
    resolve_alert,
    save_assessment_snapshot,
    save_prediction,
    storage_status,
    timestamp_to_epoch,
)
from src.storage.background_sync import (
    BackgroundSyncConfig,
    get_background_sync_status,
    run_background_sync_once,
    start_background_sync_scheduler,
    stop_background_sync_scheduler,
)
from src.storage.mongodb_sync import is_mongodb_configured, sync_to_mongodb
from src.services import mqtt_publisher
from src.inference.af_episode_tracker import AFEpisodeTracker
from src.inference.alert_engine import map_rhythm_to_alert
from src.inference.ectopy_inference import EctopyFeaturePredictor
from src.inference.hr_event import detect_hr_event
from src.inference.rhythm_inference import RhythmFeaturePredictor

try:
    from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError:  # Allows feature code and BLE demo to run without FastAPI installed.
    FastAPI = None
    HTTPException = RuntimeError
    Request = None
    HTMLResponse = None
    JSONResponse = None
    WebSocket = None
    WebSocketDisconnect = RuntimeError
    CORSMiddleware = None

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    BleakClient = None
    BleakScanner = None


MODEL_ROOT = os.getenv("MODEL_ROOT", "models")
STRESS_MODEL_DIR = os.getenv("STRESS_MODEL_DIR", os.path.join(MODEL_ROOT, "stress"))
ANOMALY_MODEL_PATH = os.getenv(
    "ANOMALY_MODEL_PATH",
    os.path.join(MODEL_ROOT, "anomaly_legacy", "isolation_forest_model.pkl"),
)
ANOMALY_SCALER_PATH = os.getenv(
    "ANOMALY_SCALER_PATH",
    os.path.join(MODEL_ROOT, "anomaly_legacy", "anomaly_scaler.pkl"),
)
ANOMALY_SCHEMA_PATH = os.getenv(
    "ANOMALY_SCHEMA_PATH",
    os.path.join(MODEL_ROOT, "anomaly_legacy", "anomaly_feature_schema.json"),
)
RHYTHM_MODEL_PATH = os.getenv(
    "RHYTHM_MODEL_PATH",
    os.path.join(MODEL_ROOT, "rhythm", "rhythm_feature_model.pkl"),
)
RHYTHM_SCALER_PATH = os.getenv(
    "RHYTHM_SCALER_PATH",
    os.path.join(MODEL_ROOT, "rhythm", "rhythm_scaler.pkl"),
)
RHYTHM_SCHEMA_PATH = os.getenv(
    "RHYTHM_SCHEMA_PATH",
    os.path.join(MODEL_ROOT, "rhythm", "rhythm_feature_schema.json"),
)
RHYTHM_LABEL_MAP_PATH = os.getenv(
    "RHYTHM_LABEL_MAP_PATH",
    os.path.join(MODEL_ROOT, "rhythm", "label_map.json"),
)
RHYTHM_DECISION_CONFIG_PATH = os.getenv(
    "RHYTHM_DECISION_CONFIG_PATH",
    os.path.join(MODEL_ROOT, "rhythm", "rhythm_decision_config.json"),
)
ECTOPY_MODEL_PATH = os.getenv(
    "ECTOPY_MODEL_PATH",
    os.path.join(MODEL_ROOT, "ectopy", "ectopy_feature_model.pkl"),
)
ECTOPY_SCALER_PATH = os.getenv(
    "ECTOPY_SCALER_PATH",
    os.path.join(MODEL_ROOT, "ectopy", "ectopy_scaler.pkl"),
)
ECTOPY_SCHEMA_PATH = os.getenv(
    "ECTOPY_SCHEMA_PATH",
    os.path.join(MODEL_ROOT, "ectopy", "ectopy_feature_schema.json"),
)
ECTOPY_LABEL_MAP_PATH = os.getenv(
    "ECTOPY_LABEL_MAP_PATH",
    os.path.join(MODEL_ROOT, "ectopy", "label_map.json"),
)
def _load_json_config(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


rhythm_decision_config = _load_json_config(RHYTHM_DECISION_CONFIG_PATH)
RHYTHM_AFIB_DECISION_MODE = os.getenv(
    "RHYTHM_AFIB_DECISION_MODE",
    str(rhythm_decision_config.get("decision_mode") or "probability_only"),
)
RHYTHM_AFIB_EPISODE_THRESHOLD = float(
    os.getenv(
        "RHYTHM_AFIB_EPISODE_THRESHOLD",
        rhythm_decision_config.get(
            "episode_threshold",
            rhythm_decision_config.get("afib_probability_threshold", 0.1),
        ),
    )
)
RHYTHM_AFIB_ALERT_THRESHOLD = float(
    os.getenv(
        "RHYTHM_AFIB_ALERT_THRESHOLD",
        rhythm_decision_config.get("alert_threshold", 0.3),
    )
)

REALTIME_SAMPLE_RATE_HZ = 130
WINDOW_SIZE = 10
STEP_SIZE = 5
REALTIME_LOG_PATH = "dataset/realtime_logs/predictions.jsonl"
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()
ALERT_WEBHOOK_LEVELS = {
    item.strip().lower()
    for item in os.getenv("ALERT_WEBHOOK_LEVELS", "medium,high,critical").split(",")
    if item.strip()
}
API_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
API_KEY = os.getenv("API_KEY", "").strip()
API_PUBLIC_PATHS = {
    item.strip()
    for item in os.getenv("API_PUBLIC_PATHS", "/health,/dashboard").split(",")
    if item.strip()
}
ALLOWED_ORIGINS = [
    item.strip()
    for item in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if item.strip()
]

HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"
POLAR_DEVICE_NAME = "Polar H10"
# Default Polar H10 MAC. The /polar/start endpoint uses this when the caller
# does not supply an explicit `address`. Override per-device by setting
# POLAR_H10_MAC in .env (preferred for multi-Pi deployments).
DEFAULT_POLAR_ADDRESS = (
    os.getenv("POLAR_H10_MAC")
    or os.getenv("POLAR_ADDRESS")
    or "24:AC:AC:13:EB:86"
)
TYPE_ECG = 0x00
# Polar H10 PMD command for ECG at 130 Hz. This command is verified by the
# standalone collector in D:\DATN\PolarH10\only_ecg.py.
ECG_START_CMD = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
ECG_STOP_CMD = bytearray([0x03, 0x00])
ACC_START_CMD = bytearray(
    [
        0x02,
        TYPE_ACC,
        0x00,
        0x01,
        FS_ACC_HZ,
        0x00,
        0x01,
        0x01,
        0x10,
        0x00,
        0x02,
        0x01,
        0x08,
        0x00,
    ]
)
ACC_STOP_CMD = bytearray([0x03, TYPE_ACC])


def _load_joblib(path):
    try:
        return joblib.load(path)
    except FileNotFoundError:
        return None


def _load_schema(path, fallback):
    try:
        return load_feature_schema(path)
    except FileNotFoundError:
        return list(fallback)


stress_predictor = StressPredictor(STRESS_MODEL_DIR)
anomaly_model = _load_joblib(ANOMALY_MODEL_PATH)
anomaly_scaler = _load_joblib(ANOMALY_SCALER_PATH)
rhythm_predictor = RhythmFeaturePredictor(
    model_path=RHYTHM_MODEL_PATH,
    scaler_path=RHYTHM_SCALER_PATH,
    schema_path=RHYTHM_SCHEMA_PATH,
    label_map_path=RHYTHM_LABEL_MAP_PATH,
)
ectopy_predictor = EctopyFeaturePredictor(
    model_path=ECTOPY_MODEL_PATH,
    scaler_path=ECTOPY_SCALER_PATH,
    schema_path=ECTOPY_SCHEMA_PATH,
    label_map_path=ECTOPY_LABEL_MAP_PATH,
)
anomaly_feature_columns = _load_schema(ANOMALY_SCHEMA_PATH, ANOMALY_FEATURE_COLUMNS)
latest_result = None
prediction_history = []
vitals_websocket_clients = set()
alert_websocket_clients = {}
polar_task = None
polar_status = {
    "running": False,
    "address": None,
    "last_error": None,
    "last_update": None,
    "last_packet_at": None,
    "last_prediction_at": None,
    "connect_attempts": 0,
    "successful_connections": 0,
    "reconnect_count": 0,
    "last_connected_at": None,
    "last_disconnected_at": None,
}
calibrated_anomaly_cache = {}
af_episode_trackers = {}
stress_rr_buffers = {}


def _unknown_rhythm(reason):
    return {
        "label": "unknown",
        "class_id": None,
        "confidence": 0.0,
        "probabilities": {},
        "possible_afib_probability": 0.0,
        "window_count": 0,
        "reason": reason,
    }


def _unknown_hr_event(reason="No reliable heart-rate event available."):
    return {
        "label": "unknown",
        "tachycardia": False,
        "bradycardia": False,
        "reason": reason,
    }


def _unknown_ectopy(reason):
    return {
        "label": "unknown",
        "class_id": None,
        "confidence": 0.0,
        "probabilities": {},
        "pvc_probability": 0.0,
        "pac_probability": 0.0,
        "ectopic_probability": 0.0,
        "window_count": 0,
        "reason": reason,
        "model_source": "ectopy_feature_model",
    }


def _unknown_af_episode(reason="No reliable rhythm result available."):
    return {
        "active": False,
        "current_episode_duration_sec": 0.0,
        "af_episode_count": 0,
        "longest_af_episode_sec": 0.0,
        "total_af_duration_sec": 0.0,
        "af_burden_percent": 0.0,
        "decision_mode": RHYTHM_AFIB_DECISION_MODE,
        "afib_probability_threshold": RHYTHM_AFIB_EPISODE_THRESHOLD,
        "reason": reason,
    }


def _get_af_tracker(patient_id):
    key = patient_id or "unknown"
    if key not in af_episode_trackers:
        af_episode_trackers[key] = AFEpisodeTracker(
            window_seconds=30.0,
            afib_probability_threshold=RHYTHM_AFIB_EPISODE_THRESHOLD,
            decision_mode=RHYTHM_AFIB_DECISION_MODE,
        )
    return af_episode_trackers[key]


def _predict_rhythm(ecg_samples, sample_rate_hz):
    return rhythm_predictor.predict(ecg_samples, sample_rate_hz)


def _persist_result(result):
    os.makedirs(os.path.dirname(REALTIME_LOG_PATH), exist_ok=True)
    with open(REALTIME_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def _websocket_payload(result):
    return {
        "type": "vitals",
        "latest_result": result,
        "timestamp": result.get("timestamp") if result else None,
    }


def _broadcast_result(result):
    if not vitals_websocket_clients:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    payload = _websocket_payload(result)

    async def _send():
        stale_clients = []
        for client in list(vitals_websocket_clients):
            try:
                await client.send_json(payload)
            except Exception:
                stale_clients.append(client)
        for client in stale_clients:
            vitals_websocket_clients.discard(client)

    loop.create_task(_send())


def _urgent_events_for_result(result):
    if not result:
        return []
    return [
        event
        for event in build_events_for_prediction(result)
        if str(event.get("severity") or "").lower() in {"high", "critical"}
    ]


def _alert_websocket_payload(event):
    if event and "ack_status" not in event:
        event = {
            **event,
            "ack_status": {
                "acknowledged": False,
                "resolved": False,
                "status": "unacknowledged",
            },
        }
    return {
        "type": "alert",
        "alert": event,
        "timestamp": event.get("timestamp") if event else None,
    }


def _broadcast_urgent_alerts(events):
    if not events or not alert_websocket_clients:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _send():
        stale_clients = []
        for client, options in list(alert_websocket_clients.items()):
            patient_id = options.get("patient_id")
            for event in events:
                if patient_id and event.get("patient_id") != patient_id:
                    continue
                try:
                    await client.send_json(_alert_websocket_payload(event))
                except Exception:
                    stale_clients.append(client)
                    break
        for client in stale_clients:
            alert_websocket_clients.pop(client, None)

    loop.create_task(_send())


def _send_webhook_payload(payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ALERT_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5):
        pass


def _process_alert_webhook_outbox(limit=10):
    if not ALERT_WEBHOOK_URL:
        return {"processed": 0}
    processed = 0
    for item in get_pending_alert_webhooks(limit=limit):
        try:
            _send_webhook_payload(item["payload"])
            mark_alert_webhook_delivered(item["webhook_id"])
        except Exception as exc:
            mark_alert_webhook_failed(item["webhook_id"], exc)
            print(f"Alert webhook failed: {exc}")
        processed += 1
    return {"processed": processed}


def _push_alert_webhook(result):
    if not ALERT_WEBHOOK_URL or not result:
        return
    events = [
        event
        for event in build_events_for_prediction(result)
        if str(event.get("severity") or event.get("level") or "").lower()
        in ALERT_WEBHOOK_LEVELS
    ]
    if not events:
        return
    payload = {
        "type": "elderly_care_alert",
        "patient_id": result.get("patient_id"),
        "timestamp": result.get("timestamp"),
        "alert_level": result.get("alert_level"),
        "message": result.get("message"),
        "heart_rate_bpm": result.get("heart_rate_bpm"),
        "events": events,
        "latest_result": result,
    }
    enqueue_alert_webhook(
        payload,
        event_ids=[event.get("event_id") for event in events if event.get("event_id")],
    )
    threading.Thread(target=_process_alert_webhook_outbox, daemon=True).start()


def record_result(
    result,
    ecg_samples=None,
    sample_rate_hz=None,
    acc_samples=None,
    acc_sample_rate_hz=None,
):
    global latest_result
    if ecg_samples is not None and sample_rate_hz is not None:
        result = save_prediction(
            result,
            ecg_samples,
            sample_rate_hz,
            acc_samples=acc_samples,
            acc_sample_rate_hz=acc_sample_rate_hz,
        )
    latest_result = result
    prediction_history.append(result)
    del prediction_history[:-50]
    _persist_result(result)
    _broadcast_result(result)
    _broadcast_urgent_alerts(_urgent_events_for_result(result))
    _push_alert_webhook(result)
    # MQTT publish — non-blocking, fire-and-forget. Separate from WebSocket
    # because MQTT survives app being killed (broker retains the last alert),
    # and from webhook because MQTT brokers handle reconnect/queueing.
    _publish_mqtt(result)
    return result


def _publish_mqtt(result):
    """Push to local MQTT broker (alert + live vitals). Never raises."""
    if not result or not mqtt_publisher.is_enabled():
        return
    try:
        mqtt_publisher.publish_vitals(result)
    except Exception as exc:  # noqa: BLE001
        # Never let MQTT failure poison the pipeline.
        print(f"MQTT publish_vitals error (non-fatal): {exc}")
    try:
        events = build_events_for_prediction(result)
        mqtt_publisher.publish_alert(result, events=events)
    except Exception as exc:  # noqa: BLE001
        print(f"MQTT publish_alert error (non-fatal): {exc}")


try:
    stored_history = list(reversed(get_history(days=7, limit=50)))
    if stored_history:
        prediction_history.extend(stored_history)
        latest_result = stored_history[-1]
except Exception:
    pass


def _validate_feature_schema(actual, expected, name):
    if list(actual) != list(expected):
        raise ValueError(
            f"{name} feature schema mismatch. Expected {expected}, got {actual}."
        )


def _get_stress_buffer(patient_id):
    key = patient_id or "unknown"
    if key not in stress_rr_buffers:
        stress_rr_buffers[key] = RollingRRBuffer(max_seconds=max(360.0, STRESS_WINDOW_SECONDS + 60.0))
    return stress_rr_buffers[key]


def _predict_stress_for_patient(ecg, sample_rate_hz, patient_id, timestamp):
    filtered = bandpass_filter(ecg, sample_rate_hz)
    peaks = detect_r_peaks(filtered, sample_rate_hz)
    chunk_start_epoch = timestamp_to_epoch(timestamp)
    if chunk_start_epoch is None:
        chunk_start_epoch = datetime.now().astimezone().timestamp() - (len(ecg) / float(sample_rate_hz))
    buffer = _get_stress_buffer(patient_id)
    buffer.add_from_peaks(peaks, sample_rate_hz, chunk_start_epoch=chunk_start_epoch)
    rr_window, rr_timestamps, coverage = buffer.stress_window(window_seconds=stress_predictor.window_seconds)
    if not buffer.ready(window_seconds=stress_predictor.window_seconds):
        result = unknown_stress(
            "warming_up_stress_window",
            model_version=stress_predictor.model_version,
            window_seconds=stress_predictor.window_seconds,
        )
        result["rr_count"] = int(rr_window.size)
        result["coverage_seconds"] = round(float(coverage), 2)
        return result
    result = stress_predictor.predict_from_rr(rr_window, rr_timestamps_sec=rr_timestamps)
    result["rr_count"] = int(rr_window.size)
    result["coverage_seconds"] = round(float(coverage), 2)
    return result


def _get_calibrated_anomaly(patient_id):
    if not patient_id:
        return None
    if patient_id not in calibrated_anomaly_cache:
        calibrated_anomaly_cache[patient_id] = load_calibrated_anomaly(patient_id)
    return calibrated_anomaly_cache[patient_id]


def _predict_anomaly_with_model(
    feature_rows,
    model,
    scaler,
    source,
    allow_distribution_guard=True,
    decision_threshold=None,
):
    X = pd.DataFrame(rows_to_matrix(feature_rows, anomaly_feature_columns), columns=anomaly_feature_columns)
    X_scaled = scaler.transform(X)

    if allow_distribution_guard:
        morphology_z = np.abs(X_scaled[:, 5:])
        max_morphology_z = float(np.max(morphology_z)) if morphology_z.size else 0.0
        if max_morphology_z > 25.0:
            return {
                "label": "unknown",
                "value": None,
                "anomaly_windows": 0,
                "total_windows": len(feature_rows),
                "reason": (
                    "Anomaly model input is outside the training distribution. "
                    "Retrain or calibrate anomaly model with Polar H10 normal data."
                ),
                "max_morphology_z": max_morphology_z,
                "model_source": source,
            }

    decision_scores = model.decision_function(X_scaled)
    if decision_threshold is None:
        raw_pred = model.predict(X_scaled)
        binary_pred = np.where(raw_pred == -1, 1, 0)
    else:
        binary_pred = np.where(decision_scores < float(decision_threshold), 1, 0)

    anomaly_windows = int(np.sum(binary_pred == 1))
    total_windows = int(len(binary_pred))
    value = 1 if anomaly_windows >= max(1, int(np.ceil(total_windows * 0.34))) else 0

    return {
        "label": "abnormal" if value == 1 else "normal",
        "value": value,
        "anomaly_windows": anomaly_windows,
        "total_windows": total_windows,
        "model_source": source,
        "mean_decision_score": float(np.mean(decision_scores)),
        "decision_threshold": None if decision_threshold is None else float(decision_threshold),
    }


def _summarize_anomaly(feature_rows, patient_id=None):
    if not feature_rows:
        return {
            "label": "unknown",
            "value": None,
            "anomaly_windows": 0,
            "total_windows": 0,
        }

    calibrated = _get_calibrated_anomaly(patient_id)
    if calibrated is not None:
        return _predict_anomaly_with_model(
            feature_rows,
            calibrated["model"],
            calibrated["scaler"],
            source="polar_calibrated",
            allow_distribution_guard=False,
            decision_threshold=calibrated["metadata"].get("decision_threshold"),
        )

    if anomaly_model is None or anomaly_scaler is None:
        return {
            "label": "unknown",
            "value": None,
            "anomaly_windows": 0,
            "total_windows": len(feature_rows),
        }

    _validate_feature_schema(anomaly_feature_columns, ANOMALY_FEATURE_COLUMNS, "anomaly")
    return _predict_anomaly_with_model(
        feature_rows,
        anomaly_model,
        anomaly_scaler,
        source="generic_mitbih_ptbdb",
        allow_distribution_guard=True,
    )


def _alert_and_message(stress, anomaly):
    stress_label = stress["label"]
    anomaly_label = anomaly["label"]

    if anomaly_label == "abnormal" and stress_label == "stress":
        return "critical", "Stress and abnormal ECG signal detected."
    if anomaly_label == "abnormal":
        return "high", "Abnormal ECG signal detected."
    if stress_label == "stress":
        return "medium", "Stress detected. ECG anomaly not detected."
    if stress_label == "non_stress" and anomaly_label == "normal":
        return "normal", "No stress or ECG anomaly detected."
    return "unknown", "Not enough reliable ECG data for a confident result."


def _rhythm_first_alert(rhythm_alert, legacy_alert_level, legacy_message, anomaly, risk):
    rhythm_alert = rhythm_alert or {}
    rhythm_level = rhythm_alert.get("level") or "unknown"
    rhythm_message = rhythm_alert.get("message") or "No significant rhythm abnormality detected."
    anomaly_label = (anomaly or {}).get("label")
    risk = risk or {}

    if rhythm_level in {"critical", "high", "medium"}:
        return rhythm_level, rhythm_message

    if risk.get("level") in {"high", "medium"}:
        return risk["level"], risk.get("reason") or "Risk trend requires monitoring."

    if anomaly_label == "abnormal" and legacy_alert_level in {"critical", "high"}:
        return legacy_alert_level, legacy_message

    if rhythm_level == "normal":
        return "normal", rhythm_message

    if legacy_alert_level in {"critical", "high"}:
        return legacy_alert_level, legacy_message

    return "unknown", rhythm_message if rhythm_level != "unknown" else legacy_message


def _suppress_activity_stress_alert(alert_level, message, stress, anomaly, sensor_context):
    activity = ((sensor_context or {}).get("activity_state") or "unknown").upper()
    stress_label = (stress or {}).get("label")
    anomaly_label = (anomaly or {}).get("label")
    if (
        alert_level == "medium"
        and stress_label == "stress"
        and anomaly_label != "abnormal"
        and activity in {"WALK", "ACTIVE"}
    ):
        return (
            "unknown",
            "Stress model output suppressed during physical activity; use rhythm and HR context instead.",
        )
    return alert_level, message


def _apply_sensor_context_alert(alert_level, message, sensor_context):
    if not sensor_context:
        return alert_level, message

    fall = sensor_context.get("fall") or {}
    if fall.get("strong_fall"):
        return (
            "critical",
            (
                f"Strong fall detected: impact {fall.get('peak_vm', 0):.0f} mG, "
                f"free-fall minimum {fall.get('min_before_1s', 0):.0f} mG."
            ),
        )
    if fall.get("fall_candidate") and alert_level not in ("critical", "high"):
        return "high", f"Possible fall detected: impact {fall.get('peak_vm', 0):.0f} mG."

    hr_context = sensor_context.get("hr_context_alert") or {}
    hr_level = hr_context.get("level")
    if hr_level == "CRITICAL" and alert_level not in ("critical",):
        return "critical", hr_context.get("reason") or "Critical heart-rate context detected."
    if hr_level == "ALERT" and alert_level not in ("critical", "high"):
        return "high", hr_context.get("reason") or "Heart-rate context alert detected."
    if hr_level == "WATCH" and alert_level in ("normal", "unknown"):
        return "medium", hr_context.get("reason") or "Heart-rate context requires monitoring."
    return alert_level, message


def _unknown_outputs_for_quality(signal_quality):
    reason = "; ".join(signal_quality.get("reasons") or ["Poor signal quality"])
    stress = unknown_stress(reason, model_version=stress_predictor.model_version, window_seconds=stress_predictor.window_seconds)
    anomaly = {
        "label": "unknown",
        "value": None,
        "anomaly_windows": 0,
        "total_windows": 0,
        "reason": reason,
    }
    risk = {"level": "unknown", "score": 0.0, "reason": "Signal quality is too poor for risk scoring."}
    return stress, anomaly, risk


def _risk_with_current(patient_id, anomaly, stress, signal_quality):
    if anomaly.get("value") is None:
        return {
            "level": "unknown",
            "score": 0.0,
            "reason": anomaly.get("reason") or "Anomaly model did not produce a reliable result.",
        }

    risk = compute_risk_summary(patient_id=patient_id, days=1)
    if signal_quality.get("label") not in ("good", "fair"):
        return {"level": "unknown", "score": 0.0, "reason": "Signal quality is too poor for risk scoring."}

    if risk["level"] == "unknown":
        if anomaly.get("value") == 1:
            return {"level": "medium", "score": 0.45, "reason": "Current ECG window is abnormal; more history is needed."}
        return {"level": "low", "score": 0.05, "reason": "Current ECG window is normal; more history is needed."}

    score = float(risk.get("score") or 0.0)
    if anomaly.get("value") == 1:
        score = min(1.0, score + 0.2)
    if stress.get("label") == "stress":
        score = min(1.0, score + 0.05)

    if score >= 0.65:
        level = "high"
    elif score >= 0.35:
        level = "medium"
    else:
        level = "low"
    return {**risk, "level": level, "score": round(score, 3)}


def _estimate_heart_rate_from_signal(ecg, sample_rate_hz, feature_rows=None):
    heart_rate = estimate_heart_rate_bpm(feature_rows or [])
    if heart_rate is not None:
        return heart_rate
    filtered = bandpass_filter(ecg, sample_rate_hz)
    peaks = detect_r_peaks(filtered, sample_rate_hz)
    rr_ms = rr_intervals_ms_from_peaks(peaks, sample_rate_hz)
    rr_ms = rr_ms[(rr_ms >= 300.0) & (rr_ms <= 2000.0)]
    if rr_ms.size == 0:
        return None
    return float(60000.0 / np.mean(rr_ms))


def predict_ecg(
    ecg_samples,
    sample_rate_hz,
    patient_id=None,
    timestamp=None,
    acc_samples=None,
    acc_sample_rate_hz=FS_ACC_HZ,
):
    if sample_rate_hz is None or float(sample_rate_hz) <= 0:
        raise ValueError("sample_rate_hz must be a positive number.")
    if ecg_samples is None:
        raise ValueError("ecg_samples is required.")

    ecg = np.asarray(ecg_samples, dtype=float).flatten()
    if ecg.size == 0:
        raise ValueError("ecg_samples must contain at least one sample.")

    result_timestamp = timestamp or datetime.now().astimezone().isoformat()
    signal_quality = evaluate_signal_quality(ecg, float(sample_rate_hz))
    if signal_quality["label"] == "poor":
        stress, anomaly, risk = _unknown_outputs_for_quality(signal_quality)
        rhythm = _unknown_rhythm("Signal quality is too poor for rhythm classification.")
        ectopy = _unknown_ectopy("Signal quality is too poor for PVC/PAC classification.")
        hr_event = _unknown_hr_event("Signal quality is too poor for heart-rate event detection.")
        af_episode = _unknown_af_episode("Signal quality is too poor for AF episode tracking.")
        rhythm_alert = {
            "level": "unknown",
            "message": "Poor ECG signal quality. Rhythm classification skipped.",
        }
        sensor_context = summarize_acc_window(
            acc_samples,
            heart_rate_bpm=None,
            sample_rate_hz=acc_sample_rate_hz or FS_ACC_HZ,
        )
        alert_level, message = "unknown", "Poor ECG signal quality. Prediction skipped."
        alert_level, message = _apply_sensor_context_alert(alert_level, message, sensor_context)
        return {
            "patient_id": patient_id,
            "timestamp": result_timestamp,
            "sample_rate_hz": float(sample_rate_hz),
            "window_count": 0,
            "heart_rate_bpm": None,
            "stress": stress,
            "anomaly": anomaly,
            "rhythm": rhythm,
            "ectopy": ectopy,
            "hr_event": hr_event,
            "af_episode": af_episode,
            "rhythm_alert": rhythm_alert,
            "signal_quality": signal_quality,
            "risk": risk,
            "sensor_context": sensor_context,
            "alert_level": alert_level,
            "message": message,
        }

    anomaly_rows = extract_anomaly_feature_rows(
        ecg,
        sample_rate_hz=float(sample_rate_hz),
        window_size=WINDOW_SIZE,
        step_size=STEP_SIZE,
        filter_signal=True,
    )

    window_count = len(anomaly_rows)
    stress = _predict_stress_for_patient(ecg, float(sample_rate_hz), patient_id, result_timestamp)
    anomaly = _summarize_anomaly(anomaly_rows, patient_id=patient_id)
    risk = _risk_with_current(patient_id, anomaly, stress, signal_quality)
    alert_level, message = _alert_and_message(stress, anomaly)
    if risk["level"] == "high" and alert_level not in ("critical", "high"):
        alert_level = "high"
        message = "High ECG risk trend detected from recent history."
    elif risk["level"] == "medium" and alert_level == "normal":
        alert_level = "medium"
        message = "Medium ECG risk trend detected from recent history."
    heart_rate_bpm = _estimate_heart_rate_from_signal(ecg, float(sample_rate_hz), anomaly_rows)
    sensor_context = summarize_acc_window(
        acc_samples,
        heart_rate_bpm=heart_rate_bpm,
        sample_rate_hz=acc_sample_rate_hz or FS_ACC_HZ,
    )
    alert_level, message = _suppress_activity_stress_alert(
        alert_level,
        message,
        stress,
        anomaly,
        sensor_context,
    )
    rhythm = _predict_rhythm(ecg, float(sample_rate_hz))
    ectopy = ectopy_predictor.predict(ecg, float(sample_rate_hz))
    afib_probability = float(
        rhythm.get("possible_afib_probability")
        if rhythm.get("possible_afib_probability") is not None
        else (rhythm.get("probabilities") or {}).get("possible_afib", 0.0)
    )
    rhythm_for_alert = rhythm.get("label")
    rhythm_confidence_for_alert = rhythm.get("confidence")
    if (
        rhythm.get("label") != "unknown"
        and RHYTHM_AFIB_DECISION_MODE == "probability_only"
        and afib_probability >= RHYTHM_AFIB_ALERT_THRESHOLD
    ):
        rhythm_for_alert = "possible_afib"
        rhythm_confidence_for_alert = afib_probability
    rhythm["possible_afib_probability"] = afib_probability
    rhythm["afib_decision"] = {
        "mode": RHYTHM_AFIB_DECISION_MODE,
        "episode_threshold": RHYTHM_AFIB_EPISODE_THRESHOLD,
        "alert_threshold": RHYTHM_AFIB_ALERT_THRESHOLD,
        "label_for_alert": rhythm_for_alert,
    }
    activity_state = (sensor_context or {}).get("activity_state") or "unknown"
    hr_event = detect_hr_event(
        heart_rate_bpm,
        activity_state=activity_state,
        duration_sec=float(ecg.size) / float(sample_rate_hz),
    )
    rhythm_alert_level, rhythm_alert_message = map_rhythm_to_alert(
        rhythm_for_alert,
        rhythm_confidence_for_alert,
        hr_event=hr_event,
        signal_quality_label=signal_quality.get("label"),
        possible_afib_probability=afib_probability,
        activity_state=activity_state,
    )
    rhythm_alert = {
        "level": rhythm_alert_level,
        "message": rhythm_alert_message,
    }
    alert_level, message = _rhythm_first_alert(
        rhythm_alert,
        alert_level,
        message,
        anomaly,
        risk,
    )
    if rhythm.get("label") == "unknown":
        af_episode = _unknown_af_episode(rhythm.get("reason") or "Rhythm classification unavailable.")
    else:
        af_episode = _get_af_tracker(patient_id).update(
            rhythm.get("label"),
            possible_afib_probability=afib_probability,
        )
    alert_level, message = _apply_sensor_context_alert(alert_level, message, sensor_context)

    return {
        "patient_id": patient_id,
        "timestamp": result_timestamp,
        "sample_rate_hz": float(sample_rate_hz),
        "window_count": window_count,
        "heart_rate_bpm": None if heart_rate_bpm is None else round(heart_rate_bpm, 2),
        "stress": stress,
        "anomaly": anomaly,
        "rhythm": rhythm,
        "ectopy": ectopy,
        "hr_event": hr_event,
        "af_episode": af_episode,
        "rhythm_alert": rhythm_alert,
        "signal_quality": signal_quality,
        "risk": risk,
        "sensor_context": sensor_context,
        "alert_level": alert_level,
        "message": message,
    }


async def find_polar_h10(timeout=20):
    if BleakScanner is None:
        raise RuntimeError("bleak is not installed. Install it to use Polar H10 collection.")

    def polar_filter(device, adv):
        if device.name and POLAR_DEVICE_NAME in device.name:
            return True
        if adv and getattr(adv, "local_name", None) and POLAR_DEVICE_NAME in adv.local_name:
            return True
        return False

    device = await BleakScanner.find_device_by_filter(polar_filter, timeout=timeout)
    if device is None:
        raise RuntimeError(f"Could not find {POLAR_DEVICE_NAME} during BLE scan")
    return device.address


async def collect_bluetooth_data(address, duration_seconds=30, collect_rr=False):
    if BleakClient is None:
        raise RuntimeError("bleak is not installed. Install it to use Polar H10 collection.")

    collected_rr = []
    collected_ecg = []
    pmd_packets_seen = 0
    pmd_ecg_packets_seen = 0

    async with BleakClient(address, timeout=30.0) as client:
        if not client.is_connected:
            raise RuntimeError("Unable to connect to Polar H10")

        def hr_callback(sender, data):
            flag = data[0]
            offset = 1
            if flag & 0x01:
                offset += 2
            else:
                offset += 1
            if flag & 0x08:
                offset += 2

            has_rr = (flag & 0x10) != 0
            if has_rr:
                while offset + 1 < len(data):
                    rr_raw = int.from_bytes(data[offset : offset + 2], "little")
                    collected_rr.append((rr_raw / 1024.0) * 1000.0)
                    offset += 2

        def ecg_callback(sender, data):
            nonlocal pmd_packets_seen, pmd_ecg_packets_seen
            pmd_packets_seen += 1
            if len(data) < 10 or data[0] != 0x00:
                return
            pmd_ecg_packets_seen += 1
            for i in range(10, len(data) - 2, 3):
                raw = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16)
                if raw & 0x800000:
                    raw -= 0x1000000
                sample = raw
                collected_ecg.append(sample)

        print(f"Connecting to Polar H10 at {address}...")
        hr_notify_started = False
        if collect_rr:
            try:
                await client.start_notify(HR_UUID, hr_callback)
                hr_notify_started = True
                print("HR/RR stream enabled.")
            except Exception as exc:
                print(f"HR/RR stream unavailable, continuing with ECG only: {exc}")
        await client.write_gatt_char(PMD_CONTROL, ECG_START_CMD, response=True)
        await asyncio.sleep(0.3)
        await client.start_notify(PMD_DATA, ecg_callback)
        print("ECG stream enabled.")
        try:
            await asyncio.sleep(duration_seconds)
        finally:
            try:
                await client.write_gatt_char(PMD_CONTROL, ECG_STOP_CMD, response=True)
            except Exception:
                pass
            try:
                await client.stop_notify(PMD_DATA)
            except Exception:
                pass
            if hr_notify_started:
                try:
                    await client.stop_notify(HR_UUID)
                except Exception:
                    pass

    stats = {
        "pmd_packets_seen": pmd_packets_seen,
        "pmd_ecg_packets_seen": pmd_ecg_packets_seen,
    }
    return np.array(collected_ecg), np.array(collected_rr), stats


async def bluetooth_prediction_stream(address, chunk_seconds=10):
    if BleakClient is None:
        raise RuntimeError("bleak is not installed. Install it to use Polar H10 collection.")

    # Cap collected buffers at ~3x the steady-state size for this chunk window.
    # If predict_ecg or SQLite write blocks longer than chunk_seconds (eg DB
    # locked, MongoDB sync running), the BLE callback keeps appending. Without
    # a cap, we'd OOM the Pi after a few stalls. deque.append() silently drops
    # the oldest sample once maxlen is hit — losing some samples is preferable
    # to crashing the process.
    from collections import deque

    ecg_buffer_cap = max(int(REALTIME_SAMPLE_RATE_HZ * chunk_seconds * 3), 4000)
    acc_buffer_cap = max(int(FS_ACC_HZ * chunk_seconds * 3), 1000)
    rr_buffer_cap = 2000  # ~10 min of RR @ 60bpm, defensive
    collected_rr = deque(maxlen=rr_buffer_cap)
    collected_ecg = deque(maxlen=ecg_buffer_cap)
    collected_acc = deque(maxlen=acc_buffer_cap)
    pmd_packets_seen = 0
    pmd_ecg_packets_seen = 0
    pmd_acc_packets_seen = 0
    next_report_at = asyncio.get_running_loop().time() + chunk_seconds

    def hr_callback(sender, data):
        flag = data[0]
        offset = 1
        if flag & 0x01:
            offset += 2
        else:
            offset += 1
        if flag & 0x08:
            offset += 2

        if flag & 0x10:
            while offset + 1 < len(data):
                rr_raw = int.from_bytes(data[offset : offset + 2], "little")
                collected_rr.append((rr_raw / 1024.0) * 1000.0)
                offset += 2

    def pmd_callback(sender, data):
        nonlocal pmd_packets_seen, pmd_ecg_packets_seen, pmd_acc_packets_seen
        pmd_packets_seen += 1
        if len(data) < 10:
            return
        data_type = data[0] & 0x3F
        if data_type == TYPE_ECG:
            pmd_ecg_packets_seen += 1
            for i in range(10, len(data) - 2, 3):
                raw = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16)
                if raw & 0x800000:
                    raw -= 0x1000000
                collected_ecg.append(raw)
        elif data_type == TYPE_ACC:
            _, samples = parse_acc_packet(bytes(data))
            if samples:
                pmd_acc_packets_seen += 1
                collected_acc.extend(samples)

    print(f"Connecting to Polar H10 at {address}...")
    polar_status["connect_attempts"] = int(polar_status.get("connect_attempts") or 0) + 1
    async with BleakClient(address, timeout=20) as client:
        if not client.is_connected:
            raise RuntimeError("Unable to connect to Polar H10")
        polar_status["successful_connections"] = int(polar_status.get("successful_connections") or 0) + 1
        polar_status["last_connected_at"] = datetime.now().astimezone().isoformat()

        hr_notify_started = False
        try:
            await client.start_notify(HR_UUID, hr_callback)
            hr_notify_started = True
            print("HR/RR stream enabled.")
        except Exception as exc:
            print(f"HR/RR stream unavailable, continuing with ECG only: {exc}")
        await client.start_notify(PMD_DATA, pmd_callback)
        print("PMD data notifications enabled.")
        await client.write_gatt_char(PMD_CONTROL, ECG_START_CMD, response=True)
        await asyncio.sleep(0.3)
        print("ECG stream enabled.")
        try:
            await client.write_gatt_char(PMD_CONTROL, ACC_START_CMD, response=True)
            await asyncio.sleep(0.3)
            print("ACC stream enabled.")
        except Exception as exc:
            polar_status["last_error"] = f"ACC stream unavailable, continuing ECG-only: {exc}"
            print(polar_status["last_error"])

        try:
            while client.is_connected:
                await asyncio.sleep(0.5)
                now = asyncio.get_running_loop().time()
                if now < next_report_at:
                    continue

                ecg_signal = np.array(collected_ecg, dtype=float)
                acc_signal = list(collected_acc)
                rr_intervals = np.array(collected_rr, dtype=float)
                stats = {
                    "pmd_packets_seen": pmd_packets_seen,
                    "pmd_ecg_packets_seen": pmd_ecg_packets_seen,
                    "pmd_acc_packets_seen": pmd_acc_packets_seen,
                }
                if pmd_packets_seen:
                    polar_status["last_packet_at"] = datetime.now().astimezone().isoformat()
                print(
                    f"Collected ECG samples: {len(ecg_signal)}, "
                    f"ACC samples: {len(acc_signal)}, "
                    f"RR intervals: {len(rr_intervals)}, "
                    f"PMD packets: {stats['pmd_packets_seen']}, "
                    f"ECG packets: {stats['pmd_ecg_packets_seen']}, "
                    f"ACC packets: {stats['pmd_acc_packets_seen']}"
                )

                collected_ecg.clear()
                collected_acc.clear()
                collected_rr.clear()
                pmd_packets_seen = 0
                pmd_ecg_packets_seen = 0
                pmd_acc_packets_seen = 0
                next_report_at = now + chunk_seconds

                if len(ecg_signal) == 0:
                    print(
                        "No ECG samples received in this window. Continuing on the same "
                        "connection; check whether another app is using the PMD stream."
                    )
                    continue

                result = predict_ecg(
                    ecg_signal,
                    sample_rate_hz=REALTIME_SAMPLE_RATE_HZ,
                    patient_id="polar_h10",
                    acc_samples=acc_signal,
                    acc_sample_rate_hz=FS_ACC_HZ,
                )
                record_result(
                    result,
                    ecg_signal.tolist(),
                    REALTIME_SAMPLE_RATE_HZ,
                    acc_samples=acc_signal if acc_signal else None,
                    acc_sample_rate_hz=FS_ACC_HZ if acc_signal else None,
                )
                polar_status["last_update"] = result["timestamp"]
                polar_status["last_prediction_at"] = result["timestamp"]
                print(result)
        finally:
            polar_status["last_disconnected_at"] = datetime.now().astimezone().isoformat()
            try:
                await client.write_gatt_char(PMD_CONTROL, ACC_STOP_CMD, response=True)
            except Exception:
                pass
            try:
                await client.write_gatt_char(PMD_CONTROL, ECG_STOP_CMD, response=True)
            except Exception:
                pass
            try:
                await client.stop_notify(PMD_DATA)
            except Exception:
                pass
            if hr_notify_started:
                try:
                    await client.stop_notify(HR_UUID)
                except Exception:
                    pass


async def polar_background_collector(address, chunk_seconds=10):
    polar_status.update(
        {
            "running": True,
            "address": address,
            "last_error": None,
            "last_update": None,
            "started_at": datetime.now().astimezone().isoformat(),
        }
    )
    seen_successful_connection = False
    try:
        while True:
            try:
                await bluetooth_prediction_stream(address, chunk_seconds=chunk_seconds)
                seen_successful_connection = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if seen_successful_connection or int(polar_status.get("successful_connections") or 0) > 0:
                    polar_status["reconnect_count"] = int(polar_status.get("reconnect_count") or 0) + 1
                polar_status["last_error"] = str(exc)
                print(f"Polar background collector error: {exc}. Reconnecting in 10 seconds.")
                await asyncio.sleep(10)
    finally:
        polar_status["running"] = False
        polar_status["stopped_at"] = datetime.now().astimezone().isoformat()


async def bluetooth_demo_loop(address=None):
    device_address = address or await find_polar_h10(timeout=20)
    while True:
        try:
            await bluetooth_prediction_stream(device_address, chunk_seconds=10)
        except (asyncio.CancelledError, KeyboardInterrupt):
            print("Stopping Bluetooth demo.")
            break
        except Exception as exc:
            print(f"Bluetooth demo error: {exc}. Reconnecting in 10 seconds.")
            await asyncio.sleep(10)


if FastAPI is not None:
    app = FastAPI(title="Elderly Care ECG API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _path_is_public(path):
        if path in API_PUBLIC_PATHS:
            return True
        return any(
            public_path.endswith("*") and path.startswith(public_path[:-1])
            for public_path in API_PUBLIC_PATHS
        )

    def _valid_api_key(supplied_key):
        return bool(API_KEY) and supplied_key == API_KEY

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        if not API_AUTH_ENABLED or request.method.upper() == "OPTIONS":
            return await call_next(request)
        if _path_is_public(request.url.path):
            return await call_next(request)
        if not API_KEY:
            return JSONResponse(
                status_code=503,
                content={"detail": "API authentication is enabled but API_KEY is not configured."},
            )
        supplied_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not _valid_api_key(supplied_key):
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key."})
        return await call_next(request)

    @app.on_event("startup")
    async def startup_background_sync():
        # Warm up MQTT connection on boot so the first prediction doesn't pay
        # the connect latency. Non-blocking — paho dials in a thread.
        if mqtt_publisher.is_enabled():
            mqtt_publisher.publish_status({"boot": True})
        if ALERT_WEBHOOK_URL:
            threading.Thread(target=_process_alert_webhook_outbox, daemon=True).start()
        config = BackgroundSyncConfig.from_env()
        if config.enabled:
            await start_background_sync_scheduler(config)

    @app.on_event("shutdown")
    async def shutdown_background_sync():
        await stop_background_sync_scheduler()
        # Publish graceful 'offline' marker before tearing down the client,
        # so subscribers see a clean goodbye instead of LWT timeout.
        try:
            mqtt_publisher.shutdown()
        except Exception as exc:  # noqa: BLE001
            print(f"MQTT shutdown error (non-fatal): {exc}")

    DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Elderly Care ECG Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #687386;
      --line: #dde5f0;
      --normal: #15803d;
      --medium: #b7791f;
      --high: #b91c1c;
      --critical: #7f1d1d;
      --unknown: #475569;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      padding: 20px 28px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }
    h1 { font-size: 22px; margin: 0; }
    main { padding: 24px; max-width: 1180px; margin: 0 auto; }
    .status {
      padding: 8px 12px;
      border-radius: 6px;
      font-weight: 700;
      color: white;
      background: var(--unknown);
      text-transform: uppercase;
      font-size: 13px;
    }
    .status.normal { background: var(--normal); }
    .status.medium { background: var(--medium); }
    .status.high { background: var(--high); }
    .status.critical { background: var(--critical); }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    button {
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--text);
      border-radius: 6px;
      padding: 9px 12px;
      cursor: pointer;
      font-weight: 700;
    }
    button.primary {
      background: #172033;
      color: white;
      border-color: #172033;
    }
    button:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-height: 116px;
    }
    .label {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 10px;
    }
    .value {
      font-size: 28px;
      font-weight: 700;
      line-height: 1.1;
    }
    .sub {
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
    }
    .wide {
      grid-column: 1 / -1;
      min-height: 0;
    }
    .history {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    .history th, .history td {
      padding: 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
    }
    .history th { color: var(--muted); font-weight: 600; }
    pre {
      white-space: pre-wrap;
      margin: 0;
      color: var(--muted);
    }
    canvas {
      width: 100%;
      height: 260px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #07111f;
    }
    @media (max-width: 860px) {
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 560px) {
      header { align-items: flex-start; flex-direction: column; }
      main { padding: 16px; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Elderly Care ECG Dashboard</h1>
      <div class="sub" id="updated">Waiting for data</div>
    </div>
    <div class="actions">
      <button class="primary" id="start-polar" onclick="startPolar()">Start Polar</button>
      <button id="stop-polar" onclick="stopPolar()">Stop Polar</button>
      <button id="mark-baseline" onclick="markBaseline()">Mark Normal Baseline</button>
      <button id="calibrate-personal-baseline" onclick="updateProgressiveBaseline()">Update 7-Day Baseline</button>
      <div class="status unknown" id="alert">unknown</div>
    </div>
  </header>
  <main>
    <section class="grid">
      <div class="card">
        <div class="label">Patient</div>
        <div class="value" id="patient">--</div>
        <div class="sub" id="windows">0 windows</div>
      </div>
      <div class="card">
        <div class="label">Heart rate</div>
        <div class="value"><span id="hr">--</span> <span style="font-size:15px">bpm</span></div>
        <div class="sub">Estimated from RR windows</div>
      </div>
      <div class="card">
        <div class="label">Stress</div>
        <div class="value" id="stress">--</div>
        <div class="sub" id="confidence">confidence --</div>
      </div>
      <div class="card">
        <div class="label">ECG anomaly</div>
        <div class="value" id="anomaly">--</div>
        <div class="sub" id="anomaly-windows">0 / 0 windows</div>
      </div>
      <div class="card">
        <div class="label">Rhythm status</div>
        <div class="value" id="rhythm">--</div>
        <div class="sub" id="rhythm-confidence">confidence --</div>
      </div>
      <div class="card">
        <div class="label">AFib probability</div>
        <div class="value"><span id="afib-prob">--</span><span style="font-size:15px">%</span></div>
        <div class="sub" id="rhythm-alert">rhythm alert --</div>
      </div>
      <div class="card">
        <div class="label">PVC/PAC-like</div>
        <div class="value" id="ectopy">--</div>
        <div class="sub" id="ectopy-detail">secondary signal | PVC -- | PAC --</div>
      </div>
      <div class="card">
        <div class="label">AF episode</div>
        <div class="value" id="af-episode">--</div>
        <div class="sub" id="af-burden">burden --</div>
      </div>
      <div class="card">
        <div class="label">Heart-rate event</div>
        <div class="value" id="hr-event">--</div>
        <div class="sub">Rule + activity context</div>
      </div>
      <div class="card">
        <div class="label">Signal quality</div>
        <div class="value" id="quality">--</div>
        <div class="sub" id="quality-reason">score --</div>
      </div>
      <div class="card">
        <div class="label">Risk trend</div>
        <div class="value" id="risk">--</div>
        <div class="sub" id="risk-reason">score --</div>
      </div>
      <div class="card">
        <div class="label">Activity</div>
        <div class="value" id="activity">--</div>
        <div class="sub" id="activity-detail">ACC --</div>
      </div>
      <div class="card">
        <div class="label">Fall status</div>
        <div class="value" id="fall">--</div>
        <div class="sub" id="fall-detail">impact --</div>
      </div>
      <div class="card wide">
        <div class="label">Latest ECG waveform</div>
        <canvas id="ecg-canvas" width="1100" height="260"></canvas>
      </div>
      <div class="card wide">
        <div class="label">Message</div>
        <div class="value" style="font-size:22px" id="message">No result yet</div>
        <div class="sub" id="polar-status">Polar collector: stopped</div>
      </div>
      <div class="card wide">
        <div class="label">Health report by time layer</div>
        <div class="value" style="font-size:22px" id="health-report-level">--</div>
        <div class="sub" id="health-report-summary">Waiting for layered assessment</div>
        <table class="history" style="margin-top:12px">
          <thead>
            <tr>
              <th>Layer</th>
              <th>Window</th>
              <th>Level</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody id="health-report-layers"></tbody>
        </table>
      </div>
      <div class="card wide">
        <div class="label">Personal baseline</div>
        <div class="value" style="font-size:22px" id="personal-baseline-state">not calibrated</div>
        <div class="sub" id="personal-baseline-progress">progress --</div>
        <div class="sub" id="personal-baseline-summary">Use up to 7 days of reliable data to calibrate individual baseline.</div>
        <table class="history" style="margin-top:12px">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Recent vs baseline</th>
            </tr>
          </thead>
          <tbody id="personal-baseline-comparisons"></tbody>
        </table>
      </div>
      <div class="card wide">
        <div class="label">Daily health assessment</div>
        <div class="value" style="font-size:22px" id="daily-health-level">--</div>
        <div class="sub" id="daily-health-summary">Waiting for 24h assessment</div>
        <div class="sub" id="daily-health-quality">quality --</div>
        <table class="history" style="margin-top:12px">
          <thead>
            <tr>
              <th>Finding</th>
              <th>Level</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody id="daily-health-findings"></tbody>
        </table>
        <div class="sub" id="daily-health-recommendation">--</div>
      </div>
      <div class="card wide">
        <div class="label">Recent predictions</div>
        <table class="history">
          <thead>
            <tr>
              <th>Time</th>
              <th>Patient</th>
              <th>HR</th>
              <th>Stress</th>
              <th>Rhythm</th>
              <th>PVC/PAC</th>
              <th>Anomaly</th>
              <th>Alert</th>
            </tr>
          </thead>
          <tbody id="history"></tbody>
        </table>
      </div>
      <div class="card wide">
        <div class="label">Session summary</div>
        <div class="sub" id="session-summary">No session summary yet</div>
      </div>
      <div class="card wide">
        <div class="label">Event timeline</div>
        <table class="history">
          <thead>
            <tr>
              <th>Time</th>
              <th>Type</th>
              <th>Severity</th>
              <th>Activity</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody id="events"></tbody>
        </table>
      </div>
      <div class="card wide">
        <div class="label">Raw latest result</div>
        <pre id="raw">{}</pre>
      </div>
    </section>
  </main>
  <script>
    function formatNumber(value, fallback = "--") {
      return value === null || value === undefined ? fallback : value;
    }
    function timeText(value) {
      if (!value) return "--";
      const d = new Date(value);
      return isNaN(d.getTime()) ? value : d.toLocaleString();
    }
    function renderLatest(data) {
      const result = data.latest_result;
      const alert = document.getElementById("alert");
      const polar = data.polar || {};
      document.getElementById("start-polar").disabled = !!polar.running;
      document.getElementById("stop-polar").disabled = !polar.running;
      document.getElementById("polar-status").textContent =
        `Polar collector: ${polar.running ? "running" : "stopped"}`
        + (polar.address ? ` | ${polar.address}` : "")
        + (polar.last_error ? ` | error: ${polar.last_error}` : "");
      if (!result) {
        alert.textContent = "waiting";
        alert.className = "status unknown";
        return;
      }
      document.getElementById("patient").textContent = result.patient_id || "--";
      document.getElementById("windows").textContent = `${result.window_count || 0} windows`;
      document.getElementById("hr").textContent = formatNumber(result.heart_rate_bpm);
      document.getElementById("stress").textContent = result.stress?.label || "--";
      document.getElementById("confidence").textContent =
        `confidence ${Math.round((result.stress?.confidence || 0) * 100)}%`
        + (result.stress?.reason ? ` | ${result.stress.reason}` : "");
      document.getElementById("anomaly").textContent = result.anomaly?.label || "--";
      document.getElementById("anomaly-windows").textContent =
        `${result.anomaly?.anomaly_windows || 0} / ${result.anomaly?.total_windows || 0} windows`;
      document.getElementById("rhythm").textContent = result.rhythm?.label || "--";
      document.getElementById("rhythm-confidence").textContent =
        `confidence ${Math.round((result.rhythm?.confidence || 0) * 100)}%`
        + (result.rhythm?.model_source ? ` | ${result.rhythm.model_source}` : "");
      document.getElementById("afib-prob").textContent =
        Math.round(((result.rhythm?.probabilities?.possible_afib) || 0) * 100);
      document.getElementById("rhythm-alert").textContent =
        `${result.rhythm_alert?.level || "--"} | ${result.rhythm_alert?.message || "--"}`;
      document.getElementById("ectopy").textContent = result.ectopy?.label || "--";
      document.getElementById("ectopy-detail").textContent =
        `secondary signal | PVC ${Math.round((result.ectopy?.pvc_probability || 0) * 100)}%`
        + ` | PAC ${Math.round((result.ectopy?.pac_probability || 0) * 100)}%`
        + (result.ectopy?.model_source ? ` | ${result.ectopy.model_source}` : "");
      document.getElementById("af-episode").textContent =
        result.af_episode?.active ? "active" : "inactive";
      document.getElementById("af-burden").textContent =
        `duration ${formatNumber(result.af_episode?.current_episode_duration_sec, 0)}s`
        + ` | burden ${formatNumber(result.af_episode?.af_burden_percent, 0)}%`;
      document.getElementById("hr-event").textContent = result.hr_event?.label || "--";
      document.getElementById("quality").textContent = result.signal_quality?.label || "--";
      document.getElementById("quality-reason").textContent =
        `score ${Math.round((result.signal_quality?.score || 0) * 100)}%`
        + (result.signal_quality?.reasons?.length ? ` | ${result.signal_quality.reasons.join("; ")}` : "");
      document.getElementById("risk").textContent = result.risk?.level || "--";
      document.getElementById("risk-reason").textContent =
        `score ${Math.round((result.risk?.score || 0) * 100)}% | ${result.risk?.reason || "--"}`;
      const sensor = result.sensor_context || {};
      const activityFeatures = sensor.activity_features || {};
      const fall = sensor.fall || {};
      const hrContext = sensor.hr_context_alert || {};
      document.getElementById("activity").textContent = sensor.activity_state || "--";
      document.getElementById("activity-detail").textContent =
        `VM std ${formatNumber(activityFeatures.acc_vm_std)} mG`
        + (hrContext.level ? ` | HR context ${hrContext.level}` : "");
      document.getElementById("fall").textContent =
        fall.strong_fall ? "strong fall" : fall.fall_candidate ? "possible fall" : fall.impact_spike ? "impact" : "clear";
      document.getElementById("fall-detail").textContent =
        `impact ${formatNumber(fall.peak_vm)} mG`
        + (fall.free_fall ? ` | free-fall ${formatNumber(fall.min_before_1s)} mG` : "");
      document.getElementById("message").textContent = result.message || "--";
      document.getElementById("updated").textContent = `Last update: ${timeText(result.timestamp)}`;
      alert.textContent = result.alert_level || "unknown";
      alert.className = `status ${result.alert_level || "unknown"}`;
      document.getElementById("raw").textContent = JSON.stringify(result, null, 2);
    }
    function renderHistory(history) {
      const tbody = document.getElementById("history");
      tbody.innerHTML = "";
      [...history].reverse().slice(0, 10).forEach((item) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${timeText(item.timestamp)}</td>
          <td>${item.patient_id || "--"}</td>
          <td>${formatNumber(item.heart_rate_bpm)}</td>
          <td>${item.stress?.label || "--"}</td>
          <td>${item.rhythm?.label || "--"}</td>
          <td>${item.ectopy?.label || "--"}</td>
          <td>${item.anomaly?.label || "--"}</td>
          <td>${item.alert_level || "--"}</td>
        `;
        tbody.appendChild(tr);
      });
    }
    function compactCounts(counts) {
      if (!counts) return "--";
      return Object.entries(counts)
        .map(([key, value]) => `${key}: ${value}`)
        .join(", ") || "--";
    }
    function renderSessionSummary(summary) {
      const target = document.getElementById("session-summary");
      const overall = summary?.overall || {};
      target.textContent =
        `sessions ${summary?.session_count || 0}, windows ${summary?.window_count || 0}`
        + ` | mean HR ${formatNumber(overall.mean_heart_rate_bpm)} bpm`
        + ` | max AFib ${Math.round((overall.max_afib_probability || 0) * 100)}%`
        + ` | rhythm ${compactCounts(overall.rhythm_counts)}`
        + ` | ectopy ${compactCounts(overall.ectopy_counts)}`
        + ` | activity ${compactCounts(overall.activity_counts)}`
        + ` | alerts ${compactCounts(overall.alert_counts)}`;
    }
    function compactEvidence(evidence) {
      if (!evidence) return "--";
      return Object.entries(evidence)
        .slice(0, 4)
        .map(([key, value]) => `${key}: ${formatNumber(value)}`)
        .join(", ") || "--";
    }
    function windowText(window) {
      if (!window) return "--";
      if (window.mode === "latest_window") {
        return `latest ${formatNumber(window.minutes)} min`;
      }
      if (window.mode === "rolling_24h") {
        return `${formatNumber(window.hours)}h`;
      }
      if (window.mode === "rolling_days") {
        return `${formatNumber(window.days)}d, ${formatNumber(window.prediction_count, 0)} predictions`;
      }
      return window.mode || "--";
    }
    function renderHealthReport(report) {
      const overall = report?.overall || {};
      const layers = report?.layers || {};
      document.getElementById("health-report-level").textContent = overall.level || "--";
      document.getElementById("health-report-summary").textContent = overall.summary || "--";
      const tbody = document.getElementById("health-report-layers");
      tbody.innerHTML = "";
      [
        ["Realtime", layers.realtime],
        ["Daily 24h", layers.daily],
        ["Long-term", layers.long_term],
      ].forEach(([label, layer]) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${label}</td>
          <td>${windowText(layer?.window || layer?.period)}</td>
          <td>${layer?.overall?.level || "--"}</td>
          <td>${layer?.overall?.summary || "--"}</td>
        `;
        tbody.appendChild(tr);
      });
      renderPersonalBaseline(report?.personal_baseline || {});
    }
    function renderPersonalBaseline(personalBaseline) {
      const calibration = personalBaseline?.calibration || {};
      const state = personalBaseline?.calibrated ? (calibration.status || "calibrated") : "not calibrated";
      document.getElementById("personal-baseline-state").textContent = state;
      document.getElementById("personal-baseline-progress").textContent =
        personalBaseline?.calibrated
          ? `day ${calibration.day_count || 0}/${calibration.target_days || 7}`
            + ` | reliable ${(personalBaseline?.baseline_source || {}).reliable_prediction_count || "--"} predictions`
            + ` | ${calibration.data_quality_ok ? "data quality ok" : "collecting baseline"}`
          : "progress --";
      document.getElementById("personal-baseline-summary").textContent =
        personalBaseline?.summary || "Use up to 7 days of reliable data to calibrate individual baseline.";
      const comparisons = personalBaseline?.comparisons || {};
      const rows = [
        ["Mean HR delta", comparisons.mean_hr_delta_bpm == null ? "--" : `${formatNumber(comparisons.mean_hr_delta_bpm)} bpm`],
        ["REST HR delta", comparisons.resting_hr_delta_bpm == null ? "--" : `${formatNumber(comparisons.resting_hr_delta_bpm)} bpm`],
        ["AF suspicion delta", comparisons.af_suspicion_ratio_delta == null ? "--" : `${Math.round(comparisons.af_suspicion_ratio_delta * 100)}%`],
        ["Anomaly delta", comparisons.abnormal_ratio_delta == null ? "--" : `${Math.round(comparisons.abnormal_ratio_delta * 100)}%`],
        ["PVC/PAC delta", comparisons.ectopy_ratio_delta == null ? "--" : `${Math.round(comparisons.ectopy_ratio_delta * 100)}%`],
      ];
      const tbody = document.getElementById("personal-baseline-comparisons");
      tbody.innerHTML = "";
      rows.forEach(([label, value]) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${label}</td><td>${value}</td>`;
        tbody.appendChild(tr);
      });
    }
    function renderDailyHealthAssessment(assessment) {
      const overall = assessment?.overall || {};
      const quality = assessment?.data_quality || {};
      const findings = assessment?.findings || [];
      document.getElementById("daily-health-level").textContent = overall.level || "--";
      document.getElementById("daily-health-summary").textContent = overall.summary || "--";
      document.getElementById("daily-health-quality").textContent =
        `quality ${quality.label || "--"}`
        + ` | valid signal ${Math.round((quality.valid_signal_ratio || 0) * 100)}%`
        + ` | predictions ${quality.prediction_count || 0}`
        + (quality.assessment_confidence ? ` | ${quality.assessment_confidence}` : "");
      const tbody = document.getElementById("daily-health-findings");
      tbody.innerHTML = "";
      findings.slice(0, 5).forEach((item) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${item.title || item.type || "--"}</td>
          <td>${item.level || "--"}</td>
          <td>${compactEvidence(item.evidence)}</td>
        `;
        tbody.appendChild(tr);
      });
      if (!findings.length) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="3">No daily health findings</td>`;
        tbody.appendChild(tr);
      }
      document.getElementById("daily-health-recommendation").textContent =
        (assessment?.recommendations || []).join(" ") || assessment?.disclaimer || "--";
    }
    function renderEvents(eventsPayload) {
      const tbody = document.getElementById("events");
      tbody.innerHTML = "";
      const events = eventsPayload?.events || [];
      [...events].reverse().slice(0, 20).forEach((item) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${timeText(item.timestamp)}</td>
          <td>${item.event_type || "--"}</td>
          <td>${item.severity || "--"}</td>
          <td>${item.activity_state || "--"}</td>
          <td>${item.message || item.label || "--"}</td>
        `;
        tbody.appendChild(tr);
      });
      if (!events.length) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="5">No events in selected period</td>`;
        tbody.appendChild(tr);
      }
    }
    function renderWaveform(samples) {
      const canvas = document.getElementById("ecg-canvas");
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = "#1f334d";
      ctx.lineWidth = 1;
      for (let x = 0; x < w; x += 50) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      }
      for (let y = 0; y < h; y += 40) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      }
      if (!samples || samples.length < 2) {
        ctx.fillStyle = "#9aa6b2";
        ctx.fillText("No ECG waveform available", 20, 30);
        return;
      }
      const min = Math.min(...samples);
      const max = Math.max(...samples);
      const range = Math.max(max - min, 1);
      ctx.strokeStyle = "#00ff88";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      samples.forEach((v, i) => {
        const x = (i / (samples.length - 1)) * w;
        const y = h - ((v - min) / range) * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
    async function refresh() {
      try {
        const res = await fetch("/latest-result");
        const data = await res.json();
        renderLatest(data);
        renderHistory(data.history || []);
        const ecgRes = await fetch("/latest-ecg?max_samples=1000");
        const ecgData = await ecgRes.json();
        renderWaveform(ecgData.samples || []);
        const patientId = data.latest_result?.patient_id || "";
        const params = new URLSearchParams({days: "1"});
        if (patientId) params.set("patient_id", patientId);
        const summaryRes = await fetch(`/session-summary?${params.toString()}`);
        renderSessionSummary(await summaryRes.json());
        const assessmentParams = new URLSearchParams({hours: "24"});
        if (patientId) assessmentParams.set("patient_id", patientId);
        const assessmentRes = await fetch(`/daily-health-assessment?${assessmentParams.toString()}`);
        renderDailyHealthAssessment(await assessmentRes.json());
        const reportParams = new URLSearchParams({daily_hours: "24", long_term_days: "7"});
        if (patientId) reportParams.set("patient_id", patientId);
        const reportRes = await fetch(`/health-report?${reportParams.toString()}`);
        renderHealthReport(await reportRes.json());
        const eventParams = new URLSearchParams(params);
        eventParams.set("limit", "20");
        const eventsRes = await fetch(`/events?${eventParams.toString()}`);
        renderEvents(await eventsRes.json());
      } catch (error) {
        document.getElementById("updated").textContent = `Dashboard error: ${error}`;
      }
    }
    async function startPolar() {
      await fetch("/polar/start", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({chunk_seconds: 10})
      });
      refresh();
    }
    async function stopPolar() {
      await fetch("/polar/stop", {method: "POST"});
      refresh();
    }
    async function markBaseline() {
      const res = await fetch("/baseline/mark-current-session", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({patient_id: "polar_h10"})
      });
      const data = await res.json();
      alert(data.status ? `Baseline: ${data.status}` : JSON.stringify(data));
      refresh();
    }
    async function updateProgressiveBaseline() {
      const patientId = document.getElementById("patient").textContent || "polar_h10";
      const res = await fetch("/personal-baseline/update-progressive", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          patient_id: patientId === "--" ? "polar_h10" : patientId,
          target_days: 7,
          min_predictions: 20,
          include_alert_windows: false
        })
      });
      const data = await res.json();
      alert(data.status ? `7-day personal baseline: ${data.status}` : JSON.stringify(data));
      refresh();
    }
    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "stress_model_loaded": stress_predictor.loaded,
            "stress_model_error": stress_predictor.load_error,
            "stress_model_dir": STRESS_MODEL_DIR,
            "stress_model_window_seconds": stress_predictor.window_seconds,
            "anomaly_model_loaded": anomaly_model is not None,
            "anomaly_scaler_loaded": anomaly_scaler is not None,
            "rhythm_model_loaded": rhythm_predictor.loaded,
            "rhythm_model_error": rhythm_predictor.load_error,
            "rhythm_model_source": "rhythm_feature_model",
            "ectopy_model_loaded": ectopy_predictor.loaded,
            "ectopy_model_error": ectopy_predictor.load_error,
            "rhythm_afib_decision_mode": RHYTHM_AFIB_DECISION_MODE,
            "rhythm_afib_episode_threshold": RHYTHM_AFIB_EPISODE_THRESHOLD,
            "rhythm_afib_alert_threshold": RHYTHM_AFIB_ALERT_THRESHOLD,
            "rhythm_decision_config_path": RHYTHM_DECISION_CONFIG_PATH,
            "rhythm_decision_config_loaded": bool(rhythm_decision_config),
            "sensor_context_config_path": sensor_context_config_path(),
            "sensor_context_config_loaded": bool(load_sensor_context_config()),
            "mongodb_sync_configured": is_mongodb_configured(),
            "mongodb_sync_scheduler": get_background_sync_status(),
            "alert_webhook_configured": bool(ALERT_WEBHOOK_URL),
            "alert_webhook_levels": sorted(ALERT_WEBHOOK_LEVELS),
            "alert_delivery": {
                **alert_delivery_status(),
                "websocket_alert_clients": len(alert_websocket_clients),
            },
            "mqtt_enabled": mqtt_publisher.is_enabled(),
            "mqtt_connected": mqtt_publisher.is_connected(),
            "mqtt_host": f"{os.getenv('MQTT_HOST', 'localhost')}:{os.getenv('MQTT_PORT', '1883')}",
            "mqtt_topic_prefix": os.getenv("MQTT_TOPIC_PREFIX", "elderly_care"),
            "api_auth_enabled": API_AUTH_ENABLED,
            "api_auth_configured": bool(API_KEY),
            "allowed_origins": ALLOWED_ORIGINS,
            "network_provisioning": read_network_status(),
            "polar": polar_status,
        }

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        return DASHBOARD_HTML

    @app.get("/latest-result")
    def get_latest_result():
        return {
            "latest_result": latest_result,
            "history": prediction_history,
            "polar": polar_status,
        }

    @app.websocket("/ws/vitals")
    async def ws_vitals(websocket: WebSocket):
        if API_AUTH_ENABLED:
            supplied_key = websocket.headers.get("X-API-Key") or websocket.query_params.get("api_key")
            if not _valid_api_key(supplied_key):
                await websocket.close(code=1008)
                return
        await websocket.accept()
        vitals_websocket_clients.add(websocket)
        try:
            if latest_result is not None:
                await websocket.send_json(_websocket_payload(latest_result))
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            vitals_websocket_clients.discard(websocket)

    @app.get("/alerts/realtime")
    def realtime_alerts(
        patient_id: str | None = None,
        limit: int = 50,
        include_acknowledged: bool = False,
    ):
        try:
            return get_realtime_alerts(
                patient_id=patient_id,
                limit=limit,
                include_acknowledged=include_acknowledged,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.websocket("/ws/alerts")
    async def ws_alerts(websocket: WebSocket):
        if API_AUTH_ENABLED:
            supplied_key = websocket.headers.get("X-API-Key") or websocket.query_params.get("api_key")
            if not _valid_api_key(supplied_key):
                await websocket.close(code=1008)
                return
        patient_id = websocket.query_params.get("patient_id") or None
        caregiver_id = websocket.query_params.get("caregiver_id") or "unknown"
        await websocket.accept()
        alert_websocket_clients[websocket] = {
            "patient_id": patient_id,
            "caregiver_id": caregiver_id,
        }
        try:
            backlog = get_realtime_alerts(
                patient_id=patient_id,
                limit=50,
                include_acknowledged=False,
            )
            await websocket.send_json({
                "type": "alert_backlog",
                "alerts": backlog.get("alerts") or [],
                "alert_count": backlog.get("alert_count") or 0,
            })
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            alert_websocket_clients.pop(websocket, None)

    @app.post("/alerts/{event_id}/ack")
    def ack_alert(event_id: str, payload: dict | None = None):
        payload = payload or {}
        try:
            return acknowledge_alert(
                event_id,
                caregiver_id=payload.get("caregiver_id") or "unknown",
                note=payload.get("note") or "",
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="alert event not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/alerts/{event_id}/resolve")
    def resolve_alert_endpoint(event_id: str, payload: dict | None = None):
        payload = payload or {}
        try:
            return resolve_alert(
                event_id,
                caregiver_id=payload.get("caregiver_id") or "unknown",
                resolution=payload.get("resolution") or "checked_ok",
                note=payload.get("note") or "",
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="alert event not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/latest-ecg")
    def latest_ecg(patient_id: str | None = None, max_samples: int = 1000):
        try:
            return get_latest_ecg(patient_id=patient_id, max_samples=max_samples)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/history")
    def history(patient_id: str | None = None, days: float = 1, limit: int = 100):
        try:
            return {"items": get_history(patient_id=patient_id, days=days, limit=limit)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/risk-summary")
    def risk_summary(patient_id: str | None = None, days: float = 1):
        payload = compute_risk_summary(patient_id=patient_id, days=days)
        save_assessment_snapshot("risk_summary", payload, patient_id=patient_id, period={"days": days})
        return payload

    @app.get("/session-summary")
    def session_summary(patient_id: str | None = None, days: float = 1):
        payload = compute_session_summary(patient_id=patient_id, days=days)
        save_assessment_snapshot("session_summary", payload, patient_id=patient_id, period={"days": days})
        return payload

    @app.get("/daily-summary")
    def daily_summary(patient_id: str | None = None, days: float = 7):
        payload = compute_daily_summary(patient_id=patient_id, days=days)
        save_assessment_snapshot("daily_summary", payload, patient_id=patient_id, period={"days": days})
        return payload

    @app.get("/daily-health-assessment")
    def daily_health_assessment(patient_id: str | None = None, hours: float = 24):
        try:
            payload = compute_daily_health_assessment(patient_id=patient_id, hours=hours)
            save_assessment_snapshot(
                "daily_health_assessment",
                payload,
                patient_id=payload.get("patient_id") or patient_id,
                period={"hours": hours},
            )
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/health-report")
    def health_report(
        patient_id: str | None = None,
        realtime_minutes: float = 5,
        daily_hours: float = 24,
        long_term_days: float = 7,
    ):
        try:
            if realtime_minutes <= 0 or daily_hours <= 0 or long_term_days <= 0:
                raise ValueError("realtime_minutes, daily_hours, and long_term_days must be positive.")
            payload = compute_temporal_health_report(
                patient_id=patient_id,
                realtime_minutes=realtime_minutes,
                daily_hours=daily_hours,
                long_term_days=long_term_days,
            )
            save_assessment_snapshot(
                "health_report",
                payload,
                patient_id=payload.get("patient_id") or patient_id,
                period={
                    "realtime_minutes": realtime_minutes,
                    "daily_hours": daily_hours,
                    "long_term_days": long_term_days,
                },
            )
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/events")
    def events(patient_id: str | None = None, days: float = 1, limit: int = 200):
        return build_event_timeline(patient_id=patient_id, days=days, limit=limit)

    @app.post("/events/rebuild")
    def rebuild_events(payload: dict | None = None):
        payload = payload or {}
        return rebuild_event_table(
            patient_id=payload.get("patient_id"),
            days=float(payload.get("days") or 30),
            limit=int(payload.get("limit") or 50000),
        )

    @app.post("/sync/mongodb")
    def sync_mongodb(payload: dict | None = None):
        payload = payload or {}
        if not is_mongodb_configured():
            raise HTTPException(status_code=400, detail="MONGODB_URI is not configured.")

        try:
            return sync_to_mongodb(
                patient_id=payload.get("patient_id"),
                days=float(payload.get("days") or 1),
                limit=int(payload.get("limit") or 5000),
                include_raw_samples=bool(payload.get("include_raw_samples") or False),
            )
        except ImportError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/storage/status")
    def get_storage_status():
        return storage_status()

    @app.get("/storage/raw-chunks")
    def storage_raw_chunks(
        patient_id: str | None = None,
        hours: float = 24,
        signal_type: str | None = None,
        limit: int = 1000,
    ):
        try:
            return {
                "items": get_raw_chunks(
                    patient_id=patient_id,
                    hours=hours,
                    signal_type=signal_type,
                    limit=limit,
                    include_payload=False,
                )
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/storage/raw-chunks/{chunk_id}")
    def storage_raw_chunk(chunk_id: str):
        chunk = get_raw_chunk(chunk_id, include_payload=False)
        if chunk is None:
            raise HTTPException(status_code=404, detail="raw chunk not found")
        return chunk

    @app.get("/storage/collection-sessions")
    def storage_collection_sessions(patient_id: str | None = None, hours: float = 24, limit: int = 200):
        try:
            return {"items": get_collection_sessions(patient_id=patient_id, hours=hours, limit=limit)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/storage/assessment-snapshots")
    def storage_assessment_snapshots(
        patient_id: str | None = None,
        hours: float = 24,
        snapshot_type: str | None = None,
        limit: int = 100,
    ):
        try:
            return {
                "items": get_assessment_snapshots(
                    patient_id=patient_id,
                    hours=hours,
                    snapshot_type=snapshot_type,
                    limit=limit,
                )
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/storage/sync-mongodb")
    def storage_sync_mongodb(payload: dict | None = None):
        return sync_mongodb(payload)

    @app.post("/storage/purge-synced")
    def storage_purge_synced(payload: dict | None = None):
        payload = payload or {}
        try:
            return purge_synced_raw_chunks(
                retention_hours=float(payload.get("retention_hours") or 24),
                limit=int(payload.get("limit") or 10000),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/storage/sync-scheduler/status")
    def storage_sync_scheduler_status():
        return get_background_sync_status()

    @app.post("/storage/sync-scheduler/start")
    async def storage_sync_scheduler_start(payload: dict | None = None):
        payload = payload or {}
        try:
            config = BackgroundSyncConfig.from_env()
            if "interval_seconds" in payload:
                config.interval_seconds = float(payload["interval_seconds"])
            if "patient_id" in payload:
                config.patient_id = payload.get("patient_id") or None
            if "days" in payload:
                config.days = float(payload["days"])
            if "limit" in payload:
                config.limit = int(payload["limit"])
            if "include_raw_samples" in payload:
                config.include_raw_samples = bool(payload["include_raw_samples"])
            if "purge_after_sync" in payload:
                config.purge_after_sync = bool(payload["purge_after_sync"])
            if "purge_retention_hours" in payload:
                config.purge_retention_hours = float(payload["purge_retention_hours"])
            if "purge_limit" in payload:
                config.purge_limit = int(payload["purge_limit"])
            if "run_immediately" in payload:
                config.run_immediately = bool(payload["run_immediately"])
            config.enabled = True
            return await start_background_sync_scheduler(config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/storage/sync-scheduler/stop")
    async def storage_sync_scheduler_stop():
        return await stop_background_sync_scheduler()

    @app.post("/storage/sync-scheduler/run-once")
    async def storage_sync_scheduler_run_once(payload: dict | None = None):
        payload = payload or {}
        try:
            config = BackgroundSyncConfig.from_env()
            if "patient_id" in payload:
                config.patient_id = payload.get("patient_id") or None
            if "days" in payload:
                config.days = float(payload["days"])
            if "limit" in payload:
                config.limit = int(payload["limit"])
            if "include_raw_samples" in payload:
                config.include_raw_samples = bool(payload["include_raw_samples"])
            if "purge_after_sync" in payload:
                config.purge_after_sync = bool(payload["purge_after_sync"])
            if "purge_retention_hours" in payload:
                config.purge_retention_hours = float(payload["purge_retention_hours"])
            if "purge_limit" in payload:
                config.purge_limit = int(payload["purge_limit"])
            return await asyncio.to_thread(run_background_sync_once, config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/polar/start")
    async def start_polar(payload: dict | None = None):
        global polar_task
        if BleakClient is None:
            raise HTTPException(status_code=500, detail="bleak is not installed.")
        if polar_task is not None and not polar_task.done():
            return {"status": "already_running", "polar": polar_status}

        payload = payload or {}
        address = payload.get("address") or DEFAULT_POLAR_ADDRESS
        chunk_seconds = int(payload.get("chunk_seconds") or 10)
        if chunk_seconds < 5:
            raise HTTPException(status_code=400, detail="chunk_seconds must be >= 5.")

        polar_task = asyncio.create_task(
            polar_background_collector(address, chunk_seconds=chunk_seconds)
        )
        return {"status": "started", "polar": polar_status}

    @app.post("/polar/stop")
    async def stop_polar():
        global polar_task
        if polar_task is None or polar_task.done():
            polar_status["running"] = False
            return {"status": "not_running", "polar": polar_status}

        polar_task.cancel()
        try:
            await polar_task
        except asyncio.CancelledError:
            pass
        polar_task = None
        polar_status["running"] = False
        return {"status": "stopped", "polar": polar_status}

    @app.post("/baseline/mark-current-session")
    def mark_current_session_baseline(payload: dict | None = None):
        global calibrated_anomaly_cache
        payload = payload or {}
        patient_id = payload.get("patient_id") or (latest_result or {}).get("patient_id") or "polar_h10"
        session_id = payload.get("session_id") or (latest_result or {}).get("session_id")
        contamination = float(payload.get("contamination") or 0.03)

        if not session_id:
            raise HTTPException(status_code=400, detail="No current session is available.")
        if contamination <= 0 or contamination >= 0.5:
            raise HTTPException(status_code=400, detail="contamination must be between 0 and 0.5.")

        try:
            metadata = train_calibration_from_session(
                patient_id=patient_id,
                session_id=session_id,
                contamination=contamination,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        calibrated_anomaly_cache[patient_id] = load_calibrated_anomaly(patient_id)
        return {"status": "calibrated", "metadata": metadata}

    @app.post("/baseline/calibrate-real-data")
    def calibrate_real_data(payload: dict | None = None):
        global calibrated_anomaly_cache
        payload = payload or {}
        person_id = payload.get("person_id") or payload.get("patient_id")
        patient_id = payload.get("patient_id") or person_id
        input_dir = payload.get("input_dir") or "data_raw/real_data"
        states = payload.get("states") or ["rest"]
        contamination = float(payload.get("contamination") or 0.03)

        if not patient_id or not person_id:
            raise HTTPException(status_code=400, detail="patient_id or person_id is required.")
        if isinstance(states, str):
            states = [state.strip().lower() for state in states.split(",") if state.strip()]
        if not states:
            raise HTTPException(status_code=400, detail="states must contain at least one state.")
        if contamination <= 0 or contamination >= 0.5:
            raise HTTPException(status_code=400, detail="contamination must be between 0 and 0.5.")

        try:
            metadata = train_calibration_from_real_data(
                patient_id=patient_id,
                input_dir=input_dir,
                states=tuple(states),
                contamination=contamination,
                real_data_person_id=person_id,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        calibrated_anomaly_cache[patient_id] = load_calibrated_anomaly(patient_id)
        return {"status": "calibrated", "metadata": metadata}

    @app.get("/baseline/status")
    def baseline_status(patient_id: str = "polar_h10"):
        calibrated = load_calibrated_anomaly(patient_id) if has_calibration(patient_id) else None
        return {
            "patient_id": patient_id,
            "calibrated": calibrated is not None,
            "metadata": None if calibrated is None else calibrated["metadata"],
        }

    @app.post("/personal-baseline/calibrate")
    def calibrate_patient_baseline(payload: dict | None = None):
        payload = payload or {}
        patient_id = payload.get("patient_id") or (latest_result or {}).get("patient_id") or "polar_h10"
        days = float(payload.get("days") or 2)
        min_predictions = int(payload.get("min_predictions") or 20)
        include_alert_windows = bool(payload.get("include_alert_windows") or False)

        try:
            return calibrate_personal_baseline(
                patient_id=patient_id,
                days=days,
                min_predictions=min_predictions,
                include_alert_windows=include_alert_windows,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/personal-baseline/update-progressive")
    def update_progressive_patient_baseline(payload: dict | None = None):
        payload = payload or {}
        patient_id = payload.get("patient_id") or (latest_result or {}).get("patient_id") or "polar_h10"
        target_days = int(payload.get("target_days") or 7)
        min_predictions = int(payload.get("min_predictions") or 20)
        include_alert_windows = bool(payload.get("include_alert_windows") or False)

        try:
            return update_progressive_personal_baseline(
                patient_id=patient_id,
                target_days=target_days,
                min_predictions=min_predictions,
                include_alert_windows=include_alert_windows,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/personal-baseline/status")
    def personal_baseline_status(patient_id: str = "polar_h10"):
        try:
            return get_personal_baseline_status(patient_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/guided-baseline/status")
    def guided_baseline_status(patient_id: str = "polar_h10", target_days: int = 7):
        try:
            return get_guided_baseline_status(patient_id=patient_id, target_days=target_days)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/guided-baseline/start")
    def guided_baseline_start(payload: dict | None = None):
        payload = payload or {}
        patient_id = payload.get("patient_id") or (latest_result or {}).get("patient_id") or "polar_h10"
        target_days = int(payload.get("target_days") or 7)
        try:
            return start_guided_baseline_session(patient_id=patient_id, target_days=target_days)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/guided-baseline/segment/complete")
    def guided_baseline_segment_complete(payload: dict | None = None):
        payload = payload or {}
        patient_id = payload.get("patient_id") or (latest_result or {}).get("patient_id") or "polar_h10"
        try:
            return complete_guided_baseline_segment(
                patient_id=patient_id,
                session_id=payload.get("session_id"),
                segment_type=payload.get("segment_type"),
                started_at=payload.get("started_at"),
                ended_at=payload.get("ended_at"),
                allow_skip=bool(payload.get("allow_skip") or False),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/guided-baseline/complete-day")
    def guided_baseline_day_complete(payload: dict | None = None):
        payload = payload or {}
        patient_id = payload.get("patient_id") or (latest_result or {}).get("patient_id") or "polar_h10"
        target_days = int(payload.get("target_days") or 7)
        try:
            return complete_guided_baseline_day(
                patient_id=patient_id,
                session_id=payload.get("session_id"),
                target_days=target_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/ingest-ecg")
    def ingest_ecg(payload: dict):
        try:
            result = predict_ecg(
                payload.get("ecg_samples"),
                sample_rate_hz=payload.get("sample_rate_hz"),
                patient_id=payload.get("patient_id"),
                timestamp=payload.get("timestamp"),
                acc_samples=payload.get("acc_samples"),
                acc_sample_rate_hz=payload.get("acc_sample_rate_hz") or FS_ACC_HZ,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return record_result(
            result,
            payload.get("ecg_samples"),
            payload.get("sample_rate_hz"),
            acc_samples=payload.get("acc_samples"),
            acc_sample_rate_hz=payload.get("acc_sample_rate_hz") or FS_ACC_HZ,
        )
else:
    app = None


def main():
    parser = argparse.ArgumentParser(description="Realtime ECG prediction pipeline")
    parser.add_argument("--bluetooth-demo", action="store_true", help="Collect from Polar H10")
    parser.add_argument(
        "--polar-address",
        default=DEFAULT_POLAR_ADDRESS,
        help="Polar H10 BLE address. Use an empty string to scan by device name.",
    )
    args = parser.parse_args()

    if args.bluetooth_demo:
        address = args.polar_address.strip() or None
        try:
            asyncio.run(bluetooth_demo_loop(address=address))
        except KeyboardInterrupt:
            print("Stopping pipeline")
    else:
        print("Run the REST API with: uvicorn pipeline:app --reload")
        print("Run the Polar H10 demo with: python pipeline.py --bluetooth-demo")


if __name__ == "__main__":
    main()
