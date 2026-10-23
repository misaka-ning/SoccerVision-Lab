"""CPU-only source/install/config identity checks; never instantiate a model."""
import hashlib
import json
from pathlib import Path
import sys

stage=Path(__file__).resolve().parent
project=Path('/home/nvidia/soccer_backend_tensorrt')
manifest=json.loads((stage/'manifest.json').read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for item in manifest:
    assert digest(project/item['path'])==item['sha256'],item['path']
import soccer_perception
from soccer_perception.ros.node import config_from_ros_params
package=Path(soccer_perception.__file__).resolve().parent
assert str(package).startswith(str(project/'install/')),str(package)
code_checks=[]
for item in manifest:
    relative=Path(item['path'])
    try: sub=relative.relative_to('soccer_perception_ros/soccer_perception')
    except ValueError:continue
    assert digest(package/sub)==item['sha256'],str(sub)
    code_checks.append(str(sub))
share=project/'install/soccer_perception_ros/share/soccer_perception_ros'
for source in (project/'soccer_perception_ros/config').glob('*.yaml'):
    assert digest(source)==digest(share/'config'/source.name),source.name
config=config_from_ros_params()
assert config.yolo_optimization=='a2_graph'
expected=project/'soccer_perception_ros/models/E01_baseline.engine'
assert config.yolo_model==expected and config.yolo_engine_path==expected
assert (config.imgsz,config.yolo_trt_batch,config.yolo_trt_dynamic)==(640,2,False)
assert config.det_conf==0.45 and config.yolo_class_ids=='0'
assert config.yolo_top_k==5 and config.deploy_packet_rate_hz==50
engine_hash=digest(expected)
assert engine_hash=='98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348'
weight_hash=digest(expected.with_suffix('.pt'))
assert weight_hash=='285c198aff043fe7e7486515dbdc1a2cc02db5daf9a0f55f8ce3c6cabf2743ac'
with expected.open('rb') as handle:
    metadata_length=int.from_bytes(handle.read(4),'little')
    assert 0<metadata_length<1000000
    metadata=json.loads(handle.read(metadata_length))
result=dict(python=sys.executable,installed_package=str(package),installed_code_matches=code_checks,
            config=dict(model=str(config.yolo_model),optimization=config.yolo_optimization,
                        conf=config.det_conf,class_ids=config.yolo_class_ids,top_k=config.yolo_top_k,
                        imgsz=config.imgsz,batch=config.yolo_trt_batch,publish_limit_hz=config.deploy_packet_rate_hz),
            engine_sha256=engine_hash,weight_sha256=weight_hash,engine_metadata=metadata,
            model_instantiated=False,production_started=False,graph_capture_tested_in_this_step=False)
(stage/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
