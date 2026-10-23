#!/usr/bin/env python3
"""Freeze native stereo Val pairs referenced by E03; never scan Train/Test."""
import argparse
import json
from pathlib import Path
import re
import struct
import tarfile

from audit_robot import sha256, write_json


def png_hw(path):
    with path.open('rb') as stream:
        header = stream.read(24)
    if header[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Expected native PNG: ' + str(path))
    width, height = struct.unpack('>II', header[16:24])
    return [height, width]


def val_file(path, base):
    path, base = path.resolve(), base.resolve()
    if path.parent != base or not path.is_file():
        raise ValueError('Expected an existing direct Val file: ' + str(path))
    return path


def image_record(name, workspace, known):
    base = workspace / 'datasets/v1'
    image = val_file(base / 'images/val' / name, base / 'images/val')
    label = val_file(base / 'labels/val' / (image.stem + '.txt'), base / 'labels/val')
    result = dict(name=name, image_source=str(image), image_sha256=sha256(image),
                  label_source=str(label), label_sha256=sha256(label), original_hw=png_hw(image))
    if name in known:
        for key in ['image_sha256', 'label_sha256']:
            if known[name][key] != result[key]:
                raise ValueError('Frozen E03 Val content changed: ' + name + ' ' + key)
        result['known_flags'] = known[name]['flags']
    else:
        result['known_flags'] = None
    result['label_count'] = len(label.read_text().splitlines())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--e03-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    manifest = json.loads((args.e03_run / 'val64_manifest.json').read_text())
    if manifest.get('split') != 'val' or manifest.get('test_accessed') is not False:
        raise ValueError('Only the frozen E03 Val manifest is allowed')
    known = {x['name']: x for x in manifest['images']}
    # Verify all 64 original files even if a stereo counterpart is unavailable.
    for name in known:
        image_record(name, args.workspace, known)
    stems = []
    for name in known:
        match = re.fullmatch(r'(.+)_(left|right)\.png', name)
        if not match:
            raise ValueError('Unexpected stereo name: ' + name)
        if match.group(1) not in stems:
            stems.append(match.group(1))
    perf = json.loads((args.e03_run / 'inputs/offline_pair.json').read_text())
    perf_stem = re.fullmatch(r'(.+)_left\.png', perf['names'][0]).group(1)
    if perf_stem not in stems:
        stems.insert(0, perf_stem)
    pairs, skipped, images = [], [], {}
    for stem in stems:
        names = [stem + '_left.png', stem + '_right.png']
        if not all((args.workspace / 'datasets/v1/images/val' / name).is_file() for name in names):
            skipped.append(dict(pair_key=stem, reason='A counterpart is absent from Val; no other split searched'))
            continue
        records = [image_record(name, args.workspace, known) for name in names]
        for item in records:
            images[item['name']] = item
        pairs.append(dict(pair_key=stem, left=names[0], right=names[1],
                          no_ball_labels=[x['label_count'] == 0 for x in records],
                          label_asymmetric=(records[0]['label_count'] == 0) != (records[1]['label_count'] == 0)))
    if perf_stem not in {x['pair_key'] for x in pairs}:
        raise ValueError('E03 fixed performance pair must still be present in Val')
    for side in ['left', 'right']:
        copied = args.e03_run / ('offline_' + side + '.png')
        original = images[perf_stem + '_' + side + '.png']
        if sha256(copied) != original['image_sha256']:
            raise ValueError('E03 fixed replay pair content changed')
    args.output.mkdir(parents=True, exist_ok=False)
    result = dict(split='val', test_accessed=False, e03_original_images_verified=len(known),
                  performance_pair=perf_stem, pairs=pairs, images=list(images.values()), skipped_pairs=skipped,
                  golden_reference='not_generated',
                  timestamp_policy='Replay timestamps and frame IDs will be explicit; original capture timestamps unavailable',
                  coverage_note='Flags inherited only where present in E03. NMS boundary/overlap synthetic cases will be separate from model Val coverage.')
    write_json(args.output / 'cases.json', result)
    bundle = args.output / 'val_cases.tar.gz'
    with tarfile.open(bundle, 'x:gz') as archive:
        archive.add(args.output / 'cases.json', arcname='cases.json')
        for name, item in images.items():
            archive.add(item['image_source'], arcname='images/' + name)
            archive.add(item['label_source'], arcname='labels/' + Path(item['label_source']).name)
    write_json(args.output / 'bundle.json', dict(path=str(bundle), sha256=sha256(bundle),
                    bytes=bundle.stat().st_size, pairs=len(pairs), images=len(images)))
    print(json.dumps(dict(pairs=len(pairs), images=len(images), skipped=len(skipped), bundle=str(bundle))))


if __name__ == '__main__':
    main()
