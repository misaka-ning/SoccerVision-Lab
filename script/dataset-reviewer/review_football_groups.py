#!/usr/bin/env python3
"""Fixed 50-image review lists; production images, labels and CSV are read-only.

create captures pending rows once, excluding priority rows by default; pass
--include-priority to include them. status/next read current review flags
without moving filenames between groups as the user progresses.
"""
from __future__ import annotations
import argparse
import collections
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(WORKSPACE/'script'))
from common.dataset_config import load_dataset,review_records
FLAGS = ('label_review_required', 'scene_review_required')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_names(path):
    names = [n.strip() for n in path.read_text(encoding='utf-8-sig').splitlines() if n.strip()]
    if not names or len(names) != len(set(names)):
        raise ValueError(f'名单为空或含重复图片：{path}')
    if any('/' in n or '\\' in n or n in ('.', '..') for n in names):
        raise ValueError(f'名单中含非法文件名：{path}')
    return names


def load_rows(dataset):
    raw = (dataset / 'metadata.csv').read_bytes()
    parsed = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
    if not {'图片', *FLAGS}.issubset(parsed.fieldnames or []):
        raise ValueError('metadata.csv 缺少图片名或审核状态字段')
    rows = {}
    for r in parsed:
        if not r['图片'] or r['图片'] in rows or any(r[k] not in ('0', '1') for k in FLAGS):
            raise ValueError('metadata.csv 存在重复图片名或非法审核状态')
        rows[r['图片']] = r
    return raw, rows


def pending(row):
    return any(row[k] == '1' for k in FLAGS)


def frame_key(name, row):
    if row.get('source_video') and row.get('source_frame_idx'):
        return row['source_video'], row['source_frame_idx']
    return ('filename', re.sub(r'_(left|right)(?=\.[^.]+$)', '', name))


def fixed_groups(names, rows, size=50):
    """Pack same-frame units, then fill odd gaps without splitting stereo pairs."""
    units = collections.OrderedDict()
    for n in names:
        units.setdefault(frame_key(n, rows[n]), []).append(n)
    if any(len(u) > 2 for u in units.values()):
        raise ValueError('同帧出现超过两个视角，需先检查来源字段')
    groups = []
    for u in units.values():
        target = next((g for g in groups if sum(map(len, g)) + len(u) <= size), None)
        if target is None:
            target = []
            groups.append(target)
        target.append(u)
    # An earlier odd group can trade one single eye for a later stereo pair.
    # This makes every group except the last exactly 50, keeping each pair whole.
    for i, group in enumerate(groups[:-1]):
        while sum(map(len, group)) < size:
            gap = size - sum(map(len, group))
            donor = next(((g, u) for g in groups[i+1:] for u in g if len(u) <= gap), None)
            if donor:
                g, u = donor
                g.remove(u)
                group.append(u)
            else:
                single = next((u for u in group if len(u) == 1), None)
                donor = next(((g, u) for g in groups[i+1:] for u in g if len(u) == 2), None)
                if gap != 1 or single is None or donor is None:
                    raise ValueError('无法在保持左右目同组的情况下填满分组')
                g, u = donor
                group.remove(single)
                g.remove(u)
                group.append(u)
                g.append(single)
    order = {n: i for i, n in enumerate(names)}
    result = [sorted((n for u in g for n in u), key=order.__getitem__) for g in groups if g]
    if names:
        assert len(result) == math.ceil(len(names) / size)
        assert all(len(g) == size for g in result[:-1])
        assert len(result[-1]) == len(names) - size * (len(result)-1)
    assert sorted(n for g in result for n in g) == sorted(names)
    membership = {n: i for i, g in enumerate(result) for n in g}
    assert all(len({membership[n] for n in u}) == 1 for u in units.values())
    return result


def output_dir(review, batch):
    return review / 'batches' / f'batch-{batch:03d}-remaining-50'


