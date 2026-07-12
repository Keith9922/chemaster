"""calc_orca MCP unit tests.

ORCA isn't installed in CI by default. These tests cover:
- The not-installed path (ENGINE_NOT_FOUND with a useful suggestion).
- Input-file generation (geometry block + keywords).
- Output parsing (energy / optimized xyz / failure detection) using
  fixture strings instead of running ORCA.
- Tool-loader integration.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from chemaster.mcp.calc_orca.server import (
    _build_input,
    _check_engine,
    _detect_geometry_failure,
    _detect_scf_failure,
    _parse_final_energy,
    _parse_optimized_xyz,
    _xyz_to_orca_geom,
    optimize,
    single_point,
)

# ──────────────────────────────────────────────────────────────────────────
# Engine probing
# ──────────────────────────────────────────────────────────────────────────


def test_engine_check_returns_path_and_version_or_none():
    path, version = _check_engine()
    if path is None:
        assert version is None
    else:
        assert isinstance(version, str) and version


# ──────────────────────────────────────────────────────────────────────────
# Geometry / input-file generation
# ──────────────────────────────────────────────────────────────────────────


def test_xyz_to_orca_geom_with_standard_xyz():
    xyz = "3\nH2O\nO 0 0 0\nH 0.96 0 0\nH -0.48 0.83 0\n"
    block = _xyz_to_orca_geom(xyz, charge=0, multiplicity=1)
    assert block.startswith("* xyz 0 1")
    assert block.endswith("*\n")
    assert "O 0 0 0" in block
    assert "H -0.48 0.83 0" in block


def test_xyz_to_orca_geom_with_charge_and_mult():
    xyz = "1\nH atom\nH 0 0 0\n"
    block = _xyz_to_orca_geom(xyz, charge=-1, multiplicity=2)
    assert "* xyz -1 2" in block


def test_build_input_includes_keywords_and_pal():
    inp = _build_input(
        keywords="B3LYP D3BJ def2-SVP", geom_block="* xyz 0 1\nH 0 0 0\n*\n",
        nproc=4, memory_gb=4,
    )
    assert "! B3LYP D3BJ def2-SVP" in inp
    assert "%pal nprocs 4 end" in inp
    # 4 GB / 4 procs = 1024 MB per thread
    assert "%maxcore 1024" in inp


# ──────────────────────────────────────────────────────────────────────────
# Output parsing (fixture strings)
# ──────────────────────────────────────────────────────────────────────────


def test_parse_final_energy_picks_last_match():
    out = """
    FINAL SINGLE POINT ENERGY     -76.351231
    ... iteration ...
    FINAL SINGLE POINT ENERGY     -76.351999
    """
    assert _parse_final_energy(out) == pytest.approx(-76.351999, abs=1e-6)


def test_parse_final_energy_returns_none_when_missing():
    out = "ORCA did not start."
    assert _parse_final_energy(out) is None


def test_parse_optimized_xyz_from_log_block(tmp_path: Path):
    """When ``calc.xyz`` doesn't exist, fall back to parsing the log."""
    out = """
  CARTESIAN COORDINATES (ANGSTROEM)
  ---------------------------------
  O      0.000000    0.000000    0.117000
  H      0.000000    0.757000   -0.469000
  H      0.000000   -0.757000   -0.469000

  ----- next block -----
"""
    xyz = _parse_optimized_xyz(out, tmp_path)
    assert xyz is not None
    assert xyz.startswith("3\n")
    assert "O 0.000000" in xyz


def test_parse_optimized_xyz_prefers_calc_xyz_file(tmp_path: Path):
    (tmp_path / "calc.xyz").write_text("4\nfrom file\nO 0 0 0\nH 0 0 1\nH 0 1 0\nH 1 0 0\n")
    xyz = _parse_optimized_xyz("anything", tmp_path)
    assert xyz.startswith("4\n")
    assert "from file" in xyz


def test_detect_scf_failure_messages():
    assert _detect_scf_failure("SCF NOT CONVERGED in 200 cycles")
    assert _detect_scf_failure("TROUBLE IN SCF")
    assert not _detect_scf_failure("SCF converged in 12 iterations")


def test_detect_geometry_failure_messages():
    assert _detect_geometry_failure("GEOMETRY OPTIMIZATION FAILED")
    assert _detect_geometry_failure("OPT NOT CONVERGED after 100 steps")
    assert not _detect_geometry_failure("OPT CONVERGED")


# ──────────────────────────────────────────────────────────────────────────
# Tool-level: ENGINE_NOT_FOUND when orca is absent
# ──────────────────────────────────────────────────────────────────────────


def _orca_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda x: None)


def test_single_point_returns_engine_not_found_when_orca_missing(monkeypatch):
    _orca_missing(monkeypatch)
    r = single_point("3\nH2O\nO 0 0 0\nH 1 0 0\nH 0 1 0\n")
    assert not r["ok"]
    assert r["error_code"] == "ENGINE_NOT_FOUND"
    assert "orcaforum" in r["suggestion"]


def test_optimize_returns_engine_not_found_when_orca_missing(monkeypatch):
    _orca_missing(monkeypatch)
    r = optimize("3\nH2O\nO 0 0 0\nH 1 0 0\nH 0 1 0\n")
    assert not r["ok"]
    assert r["error_code"] == "ENGINE_NOT_FOUND"


# ──────────────────────────────────────────────────────────────────────────
# Tool-loader integration
# ──────────────────────────────────────────────────────────────────────────


def test_orca_tools_registered_in_default_registry():
    from chemaster.agent.tool_loader import build_default_registry
    reg = build_default_registry()
    assert reg.has("calc_orca_single_point")
    assert reg.has("calc_orca_optimize")
    sp = reg.get("calc_orca_single_point")
    assert sp.is_long_running        # should require user confirmation
