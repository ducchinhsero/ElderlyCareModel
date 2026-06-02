import unittest

from fastapi.testclient import TestClient

from src.api import pipeline


class ApiAuthTest(unittest.TestCase):
    def setUp(self):
        self.original_enabled = pipeline.API_AUTH_ENABLED
        self.original_key = pipeline.API_KEY
        self.original_public_paths = set(pipeline.API_PUBLIC_PATHS)

    def tearDown(self):
        pipeline.API_AUTH_ENABLED = self.original_enabled
        pipeline.API_KEY = self.original_key
        pipeline.API_PUBLIC_PATHS = self.original_public_paths

    def test_auth_disabled_keeps_existing_behavior(self):
        pipeline.API_AUTH_ENABLED = False
        response = TestClient(pipeline.app).get("/latest-result")
        self.assertEqual(response.status_code, 200)

    def test_auth_enabled_rejects_missing_key_for_protected_endpoint(self):
        pipeline.API_AUTH_ENABLED = True
        pipeline.API_KEY = "secret"
        pipeline.API_PUBLIC_PATHS = {"/health"}
        response = TestClient(pipeline.app).get("/latest-result")
        self.assertEqual(response.status_code, 401)
        response = TestClient(pipeline.app).get("/alerts/realtime")
        self.assertEqual(response.status_code, 401)

    def test_auth_enabled_accepts_valid_key_for_protected_endpoint(self):
        pipeline.API_AUTH_ENABLED = True
        pipeline.API_KEY = "secret"
        pipeline.API_PUBLIC_PATHS = {"/health"}
        response = TestClient(pipeline.app).get("/latest-result", headers={"X-API-Key": "secret"})
        self.assertEqual(response.status_code, 200)

    def test_public_endpoint_does_not_require_key(self):
        pipeline.API_AUTH_ENABLED = True
        pipeline.API_KEY = "secret"
        pipeline.API_PUBLIC_PATHS = {"/health"}
        response = TestClient(pipeline.app).get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertIn("network_provisioning", response.json())

    def test_alert_websocket_sends_backlog(self):
        original_get_realtime_alerts = pipeline.get_realtime_alerts
        pipeline.API_AUTH_ENABLED = False
        pipeline.get_realtime_alerts = lambda **kwargs: {
            "alert_count": 1,
            "alerts": [
                {
                    "event_id": "event-1",
                    "patient_id": kwargs.get("patient_id"),
                    "event_type": "fall_candidate",
                    "severity": "critical",
                    "label": "strong_fall",
                    "message": "Strong fall detected.",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "ack_status": {
                        "acknowledged": False,
                        "resolved": False,
                        "status": "unacknowledged",
                    },
                }
            ],
        }
        try:
            with TestClient(pipeline.app).websocket_connect(
                "/ws/alerts?patient_id=polar_h10&caregiver_id=caregiver_1"
            ) as websocket:
                message = websocket.receive_json()
                self.assertEqual(message["type"], "alert_backlog")
                self.assertEqual(message["alert_count"], 1)
                self.assertEqual(message["alerts"][0]["severity"], "critical")
        finally:
            pipeline.get_realtime_alerts = original_get_realtime_alerts


if __name__ == "__main__":
    unittest.main()
