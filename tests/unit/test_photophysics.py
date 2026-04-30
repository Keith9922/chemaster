"""kb.formulas.photophysics 单元测试 —— TADF 公式正确性。"""

from __future__ import annotations

import pytest

from chemaster.kb.formulas import photophysics as P


def test_krisc_marcus_typical_tadf():
    """TADF 典型分子量级检查：4CzIPN 类。

    ΔE_ST ≈ 0.10 eV, SOC ≈ 1 cm^-1, λ ≈ 0.2 eV
    实验 kRISC ≈ 10^5 ~ 10^7 s^-1。
    """
    k = P.krisc_marcus(0.10, 1.0, 0.20, T=298.15) if False else \
        P.krisc_marcus(0.10, 1.0, 0.20, temperature_K=298.15)
    assert 1e3 < k < 1e9   # 宽容数量级（公式简化）


def test_krisc_zero_lambda_raises():
    with pytest.raises(ValueError):
        P.krisc_marcus(0.1, 1.0, 0.0)


def test_strickler_berg_order_of_magnitude():
    """3 eV 跃迁、f = 0.1：k_F 应在 10^7 ~ 10^8 量级。"""
    k = P.kf_strickler_berg(3.0, 0.1)
    assert 1e6 < k < 1e10


def test_plqy_formula():
    assert P.plqy(kf=1e8, knr=0, kisc=0) == pytest.approx(1.0)
    assert P.plqy(kf=1e8, knr=1e8, kisc=0) == pytest.approx(0.5)
    assert P.plqy(kf=0, knr=0, kisc=0) == 0.0


def test_tadf_quantum_yield_basic():
    out = P.tadf_quantum_yield(kf=1e7, knr_s1=1e6, kisc=1e8, krisc=1e5, knr_t1=1e3)
    assert out["isc_efficiency"] > 0.9
    assert 0 <= out["prompt_phi"] <= 1


# ──────────────────────────────────────────────────────────────────────────
# New formulas (kisc / kic Marcus + Einstein dipole rate)
# ──────────────────────────────────────────────────────────────────────────


def test_kisc_marcus_matches_krisc_for_same_inputs():
    """Forward / reverse ISC use the same formula (Marcus is symmetric in |ΔE|)."""
    forward = P.kisc_marcus(0.034158, 5.56, 0.20, temperature_K=298.15)
    reverse = P.krisc_marcus(0.034158, 5.56, 0.20, temperature_K=298.15)
    assert forward == reverse
    assert forward > 0


def test_kisc_marcus_classical_does_not_reproduce_jingti_high_gap():
    """师姐 jingti S1→T1 dataset: ΔE = 0.034 H ≈ 0.93 eV, SOC = 5.56 cm⁻¹,
    reported kisc ≈ 1.17 × 10⁹ /s.

    Honest check: classical Marcus *cannot* reproduce this rate when
    ΔE >> λ (Marcus barrier exp(-(ΔE+λ)²/4λkBT) becomes vanishingly
    small). The 师姐 number comes from MOMAP MLJ + TVCF which folds in
    high-frequency vibrational modes (quantum tunnelling channels).

    This test documents the limitation: with reasonable λ ≈ 0.2 eV,
    the classical Marcus rate underestimates the true ISC by many
    orders of magnitude. ChemMaster's photophysics module needs an
    MLJ implementation before it can quantitatively reproduce TADF
    rates of this kind. (Roadmap.)
    """
    delta_eV = 0.034158 * 27.211386
    k_classical = P.kisc_marcus(delta_eV, soc_cm_inv=5.56,
                               reorganization_energy_eV=0.20,
                               temperature_K=298.15)
    # The classical rate is essentially zero — that's the bug we're
    # documenting. Just assert it's a non-negative finite number, not
    # that it matches reality.
    assert k_classical >= 0.0
    assert k_classical < 1e9, (
        "Classical Marcus should under-shoot the师姐 reference (1.17e9 /s) "
        "for this gap; if it doesn't, our formula has a sign/units bug."
    )


def test_kic_marcus_uses_nacme_in_place_of_soc():
    """kic 公式与 kisc 同一 Marcus 形式，不同的是耦合矩阵元含义。
    给定相同的数值，两者应返回同一速率。"""
    k_isc = P.kisc_marcus(0.5, 10.0, 0.2)
    k_ic = P.kic_marcus(0.5, 10.0, 0.2)
    assert k_isc == k_ic


def test_kr_einstein_from_dipole_order_of_magnitude():
    """3 eV 跃迁、µ = 1 Debye → k_r ≈ 5.8e10 s⁻¹ 量级."""
    k = P.kr_einstein_from_dipole(3.0, 1.0)
    assert 1e9 < k < 1e12


def test_kr_einstein_jingti_s1_to_s0_within_two_orders_of_magnitude():
    """师姐 s1→s0：ΔE 0.125349 H ≈ 3.412 eV; emission dipole 0.302879 Debye;
    reported kr ≈ 8.16e8 /s.

    Note: simple Einstein A doesn't include Franck-Condon vibrational
    overlap or Herzberg-Teller vibronic coupling that MOMAP TVCF
    accounts for. We assert order-of-magnitude agreement only.
    """
    delta_eV = 0.125349 * 27.211386
    k = P.kr_einstein_from_dipole(delta_eV, transition_dipole_debye=0.302879)
    ref = 8.16e8
    # Within 2 orders of magnitude of the师姐 reference.
    assert ref / 100 < k < ref * 100, (
        f"kr {k:.2e} more than 2 orders off the师姐 reference {ref:.2e}; "
        "if this is wider than that we likely have a unit/formula bug."
    )
