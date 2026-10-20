#!/usr/bin/env python3
"""Train the project's football detector with a YAML configuration."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config" / "train.yaml"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common.dataset_config import load_dataset, materialize_yaml


def project_path(value: str) -> Path:
    """Resolve training paths from the repository, regardless of the current cwd."""
    path = Path(value).expanduser()
    return (PROJECT_ROOT / path).resolve()


def require_file(value: str, suffixes: tuple[str, ...]) -> str:
    path = project_path(value)
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"文件类型应为 {', '.join(suffixes)}：{path}")
    if not path.is_file():
        raise ValueError(f"文件不存在：{path}")
    return str(path)


def read_config(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("缺少 PyYAML，请先安装 requirements.txt 中的依赖。") from exc
    try:
        with path.open(encoding="utf-8-sig") as stream:
            config = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 格式错误：{path}\n{exc}") from exc
    if not isinstance(config, dict) or not all(isinstance(key, str) for key in config):
        raise ValueError(f"配置必须是 YAML 键值映射：{path}")
    return config


def build_plan(args: argparse.Namespace) -> tuple[str, dict]:
    overrides = {
        key: getattr(args, key)
        for key in ("data", "epochs", "batch", "imgsz", "device", "name")
        if getattr(args, key) is not None
    }
    if args.resume:
        if args.config is not None or args.dataset_config or args.dataset_version or set(overrides) - {"device"}:
            raise ValueError("续训读取 checkpoint 原参数；仅支持额外覆盖 --device。")
        model = require_file(args.resume, (".pt",))
        return model, {"resume": True, **overrides}

    config_path = Path(args.config).expanduser().resolve() if args.config else DEFAULT_CONFIG
    config = read_config(config_path)
    config.update(overrides)
    if not config.get('data'):
        selected=load_dataset(args.dataset_config,args.dataset_version,root=PROJECT_ROOT)
        config['data']=str(materialize_yaml(selected))
        print(f'数据版本：{selected["version"]}；目录：{selected["root"]}')
    elif args.dataset_config or args.dataset_version:
        raise ValueError('显式data不能与--dataset-config/--dataset-version同时使用；将训练配置data设为null以使用共享选择。')
    if config.get("task", "detect") != "detect" or config.get("mode", "train") != "train":
        raise ValueError("本脚本只支持 task: detect、mode: train。")
    if config.get("resume") or config.get("cfg"):
        raise ValueError("请使用 --resume 指定续训权重；训练参数直接写在此配置中。")
    for key in ("model", "data", "project"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"配置必须提供非空字符串：{key}")
    model = require_file(config.pop("model"), (".pt", ".yaml", ".yml"))
    config["data"] = require_file(config["data"], (".yaml", ".yml"))
    dataset = read_config(Path(config["data"]))
    if not all(dataset.get(key) for key in ("train", "val", "names")):
        raise ValueError("数据集 YAML 必须包含非空 train、val 和 names。")
    config["project"] = str(project_path(config["project"]))
    if isinstance(config.get("pretrained"), str):
        config["pretrained"] = require_file(config["pretrained"], (".pt",))
    for key in ("epochs", "imgsz"):
        value = config.get(key)
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError(f"{key} 必须为正整数。")
    batch = config.get("batch")
    if batch is not None and (
        type(batch) not in (int, float)
        or not (batch == -1 or (type(batch) is int and batch > 0) or 0 < batch < 1)
    ):
        raise ValueError("batch 必须为正整数、-1（自动）或 0 到 1 之间的显存比例。")
    return model, config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="训练 YAML 路径（相对当前目录）；默认 config/train.yaml")
    parser.add_argument("--data", help="覆盖数据集 YAML（相对仓库根目录）")
    parser.add_argument('--dataset-config',help='覆盖script/config.yaml，相对仓库根目录')
    parser.add_argument('--dataset-version',help='本次覆盖共享配置中的数据版本')
    parser.add_argument("--resume", metavar="LAST_PT", help="从指定 checkpoint 续训（相对仓库根目录）")
    parser.add_argument("--epochs", type=int, help="覆盖训练轮数")
    parser.add_argument("--batch", type=int, help="覆盖 batch size；-1 为自动")
    parser.add_argument("--imgsz", type=int, help="覆盖输入尺寸")
    parser.add_argument("--device", help="设备，例如 0、0,1 或 cpu；默认自动选择")
    parser.add_argument("--name", help="覆盖实验名称")
    parser.add_argument("--dry-run", action="store_true", help="检查文件和基本配置并打印参数，不加载模型")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        model_path, train_args = build_plan(args)
    except (ValueError, OSError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    print(f"模型：{model_path}")
    print(f"训练参数：{train_args}")
    print("提示：训练不按 metadata.csv 审核标记筛选样本，请确认数据已审核。")
    if args.dry_run:
        print("预检查通过；尚未验证模型兼容性、图片/标注内容或训练设备。")
        return 0
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        print(f"无法导入训练依赖：{exc}；请安装 requirements.txt 中的依赖。", file=sys.stderr)
        return 2
    model = YOLO(model_path, task="detect")
    model.train(**train_args)
    print(f"训练结果：{model.trainer.save_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
