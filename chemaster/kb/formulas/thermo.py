"""热力学公式 —— ZPE、RRHO 修正、自由能等。

设计原则：
- 浮点全部走 ASE / Python，**不让 LLM 算**。
- 单位约定：振动频率 cm⁻¹；能量 Hartree（边界处）；ASE 内部 eV，进出口换算。
- ``thermal_corrections`` 用 ASE ``IdealGasThermo`` 实现完整 RRHO，不是 ZPE-only。
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

from chemaster.kb.formulas import constants as C


# ──────────────────────────────────────────────────────────────────────
# ZPE
# ──────────────────────────────────────────────────────────────────────

def zpe_from_frequencies_cm_inv(freqs_cm_inv: Iterable[float]) -> float:
    """零点振动能 (Hartree)。

    ZPE = (1/2) Σᵢ hcνᵢ ; ν 单位 cm⁻¹。

    虚频（< 0）会被自动过滤。

    Args:
        freqs_cm_inv: 振动频率列表，cm⁻¹。

    Returns:
        ZPE，单位 Hartree。
    """
    freqs = [f for f in freqs_cm_inv if f > 0]
    zpe_cm_inv = 0.5 * sum(freqs)
    return zpe_cm_inv / C.get("hartree_to_cm_inv").value


# ──────────────────────────────────────────────────────────────────────
# 完整 RRHO 修正（H、TS、G）
# ──────────────────────────────────────────────────────────────────────

def thermal_corrections(
    freqs_cm_inv: Iterable[float],
    temperature_K: float = 298.15,
    pressure_Pa: float = 101_325.0,
    geometry: Literal["nonlinear", "linear", "monatomic"] = "nonlinear",
    symmetry_number: int = 1,
    spin: float = 0.0,
    atoms=None,  # noqa: ANN001
) -> dict:
    """理想气体 RRHO 热力学修正 —— H、TS、G 修正项。

    本函数返回的"修正"加在电子能 ``E_elec`` 上即得 H/G。

    Args:
        freqs_cm_inv: 振动频率列表（cm⁻¹）。虚频自动过滤。
        temperature_K: 温度。
        pressure_Pa: 压力（Pa；1 atm = 101325 Pa）。
        geometry: 'nonlinear' / 'linear' / 'monatomic'。
        symmetry_number: 转动对称数 σ（C2v=2, D6h=12, ...）；不知道写 1 偏保守。
        spin: 自旋量子数 S（singlet=0, doublet=0.5, triplet=1, ...）。
        atoms: ``ase.Atoms`` 对象（含 mass + positions）。若给出会算转动惯量；
            否则只能给 ZPE。

    Returns:
        ::

            {
              "zpe_Eh":            float,
              "h_corr_Eh":         float | None,
              "ts_Eh":             float | None,    # T·S
              "g_corr_Eh":         float | None,
              "temperature_K":     float,
              "pressure_Pa":       float,
              "method":            str,             # "ASE-IdealGasThermo" or "ZPE-only"
            }

    Notes:
        - 完整 RRHO 需要 ASE atoms（带 mass + positions）。无 atoms 时退化为只给 ZPE。
        - 单原子（monatomic）忽略 freqs。
    """
    freqs = [f for f in freqs_cm_inv if f > 0]
    zpe_Eh = zpe_from_frequencies_cm_inv(freqs)

    if atoms is None:
        return {
            "zpe_Eh": zpe_Eh,
            "h_corr_Eh": None,
            "ts_Eh": None,
            "g_corr_Eh": None,
            "temperature_K": temperature_K,
            "pressure_Pa": pressure_Pa,
            "method": "ZPE-only",
            "_note": "atoms=None：缺转动惯量信息，只能给 ZPE。传 ase.Atoms 拿完整 RRHO。",
        }

    # 走 ASE 完整 RRHO
    try:
        from ase.thermochemistry import IdealGasThermo  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "ASE 未安装；完整 RRHO 需要 ase.thermochemistry。"
            "pip install ase 或 conda install -c conda-forge ase。"
        ) from e

    # ASE 接收 vib_energies (eV)，频率 (cm⁻¹) 换算
    h_eV_per_cm_inv = C.get("planck").value * C.get("c").value * 100 / C.get("eV_to_J").value
    vib_energies_eV = [f * h_eV_per_cm_inv for f in freqs]

    thermo = IdealGasThermo(
        vib_energies=vib_energies_eV,
        potentialenergy=0.0,           # 我们只要 corrections，不要绝对值
        atoms=atoms,
        geometry=geometry,
        symmetrynumber=symmetry_number,
        spin=spin,
    )

    # ASE 给的都是 eV
    H_eV = thermo.get_enthalpy(temperature=temperature_K, verbose=False)
    S_eV_per_K = thermo.get_entropy(
        temperature=temperature_K, pressure=pressure_Pa, verbose=False
    )
    G_eV = thermo.get_gibbs_energy(
        temperature=temperature_K, pressure=pressure_Pa, verbose=False
    )
    TS_eV = temperature_K * S_eV_per_K

    # eV → Hartree
    eV_per_Eh = C.get("hartree_to_eV").value
    return {
        "zpe_Eh": zpe_Eh,
        "h_corr_Eh": float(H_eV / eV_per_Eh),
        "ts_Eh": float(TS_eV / eV_per_Eh),
        "g_corr_Eh": float(G_eV / eV_per_Eh),
        "temperature_K": temperature_K,
        "pressure_Pa": pressure_Pa,
        "method": "ASE-IdealGasThermo",
    }


# ──────────────────────────────────────────────────────────────────────
# Boltzmann 权重（多构象平均必备）
# ──────────────────────────────────────────────────────────────────────

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
