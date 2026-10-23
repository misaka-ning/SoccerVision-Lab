import unittest

from run_correctness_robot import select_variants


class CorrectnessScopeTests(unittest.TestCase):
    def test_legacy_single_component_schedule_is_preserved(self):
        variants = select_variants({})
        self.assertEqual(len(variants), 7)
        self.assertEqual(variants['B_Graph'], {'engine': 'graph'})
        self.assertNotIn('R4_AB', variants)

    def test_combination_needs_exact_coordinator_scope(self):
        payload = {'mode': 'ab_combination_correctness'}
        for gate in [None, {}, {'status': 'approved_for_ab_correctness_only',
                               'allowed_switches': {'postprocess': 'a2', 'engine': 'graph', 'preprocess': 'c2'}}]:
            with self.assertRaises(RuntimeError):
                select_variants(payload, gate)
        variants = select_variants(payload, {'status': 'approved_for_ab_correctness_only',
                                   'allowed_switches': {'postprocess': 'a2', 'engine': 'graph'}})
        self.assertEqual(list(variants), ['R0', 'R4_AB'])
        self.assertEqual(variants['R0'], {})
        self.assertEqual(variants['R4_AB'], {'postprocess': 'a2', 'engine': 'graph'})

    def test_unknown_modes_do_not_start_work(self):
        with self.assertRaises(ValueError):
            select_variants({'mode': 'production_or_int8'})

    def test_c2_diagnostic_requires_its_own_explicit_gate(self):
        payload = {'mode': 'ab_abc_combination_correctness'}
        with self.assertRaises(RuntimeError):
            select_variants(payload, {'status': 'approved_for_ab_correctness_only',
                                     'allowed_switches': {'postprocess': 'a2', 'engine': 'graph'}})
        allowed = {'R4_AB': {'postprocess': 'a2', 'engine': 'graph'},
                   'R5_ABC': {'postprocess': 'a2', 'engine': 'graph', 'preprocess': 'c2'}}
        self.assertEqual(select_variants(payload, {'status': 'approved_for_ab_abc_correctness_only',
                                                  'allowed_combinations': allowed}), dict(R0={}, **allowed))
        wrong = {'R4_AB': allowed['R4_AB'], 'R5_ABC': dict(allowed['R5_ABC'], postprocess='a1+a2')}
        with self.assertRaises(RuntimeError):
            select_variants(payload, {'status': 'approved_for_ab_abc_correctness_only', 'allowed_combinations': wrong})


if __name__ == '__main__':
    unittest.main()
