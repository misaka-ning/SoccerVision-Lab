"""Explicit opt-in and backend initialization regression checks."""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from soccer_perception.adapters.optimization import experimental_predictor_class
from soccer_perception.adapters.yolo import YoloBallDetector

class OptimizationIntegrationTests(unittest.TestCase):
 def test_default_needs_no_predictor_override(self):
  with patch.dict(os.environ,{},clear=True):
   self.assertIsNone(experimental_predictor_class())
 def test_misspelled_or_unsafe_combinations_fail(self):
  for setting in [{'SOCCER_YOLO_PREPROCESS':'ruse'},{'SOCCER_YOLO_POSTPROCESS':'single'},{'SOCCER_YOLO_NMS':'numpy'}]:
   with self.subTest(setting=setting),patch.dict(os.environ,setting,clear=True),self.assertRaises(ValueError):experimental_predictor_class()
 def check_setup(self,extension):
  seen={}
  class Predictor:
   def __init__(self,overrides,_callbacks):seen.update(overrides);self.ready=False
   def setup_model(self,model,verbose):self.ready=True
  class Model:
   def __init__(self,*args,**kwargs):self.overrides={'task':'detect'};self.callbacks={};self.model='backend';self.predictor=None
   @property
   def names(self):
    if self.predictor is not None:assert self.predictor.ready
    return {0:'football'}
  module=types.ModuleType('ultralytics');module.YOLO=Model
  detector=YoloBallDetector(Path('test'+extension),.45,640,'cpu',[0],False)
  with patch.object(detector, '_prepare_model_path', return_value=Path('test'+extension)),patch.dict(sys.modules,{'ultralytics':module}),patch('soccer_perception.adapters.yolo._install_torchvision_nms_fallback'),patch('soccer_perception.adapters.optimization.experimental_predictor_class',return_value=Predictor):
   detector.load()
  self.assertEqual(seen['imgsz'],640);self.assertEqual(seen['conf'],.45);self.assertEqual(seen['classes'],[0]);self.assertFalse(seen['verbose'])
  self.assertEqual(detector.names,{0:'football'})
  return seen
 def test_engine_keeps_binding_precision(self):
  seen=self.check_setup('.engine');self.assertNotIn('half',seen);self.assertNotIn('device',seen)
 def test_pt_initialization_honors_requested_device_and_precision(self):
  seen=self.check_setup('.pt');self.assertEqual(seen['device'],'cpu');self.assertFalse(seen['half'])
