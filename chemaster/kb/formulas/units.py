"""单位换算 —— 基于 ``pint``，配合化学常用单位。

设计目标：MCP 边界传值都带 unit；内部任何换算走本模块。
"""

from __future__ import annotations

from functools import cache

import pint


class UnitMismatchError(ValueError):
    """源单位与目标单位维度不匹配。"""


@cache
def get_registry() -> pint.UnitRegistry:
    """返回（缓存的）UnitRegistry，预定义化学单位。"""
    ureg = pint.UnitRegistry()

    # pint 自带 hartree，但补一些化学常用别名
    ureg.define("Eh = hartree")
    ureg.define("kcal_per_mol = kilocalorie / mole = kcal/mol")
    ureg.define("kJ_per_mol = kilojoule / mole = kJ/mol")
    ureg.define("wavenumber = 1 / centimeter = cm^-1 = cm⁻¹")

    # 化学常用复合单位
    ureg.define("debye = 3.33564e-30 * coulomb * meter = D")

    return ureg


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """单位换算。

    Args:
        value: 数值
        from_unit: 源单位字符串，例 ``"hartree"`` / ``"kcal/mol"`` / ``"angstrom"``
        to_unit: 目标单位字符串

    Returns:
        换算后的数值（float，无单位）。

    Raises:
        UnitMismatchError: 维度不匹配（如 hartree → angstrom）。
    """
    ureg = get_registry()
    try:
        q = (value * ureg(from_unit)).to(ureg(to_unit))
    except pint.DimensionalityError as e:
        raise UnitMismatchError(str(e)) from e
    return q.magnitude


def with_unit(value: float, unit: str) -> dict:
    """打成 ``{value, unit}`` 字典 —— MCP 出参规范。"""
    return {"value": float(value), "unit": unit}


# ---- 化学常用快捷换算 ----
# 全部基于 constants.py 中的精确比例，比 pint 走通用换算更快也更可读。
from chemaster.kb.formulas.constants import get as _get_const  # noqa: E402


def hartree_to_kcal_per_mol(x: float) -> float:
    return x * _get_const("hartree_to_kcal_per_mol").value


def hartree_to_eV(x: float) -> float:
    return x * _get_const("hartree_to_eV").value


def hartree_to_kJ_per_mol(x: float) -> float:
    return x * _get_const("hartree_to_kJ_per_mol").value


def hartree_to_cm_inv(x: float) -> float:
    return x * _get_const("hartree_to_cm_inv").value


def bohr_to_angstrom(x: float) -> float:
    return x * _get_const("bohr_to_angstrom").value


def angstrom_to_bohr(x: float) -> float:
    return x / _get_const("bohr_to_angstrom").value


def eV_to_J(x: float) -> float:
    return x * _get_const("eV_to_J").value


def J_to_eV(x: float) -> float:
    return x / _get_const("eV_to_J").value
