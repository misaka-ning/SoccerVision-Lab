"""Meaningful graph check: narrowed block equals a masked original block."""
import importlib.util
from pathlib import Path
import sys
import unittest

import torch
from ultralytics.nn.modules.block import C3k2

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import migrate


class MigrationTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(42);torch.set_num_threads(2)
        self.old=C3k2(24,32,n=1,c3k=True,e=.5).eval()
        self.new=C3k2(24,32,n=1,c3k=True,e=.4375).eval()

    def test_concat_mapping_preserves_each_branch_offset(self):
        maps=migrate.transfer_layer19(self.old,self.new)
        cv1=next(m for m in maps if m['module']=='cv1')
        cv2=next(m for m in maps if m['module']=='cv2')
        self.assertEqual(cv1['output_indices'],list(range(14))+list(range(16,30)))
        self.assertEqual(cv2['input_indices'],list(range(14))+list(range(16,30))+list(range(32,46)))
        torch.testing.assert_close(self.new.cv2.conv.weight[:,14],self.old.cv2.conv.weight[:,16],atol=0,rtol=0)

    def test_forward_equals_original_with_discarded_activations_masked(self):
        maps=migrate.transfer_layer19(self.old,self.new);hooks=[]
        for item in maps:
            module=self.old.get_submodule(item['module']);indices=item['output_indices']
            if len(indices)==module.conv.out_channels:continue
            def mask(module,inputs,output,indices=indices):
                gate=output.new_zeros(output.shape[1]);gate[indices]=1
                return output*gate.view(1,-1,1,1)
            hooks.append(module.register_forward_hook(mask))
        with torch.inference_mode():
            x=torch.rand(2,24,11,13)
            torch.testing.assert_close(self.new(x),self.old(x),atol=1e-6,rtol=1e-5)
        for hook in hooks:hook.remove()

    def test_control_is_exact_and_no_bn_statistics_are_reset(self):
        same=C3k2(24,32,n=1,c3k=True,e=.5).eval()
        self.old.cv1.bn.running_mean.fill_(.7);self.old.cv1.bn.num_batches_tracked.fill_(23)
        migrate.transfer_layer19(self.old,same)
        self.assertTrue(all(torch.equal(v,same.state_dict()[k])for k,v in self.old.state_dict().items()))

    def test_refuse_attention_or_changed_interface(self):
        for block in [C3k2(24,32,n=1,c3k=True,e=.4375,attn=True),C3k2(24,16,n=1,c3k=True,e=.4375)]:
            with self.assertRaises(ValueError):migrate.transfer_layer19(self.old,block)


if __name__=='__main__':unittest.main()
