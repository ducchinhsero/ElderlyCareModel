import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.pipeline import app


class DailyHealthApiTest(unittest.TestCase):
    def test_daily_health_assessment_endpoint_shape(self):
        expected = {
            "patient_id": "test_patient",
            "period": {"mode": "rolling_24h", "hours": 24.0},
            "data_quality": {"label": "good", "prediction_count": 20},
            "overall": {"level": "low", "score": 0.2, "summary": "ok"},
            "findings": [],
            "recommendations": ["Continue routine monitoring."],
            "disclaimer": "This is a screening/risk assessment output, not a medical diagnosis.",
        }
        with patch("src.api.pipeline.compute_daily_health_assessment", return_value=expected) as mocked:
            response = TestClient(app).get(
                "/daily-health-assessment",
                params={"patient_id": "test_patient", "hours": 24},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        mocked.assert_called_once_with(patient_id="test_patient", hours=24.0)

    def test_daily_health_assessment_rejects_invalid_hours(self):
        with patch("src.api.pipeline.compute_daily_health_assessment", side_effect=ValueError("hours must be positive")):
            response = TestClient(app).get("/daily-health-assessment", params={"hours": 0})

        self.assertEqual(response.status_code, 400)
        self.assertIn("hours must be positive", response.json()["detail"])

    def test_health_report_endpoint_shape(self):
        expected = {
            "patient_id": "test_patient",
            "report_type": "temporal_health_report",
            "layers": {
                "realtime": {"overall": {"level": "low"}},
                "daily": {"overall": {"level": "low"}},
                "long_term": {"overall": {"level": "unknown"}},
            },
            "overall": {"level": "low"},
            "disclaimer": "This is a screening/risk assessment output, not a medical diagnosis.",
        }
        with patch("src.api.pipeline.compute_temporal_health_report", return_value=expected) as mocked:
            response = TestClient(app).get(
                "/health-report",
                params={
                    "patient_id": "test_patient",
                    "realtime_minutes": 5,
                    "daily_hours": 24,
                    "long_term_days": 7,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        mocked.assert_called_once_with(
            patient_id="test_patient",
            realtime_minutes=5.0,
            daily_hours=24.0,
            long_term_days=7.0,
        )

    def test_health_report_rejects_invalid_windows(self):
        response = TestClient(app).get("/health-report", params={"long_term_days": 0})

        self.assertEqual(response.status_code, 400)
        self.assertIn("must be positive", response.json()["detail"])

    def test_personal_baseline_status_endpoint(self):
        expected = {"patient_id": "test_patient", "calibrated": False, "baseline": None}
        with patch("src.api.pipeline.get_personal_baseline_status", return_value=expected) as mocked:
            response = TestClient(app).get(
                "/personal-baseline/status",
                params={"patient_id": "test_patient"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        mocked.assert_called_once_with("test_patient")

    def test_personal_baseline_calibrate_endpoint(self):
        expected = {
            "status": "calibrated",
            "path": "dataset/realtime_logs/personal_baseline/test_patient/personal_baseline.json",
            "baseline": {"patient_id": "test_patient"},
        }
        with patch("src.api.pipeline.calibrate_personal_baseline", return_value=expected) as mocked:
            response = TestClient(app).post(
                "/personal-baseline/calibrate",
                json={
                    "patient_id": "test_patient",
                    "days": 2,
                    "min_predictions": 20,
                    "include_alert_windows": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        mocked.assert_called_once_with(
            patient_id="test_patient",
            days=2.0,
            min_predictions=20,
            include_alert_windows=False,
        )

    def test_personal_baseline_update_progressive_endpoint(self):
        expected = {
            "status": "warming_up",
            "path": "dataset/realtime_logs/personal_baseline/test_patient/personal_baseline.json",
            "baseline": {"patient_id": "test_patient", "calibration": {"target_days": 7}},
        }
        with patch("src.api.pipeline.update_progressive_personal_baseline", return_value=expected) as mocked:
            response = TestClient(app).post(
                "/personal-baseline/update-progressive",
                json={
                    "patient_id": "test_patient",
                    "target_days": 7,
                    "min_predictions": 20,
                    "include_alert_windows": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        mocked.assert_called_once_with(
            patient_id="test_patient",
            target_days=7,
            min_predictions=20,
            include_alert_windows=False,
        )


if __name__ == "__main__":
    unittest.main()