def create(review, dataset, batch, *, include_priority=False):
    out = output_dir(review, batch)
    if out.exists():
        raise ValueError(f'固定分组已存在，保留原组号和名单：{out}')
    batch_path = review / 'batches' / f'batch-{batch:03d}.txt'
    priority_path = review / 'batches' / f'batch-{batch:03d}-priority.txt'
    full = read_names(batch_path)
    priority = set(read_names(priority_path))
    if not priority.issubset(full):
        raise ValueError('疑点名单含本批以外的图片')
    # Only assistant-prechecked batches may be presented for user review.
    proposal_path = review / f'batch-{batch:03d}' / 'proposals.json'
    proposals = json.loads(proposal_path.read_text(encoding='utf-8'))
    if len(proposals) != len(full) or {q['filename'] for q in proposals} != set(full):
        raise ValueError('本批尚无完整的助手逐图预审记录')
    raw, rows = load_rows(dataset)
    missing = set(full) - rows.keys()
    if missing:
        raise ValueError(f'当前 metadata 中缺少 {len(missing)} 张本批图片')
    eligible = full if include_priority else [n for n in full if n not in priority]
    done = [n for n in eligible if not pending(rows[n])]
    selected = [n for n in eligible if pending(rows[n])]
    if not selected:
        scope = '图片' if include_priority else '非疑点图片'
        raise ValueError(f'本批{scope}已全部通过，无需创建分组')
    groups = fixed_groups(selected, rows)
    temporary = Path(tempfile.mkdtemp(prefix=f'.batch-{batch:03d}-groups-', dir=out.parent))
    try:
        manifest_groups = []
        for i, names in enumerate(groups, 1):
            data = ''.join(n+'\n' for n in names).encode('utf-8')
            filename = f'group-{i:03d}.txt'
            (temporary / filename).write_bytes(data)
            manifest_groups.append(dict(group=i, count=len(names), file=filename, sha256=sha(data)))
        priority_pending = sum(pending(rows[n]) for n in priority)
        manifest = dict(batch=batch, created_at_utc=datetime.now(timezone.utc).isoformat(), dataset=str(dataset), group_size=50,
                        selection='all_pending' if include_priority else 'non_priority_pending',
                        include_priority=include_priority,
                        source_metadata_sha256=sha(raw), source_batch_sha256=sha(batch_path.read_bytes()),
                        source_priority_sha256=sha(priority_path.read_bytes()), source_proposals_sha256=sha(proposal_path.read_bytes()),
                        batch_count=len(full), priority_count=len(priority), priority_pending_count=priority_pending,
                        excluded_priority_count=0 if include_priority else len(priority),
                        excluded_priority_pending=0 if include_priority else priority_pending,
                        excluded_already_passed=done, selected_count=len(selected), groups=manifest_groups,
                        policy=('固定快照；包含本批待审疑点；排除创建时两项都已通过的图片；左右目同组；只读正式数据集'
                                if include_priority else
                                '固定快照；排除本批疑点及创建时两项都已通过的图片；左右目同组；只读正式数据集'))
        (temporary / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        if include_priority:
            title = '全部待审图片（含疑点）'
            selection_note = (f'本批 {len(full)} 张；包含本批疑点名单中的待审图片（疑点名单共 {len(priority)} 张，'
                              f'其中创建时仍待审 {priority_pending} 张），排除创建时两项都已通过的 {len(done)} 张。'
                              f'固定收录 **{len(selected)} 张，{len(groups)} 组**；左右目配对不跨组。')
        else:
            title = '其余图片'
            selection_note = (f'本批 {len(full)} 张；排除疑点 {len(priority)} 张，以及其他图片中两项已通过的 {len(done)} 张。'
                              f'剩余 **{len(selected)} 张，{len(groups)} 组**；左右目配对不跨组。'
                              f'疑点里用户保留待定的 {priority_pending} 张继续保留原状态，不混入这些组。')
        guide = f'''# 第 {batch} 批：{title}每组 50 张

固定创建时间：{manifest['created_at_utc']}。

{selection_note}

从仓库根目录运行：

```bash
./script/dataset-reviewer/review_football_batch.sh {batch} --group 1
# 查看各组目前的双项通过数、待球框及待场景数：
./script/dataset-reviewer/review_football_batch.sh {batch} --groups
# 打开第一组仍有待处理项的固定分组：
./script/dataset-reviewer/review_football_batch.sh {batch} --group next
```

`--group 1` 指定启动时打开的组；窗口加载所有固定组，使用“前50张 / 后50张”直接翻页，无需重启。也可改为 2、3……从指定组开始。名单始终固定，审核后不重新分组，文件名不会在组间移动。保存仍写回原始 datasets；此工具只生成名单、只读查询进度，不会通过或重置任何图片。

`next` 按两项审核标志查找首个未全通过组；组内如果保留不确定图片，它会继续指向该组。可指定下一组号继续。不要只按“待 label 审核”筛选，否则会漏掉仅场景待审的图片。

| 组号 | 图片数 |
| --- | ---: |
'''
        guide += ''.join(f'| {i} | {len(g)} |\n' for i, g in enumerate(groups, 1))
        (temporary / 'README.md').write_text(guide, encoding='utf-8')
        if out.exists():
            raise ValueError('另一进程已创建分组，保留其固定名单')
        os.rename(temporary, out)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def progress(review, dataset, batch):
    out = output_dir(review, batch)
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    same_dataset=manifest['dataset']==str(dataset)
    if not same_dataset:
        selected=load_dataset()
        same_dataset=selected['root']==dataset and Path(manifest['dataset']) in selected['review_dataset_aliases']
    if manifest['batch'] != batch or not same_dataset:
        raise ValueError('分组清单对应的数据集或批次不一致')
    _, rows = load_rows(dataset)
    result = []
    seen = set()
    for item in manifest['groups']:
        path = out / item['file']
        if path.name != item['file'] or sha(path.read_bytes()) != item['sha256']:
            raise ValueError('固定分组名单被改动，请先检查 manifest.json')
        names = read_names(path)
        if len(names) != item['count'] or set(names) & seen or not set(names).issubset(rows):
            raise ValueError('分组图片数量、重复项或当前 metadata 不一致')
        seen.update(names)
        pending_label = sum(rows[n][FLAGS[0]] == '1' for n in names)
        pending_scene = sum(rows[n][FLAGS[1]] == '1' for n in names)
        complete = sum(not pending(rows[n]) for n in names)
        result.append(dict(group=item['group'], count=len(names), passed=complete, pending=len(names)-complete,
                           label_pending=pending_label, scene_pending=pending_scene))
    if len(seen) != manifest['selected_count']:
        raise ValueError('固定分组总数不匹配')
    return result


def gallery_list(review, dataset, batch):
    """Join immutable groups for Qt's in-window 50-image pagination."""
    progress(review, dataset, batch)  # Validate every source list and current row.
    out = output_dir(review, batch)
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    names = [n for g in manifest['groups'] for n in read_names(out / g['file'])]
    # Qt pages are 50 images. Keep their boundaries equal to fixed group files.
    if any(g['count'] != 50 for g in manifest['groups'][:-1]):
        raise ValueError('固定分组的分页边界不是50张')
    data = ''.join(n+'\n' for n in names).encode('utf-8')
    path = out / 'all-groups.txt'
    try:
        with path.open('xb') as stream:
            stream.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError('平铺总名单与固定分组不一致，请先检查 all-groups.txt')
    return path.resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['create', 'status', 'next', 'gallery-list'])
    parser.add_argument('--batch', type=int, choices=range(1, 10), required=True)
    parser.add_argument('--include-priority', action='store_true',
                        help='仅用于 create：将本批疑点中的待审图片也纳入固定分组')
    args = parser.parse_args()
    if args.include_priority and args.command != 'create':
        parser.error('--include-priority 仅可用于 create')
    try:
        selected=load_dataset()
        REVIEW,DATASET=review_records(selected),selected['root']
        if args.command == 'create':
            m = create(REVIEW, DATASET, args.batch, include_priority=args.include_priority)
            print(json.dumps({k:m[k] for k in ['batch','selection','selected_count','priority_count','excluded_priority_count','excluded_already_passed','groups']}, ensure_ascii=False))
        elif args.command == 'gallery-list':
            print(gallery_list(REVIEW, DATASET, args.batch))
        else:
            rows = progress(REVIEW, DATASET, args.batch)
            if args.command == 'next':
                item = next((r for r in rows if r['pending']), None)
                if item:
                    print(item['group'])
            else:
                manifest = json.loads((output_dir(REVIEW, args.batch) / 'manifest.json').read_text(encoding='utf-8'))
                scope = '全部待审样本（含疑点）' if manifest.get('selection') == 'all_pending' else '普通样本'
                print(f'第 {args.batch} 批{scope}固定分组（50 张/组，最后一组为余数）')
                print('组号  图片数  两项已通过  待球框  待场景')
                for r in rows:
                    print(f"{r['group']:>4}  {r['count']:>6}  {r['passed']:>10}  {r['label_pending']:>6}  {r['scene_pending']:>6}")
                print(f"共 {sum(r['count'] for r in rows)} 张，{len(rows)} 组；两项已通过 {sum(r['passed'] for r in rows)} 张。")
        return 0
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f'分组工具：{exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
