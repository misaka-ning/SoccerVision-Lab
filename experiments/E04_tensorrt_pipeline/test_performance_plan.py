import tempfile
from pathlib import Path
import unittest

from performance_plan import schedule, stats, summarize, is_baseline_end


class PerformancePlanTests(unittest.TestCase):
    def test_candidates_are_repeated_and_bracketed_with_baseline(self):
        jobs = schedule(['detector'])
        self.assertEqual(len(jobs), 21)
        for index in range(3):
            block = jobs[index * 7:(index + 1) * 7]
            self.assertEqual((block[0]['variant'], block[-1]['variant']), ('R0', 'R0'))
            self.assertEqual({x['variant'] for x in block[1:-1]}, {'A1', 'A2', 'A1_A2', 'B_Graph', 'C2'})
        self.assertTrue(all(x['warmup'] == 100 and x['seconds'] == 60 for x in jobs))
        self.assertEqual(len({x['name'] for x in jobs}), len(jobs))

    def test_graph_execution_has_three_interleaved_pairs(self):
        jobs = schedule(['execution'])
        self.assertEqual([x['variant'] for x in jobs], ['b0', 'graph', 'graph', 'b0', 'b0', 'graph'])
        with self.assertRaises(ValueError): schedule(['combination_A_B'])

    def test_combination_has_contemporary_a2_and_balanced_brackets(self):
        jobs = schedule(['detector', 'system'], matrix='combined_pipeline')
        self.assertEqual(len(jobs), 30)
        self.assertEqual(sum(is_baseline_end(j, jobs) for j in jobs), 6)
        self.assertTrue(all(j['position'] == 4 for j in jobs if is_baseline_end(j, jobs)))
        for scope in ['detector', 'system']:
            for index in [1, 2, 3]:
                block = [j for j in jobs if j['scope'] == scope and j['round'] == index]
                self.assertEqual([block[0]['variant'], block[-1]['variant']], ['R0', 'R0'])
                self.assertEqual({j['variant'] for j in block[1:-1]}, {'A2', 'R4_AB', 'R5_ABC'})
        for variant in ['A2', 'R4_AB', 'R5_ABC']:
            self.assertEqual(sorted(j['position'] for j in jobs if j['scope']=='system' and j['variant']==variant), [1, 2, 3])
        with self.assertRaises(ValueError): schedule(['execution'], matrix='combined_pipeline')
        with self.assertRaises(ValueError): schedule(['system'], matrix='invented')

    def test_legacy_last_baseline_is_still_position_six(self):
        jobs = schedule(['detector'])
        self.assertEqual([j['position'] for j in jobs if is_baseline_end(j,jobs)], [6, 6, 6])

    def test_percentiles_include_tail_and_reject_nonfinite(self):
        result = stats([1, 2, 3, 4, 100])
        self.assertGreater(result['p99'], result['p95'])
        with self.assertRaises(ValueError): stats([float('nan')])

    def test_hz_uses_real_intervals_including_between_cycle_waits(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'frames.csv'
            path.write_text('cycle_start,cycle_end,publish_end,cycle_ms,left_candidates,right_candidates\n'
                            '0,0.02,0.019,20,1,1\n0.1,0.12,0.119,20,1,1\n')
            result = summarize(path, 'system')
            self.assertAlmostEqual(result['processing_hz'], 2 / .12)
            self.assertAlmostEqual(result['publish_hz'], 10)
            self.assertNotAlmostEqual(result['processing_hz'], 1000 / result['cycle_ms']['mean'])

    def test_observed_measurement_validity_stays_distinct_from_tracking(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'frames.csv'
            path.write_text('cycle_start,cycle_end,publish_end,cycle_ms,left_candidates,right_candidates,frame_idx,frame_timestamp_s,measurement_valid,tracking_valid,track_initialized,coasting\n'
                            '0,0.02,0.019,20,1,1,101,5.1,1,1,1,0\n0.1,0.12,0.119,20,0,0,102,5.2,0,1,1,1\n')
            result = summarize(path, 'system')
            self.assertEqual(result['packet_flags']['measurement_valid']['fraction'], .5)
            self.assertEqual(result['packet_flags']['tracking_valid']['fraction'], 1)
            self.assertEqual(result['frame_association']['frame_idx_nonincreasing'], 0)
            self.assertEqual(result['frame_association']['timestamp_nonincreasing'], 0)


if __name__ == '__main__':
    unittest.main()
