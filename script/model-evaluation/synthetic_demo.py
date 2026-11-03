"""CPU-only synthetic operating-point demonstration; no model or dataset I/O."""
from __future__ import annotations

import json

from eval_metrics import operating, prepare


def synthetic_records():
    """Four invented images, two GT balls; boxes use xyxy coordinates."""
    return prepare([
        dict(image='duplicate', gt=[[0, 0, 10, 10]],
             boxes=[[0, 0, 10, 10], [0, 0, 9, 10]], scores=[.4, .9]),
        dict(image='weak_ball', gt=[[20, 20, 30, 30]],
             boxes=[[20, 20, 30, 30]], scores=[.4]),
        dict(image='no_ball_false_alarm', gt=[],
             boxes=[[1, 1, 3, 3], [4, 4, 6, 6]], scores=[.6, .4]),
        dict(image='no_ball_clean', gt=[], boxes=[], scores=[]),
    ])


def demo():
    records = synthetic_records()
    return {
        'label': '合成演示：非模型成绩，非性能基准',
        'description': '代码生成4张虚拟图片的框；不执行推理、NMS或AP计算。',
        'operating_points': [operating(records, confidence, .5)
                             for confidence in (.25, .5, .75)],
    }


if __name__ == '__main__':
    print(json.dumps(demo(), ensure_ascii=False, indent=2, allow_nan=False))
