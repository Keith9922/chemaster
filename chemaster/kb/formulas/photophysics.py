"""光物理公式 —— Marcus、kRISC、kF、kIC、Strickler-Berg 等。

TADF 流水线的最后一步用 Marcus(-Levich-Jortner) 算 kRISC。
所有能量进 SI 转 J 内部计算，输入约定常用单位（eV、cm^-1、meV）。
"""

from __future__ import annotations

import math

from chemaster.kb.formulas import constants as C
from chemaster.kb.formulas import units as U


def krisc_marcus(
    delta_E_ST_eV: float,
    soc_cm_inv: float,
    reorganization_energy_eV: float,
    temperature_K: float = 298.15,
) -> float:
    """Marcus 经典模型估算 RISC 速率（高温极限）。

    k_RISC = (2π / ħ) · |H_SOC|^2 · (4π λ kBT)^(-1/2) · exp(-(ΔE_ST + λ)^2 / (4 λ kBT))

    Args:
        delta_E_ST_eV: ΔE_ST = E(S1) - E(T1)，eV。TADF 中通常 > 0。
        soc_cm_inv: <S1|H_SO|T1> 矩阵元，cm^-1。
        reorganization_energy_eV: 重组能 λ，eV。
        temperature_K: 温度。

    Returns:
        k_RISC，s^-1。
    """
    # 全部换 SI（J）
    h_J = C.get("planck").value
    hbar_J = C.get("hbar").value
    kB_J = C.get("kb").value

    delta_E_J = U.eV_to_J(delta_E_ST_eV)
    lam_J = U.eV_to_J(reorganization_energy_eV)
    soc_J = (soc_cm_inv * 100) * h_J * C.get("c").value   # cm^-1 → m^-1 → J

    if lam_J <= 0:
        raise ValueError("Reorganization energy λ must be > 0.")

    pre = (2.0 * math.pi / hbar_J) * (soc_J ** 2)
    fc = 1.0 / math.sqrt(4.0 * math.pi * lam_J * kB_J * temperature_K)
    expo = -((delta_E_J + lam_J) ** 2) / (4.0 * lam_J * kB_J * temperature_K)

    return pre * fc * math.exp(expo)


def kf_strickler_berg(
    energy_eV: float,
    oscillator_strength: float,
    refractive_index: float = 1.0,
) -> float:
    """Strickler-Berg 公式从振子强度估算辐射速率。

    k_F ≈ 2.88e-9 · n^2 · (E/cm^-1)^2 · f   [s^-1]

    Args:
        energy_eV: 跃迁能，eV
        oscillator_strength: 振子强度 f
        refractive_index: 介质折射率，默认 1（气相）

    Returns:
        辐射速率 k_F，s^-1
    """
    energy_cm_inv = U.eV_to_J(energy_eV) / (C.get("planck").value * C.get("c").value * 100)
    return 0.677 * refractive_index ** 2 * (energy_cm_inv ** 2) * oscillator_strength


def kr_einstein_from_dipole(
    energy_eV: float,
    transition_dipole_debye: float,
    refractive_index: float = 1.0,
) -> float:
    """Einstein-A 形式的辐射速率，直接吃跃迁偶极矩 µ (Debye).

    k_F = (8π² · n · µ²·E³) / (3 · ε₀ · h · c³ · ℏ²)

    简化数值版（µ in Debye, E in eV）：
        k_F [s⁻¹] ≈ 2.143e10 · n · µ² · E³

    本函数与 MOMAP 用法一致：MOMAP TVCF 输出的 EDMA (Electric Dipole
    transition Moment Absorption / Emission) 单位是 Debye, 平方后乘前因子。

    Args:
        energy_eV: 跃迁能，eV
        transition_dipole_debye: |µ| 长度模长，Debye
        refractive_index: 介质折射率，默认 1（气相）

    Returns:
        辐射速率 k_F，s⁻¹
    """
    return 2.142935e10 * refractive_index * (transition_dipole_debye ** 2) * (energy_eV ** 3)


