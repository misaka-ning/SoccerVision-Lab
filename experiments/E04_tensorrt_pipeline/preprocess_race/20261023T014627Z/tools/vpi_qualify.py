"""One isolated qualification process. No TensorRT/Graph context is created."""
import json
from pathlib import Path
import sys
import cv2
from vpi_probe import probe
image=cv2.imread(sys.argv[1],cv2.IMREAD_COLOR)
if image is None:raise RuntimeError('Unreadable fixed Val image')
r=min(640/image.shape[0],640/image.shape[1])
report=probe(image,(round(image.shape[1]*r),round(image.shape[0]*r)))
Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
if report['status'] in ('synchronization_failed','prior_synchronization_failed'):raise SystemExit(2)
