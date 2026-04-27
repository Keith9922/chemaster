"""pytest 全局 fixture。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """返回 tests/fixtures/ 路径。"""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_runs_dir(tmp_path: Path) -> Path:
    """临时 runs/ 目录（每个测试隔离）。"""
    d = tmp_path / "runs"
    d.mkdir()
    return d
