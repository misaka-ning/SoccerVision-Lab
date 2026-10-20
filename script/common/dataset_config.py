#!/usr/bin/env python3
"""Read the shared dataset selection afresh on every invocation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def load_dataset(config=None, version=None, *, root=ROOT):
    """Paths in YAML are relative to the repository, never the caller's cwd."""
    root = Path(root).resolve()
    path = Path(config or os.environ.get('FOOTBALL_DATASET_CONFIG') or root/'script/config.yaml').expanduser()
    path = (root/path).resolve()
    try:
        import yaml
    except ImportError as exc:
        raise ValueError('读取共享配置需要PyYAML；本机请使用 /opt/VisionStudio/runtime/bin/python。') from exc
    try:
        cfg = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    except yaml.YAMLError as exc:
        raise ValueError(f'共享配置YAML格式错误：{path}：{exc}') from exc
    if not isinstance(cfg, dict) or not isinstance(cfg.get('datasets'), dict):
        raise ValueError(f'共享配置须包含dataset_version和datasets映射：{path}')
    name = version if version is not None else cfg.get('dataset_version')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
        raise ValueError('dataset_version须为版本名，例如v0、v1。')
    entry = cfg['datasets'].get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get('root'), str) or not entry['root'].strip():
        raise ValueError(f'数据集版本未配置或root为空：{name}')
    def resolve(value):
        return (root/Path(value).expanduser()).resolve()
    data = resolve(entry['root'])
    if not data.is_dir() or not (data/'metadata.csv').is_file():
        raise ValueError(f'版本{name}缺少数据目录或metadata.csv：{data}')
    return dict(version=name,root=data,metadata=data/'metadata.csv',config=path,repo_root=root,
                source_version=entry.get('source_version'),manifest_id=entry.get('manifest_id'),
                review_dataset_aliases=[resolve(p) for p in entry.get('review_dataset_aliases',[])],
                review_records=resolve(entry['review_records']) if entry.get('review_records') else None)


def materialize_yaml(dataset):
    """Build a local, directory-based YOLO view; leave frozen YAML/lists alone.

    Both current versions' images/{train,val,test} exactly match their formal
    splits. Reserved/buffer/excluded directories are never included.
    """
    data = dataset['root']
    for split in ('train','val','test'):
        if not (data/'images'/split).is_dir() or not (data/'labels'/split).is_dir():
            raise ValueError(f'版本{dataset["version"]}缺少images/labels/{split}目录：{data}')
    output = dataset['repo_root']/'experiments/configs/datasets'/f'{dataset["version"]}.dataset.yaml'
    # Refuse symlinked output paths rather than writing into a source dataset.
    for item in (output,*output.parents):
        if item.is_symlink():
            raise ValueError(f'运行配置输出路径不能是软链接：{item}')
        if item == dataset['repo_root']:
            break
    if output == data or data in output.parents:
        raise ValueError('运行配置必须放在原数据集之外。')
    content = ('# Generated from script/config.yaml at runtime; do not edit.\n'
               f'# Dataset version: {dataset["version"]}\n'
               'path: '+json.dumps(str(data),ensure_ascii=False)+'\n'
               'train: images/train\nval: images/val\ntest: images/test\nnc: 1\nnames:\n  0: football\n')
    if not output.is_file() or output.read_text(encoding='utf-8') != content:
        output.parent.mkdir(parents=True,exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,delete=False) as stream:
                temp = Path(stream.name)
                stream.write(content)
            os.replace(temp,output)
        finally:
            if temp is not None:temp.unlink(missing_ok=True)
    return output


def review_records(dataset):
    path = dataset['review_records']
    if path is None or not (path/'batches').is_dir():
        raise ValueError(f'版本{dataset["version"]}尚未配置/建立固定审核批次；请用review_dataset.sh打开完整数据集。')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--version')
    parser.add_argument('--field',choices=['root','metadata','version','review_records','dataset_yaml','json'],default='json')
    args = parser.parse_args()
    try:
        d = load_dataset(args.config,args.version)
        value = materialize_yaml(d) if args.field == 'dataset_yaml' else review_records(d) if args.field == 'review_records' else d if args.field == 'json' else d[args.field]
        print(json.dumps(value,default=str,ensure_ascii=False) if isinstance(value,dict) else value)
        return 0
    except (OSError,ValueError,TypeError) as exc:
        print(f'数据集配置错误：{exc}',file=sys.stderr)
        return 2


if __name__ == '__main__':raise SystemExit(main())
