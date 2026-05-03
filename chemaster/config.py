"""配置文件读写 —— ``~/.chemaster/config.yaml``。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml


DEFAULT_CONFIG_DIR = Path(os.environ.get("CHEMASTER_CONFIG_DIR", "")) \
    if os.environ.get("CHEMASTER_CONFIG_DIR") \
    else Path.home() / ".chemaster"

DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"


def repo_root() -> Path:
    """返回仓库根（``config.example.yaml`` 所在目录）。"""
    here = Path(__file__).resolve()
    # chemaster/config.py → 仓库根上溯 2 级
    return here.parent.parent


def init_config(force: bool = False, src: Path | None = None,
                dst: Path | None = None) -> Path:
    """复制 ``config.example.yaml`` 到 ``~/.chemaster/config.yaml``。

    Args:
        force: 已存在时是否覆盖。
        src: 源 example 路径，默认仓库根 ``config.example.yaml``。
        dst: 目标路径，默认 ``~/.chemaster/config.yaml``。

    Returns:
        最终目标路径。

    Raises:
        FileExistsError: 目标已存在且 ``force=False``。
        FileNotFoundError: 源 example 不存在。
    """
    src = src or (repo_root() / "config.example.yaml")
    dst = dst or DEFAULT_CONFIG_PATH

    if not src.exists():
        raise FileNotFoundError(
            f"config.example.yaml not found at {src}. "
            "请确认仓库完整。"
        )

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not force:
        raise FileExistsError(
            f"{dst} 已存在；--force 覆盖，或手工编辑。"
        )
    shutil.copy(src, dst)
    return dst


def load_config(path: Path | None = None) -> dict:
    """读 ``config.yaml``，缺失返回 ``{}``。"""
    p = path or DEFAULT_CONFIG_PATH
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
