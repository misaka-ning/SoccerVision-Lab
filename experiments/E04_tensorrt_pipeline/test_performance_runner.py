import io
import subprocess
import unittest
from unittest.mock import Mock, patch

from performance_plan import schedule
from performance_runner import run_child, supersede_partial_blocks
from run_performance_robot import validate_packet_observation


class RunnerGuards(unittest.TestCase):
    def test_timeout_terminates_only_created_worker_group(self):
        child = Mock(pid=45678)
        child.wait.side_effect = [subprocess.TimeoutExpired('own_worker', 240), 0]
        child.poll.return_value = None
        with patch('performance_runner.subprocess.Popen', return_value=child), patch('performance_runner.os.killpg') as kill:
            with self.assertRaises(subprocess.TimeoutExpired): run_child(['own_worker'], io.StringIO(), 8, lambda pid: None)
        self.assertEqual(kill.call_args.args[0], 45678)
        self.assertEqual(kill.call_count, 1)

    def test_resume_restarts_entire_incomplete_bracket_but_keeps_data(self):
        specs = schedule(['detector'])
        jobs = [dict(x, status='complete', output='preserved') for x in specs[:3]]
        self.assertTrue(supersede_partial_blocks(jobs, specs, ['detector']))
        self.assertTrue(all(j['status'] == 'superseded_incomplete_block' for j in jobs))
        self.assertTrue(all(j['output'] == 'preserved' for j in jobs))

    def test_metadata_failure_also_cleans_up_created_child(self):
        child = Mock(pid=45678)
        child.poll.return_value = None
        child.wait.return_value = 0
        with patch('performance_runner.subprocess.Popen', return_value=child), patch('performance_runner.os.killpg') as kill:
            with self.assertRaises(OSError):
                run_child(['own_worker'], io.StringIO(), 8, Mock(side_effect=OSError('write failed')))
        self.assertEqual(kill.call_args.args[0], 45678)

    def test_complete_blocks_are_not_repeated(self):
        specs = schedule(['detector'])
        jobs = [dict(x, status='complete') for x in specs[:7]]
        self.assertFalse(supersede_partial_blocks(jobs, specs, ['detector']))
        self.assertTrue(all(j['status'] == 'complete' for j in jobs))

    def test_combination_resume_preserves_full_blocks_and_restarts_partial_block(self):
        specs = schedule(['system'], matrix='combined_pipeline')
        jobs = [dict(x, status='complete', output='keep') for x in specs[:7]]
        self.assertTrue(supersede_partial_blocks(jobs, specs, ['system']))
        self.assertTrue(all(j['status']=='complete' for j in jobs[:5]))
        self.assertTrue(all(j['status']=='superseded_incomplete_block' for j in jobs[5:]))
        self.assertTrue(all(j['output']=='keep' for j in jobs))

    def test_other_matrix_records_do_not_complete_combination_block(self):
        specs = schedule(['system'], matrix='combined_pipeline')
        jobs = [dict(x, status='complete') for x in specs[1:5]]
        jobs.append(dict(specs[0], matrix_id='single_components', status='complete'))
        self.assertTrue(supersede_partial_blocks(jobs, specs, ['system']))
        self.assertTrue(all(j['status']=='superseded_incomplete_block' for j in jobs[:4]))
        self.assertEqual(jobs[-1]['status'], 'complete')

    def test_packet_guard_accepts_empty_measurements_with_valid_frame_association(self):
        from packet_observer import FIELDS
        hook = {'packet_observer': dict(restore='complete', warmup_calls=100, calls=110, fields=list(FIELDS))}
        metrics = dict(packet_flags={'measurement_valid': dict(count=0, fraction=0)},
                       frame_association=dict(frame_idx_nonincreasing=0, timestamp_nonincreasing=0))
        validate_packet_observation(hook, metrics, 10)

    def test_packet_guard_rejects_stale_frame_or_missing_fields(self):
        from packet_observer import FIELDS
        hook = {'packet_observer': dict(restore='complete', warmup_calls=100, calls=110, fields=list(FIELDS))}
        for association in [{}, dict(frame_idx_nonincreasing=1, timestamp_nonincreasing=0),
                            dict(frame_idx_nonincreasing=0, timestamp_nonincreasing=1)]:
            with self.assertRaises(RuntimeError):
                validate_packet_observation(hook, dict(packet_flags={'measurement_valid': {}}, frame_association=association), 10)
        hook['packet_observer']['fields'].pop()
        with self.assertRaises(RuntimeError):
            validate_packet_observation(hook, dict(packet_flags={'measurement_valid': {}}, frame_association=dict(frame_idx_nonincreasing=0, timestamp_nonincreasing=0)), 10)


if __name__ == '__main__':
    unittest.main()
