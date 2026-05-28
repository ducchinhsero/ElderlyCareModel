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


if __name__ == "__main__":
    unittest.main()
