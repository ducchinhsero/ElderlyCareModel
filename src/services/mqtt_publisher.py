"""MQTT publisher for Edge AI alert delivery.

Design goal: deliver realtime vitals and critical alerts from the Pi to a
Flutter (or any) app over LAN MQTT, completely independent of MongoDB
Atlas / cloud / internet. The cloud sync path remains for archive only.

Three topic tiers:

  {prefix}/{patient_id}/vitals/live   QoS=0 retain=false  -- high freq
  {prefix}/{patient_id}/alert         QoS=2 retain=true   -- critical, exactly-once
  {prefix}/service/status             QoS=1 retain=true   -- online/offline via LWT

The app subscribes once and receives:
  * "live" stream while connected to the LAN MQTT broker
  * "alert" topic with retained latest alert, even after a reconnect/restart
  * "service/status" so the app UI can show "Pi offline" when broker LWT fires

paho-mqtt's `loop_start()` spawns a daemon thread; we keep one module-level
client and let paho handle reconnect backoff. Publishing is fire-and-forget
from the caller's thread — it never blocks the FastAPI request loop.
"""

import json
import logging
import os
import threading


_logger = logging.getLogger("elderly_care.mqtt")

MQTT_ENABLED = os.getenv("MQTT_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME") or None
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD") or None
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "elderly_care").strip("/")
MQTT_QOS_VITALS = int(os.getenv("MQTT_QOS_VITALS", "0"))
MQTT_QOS_ALERT = int(os.getenv("MQTT_QOS_ALERT", "2"))
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", f"elderly_care_pi_{os.getpid()}")
# Vitals over MQTT do NOT need the full prediction object — phone clients
# pay battery/bandwidth to deserialize it. Drop heavy fields by default.
MQTT_INCLUDE_RAW_SAMPLES = os.getenv("MQTT_INCLUDE_RAW_SAMPLES", "0").strip().lower() in {"1", "true", "yes", "on"}
# Only publish to alert topic when severity meets this floor.
MQTT_ALERT_MIN_LEVEL = os.getenv("MQTT_ALERT_MIN_LEVEL", "medium").strip().lower()
_LEVEL_RANK = {"normal": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

_client = None
_client_lock = threading.Lock()
_connect_attempted = False


def _service_status_topic():
    return f"{MQTT_TOPIC_PREFIX}/service/status"


def _vitals_topic(patient_id):
    return f"{MQTT_TOPIC_PREFIX}/{patient_id or 'unknown'}/vitals/live"


def _alert_topic(patient_id):
    return f"{MQTT_TOPIC_PREFIX}/{patient_id or 'unknown'}/alert"


def _load_paho():
    try:
        import paho.mqtt.client as mqtt  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "paho-mqtt is required for MQTT publishing. Install with: pip install paho-mqtt"
        ) from exc
    return mqtt


def _on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        _logger.info("MQTT connected to %s:%s", MQTT_HOST, MQTT_PORT)
        try:
            client.publish(
                _service_status_topic(),
                json.dumps({"status": "online", "pid": os.getpid()}),
                qos=1,
                retain=True,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("MQTT online status publish failed: %s", exc)
    else:
        _logger.warning("MQTT connect failed rc=%s", rc)


def _on_disconnect(client, userdata, rc, properties=None):
    if rc != 0:
        _logger.warning("MQTT unexpected disconnect rc=%s; auto-reconnect armed", rc)


def _get_client():
    """Return a connected mqtt client, or None if disabled / unavailable.

    First call kicks off an async connect via paho's loop_start(); subsequent
    calls are a cheap lock + cached return.
    """
    global _client, _connect_attempted
    if not MQTT_ENABLED:
        return None
    with _client_lock:
        if _client is not None:
            return _client
        if _connect_attempted:
            # Previous connect attempt failed (eg paho not installed); don't
            # keep retrying on every record_result call — that would spam logs.
            return None
        _connect_attempted = True
        try:
            mqtt = _load_paho()
        except ImportError as exc:
            _logger.warning("MQTT disabled: %s", exc)
            return None

        try:
            client = mqtt.Client(
                client_id=MQTT_CLIENT_ID,
                clean_session=False,
                protocol=mqtt.MQTTv311,
            )
        except TypeError:
            # paho-mqtt v2 API: client_id is positional, callback_api_version required
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, MQTT_CLIENT_ID, clean_session=False)

        if MQTT_USERNAME and MQTT_PASSWORD:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        client.on_connect = _on_connect
        client.on_disconnect = _on_disconnect

        # Last Will: broker will publish offline marker if Pi loses connection
        # without a clean disconnect (kernel panic, power loss, etc.). The
        # app's UI can show "Pi offline" the moment LWT fires.
        client.will_set(
            _service_status_topic(),
            json.dumps({"status": "offline"}),
            qos=1,
            retain=True,
        )
        # Reconnect with backoff to avoid hammering broker during outage.
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        try:
            client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE)
            client.loop_start()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("MQTT connect_async failed: %s", exc)
            return None

        _client = client
        return _client


