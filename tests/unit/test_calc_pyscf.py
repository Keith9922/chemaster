"""Unit tests for chem.calc_pyscf MCP — open-source X2C SOC reference."""
from __future__ import annotations

import pytest

pyscf = pytest.importorskip("pyscf", reason="PySCF not installed")

from chemaster.mcp.calc_pyscf.server import (  # noqa: E402
    _check_engine,
    _xyz_to_pyscf_atom,
    single_point,
    x2c_soc,
)

H2_XYZ = """2
H2 minimal
H 0 0 0
H 0 0 0.74
"""


def test_check_engine_returns_version():
    version, err = _check_engine()
    assert err is None
    assert version is not None
    # PySCF 2.x is what we tested against
    assert version.startswith("2.")


def test_xyz_to_pyscf_atom_with_header():
    s = _xyz_to_pyscf_atom(H2_XYZ)
    assert "H 0 0 0" in s
    assert "H 0 0 0.74" in s
    assert ";" in s  # joined with semicolons


def test_xyz_to_pyscf_atom_without_header():
    flat = "H 0 0 0\nH 0 0 0.74"
    s = _xyz_to_pyscf_atom(flat)
    assert "H 0 0 0" in s
    assert "H 0 0 0.74" in s


def test_xyz_to_pyscf_atom_empty_raises():
    with pytest.raises(ValueError):
        _xyz_to_pyscf_atom("")


def test_single_point_h2_hf_nr():
    """H2 HF/sto-3g non-relativistic — well-known reference."""
    r = single_point(geometry_xyz=H2_XYZ, method="HF", basis="sto-3g",
                     relativistic="none")
    assert r["ok"] is True
    assert r["converged"] is True
    # H2 HF/sto-3g energy ≈ -1.117 Ha (textbook)
    assert -1.13 < r["energy_hartree"] < -1.10
    assert r["n_electrons"] == 2
    assert r["n_basis"] == 2  # sto-3g for H is 1 contracted GTO each
    assert r["data_source"] == "real_pyscf"
    assert "pyscf" in r["engine"].lower()


def test_single_point_h2_hf_scalar_relativistic():
    """X2C scalar should give a tiny shift relative to NR (light atoms)."""
    r_nr = single_point(geometry_xyz=H2_XYZ, method="HF", basis="sto-3g",
                        relativistic="none")
    r_sc = single_point(geometry_xyz=H2_XYZ, method="HF", basis="sto-3g",
                        relativistic="scalar")
    assert r_sc["ok"] is True
    # Relativistic correction should be small but nonzero for H2
    assert r_sc["relativistic"] == "scalar"
    diff_meV = (r_sc["energy_hartree"] - r_nr["energy_hartree"]) * 27211.4
    # For H2 the correction is < ~10 meV
    assert abs(diff_meV) < 100.0


def test_single_point_h2_hf_soc():
    """SOC level should converge for H2 (sub-meV correction expected)."""
    r = single_point(geometry_xyz=H2_XYZ, method="HF", basis="sto-3g",
                     relativistic="soc")
    assert r["ok"] is True
    assert r["converged"] is True
    assert r["relativistic"] == "soc"


def test_single_point_invalid_relativistic_option():
    r = single_point(geometry_xyz=H2_XYZ, relativistic="bogus")
    assert r["ok"] is False
    assert r["error_code"] == "INVALID_OPTION"


def test_single_point_invalid_geometry():
    r = single_point(geometry_xyz="")
    assert r["ok"] is False
    assert r["error_code"] == "INVALID_GEOMETRY"


def test_x2c_soc_three_stage_h2():
    """End-to-end three-stage analysis on H2."""
    r = x2c_soc(geometry_xyz=H2_XYZ, method="HF", basis="sto-3g")
    assert r["ok"] is True
    assert "stages" in r
    assert set(r["stages"]) == {"nr", "scalar", "soc"}
    assert all(s["energy_hartree"] for s in r["stages"].values())
    # For H2, both corrections are small in absolute terms
    assert abs(r["scalar_correction_meV"]) < 100.0
    assert abs(r["soc_correction_meV"]) < 10.0
    assert "interpretation" in r


def test_calc_pyscf_registered_in_default_tool_loader():
    """Verify the new tools are picked up by build_default_registry."""
    from chemaster.agent.tool_loader import build_default_registry
    reg = build_default_registry()
    names = reg.names()
    assert "calc_pyscf_single_point" in names
    assert "calc_pyscf_x2c_soc" in names


def test_calc_pyscf_x2c_soc_marked_chemistry_decision():
    """The 3-stage SOC tool exposes chemistry-decision flag."""
    from chemaster.agent.tool_loader import build_default_registry
    reg = build_default_registry()
    tool = reg.get("calc_pyscf_x2c_soc")
    assert tool.is_chemistry_decision is True
    assert tool.is_long_running is True
