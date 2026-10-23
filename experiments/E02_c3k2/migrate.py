"""Deterministic branch-aware prefix transfer for E02 layer 19 only.

This is a width-reduction pilot, not an importance-ranked pruning method.
Channel identities are kept across split, concat and residual connections.
"""
from __future__ import annotations

import torch
from ultralytics.nn.modules.block import C3k, C3k2
from ultralytics.nn.modules.conv import Conv


def prefix(size):
    return list(range(size))


def branches(old_width, new_width, count):
    return [part * old_width + channel for part in range(count) for channel in range(new_width)]


def transfer_layer19(source, target):
    if type(source) is not C3k2 or type(target) is not C3k2:
        raise ValueError('Only the audited ordinary C3k2 block is supported')
    if source.c < target.c or len(source.m) != len(target.m):
        raise ValueError('Only a hidden-width reduction with unchanged repeats is supported')
    if source.cv1.conv.in_channels != target.cv1.conv.in_channels or source.cv2.conv.out_channels != target.cv2.conv.out_channels:
        raise ValueError('Layer input and output channels must stay unchanged')
    report = []

    @torch.no_grad()
    def conv(old, new, inputs, outputs, name):
        if type(old) is not Conv or type(new) is not Conv:
            raise ValueError(f'Unsupported convolution wrapper: {name}')
        a, b = old.conv, new.conv
        if a.groups != 1 or b.groups != 1 or a.kernel_size != b.kernel_size or a.stride != b.stride or a.padding != b.padding:
            raise ValueError(f'Unvalidated convolution structure: {name}')
        if len(inputs) != b.in_channels or len(outputs) != b.out_channels:
            raise ValueError(f'Wrong channel map length: {name}')
        ii, oo = torch.tensor(inputs), torch.tensor(outputs)
        value = a.weight.detach().index_select(0, oo).index_select(1, ii)
        b.weight.copy_(value)
        if a.bias is not None or b.bias is not None:
            if a.bias is None or b.bias is None:
                raise ValueError(f'Bias mismatch: {name}')
            b.bias.copy_(a.bias.index_select(0, oo))
        for field in ['weight', 'bias', 'running_mean', 'running_var']:
            getattr(new.bn, field).copy_(getattr(old.bn, field).index_select(0, oo))
        new.bn.num_batches_tracked.copy_(old.bn.num_batches_tracked)
        if old.bn.eps != new.bn.eps or old.bn.momentum != new.bn.momentum:
            raise ValueError(f'BatchNorm semantics changed: {name}')
        # Auditable map also drives the masked-source equivalence test.
        report.append(dict(module=name, input_indices=inputs, output_indices=outputs,
                           old_weight_shape=list(a.weight.shape), new_weight_shape=list(b.weight.shape)))

    kept = prefix(target.c)
    conv(source.cv1, target.cv1, prefix(target.cv1.conv.in_channels), branches(source.c, target.c, 2), 'cv1')
    conv(source.cv2, target.cv2, branches(source.c, target.c, 2 + len(source.m)), prefix(target.cv2.conv.out_channels), 'cv2')
    for index, (old, new) in enumerate(zip(source.m, target.m)):
        if type(old) is not C3k or type(new) is not C3k or len(old.m) != len(new.m):
            raise ValueError('Attention/Bottleneck variants require a separate transfer audit')
        old_inner, new_inner = old.cv1.conv.out_channels, new.cv1.conv.out_channels
        hidden = prefix(new_inner)
        conv(old.cv1, new.cv1, kept, hidden, f'm.{index}.cv1')
        conv(old.cv2, new.cv2, kept, hidden, f'm.{index}.cv2')
        conv(old.cv3, new.cv3, branches(old_inner, new_inner, 2), kept, f'm.{index}.cv3')
        for j, (ob, nb) in enumerate(zip(old.m, new.m)):
            if ob.add != nb.add or not ob.add:
                raise ValueError('Residual connection semantics changed')
            intermediate = prefix(nb.cv1.conv.out_channels)
            conv(ob.cv1, nb.cv1, hidden, intermediate, f'm.{index}.m.{j}.cv1')
            conv(ob.cv2, nb.cv2, intermediate, hidden, f'm.{index}.m.{j}.cv2')
    return report


def transfer_model(source, target):
    old, new = source.state_dict(), target.state_dict()
    if set(old) != set(new):
        raise ValueError('State keys differ: refusing a partial/random transfer')
    outside = {}
    for key, value in new.items():
        if not key.startswith('model.19.'):
            if old[key].shape != value.shape:
                raise ValueError(f'Unexpected change outside layer 19: {key}')
            outside[key] = old[key]
    target.load_state_dict(outside, strict=False)
    mapping = transfer_layer19(source.model[19], target.model[19])
    after = target.state_dict()
    for key in outside:
        if not torch.equal(after[key], old[key]):
            raise AssertionError(f'Failed exact transfer: {key}')
    return dict(strategy='branch-aware deterministic prefix (not saliency-ranked)',
                copied_outside_layer19_tensors=len(outside), total_tensors=len(after),
                random_uninitialized_tensors=[], channel_maps=mapping)
