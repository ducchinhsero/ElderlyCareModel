import unittest

import numpy as np

from src.features.acc_features import (
    FS_ACC_HZ,
    classify_activity,
    detect_fall,
    parse_acc_packet,
    summarize_acc_window,
)


def acc_packet(samples, timestamp_ns=123456789):
    payload = bytearray([0x02])
    payload.extend(int(timestamp_ns).to_bytes(8, "little"))
    payload.append(0x01)
    for x, y, z in samples:
        payload.extend(int(x).to_bytes(2, "little", signed=True))
        payload.extend(int(y).to_bytes(2, "little", signed=True))
        payload.extend(int(z).to_bytes(2, "little", signed=True))
    return bytes(payload)


class ACCFeatureTests(unittest.TestCase):
    def test_parse_acc_packet_reads_int16_samples(self):
        timestamp_ns, samples = parse_acc_packet(acc_packet([(1000, 0, 0), (-1000, 20, -30)]))

        self.assertEqual(timestamp_ns, 123456789)
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0][:3], (1000.0, 0.0, 0.0))
        self.assertAlmostEqual(samples[0][3], 1000.0)

    def test_parse_acc_packet_ignores_non_acc_packet(self):
        timestamp_ns, samples = parse_acc_packet(bytes([0x00]) + b"\x00" * 12)

        self.assertEqual(timestamp_ns, 0)
        self.assertEqual(samples, [])

    def test_classify_activity_thresholds(self):
        self.assertEqual(classify_activity(10), "REST")
        self.assertEqual(classify_activity(50), "SLOW_WALK")
        self.assertEqual(classify_activity(120), "WALK")
        self.assertEqual(classify_activity(350), "ACTIVE")

    def test_detect_fall_requires_free_fall_before_impact(self):
        vm = np.ones(FS_ACC_HZ * 6) * 1000
        vm[30:36] = 300
        vm[42] = 3300
        vm[43:] = 1005

        fall = detect_fall(vm)

        self.assertTrue(fall["impact_spike"])
        self.assertTrue(fall["free_fall"])
        self.assertTrue(fall["post_still"])
        self.assertTrue(fall["fall_candidate"])
        self.assertTrue(fall["strong_fall"])

    def test_detect_fall_rejects_active_motion_without_post_still(self):
        rng = np.random.default_rng(42)
        vm = 1200 + rng.normal(0, 260, FS_ACC_HZ * 6)
        vm[30:36] = 300
        vm[42] = 4200
        vm[43:] = 1200 + rng.normal(0, 300, vm[43:].shape[0])

        fall = detect_fall(vm)

        self.assertTrue(fall["impact_spike"])
        self.assertTrue(fall["free_fall"])
        self.assertFalse(fall["post_still"])
        self.assertFalse(fall["fall_candidate"])
        self.assertFalse(fall["strong_fall"])
        self.assertTrue(fall["impact_only"])

    def test_detect_fall_rejects_walking_spike_without_free_fall(self):
        vm = np.ones(FS_ACC_HZ * 6) * 1000
        vm[30] = 2300
        vm[70] = 2400

        fall = detect_fall(vm)

        self.assertTrue(fall["impact_spike"])
        self.assertFalse(fall["fall_candidate"])
        self.assertFalse(fall["strong_fall"])

    def test_summarize_acc_window_returns_sensor_context(self):
        samples = [(1000, 0, 0), (1010, 0, 0), (990, 0, 0)] * 10

        context = summarize_acc_window(samples, heart_rate_bpm=72)

        self.assertEqual(context["activity_state"], "REST")
        self.assertIn("activity_features", context)
        self.assertIn("fall", context)
        self.assertIn("hr_context_alert", context)


if __name__ == "__main__":
    unittest.main()
