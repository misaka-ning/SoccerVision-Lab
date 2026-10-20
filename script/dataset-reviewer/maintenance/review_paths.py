"""Keep reusable review code separate from historical audit records."""
from pathlib import Path
import sys

PRODUCT = Path(__file__).resolve().parents[1]
WORKSPACE = PRODUCT.parents[1]
RECORDS = WORKSPACE / 'dataset_processing'
LOCK_RUNNER = PRODUCT / 'build/release/qt_review_lock_runner'
sys.path.insert(0,str(WORKSPACE/'script'))
from common.dataset_config import load_dataset,review_records


def current_dataset():
    return load_dataset()['root']
