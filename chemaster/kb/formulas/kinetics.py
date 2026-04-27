"""化学动力学公式 —— Eyring、Arrhenius。"""

from __future__ import annotations

import math

from chemaster.kb.formulas import constants as C


def arrhenius(A: float, Ea_kJ_per_mol: float, T_K: float = 298.15) -> float:
    """Arrhenius 速率常数。

    k = A · exp(-Ea / (R T))

    Args:
        A: 频率因子 (与 k 同单位，常 s^-1)
        Ea_kJ_per_mol: 活化能，kJ/mol
        T_K: 温度

    Returns:
        速率常数 k（与 A 单位一致）
    """
    R = C.get("R").value          # J/(mol·K)
    Ea_J = Ea_kJ_per_mol * 1000.0
    return A * math.exp(-Ea_J / (R * T_K))


def eyring(
    delta_G_act_kJ_per_mol: float,
    T_K: float = 298.15,
    transmission_coeff: float = 1.0,
) -> float:
    """Eyring 方程算反应速率常数。

    k = κ · (kB T / h) · exp(-ΔG‡ / RT)

    Args:
        delta_G_act_kJ_per_mol: 活化自由能，kJ/mol
        T_K: 温度
        transmission_coeff: 透射系数 κ，默认 1

    Returns:
        速率常数 k，s^-1
    """
    kB = C.get("kb").value        # J/K
    h = C.get("planck").value     # J·s
    R = C.get("R").value          # J/(mol·K)
    dG_J = delta_G_act_kJ_per_mol * 1000.0
    return transmission_coeff * (kB * T_K / h) * math.exp(-dG_J / (R * T_K))


def eyring_T_to_observe_k(
    target_k: float,
    delta_G_act_kJ_per_mol: float,
    transmission_coeff: float = 1.0,
    T_low: float = 100.0,
    T_high: float = 2000.0,
    tol: float = 1e-3,
) -> float:
    """二分法求"要让 k 达到 target_k 需要多少温度"。便于实验设计。"""
    lo, hi = T_low, T_high
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        k = eyring(delta_G_act_kJ_per_mol, mid, transmission_coeff)
        if k < target_k:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
