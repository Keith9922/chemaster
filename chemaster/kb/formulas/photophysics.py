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


def k_mlj(
    delta_G_eV: float,
    coupling_cm_inv: float,
    reorg_classical_eV: float,
    reorg_quantum_eV: float,
    omega_eff_cm_inv: float,
    temperature_K: float = 298.15,
    n_max: int = 30,
) -> float:
    """Marcus-Levich-Jortner rate constant (semi-classical with one
    high-frequency vibrational acceptor mode).

    k_MLJ = (2π/ℏ)·|H|² · √(1/(4π λ_s k_B T)) ·
            Σ_{n=0}^{n_max} [e^{-S} S^n / n!] ·
                            exp[−(ΔG° + n·ℏω + λ_s)² / (4 λ_s k_B T)]

    where the high-frequency mode contributes a Franck-Condon weighted
    density of vibrational acceptor states with Huang-Rhys factor
    S = λ_v / ℏω. This is what extends classical Marcus to large electronic
    energy gaps where the simple classical form predicts vanishing rates.

    Use this for ISC, RISC, and IC at gaps ≳ 0.5 eV (where classical Marcus
    underestimates by many orders of magnitude). The dominant vibrational
    acceptor in organic emitters is typically a C=C / C=N stretch at
    ~1400–1600 cm⁻¹.

    Sign convention (Marcus standard):
        ΔG° < 0  → exoergic (downhill); maximum rate at ΔG° = -λ_total
        ΔG° > 0  → endoergic (uphill); thermally activated
        For ISC  (S1 → T1):  ΔG° = -|ΔE_ST|  (negative, S1 is above T1)
        For RISC (T1 → S1):  ΔG° = +|ΔE_ST|  (positive)

    Args:
        delta_G_eV: Signed Marcus driving force ΔG° in eV (see convention
            above).
        coupling_cm_inv: |H| matrix element in cm⁻¹. SOC for spin-flip
            (ISC, RISC), NACME for same-spin (IC).
        reorg_classical_eV: λ_s, the LOW-frequency / solvent / classical
            reorganization energy (typ. 0.05–0.5 eV for organics).
        reorg_quantum_eV: λ_v, the HIGH-frequency vibrational reorganization
            energy (typ. 0.05–0.4 eV); used to compute S = λ_v / ℏω.
        omega_eff_cm_inv: effective high-frequency mode ℏω in cm⁻¹
            (typ. 1300–1700 for C=C/C=N stretch in TADF emitters).
        temperature_K: temperature in K.
        n_max: truncate the Franck-Condon sum at this many vibrational quanta
            (30 is overkill for ΔG° < 1.5 eV; bump for very large gaps).

    Returns:
        Rate constant in s⁻¹.

    Raises:
        ValueError: λ_s ≤ 0 or ℏω ≤ 0.

    Notes:
        - When λ_v → 0 (S → 0), only the n=0 term survives and k_MLJ
          reduces to classical Marcus with the same |H|, λ_s, ΔG°. This is
          a useful sanity check.
        - Truncation: for the n=n_max term to contribute negligibly, you need
          (n_max·ℏω) ≫ |ΔG°+λ_s|. The Poisson FC weight S^n/n! also dies for
          n ≫ S, but the exponential matters more in the inverted region.
        - For very large ΔG° (≳ 2 eV) consider using the analytic
          high-frequency limit (e.g. Bixon-Jortner energy-gap law) instead;
          numerical truncation here may need n_max > 30.

    References:
        Jortner, J. *J. Chem. Phys.* 1976, 64, 4860.
        Bixon, M.; Jortner, J. *Adv. Chem. Phys.* 1999, 106, 35.
        Marian, C. M. *WIREs Comput. Mol. Sci.* 2012, 2, 187.
    """
    if reorg_classical_eV <= 0:
        raise ValueError("Classical reorganization energy λ_s must be > 0.")
    if omega_eff_cm_inv <= 0:
        raise ValueError("Effective vibrational frequency ω must be > 0.")
    if reorg_quantum_eV < 0:
        raise ValueError("Quantum reorganization energy λ_v must be ≥ 0.")
    if n_max < 0:
        raise ValueError("n_max must be ≥ 0.")

    h_J = C.get("planck").value
    hbar_J = C.get("hbar").value
    kB_J = C.get("kb").value
    c_m_per_s = C.get("c").value

    delta_G_J = U.eV_to_J(delta_G_eV)
    lam_s_J = U.eV_to_J(reorg_classical_eV)
    coupling_J = (coupling_cm_inv * 100.0) * h_J * c_m_per_s   # cm⁻¹ → m⁻¹ → J
    omega_J = (omega_eff_cm_inv * 100.0) * h_J * c_m_per_s

    # Huang-Rhys factor for the dominant high-frequency mode
    S_HR = U.eV_to_J(reorg_quantum_eV) / omega_J  # dimensionless

    pre = (2.0 * math.pi / hbar_J) * (coupling_J ** 2)
    fc_envelope = 1.0 / math.sqrt(4.0 * math.pi * lam_s_J * kB_J * temperature_K)

    # Franck-Condon weighted sum over vibrational acceptor states
    # FC_n = e^{-S} S^n / n!     (Poisson distribution)
    # exp_n = exp[-(ΔG° + nℏω + λ_s)² / (4 λ_s kBT)]
    #
    # Compute FC_n iteratively to avoid overflow at large n (S^n / n!).
    fc_sum = 0.0
    fc_n = math.exp(-S_HR)  # FC_0 = e^{-S}
    for n in range(n_max + 1):
        if n > 0:
            fc_n = fc_n * S_HR / n  # FC_n = FC_{n-1} * S / n
        gap_n = delta_G_J + n * omega_J + lam_s_J
        expo = -(gap_n ** 2) / (4.0 * lam_s_J * kB_J * temperature_K)
        fc_sum += fc_n * math.exp(expo)

    return pre * fc_envelope * fc_sum


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
