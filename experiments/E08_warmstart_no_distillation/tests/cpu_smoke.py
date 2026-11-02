"""Review-only synthetic CPU smoke; never qualifies a formal run's GPU preflight."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('e08_cpu_smoke', HERE/'e08.py')
e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--init', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    run = Path(a.output).resolve()
    initial = Path(a.init).resolve()
    if e.sha(initial) != e.STUDENT_SHA:
        raise ValueError('real E05 best SHA required for the initialization audit')
    run.mkdir(parents=True, exist_ok=False)
    os.environ.update(YOLO_CONFIG_DIR=str(run/'runtime/yolo'), MPLCONFIGDIR=str(run/'runtime/mpl'),
                      YOLO_OFFLINE='true', YOLO_AUTOINSTALL='false', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
    import torch
    import ultralytics
    import yaml
    from PIL import Image, ImageDraw
    from ultralytics.models.yolo.detect import DetectionTrainer
    torch.set_num_threads(2)
    if ultralytics.__version__ != '8.4.173' or not torch.__version__.startswith('2.9.1'):
        raise ValueError('use pinned environment')
    shutil.copy2(initial, run/'init.pt')
    for split in ('train', 'val'):
        for i in range(8):
            image = run/'synthetic/images'/split/f'{i}.png'; image.parent.mkdir(parents=True, exist_ok=True)
            label = run/'synthetic/labels'/split/f'{i}.txt'; label.parent.mkdir(parents=True, exist_ok=True)
            im = Image.new('RGB', (640, 640), (25, 95+i, 30))
            ImageDraw.Draw(im).ellipse((280, 280, 360, 360), fill=(240, 240, 240))
            im.save(image); label.write_text('0 0.5 0.5 0.125 0.125\n')
    (run/'dataset.train-val.yaml').write_text(yaml.safe_dump(dict(path=str(run/'synthetic'),
        train='images/train', val='images/val', nc=1, names={0: 'football'})))
    config = e.config_for(run)
    config.update(device='cpu', workers=0, plots=False, save_period=-1, project=str(run/'smoke'))
    before = e.sha(run/'init.pt')
    with e.control.no_teacher_load([run/'init.pt'], run/'smoke') as loads:
        result = e.one_step(run, config, {'train': 8, 'val': 8}, DetectionTrainer, torch)
    if e.sha(run/'init.pt') != before:
        raise ValueError('smoke changed formal initialization')
    result.update(status='passed', scope='synthetic CPU only; formal Train/Val GPU smoke not_run',
                  torch=torch.__version__, ultralytics=ultralytics.__version__,
                  init_sha256=before, initialization_unchanged=True, checkpoint_load_audit=loads,
                  changes_from_formal=dict(device='cpu', workers=0, plots=False, save_period=-1,
                                           dataset='8 synthetic Train + 8 synthetic Val', amp_effective=False))
    e.dump(run/'cpu_smoke.json', result)
    print(run/'cpu_smoke.json')


if __name__ == '__main__': main()
