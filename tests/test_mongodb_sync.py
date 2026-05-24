import unittest

from src.storage.mongodb_sync import event_id_for, is_mongodb_configured


class MongoDBSyncTests(unittest.TestCase):
    def test_event_id_is_deterministic(self):
        event = {
            "patient_id": "polar_h10",
            "session_id": "20260521",
            "timestamp": "2026-05-21T10:00:00+07:00",
            "event_type": "rhythm_alert",
            "severity": "high",
            "label": "possible_afib",
            "message": "Possible AFib rhythm detected.",
        }
        self.assertEqual(event_id_for(event), event_id_for(dict(reversed(list(event.items())))))

    def test_mongodb_config_detection_accepts_explicit_uri(self):
        self.assertTrue(is_mongodb_configured("mongodb://localhost:27017"))


if __name__ == "__main__":
    unittest.main()
