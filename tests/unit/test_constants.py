"""kb.formulas.constants 单元测试。"""

from __future__ import annotations

import pytest

from chemaster.kb.formulas import constants as C


def test_get_known_constant():
    h = C.get("hbar")
    assert h.value == pytest.approx(1.054571817e-34, rel=1e-6)
    assert "J" in h.unit


def test_alias_lookup():
    assert C.get("avogadro").name == "NA"
    assert C.get("speed_of_light").name == "c"


def test_unknown_raises():
    with pytest.raises(C.UnknownConstantError):
        C.get("not-a-constant")


def test_list_names_nonempty():
    names = C.list_names()
    assert "hbar" in names
    assert "hartree_to_kcal_per_mol" in names
