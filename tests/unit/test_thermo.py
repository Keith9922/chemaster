"""kb.formulas.thermo 单元测试 —— ZPE + 完整 RRHO 修正。"""

from __future__ import annotations

import pytest

from chemaster.kb.formulas import thermo as T


# ---- ZPE ----

def test_zpe_h2o():
    """H2O B3LYP-D3(BJ)/def2-TZVP 频率约 1617/3786/3891 cm⁻¹，
    ZPE ≈ (1617+3786+3891)/2 = 4647 cm⁻¹ ≈ 0.0212 Hartree。"""
    freqs = [1617.0, 3786.0, 3891.0]
    zpe = T.zpe_from_frequencies_cm_inv(freqs)
    assert 0.020 < zpe < 0.022, f"H2O ZPE {zpe} Eh outside expected range"


def test_zpe_filters_imaginary():
    """虚频应被过滤。"""
    freqs = [-200.0, 1617.0, 3786.0, 3891.0]
    zpe = T.zpe_from_frequencies_cm_inv(freqs)
    expected = T.zpe_from_frequencies_cm_inv([1617.0, 3786.0, 3891.0])
    assert zpe == pytest.approx(expected)


def test_zpe_empty():
    assert T.zpe_from_frequencies_cm_inv([]) == 0.0


# ---- thermal_corrections ----

def test_thermal_corrections_zpe_only_when_no_atoms():
    """没传 atoms 时降级到 ZPE-only。"""
    out = T.thermal_corrections([1617.0, 3786.0, 3891.0])
    assert out["zpe_Eh"] > 0
    assert out["h_corr_Eh"] is None
    assert out["g_corr_Eh"] is None
    assert out["method"] == "ZPE-only"


def test_thermal_corrections_full_rrho_h2o():
    """有 atoms 时走完整 RRHO（需要 ASE）。
    H2O 在 298.15 K 下 g_corr 应在 -0.005 ~ +0.005 Hartree 量级，
    h_corr 应略大于 ZPE（~0.024 Hartree）。
    """
    pytest.importorskip("ase")
    from ase import Atoms

    h2o = Atoms(
        symbols=["O", "H", "H"],
        positions=[
            (0.0, 0.0, 0.117),
            (0.0, 0.757, -0.470),
            (0.0, -0.757, -0.470),
        ],
    )
    out = T.thermal_corrections(
        [1617.0, 3786.0, 3891.0],
        atoms=h2o,
        geometry="nonlinear",
        symmetry_number=2,    # H2O 是 C2v
        spin=0.0,
    )
    assert out["method"] == "ASE-IdealGasThermo"
    assert out["zpe_Eh"] > 0
    assert out["h_corr_Eh"] is not None
    assert out["g_corr_Eh"] is not None
    assert out["ts_Eh"] is not None
    # H_corr ≥ ZPE （因为 H = ZPE + 转动平动 + ∫CpdT，全部 > 0）
    assert out["h_corr_Eh"] > out["zpe_Eh"]
    # G_corr < H_corr（因为 G = H - TS，TS > 0）
    assert out["g_corr_Eh"] < out["h_corr_Eh"]


# ---- Boltzmann ----

def test_boltzmann_weights_sum_to_one():
    energies = [0.0, 0.001, 0.002]   # Hartree
    weights = T.boltzmann_weights(energies, temperature_K=298.15)
    assert abs(sum(weights) - 1.0) < 1e-9
    # 最稳的占比最大
    assert weights[0] > weights[1] > weights[2]


def test_boltzmann_weights_empty():
    assert T.boltzmann_weights([]) == []