def kisc_marcus(
    delta_E_ST_eV: float,
    soc_cm_inv: float,
    reorganization_energy_eV: float,
    temperature_K: float = 298.15,
) -> float:
    """Marcus 经典模型估算 ISC (S1 → T1) 速率。

    与 krisc_marcus 的公式一致；区别是 ΔE 的符号约定：
    - S1 → T1（正向 ISC）：ΔE = E(T1) − E(S1) < 0（T1 通常低于 S1）
    - 但 Marcus 模型对 ΔE 平方依赖，所以两个方向用同一公式都可以。
    本函数把传入的 ΔE_ST 当作 |ΔE|（默认 S1−T1 的差），保证对称。

    Args:
        delta_E_ST_eV: |ΔE_ST| = |E(S1) − E(T1)|，eV
        soc_cm_inv: <S1|H_SO|T1> 矩阵元，cm⁻¹
        reorganization_energy_eV: 重组能 λ，eV
        temperature_K: 温度

    Returns:
        k_ISC，s⁻¹
    """
    # Just call krisc_marcus with the absolute energy gap — Marcus is
    # symmetric in ΔE.
    return krisc_marcus(abs(delta_E_ST_eV), soc_cm_inv,
                       reorganization_energy_eV, temperature_K)


def kic_marcus(
    delta_E_eV: float,
    nacme_cm_inv: float,
    reorganization_energy_eV: float,
    temperature_K: float = 298.15,
) -> float:
    """Marcus 经典近似的内转换速率 (S2 → S1 / S1 → S2 等同自旋态间).

    数学上和 krisc/kisc 同一公式，把 SOC 矩阵元换成 NACME（非绝热耦合矩阵元）：

        k_IC = (2π / ℏ) · |H_NACME|² · √(1/(4π λ kBT)) · exp(−(ΔE+λ)²/(4λkBT))

    NACME 的单位与 SOC 一样可以 cm⁻¹（MOMAP / Gaussian 输出常用）。

    Args:
        delta_E_eV: ΔE = E(initial) − E(final)，eV（同自旋）
        nacme_cm_inv: |H_NACME| 矩阵元，cm⁻¹
        reorganization_energy_eV: 重组能 λ，eV
        temperature_K: 温度

    Returns:
        k_IC，s⁻¹
    """
    return krisc_marcus(abs(delta_E_eV), nacme_cm_inv,
                       reorganization_energy_eV, temperature_K)


def plqy(kf: float, knr: float, kisc: float = 0.0) -> float:
    """光致发光量子产率。

    Φ = k_F / (k_F + k_NR + k_ISC)
    """
    total = kf + knr + kisc
    if total <= 0:
        return 0.0
    return kf / total


def tadf_quantum_yield(
    kf: float,
    knr_s1: float,
    kisc: float,
    krisc: float,
    knr_t1: float,
) -> dict:
    """TADF 体系的量子产率分解（前者→S1 直接荧光部分；后者→延迟荧光）。

    返回 {prompt_phi, delayed_phi, total_phi, isc_efficiency}.

    简化模型：稳态近似下 S1 ⇌ T1, S1 → S0 (k_F + k_NR_S1), T1 → S0 (k_NR_T1)。
    """
    if any(x < 0 for x in (kf, knr_s1, kisc, krisc, knr_t1)):
        raise ValueError("All rate constants must be ≥ 0.")
    s1_total = kf + knr_s1 + kisc
    if s1_total <= 0:
        return {"prompt_phi": 0.0, "delayed_phi": 0.0, "total_phi": 0.0, "isc_efficiency": 0.0}
    phi_isc = kisc / s1_total
    t1_total = krisc + knr_t1
    phi_risc = krisc / t1_total if t1_total > 0 else 0.0
    phi_prompt = kf / s1_total
    # 延迟荧光：每个进 T1 的分子有 phi_risc 概率回 S1，再 phi_prompt 概率发光，可循环
    cycle_factor = 1.0 / (1.0 - phi_isc * phi_risc) if phi_isc * phi_risc < 1.0 else float("inf")
    phi_delayed = phi_prompt * phi_isc * phi_risc * cycle_factor - phi_prompt * phi_isc * phi_risc
    return {
        "prompt_phi": phi_prompt,
        "delayed_phi": phi_delayed,
        "total_phi": phi_prompt * cycle_factor,
        "isc_efficiency": phi_isc,
    }
