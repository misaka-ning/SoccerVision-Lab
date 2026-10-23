import unittest

from review_performance import paired_change


def job(mean, start, end):
    return dict(round=1, metrics={'detector_wall_ms': {'mean': mean}},
                started_utc='2026-10-22T06:%02d:00+00:00' % start,
                completed_utc='2026-10-22T06:%02d:00+00:00' % end)


class PairingTests(unittest.TestCase):
    def test_midpoint_candidate_uses_both_baselines(self):
        result = paired_change(job(50, 0, 2), job(54, 10, 12), job(48, 5, 7), 'detector_wall_ms')
        self.assertEqual(result['baseline_ms'], 52)
        self.assertEqual(result['saved_ms'], 4)
        self.assertAlmostEqual(result['reduction_percent'], 100 * 4 / 52)
        self.assertEqual(result['interpolated_baseline_ms'], 52)

    def test_early_candidate_exposes_drift_sensitivity(self):
        result = paired_change(job(50, 0, 2), job(54, 10, 12), job(51, 1, 3), 'detector_wall_ms')
        self.assertGreater(result['reduction_percent'], 0)
        self.assertEqual(result['interpolated_baseline_ms'], 50.4)
        self.assertLess(result['interpolated_reduction_percent'], 0)

    def test_slow_candidate_keeps_negative_result(self):
        result = paired_change(job(50, 0, 2), job(50, 10, 12), job(51, 5, 7), 'detector_wall_ms')
        self.assertEqual(result['saved_ms'], -1)
        self.assertEqual(result['reduction_percent'], -2)


if __name__ == '__main__':
    unittest.main()
