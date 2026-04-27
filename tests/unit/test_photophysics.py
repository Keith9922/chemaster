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
