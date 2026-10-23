"""Opt-in E04 hooks. Importing this package never changes a detector."""

from importlib import import_module


DEFAULTS = {'postprocess': 'a0', 'engine': 'b0', 'preprocess': 'c0'}
MODULES = {'postprocess': 'postprocess', 'engine': 'graph', 'preprocess': 'preprocess'}
ORDER = ('engine', 'preprocess', 'postprocess')


class PipelineOptimizations:
    def __init__(self, detector, variants=None):
        self.variants = dict(DEFAULTS)
        if variants:
            unknown = set(variants) - set(DEFAULTS)
            if unknown:
                raise ValueError('Unknown optimization keys: ' + repr(sorted(unknown)))
            self.variants.update(variants)
        self.handles = []
        self.restored = False
        try:
            for key in ORDER:
                module = import_module(__name__ + '.' + MODULES[key])
                self.handles.append((key, module.install(detector, self.variants[key])))
        except BaseException:
            self.restore()
            raise

    def describe(self):
        return {'requested': dict(self.variants), 'restored': self.restored,
                'components': {key: handle.describe() for key, handle in self.handles}}

    def restore(self):
        if self.restored:
            return
        errors = []
        for key, handle in reversed(self.handles):
            try:
                handle.restore()
            except Exception as error:
                errors.append((key, repr(error)))
        self.restored = not errors
        if errors:
            raise RuntimeError('Optimization restore failed: ' + repr(errors))


def install_pipeline(detector, variants=None):
    """Called after predictor/backend initialization, before warmup/measurement."""
    return PipelineOptimizations(detector, variants)
