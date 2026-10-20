"""Read-only, reviewed single-class YOLO dataset selection."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff'}
SCENES = ('Small', 'Occluded', 'Blurred', 'No Ball')


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def resolve_path(value, base: Path) -> Path:
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def read_yaml(path: Path) -> dict:
    import yaml
    with path.open(encoding='utf-8-sig') as stream:
        result = yaml.safe_load(stream)
    if not isinstance(result, dict):
        raise ValueError(f'数据集配置须为YAML映射：{path}')
    return result


def list_images(entry, root: Path) -> list[Path]:
    result = []
    for value in entry if isinstance(entry, list) else [entry]:
        path = resolve_path(value, root)
        if path.is_dir():
            result.extend(sorted(p.resolve() for p in path.rglob('*') if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()))
        elif path.is_file() and path.suffix.lower() == '.txt':
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if line.strip():
                    result.append(resolve_path(line.strip(), path.parent))
        else:
            raise ValueError(f'集合路径不存在或不是图片目录/名单：{path}')
    if len(set(result)) != len(result):
        raise ValueError('集合中有重复图片路径，请先修正名单。')
    if any(not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES for p in result):
        raise ValueError('图片名单存在缺失文件或非图片文件。')
    if any('\n' in str(p) or '\r' in str(p) or '*' in str(p) for p in result):
        raise ValueError('图片路径不能包含换行或通配符*，以保证流式名单唯一对应。')
    return sorted(result,key=str)


def label_path(image: Path) -> Path:
    parts = list(image.parts)
    positions = [i for i, part in enumerate(parts) if part == 'images']
    if not positions:
        raise ValueError(f'图片路径须遵循 images/… → labels/… 的YOLO目录约定：{image}')
    parts[positions[-1]] = 'labels'
    return Path(*parts).with_suffix('.txt')


def read_boxes(path: Path, width: int, height: int) -> list[list[float]]:
    if not path.is_file():
        raise ValueError(f'缺少label，不能当成无球负样本：{path}')
    boxes = []
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5 or fields[0] != '0':
            raise ValueError(f'只支持0=football的检测框，label格式错误：{path}:{number}')
        x, y, w, h = map(float, fields[1:])
        if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
            raise ValueError(f'label含非有限数或无效宽高：{path}:{number}')
        xyxy = [x-w/2, y-h/2, x+w/2, y+h/2]
        if min(xyxy) < -1e-6 or max(xyxy) > 1+1e-6:
            raise ValueError(f'label越界：{path}:{number}')
        boxes.append([max(0, xyxy[0])*width, max(0, xyxy[1])*height,
                      min(1, xyxy[2])*width, min(1, xyxy[3])*height])
    return boxes


@dataclass
class Sample:
    image: Path
    label: Path
    width: int
    height: int
    gt: list
    flags: dict
    hashes: dict

    def manifest(self):
        return dict(image=str(self.image), label=str(self.label), width=self.width, height=self.height,
                    gt_boxes=len(self.gt), scenes=self.flags, **self.hashes)


@dataclass
class Selection:
    root: Path
    data: Path
    metadata: Path
    samples: list[Sample]
    skipped: list[dict]
    hashes: dict
    available_before_limit: int


def select(data: Path, split: str, metadata: Path | None = None, limit: int | None = None) -> Selection:
    from PIL import Image
    config = read_yaml(data)
    names = config.get('names')
    if not isinstance(names, (dict,list)) or len(names) != 1 or (isinstance(names, dict) and set(map(str, names)) != {'0'}):
        raise ValueError('本工具只评估单类数据集，dataset.yaml须只有0=football。')
    root = resolve_path(config.get('path', '.'), data.parent)
    if not config.get(split):
        raise ValueError(f'dataset.yaml未配置 {split} 集。')
    images = list_images(config[split], root)
    if not images:
        raise ValueError(f'{split} 集为空，不能生成该集合的指标。当前项目Test待独立补采；可显式使用 --split val。')
    metadata = metadata or root/'metadata.csv'
    if not metadata.is_file():
        raise ValueError(f'缺少审核metadata：{metadata}；可用 --metadata 指定。')
    hashes = {'dataset_yaml_sha256': digest(data), 'metadata_sha256': digest(metadata)}
    with metadata.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'图片', 'split', 'annotation_status', 'label_review_required', 'scene_review_required', *SCENES}
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f'metadata缺少字段：{sorted(required-set(reader.fieldnames or []))}')
        rows = {}
        for row in reader:
            if row['图片'] in rows:
                raise ValueError('metadata含重复图片名。')
            rows[row['图片']] = row
    samples, skipped, seen_names = [], [], set()
    for image in images:
        if image.name in seen_names:
            raise ValueError('不同目录含同名图片，无法和metadata唯一关联。')
        seen_names.add(image.name)
        row = rows.get(image.name)
        if row is None:
            raise ValueError(f'图片未登记在metadata：{image}')
        reason = None
        if row['annotation_status'] == 'reviewed_excluded':
            reason = 'reviewed_excluded'
        elif row['label_review_required'] != '0' or row['scene_review_required'] != '0':
            reason = 'review_pending'
        elif row['annotation_status'] not in ('reviewed_annotation', 'negative_confirmed'):
            reason = 'not_confirmed_usable'
        if reason:
            skipped.append(dict(image=str(image), reason=reason))
            continue
        if row['split'] != split:
            raise ValueError(f'metadata.split与实际选择集合不一致：{image.name}')
        if any(row[k] not in ('0', '1') for k in SCENES):
            raise ValueError(f'场景值不是0/1：{image.name}')
        with Image.open(image) as im:
            width, height = im.size
            im.verify()
        label = label_path(image)
        boxes = read_boxes(label, width, height)
        if row['No Ball'] != ('0' if boxes else '1'):
            raise ValueError(f'No Ball与最终label不一致：{image.name}')
        expected = 'reviewed_annotation' if boxes else 'negative_confirmed'
        if row['annotation_status'] != expected:
            raise ValueError(f'审核状态与球框数量不一致：{image.name}')
        samples.append(Sample(image, label, width, height, boxes, {k:int(row[k]) for k in SCENES},
                              {'image_sha256':digest(image), 'label_sha256':digest(label)}))
    available = len(samples)
    if limit is not None:
        samples = samples[:limit]
    if not samples:
        raise ValueError('选定集合没有可用且已完成双项审核的样本。')
    return Selection(root, data, metadata, samples, skipped, hashes, available)


def assert_unchanged(selection: Selection):
    if digest(selection.data) != selection.hashes['dataset_yaml_sha256'] or digest(selection.metadata) != selection.hashes['metadata_sha256']:
        raise RuntimeError('评估期间数据配置或metadata发生变化，结果不作为完整评估发布。')
    for sample in selection.samples:
        if digest(sample.image) != sample.hashes['image_sha256'] or digest(sample.label) != sample.hashes['label_sha256']:
            raise RuntimeError(f'评估期间原图或label变化：{sample.image}')
