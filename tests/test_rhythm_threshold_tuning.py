import unittest

from src.training.tune_rhythm_thresholds import select_threshold, threshold_metrics


class RhythmThresholdTuningTest(unittest.TestCase):
    def test_selects_threshold_matching_recall_and_precision_policy(self):
        y_true = [0, 0, 0, 1, 1]
        probs = [0.02, 0.10, 0.20, 0.30, 0.90]
        rows = threshold_metrics(y_true, probs, thresholds=[0.10, 0.25, 0.50])

        selected, fallback_used = select_threshold(
            rows,
            target_recall=0.5,
            precision_floor=0.8,
        )

        self.assertFalse(fallback_used)
        self.assertEqual(selected["threshold"], 0.25)
        self.assertEqual(selected["precision"], 1.0)
        self.assertEqual(selected["recall"], 1.0)

    def test_falls_back_to_best_f1_when_policy_has_no_candidate(self):
        rows = [
            {"threshold": 0.1, "precision": 0.4, "recall": 1.0, "f1": 0.57, "predicted_positive_ratio": 0.5},
            {"threshold": 0.2, "precision": 0.6, "recall": 0.8, "f1": 0.69, "predicted_positive_ratio": 0.4},
        ]

        selected, fallback_used = select_threshold(
            rows,
            target_recall=0.95,
            precision_floor=0.8,
        )

        self.assertTrue(fallback_used)
        self.assertEqual(selected["threshold"], 0.2)


if __name__ == "__main__":
    unittest.main()
