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


# psi4.core.get_active_wavefunction is a C-extension attribute that
# unittest.mock cannot create with `create=True` consistently across psi4
# versions. We pre-attach a noop attribute at import time so per-test patches
# can replace it cleanly. See PITFALLS §8 (rdkit-before-psi4 segfault) for why
# the production code has to use this fallback path.
def _ensure_psi4_core_attrs() -> None:
    try:
        import psi4
    except ImportError:
        return
    if not hasattr(psi4.core, "get_active_wavefunction"):
        psi4.core.get_active_wavefunction = lambda: None  # type: ignore[attr-defined]


_ensure_psi4_core_attrs()
