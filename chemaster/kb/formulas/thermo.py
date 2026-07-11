"""热力学公式 —— ZPE、热修正、自由能等。

注意：振动频率单位约定 cm^-1（波数）；能量约定 Hartree。
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from chemaster.kb.formulas import constants as C


def zpe_from_frequencies_cm_inv(freqs_cm_inv: Iterable[float]) -> float:
    """零点振动能 (Hartree)。

    ZPE = (1/2) Σᵢ hcνᵢ ; ν 单位 cm^-1。

    虚频（< 0）应被调用方在传入前剔除或单独处理。

    Args:
        freqs_cm_inv: 振动频率列表，cm^-1。

    Returns:
        ZPE，单位 Hartree。
    """
    freqs = [f for f in freqs_cm_inv if f > 0]
    zpe_cm_inv = 0.5 * sum(freqs)
    return zpe_cm_inv / C.get("hartree_to_cm_inv").value


def thermal_corrections(
    freqs_cm_inv: Iterable[float],
    temperature_K: float = 298.15,
    pressure_Pa: float = 101_325.0,
    molecular_mass_amu: float | None = None,
    rotational_symmetry: int = 1,
    moments_of_inertia_amu_A2: tuple[float, float, float] | None = None,
    n_atoms: int | None = None,
    is_linear: bool = False,
) -> dict:
    """理想气体 RRHO 热力学修正（H、S、G 修正项）。

    本函数只处理"修正"——加在电子能 E_elec 上得到 H/G。

    Returns:
        {
          "zpe_Eh":            float,
          "h_corr_Eh":         float,    # = ZPE + ∫CpdT
          "ts_Eh":             float,    # T·S，Eh
          "g_corr_Eh":         float,    # = h_corr - T·S
          "temperature_K":     float,
          "pressure_Pa":       float,
        }

    备注：完整的 RRHO 实现需要分子的转动惯量、分子量、对称性等。
    建议直接读取 psi4 / ORCA 的输出（它们都已实现），本函数主要供
    交叉验证或独立 hand-derived 公式核查。当前实现仅给出 ZPE，
    其余字段返回 None 以提示调用方"请用引擎自带的"。
    """
    zpe = zpe_from_frequencies_cm_inv(freqs_cm_inv)

    # 完整 RRHO 实现见 ASE thermochemistry 模块（chemaster.kb.formulas
    # 故意保持简单；TODO Phase 2 接入完整实现）
    return {
        "zpe_Eh": zpe,
        "h_corr_Eh": None,
        "ts_Eh": None,
        "g_corr_Eh": None,
        "temperature_K": temperature_K,
        "pressure_Pa": pressure_Pa,
        "_note": "Use psi4/ORCA built-in thermochemistry. This is ZPE-only stub.",
    }


def boltzmann_weights(
    energies_Eh: Iterable[float],
    temperature_K: float = 298.15,
) -> list[float]:
    """给一组能量算 Boltzmann 权重（归一）。

    多构象平均必须用此函数，不能算术平均（PITFALLS §10.8）。

    Args:
        energies_Eh: 能量列表，Hartree
        temperature_K: 温度

    Returns:
        归一化权重，求和 = 1
    """
    e_list = list(energies_Eh)
    if not e_list:
        return []
    e_min = min(e_list)
    kT_Eh = C.get("kb").value * temperature_K / C.get("hartree").value
    raw = [math.exp(-(e - e_min) / kT_Eh) for e in e_list]
    z = sum(raw)
    return [r / z for r in raw]
