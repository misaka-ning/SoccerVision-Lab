#!/usr/bin/env python3
"""Fail early on a missing evaluation dependency or incompatible CUDA runtime."""
import argparse
import importlib.metadata
import re
import sys


def check(device):
    for name in ('torch','torchvision','ultralytics','numpy','matplotlib','Pillow','PyYAML'):
        importlib.metadata.version(name)
    import torch
    if device == 'cpu':
        return f'运行环境检查通过：PyTorch {torch.__version__} / CPU'
    if torch.version.cuda is None:
        raise ValueError(f'当前Python中的PyTorch {torch.__version__} 是CPU版，不能使用GPU。'
                         '请用FOOTBALL_EVAL_PYTHON指定CUDA环境；本机已有环境为'
                         '~/.local/share/vision-studio/gpu-runtime/bin/python。')
    if not torch.cuda.is_available():
        raise ValueError('当前环境支持CUDA，但无法访问GPU；请检查NVIDIA驱动和CUDA_VISIBLE_DEVICES，'
                         '并在本机终端运行nvidia-smi确认显卡可见。')
    value=device.removeprefix('cuda:')
    if not re.fullmatch(r'\d+(,\d+)*',value):
        raise ValueError('设备应为cpu或GPU编号，例如--device 0。')
    indices=[int(v) for v in value.split(',')]
    count=torch.cuda.device_count()
    if any(i>=count for i in indices):
        raise ValueError(f'请求GPU {value}，但当前只可见{count}张GPU。')
    names=', '.join(f'{i}: {torch.cuda.get_device_name(i)}' for i in indices)
    return f'运行环境检查通过：PyTorch {torch.__version__} / CUDA {torch.version.cuda} / {names}'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',default='0')
    args=parser.parse_args()
    try:
        print(check(args.device))
        return 0
    except (ImportError,importlib.metadata.PackageNotFoundError,ValueError,RuntimeError) as exc:
        print(f'评估环境检查失败：{exc}',file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
