"""物理常数 —— LLM 不算数，从这里取。

数值来自 ``scipy.constants``（CODATA 2018）。提供统一的别名表与查询接口。
"""

from __future__ import annotations

from dataclasses import dataclass

import scipy.constants as sc


@dataclass(frozen=True)
class Constant:
    name: str
    value: float
    unit: str
    source: str = "CODATA-2018 (scipy.constants)"
    aliases: tuple[str, ...] = ()


# 常用物理常数表。新增请追加到这里。
_CONSTANTS: dict[str, Constant] = {
    "planck":     Constant("planck",     sc.Planck,            "J·s",          aliases=("h",)),
    "hbar":       Constant("hbar",       sc.hbar,              "J·s"),
    "kb":         Constant("kb",         sc.Boltzmann,         "J/K",          aliases=("boltzmann", "k_B")),
    "c":          Constant("c",          sc.c,                 "m/s",          aliases=("speed_of_light",)),
    "e":          Constant("e",          sc.e,                 "C",            aliases=("elementary_charge",)),
    "NA":         Constant("NA",         sc.N_A,               "1/mol",        aliases=("avogadro",)),
    "R":          Constant("R",          sc.R,                 "J/(mol·K)",    aliases=("gas_constant",)),
    "epsilon_0":  Constant("epsilon_0",  sc.epsilon_0,         "F/m"),
    "mu_0":       Constant("mu_0",       sc.mu_0,              "N/A^2"),
    "m_e":        Constant("m_e",        sc.m_e,               "kg",           aliases=("electron_mass",)),
    "m_p":        Constant("m_p",        sc.m_p,               "kg",           aliases=("proton_mass",)),
    "bohr":       Constant("bohr",       sc.physical_constants["Bohr radius"][0],   "m",  aliases=("a0",)),
    "hartree":    Constant("hartree",    sc.physical_constants["Hartree energy"][0],"J",  aliases=("E_h",)),
    "rydberg":    Constant("rydberg",    sc.physical_constants["Rydberg constant times hc in J"][0], "J"),
    "eV_to_J":    Constant("eV_to_J",    sc.eV,                "J/eV"),
    "cal_to_J":   Constant("cal_to_J",   sc.calorie,           "J/cal"),
    # 化学常用换算（直接给比例，便于 LLM 引用）
    "hartree_to_kcal_per_mol": Constant("hartree_to_kcal_per_mol", 627.5094740631, "kcal/(mol·Hartree)"),
    "hartree_to_eV":           Constant("hartree_to_eV",           27.211386245988, "eV/Hartree"),
    "hartree_to_kJ_per_mol":   Constant("hartree_to_kJ_per_mol",   2625.4996394798, "kJ/(mol·Hartree)"),
    "hartree_to_cm_inv":       Constant("hartree_to_cm_inv",       219474.6313632,  "cm^-1/Hartree"),
    "bohr_to_angstrom":        Constant("bohr_to_angstrom",        0.5291772105,    "Å/Bohr"),
    "atomic_unit_to_debye":   Constant("atomic_unit_to_debye",   2.5417463148,    "Debye/atomic_unit"),
}

# 反向别名查找表
_ALIAS_MAP: dict[str, str] = {}
for key, c in _CONSTANTS.items():
    _ALIAS_MAP[key.lower()] = key
    for a in c.aliases:
        _ALIAS_MAP[a.lower()] = key


class UnknownConstantError(KeyError):
    """请求的常数不在表里。"""


def get(name: str) -> Constant:
    """按名查常数。

    Args:
        name: 常数名或别名（大小写不敏感）。

    Raises:
        UnknownConstantError: 不在表内。
    """
    canonical = _ALIAS_MAP.get(name.lower())
    if canonical is None:
        raise UnknownConstantError(f"Unknown constant: {name!r}. Try one of: {sorted(_CONSTANTS)}")
    return _CONSTANTS[canonical]


def list_names() -> list[str]:
    """返回全部规范常数名。"""
    return sorted(_CONSTANTS.keys())
