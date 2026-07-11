"""pytest 全局 fixture。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_user_kb(tmp_path_factory, monkeypatch):
    """与开发者机器上的真实 ~/.chemaster 隔离。

    - kb MCP 会把 user_kb 文档并入语料；不隔离的话，单测结果取决于
      开发者个人的用户知识库内容（曾导致 test_list_skills 在有
      user_kb/notes 的机器上失败）。
    - agent 的权限分级会 lazy-load ~/.chemaster/policy.yaml（不存在时
      还会写入默认文件）；单测不应读写真实主目录。
    """
    monkeypatch.setenv(
        "CHEMASTER_USER_KB_DIR", str(tmp_path_factory.mktemp("user_kb"))
    )
    monkeypatch.setenv(
        "CHEMASTER_HOME", str(tmp_path_factory.mktemp("chemaster_home"))
    )
    from chemaster.mcp.kb.server import reset_doc_cache

    reset_doc_cache()
    yield
    reset_doc_cache()


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
