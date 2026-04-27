"""kb.formulas.units 单元测试。"""

from __future__ import annotations

import pytest

from chemaster.kb.formulas import units as U


def test_hartree_to_kcal():
    assert U.hartree_to_kcal_per_mol(1.0) == pytest.approx(627.509, rel=1e-4)


def test_hartree_to_eV():
    assert U.hartree_to_eV(1.0) == pytest.approx(27.2114, rel=1e-4)


def test_bohr_to_angstrom():
    assert U.bohr_to_angstrom(1.0) == pytest.approx(0.529177, rel=1e-4)


def test_pint_convert_energy():
    assert U.convert(1.0, "hartree", "eV") == pytest.approx(27.2114, rel=1e-3)


def test_pint_convert_length():
    assert U.convert(1.0, "angstrom", "nanometer") == pytest.approx(0.1)


def test_unit_mismatch_raises():
    with pytest.raises(U.UnitMismatchError):
        U.convert(1.0, "hartree", "angstrom")


def test_with_unit_dict():
    out = U.with_unit(-76.4, "Hartree")
    assert out == {"value": -76.4, "unit": "Hartree"}