def _compact_vitals(result):
    """Strip heavy fields so phone clients don't pay for raw ECG arrays."""
    keep = (
        "patient_id",
        "timestamp",
        "heart_rate_bpm",
        "rhythm",
        "stress",
        "ectopy",
        "hr_event",
        "af_episode",
        "signal_quality",
        "sensor_context",
        "alert_level",
        "message",
        "anomaly",
    )
    compact = {k: result.get(k) for k in keep if k in result}
    if MQTT_INCLUDE_RAW_SAMPLES:
        if "ecg_samples" in result:
            compact["ecg_samples"] = result["ecg_samples"]
        if "acc_samples" in result:
            compact["acc_samples"] = result["acc_samples"]
    return compact


def _alert_meets_floor(level):
    rank = _LEVEL_RANK.get(str(level or "").lower(), -1)
    floor = _LEVEL_RANK.get(MQTT_ALERT_MIN_LEVEL, 2)
    return rank >= floor


def publish_vitals(result):
    """Push a compact vitals frame on the 'live' topic. Never raises."""
    if not result:
        return
    client = _get_client()
    if client is None:
        return
    patient_id = result.get("patient_id") or "unknown"
    payload = json.dumps(_compact_vitals(result), ensure_ascii=False, default=str)
    try:
        client.publish(_vitals_topic(patient_id), payload, qos=MQTT_QOS_VITALS, retain=False)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("MQTT publish vitals failed: %s", exc)


def publish_alert(result, events=None):
    """Push a critical alert on the 'alert' topic with retain=True.

    Only fires when alert_level meets MQTT_ALERT_MIN_LEVEL (default medium).
    retain=True so a freshly-connected app immediately sees the latest alert.
    QoS=2 for exactly-once delivery (no duplicate alarm spam, no loss).
    """
    if not result:
        return
    level = result.get("alert_level")
    if not _alert_meets_floor(level):
        return
    client = _get_client()
    if client is None:
        return
    patient_id = result.get("patient_id") or "unknown"
    payload = json.dumps(
        {
            "patient_id": patient_id,
            "timestamp": result.get("timestamp"),
            "alert_level": level,
            "message": result.get("message"),
            "heart_rate_bpm": result.get("heart_rate_bpm"),
            "rhythm": result.get("rhythm"),
            "ectopy": result.get("ectopy"),
            "hr_event": result.get("hr_event"),
            "af_episode": result.get("af_episode"),
            "events": events or [],
        },
        ensure_ascii=False,
        default=str,
    )
    try:
        client.publish(_alert_topic(patient_id), payload, qos=MQTT_QOS_ALERT, retain=True)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("MQTT publish alert failed: %s", exc)


def publish_status(extra=None):
    """Publish service heartbeat to {prefix}/service/status (retained)."""
    client = _get_client()
    if client is None:
        return
    doc = {"status": "online", "pid": os.getpid()}
    if extra:
        doc.update(extra)
    try:
        client.publish(_service_status_topic(), json.dumps(doc), qos=1, retain=True)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("MQTT publish status failed: %s", exc)


def is_enabled():
    return MQTT_ENABLED


def is_connected():
    """Best-effort check. paho exposes .is_connected() in modern versions."""
    client = _client
    if client is None:
        return False
    try:
        return bool(client.is_connected())
    except Exception:  # noqa: BLE001
        return False


def shutdown():
    """Clean disconnect — publishes offline status BEFORE closing socket so
    subscribers see a graceful goodbye instead of LWT-triggered offline.
    Call from FastAPI lifespan shutdown event.
    """
    global _client
    with _client_lock:
        client = _client
        _client = None
    if client is None:
        return
    try:
        client.publish(
            _service_status_topic(),
            json.dumps({"status": "offline", "reason": "graceful_shutdown"}),
            qos=1,
            retain=True,
        )
        # Brief wait so the publish has a chance to ACK before we tear down.
        client.loop_stop()
        client.disconnect()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("MQTT shutdown error: %s", exc)


# ----- Reset hook for tests -----
def _reset_for_tests():
    global _client, _connect_attempted
    with _client_lock:
        if _client is not None:
            try:
                _client.loop_stop()
                _client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        _client = None
        _connect_attempted = False
