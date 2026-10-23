import sys
import types
import unittest
from unittest.mock import patch

from soccer_perception.optimizations import DEFAULTS, install_pipeline


class IntegrationLifecycle(unittest.TestCase):
    def modules(self, calls, fail=None):
        result = {}
        for name in ['graph', 'preprocess', 'postprocess']:
            module = types.ModuleType('soccer_perception.optimizations.' + name)
            def install(detector, variant, name=name):
                calls.append(('install', name, variant))
                if name == fail:
                    raise ValueError('injected setup error')
                class Handle:
                    def describe(self): return {'effective': variant}
                    def restore(self): calls.append(('restore', name))
                return Handle()
            module.install = install
            result[module.__name__] = module
        return result

    def test_default_hooks_and_reverse_idempotent_restore(self):
        calls = []
        with patch.dict(sys.modules, self.modules(calls)):
            handle = install_pipeline(object())
            self.assertEqual(handle.describe()['requested'], DEFAULTS)
            handle.restore(); handle.restore()
        self.assertEqual([x[1] for x in calls if x[0] == 'restore'], ['postprocess', 'preprocess', 'graph'])

    def test_partial_setup_failure_restores_prior_components(self):
        calls = []
        with patch.dict(sys.modules, self.modules(calls, fail='postprocess')):
            with self.assertRaisesRegex(ValueError, 'injected'):
                install_pipeline(object(), {'engine': 'graph'})
        self.assertEqual(calls[-2:], [('restore', 'preprocess'), ('restore', 'graph')])

    def test_unknown_option_fails_before_mutation(self):
        calls = []
        with patch.dict(sys.modules, self.modules(calls)):
            with self.assertRaises(ValueError): install_pipeline(object(), {'engien': 'graph'})
        self.assertFalse(calls)

    def test_failed_cleanup_can_be_retried(self):
        calls = []
        modules = self.modules(calls)
        count = [0]
        class Handle:
            def describe(self): return {}
            def restore(self):
                count[0] += 1
                if count[0] == 1: raise RuntimeError('transient cleanup failure')
        modules['soccer_perception.optimizations.graph'].install = lambda *args: Handle()
        with patch.dict(sys.modules, modules):
            handle = install_pipeline(object())
            with self.assertRaisesRegex(RuntimeError, 'cleanup failure'): handle.restore()
            self.assertFalse(handle.restored)
            handle.restore()
            self.assertTrue(handle.restored)
            self.assertEqual(count[0], 2)


if __name__ == '__main__':
    unittest.main()
