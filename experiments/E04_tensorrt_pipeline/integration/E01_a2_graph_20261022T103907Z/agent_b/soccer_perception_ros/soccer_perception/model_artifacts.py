"""Explicit, serialized TensorRT export with reusable artifact metadata."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _nonempty(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f'Model file missing or empty: {path}. Run bash deployment/build_engine.sh.')


def _engine_path(detector) -> Path:
    path = detector.model_path if detector.model_path.suffix.lower() == '.engine' else (
        detector.engine_path or detector.model_path.with_suffix('.engine'))
    path = path.expanduser().resolve()
    if path.suffix.lower() != '.engine':
        raise ValueError(f'TensorRT destination must end in .engine: {path}')
    return path


def _signature(detector) -> dict:
    _nonempty(detector.model_path)
    return {
        'source_sha256': sha256(detector.model_path),
        'imgsz': detector.imgsz,
        'batch': detector.trt_batch,
        'dynamic': detector.trt_dynamic,
        'requested_half': detector.half,
        'device': str(detector.device),
    }


def _metadata_path(engine: Path) -> Path:
    return engine.with_suffix(engine.suffix + '.json')


def _validate(detector, engine: Path) -> None:
    _nonempty(engine)
    metadata = _metadata_path(engine)
    if not metadata.is_file():
        raise RuntimeError(f'Existing engine has no build metadata: {engine}. '
                           'After verifying its weights/settings, run bash deployment/build_engine.sh '
                           '--adopt-existing; or explicitly rebuild with --force.')
    try:
        data = json.loads(metadata.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise RuntimeError(f'Invalid engine metadata: {metadata}; explicitly rebuild with --force.') from exc
    if (not isinstance(data, dict) or data.get('signature') != _signature(detector)
            or data.get('engine_sha256') != sha256(engine)):
        raise RuntimeError(f'Engine weights/settings/content changed: {engine}. '
                           'Run bash deployment/build_engine.sh --force to rebuild explicitly.')


def require_engine(detector) -> Path:
    engine = _engine_path(detector)
    # An explicitly configured .engine can be supplied without its source PT.
    if detector.model_path.suffix.lower() == '.engine':
        _nonempty(engine)
    else:
        _validate(detector, engine)
    print(f'Using TensorRT engine: {engine}', file=sys.stderr)
    return engine


@contextmanager
def _build_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.engine-build.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f'Another model export is running in {directory}; wait for it to finish.') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _write_metadata(engine: Path, signature: dict, *, adopted: bool) -> None:
    data = {'signature': signature, 'engine_sha256': sha256(engine), 'adopted': adopted}
    with tempfile.NamedTemporaryFile(mode='w', dir=engine.parent, delete=False, encoding='utf-8') as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, indent=2)
        stream.write('\n')
    try:
        os.replace(temporary, _metadata_path(engine))
    finally:
        temporary.unlink(missing_ok=True)


def build_engine(detector, yolo_cls, *, force=False, adopt_existing=False) -> Path:
    if force and adopt_existing:
        raise ValueError('--force and --adopt-existing are mutually exclusive')
    engine = _engine_path(detector)
    if detector.model_path.suffix.lower() == '.engine':
        if force or adopt_existing:
            raise ValueError('Configure yolo_model as the source .pt to build/adopt an engine.')
        return require_engine(detector)
    if detector.model_path.suffix.lower() != '.pt':
        raise ValueError('TensorRT export requires a .pt yolo_model.')
    model = detector.model_path.resolve()
    _nonempty(model)
    with model.open('rb') as stream:
        if stream.read(128).startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise ValueError(f'Model is a Git LFS pointer: {model}; restore the real weights first.')
    # Lock beside PT because exports from that PT share an ONNX destination.
    with _build_lock(model.parent):
        signature = _signature(detector)
        if adopt_existing:
            _nonempty(engine)
            if _metadata_path(engine).exists():
                _validate(detector, engine)
            else:
                _write_metadata(engine, signature, adopted=True)
            return engine
        if engine.exists() and not force:
            _validate(detector, engine)
            print(f'Reusing TensorRT engine: {engine}', file=sys.stderr)
            return engine
        if engine.exists() and not engine.is_file():
            raise RuntimeError(f'Engine path is not a file: {engine}')
        engine.parent.mkdir(parents=True, exist_ok=True)
        # Export in a staging directory: failures never damage existing artifacts.
        with tempfile.TemporaryDirectory(prefix='.export-', dir=model.parent) as directory:
            staged_model = Path(directory) / model.name
            shutil.copyfile(model, staged_model)
            kwargs = dict(format='engine', imgsz=detector.imgsz, batch=detector.trt_batch,
                          half=detector._trt_export_half(), dynamic=detector.trt_dynamic,
                          simplify=False, device=detector._trt_export_device())
            if detector.trt_workspace_gb is not None:
                kwargs['workspace'] = detector.trt_workspace_gb
            print(f'Exporting {model} -> {engine}', file=sys.stderr)
            exported = Path(yolo_cls(str(staged_model)).export(**kwargs)).resolve()
            _nonempty(exported)
            if exported.parent != Path(directory).resolve():
                raise RuntimeError(f'Exporter returned an unexpected destination: {exported}')
            onnx = staged_model.with_suffix('.onnx')
            destination = model.with_suffix('.onnx')
            if onnx.is_file():
                _nonempty(onnx)
                if destination.exists() and not force and sha256(onnx) != sha256(destination):
                    raise RuntimeError(f'Existing ONNX differs: {destination}. '
                                       'Use --force to explicitly replace it; existing files were preserved.')
            # Publish on the destination filesystem so a custom engine path can be on another disk.
            with tempfile.NamedTemporaryFile(dir=engine.parent, delete=False) as stream:
                staged_engine = Path(stream.name)
            try:
                shutil.copyfile(exported, staged_engine)
                if onnx.is_file():
                    os.replace(onnx, destination)
                os.replace(staged_engine, engine)
                _write_metadata(engine, signature, adopted=False)
            finally:
                staged_engine.unlink(missing_ok=True)
        return engine
