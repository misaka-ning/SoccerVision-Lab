import types
import unittest

from candidate_entry import patch_detector
from compare_goldens import compare_value


class CandidateToolTests(unittest.TestCase):
    def test_protocol_types_are_preserved(self):
        for a, b in [(True, 1), (False, 0), (1, 1.0), ('1', 1), (None, False)]:
            self.assertTrue(compare_value(a, b), (a, b))
        self.assertFalse(compare_value({'valid': True, 'x_m': 1.0}, {'valid': True, 'x_m': 1.0 + 1e-12}))

    def test_lazy_initialization_returns_current_candidate_result(self):
        class Detector:
            def __init__(self):
                self.model = types.SimpleNamespace(predictor=types.SimpleNamespace())
                self.calls = []
                self.optimized = False
            def detect_candidates_batch(self, frames, top_k=None):
                self.calls.append((frames, self.optimized))
                return (frames, self.optimized)
        def install(detector, variants):
            detector.optimized = True
            return object()
        original, states = patch_detector(Detector, install, {})
        try:
            detector = Detector()
            self.assertEqual(detector.detect_candidates_batch('left/right A'), ('left/right A', True))
            self.assertEqual(detector.detect_candidates_batch('left/right B'), ('left/right B', True))
            self.assertEqual(detector.calls, [('left/right A', False), ('left/right A', True), ('left/right B', True)])
            self.assertEqual(len(states), 1)
        finally:
            Detector.detect_candidates_batch = original


if __name__ == '__main__':
    unittest.main()
