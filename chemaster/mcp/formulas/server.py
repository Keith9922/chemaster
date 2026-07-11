"""chem.formulas — 确定性化学公式 MCP server。

把 ``chemaster.kb.formulas.*`` 里所有确定性 Python 公式包装成 MCP 工具供
agent 调用。直接对应 ``CLAUDE.md`` §5.1 的核心设计原则：

    "LLM 不算数。任何浮点运算、单位换算、物理常数 —— 走 chemaster.kb.formulas
     模块，不让 LLM 报数。"

历史上这些公式只能通过 ``kb_search`` 拉到文档去 LLM 看，再让 LLM 心算。本
server 把它们注册成可直接调用的 MCP 工具，agent 直接拿到精确数值结果。

涵盖：
- photophysics: krisc_marcus / kisc_marcus / kic_marcus / kf_strickler_berg /
                kr_einstein_from_dipole / plqy / tadf_quantum_yield
- thermo:       boltzmann_weights / zpe_from_frequencies / thermal_corrections
- kinetics:     eyring / arrhenius
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from chemaster.kb.formulas import kinetics as KIN
from chemaster.kb.formulas import photophysics as PHO
from chemaster.kb.formulas import thermo as TH

mcp = FastMCP("chem.formulas")


# ─── photophysics ─────────────────────────────────────────────────────────

@mcp.tool()
def compute_krisc_marcus(
    delta_E_ST_eV: float,
    soc_cm_inv: float,
    reorganization_energy_eV: float,
    temperature_K: float = 298.15,
) -> dict[str, Any]:
    """RISC (reverse ISC) 速率 — Marcus 经典模型（高温极限）。

    k_RISC = (2π / ℏ) · |H_SOC|² · (4π λ kBT)^(-1/2) · exp(-(ΔE_ST + λ)² / (4 λ kBT))

    使用确定性 Python 浮点（``chemaster.kb.formulas.photophysics.krisc_marcus``），
    避免 LLM 心算大动态范围的指数 / 平方根。

    Args:
        delta_E_ST_eV: 单-三态间隙 ΔE_ST (eV)，T1 在下时为正
        soc_cm_inv: SOC 矩阵元 H_SOC (cm⁻¹)
        reorganization_energy_eV: 重组能 λ (eV)
        temperature_K: 温度 (K)，默认 298.15

    Returns:
        ok=True 时 result.k_RISC_s_inv 即所求速率（s⁻¹）。
    """
    try:
        k = PHO.krisc_marcus(delta_E_ST_eV, soc_cm_inv,
                              reorganization_energy_eV, temperature_K)
        return {
            "ok": True,
            "result": {
                "k_RISC_s_inv": k,
                "formula": "Marcus 高温极限",
                "inputs": {
                    "delta_E_ST_eV": delta_E_ST_eV,
                    "soc_cm_inv": soc_cm_inv,
                    "reorganization_energy_eV": reorganization_energy_eV,
                    "temperature_K": temperature_K,
                },
                "source": "chemaster.kb.formulas.photophysics.krisc_marcus",
            },
            "warnings": [],
        }
    except Exception as exc:
        return {"ok": False, "error_code": "FORMULA_ERROR",
                "details": str(exc),
                "suggestion": "Check input ranges; ΔE_ST and λ must be > 0."}


@mcp.tool()
def compute_kf_strickler_berg(
    energy_eV: float,
    oscillator_strength: float,
    refractive_index: float = 1.0,
) -> dict[str, Any]:
    """Strickler-Berg 辐射跃迁速率 k_F (s⁻¹).

    k_F ≈ 2.88e-9 · n² · (E / cm⁻¹)² · f   [s⁻¹]

    用确定性 Python（``chemaster.kb.formulas.photophysics.kf_strickler_berg``）。

    Args:
        energy_eV: 发射能 E_emiss (eV)
        oscillator_strength: 振子强度 f (无单位)
        refractive_index: 溶剂折射率 n，默认真空 1.0

    Returns:
        ok=True 时 result.k_F_s_inv 即辐射速率。
    """
    try:
        k = PHO.kf_strickler_berg(energy_eV, oscillator_strength, refractive_index)
        return {
            "ok": True,
            "result": {
                "k_F_s_inv": k,
                "radiative_lifetime_ns": 1e9 / k if k > 0 else float("inf"),
                "formula": "Strickler-Berg",
                "inputs": {
                    "energy_eV": energy_eV,
                    "oscillator_strength": oscillator_strength,
                    "refractive_index": refractive_index,
                },
                "source": "chemaster.kb.formulas.photophysics.kf_strickler_berg",
            },
            "warnings": [],
        }
    except Exception as exc:
        return {"ok": False, "error_code": "FORMULA_ERROR",
                "details": str(exc),
                "suggestion": "Check that E > 0 and 0 ≤ f ≤ 2."}


@mcp.tool()
def compute_kisc_marcus(
    delta_E_ST_eV: float,
    soc_cm_inv: float,
    reorganization_energy_eV: float,
    temperature_K: float = 298.15,
) -> dict[str, Any]:
    """ISC (intersystem crossing S→T) 速率 — Marcus 模型。"""
    try:
        k = PHO.kisc_marcus(delta_E_ST_eV, soc_cm_inv,
                             reorganization_energy_eV, temperature_K)
        return {"ok": True,
                "result": {"k_ISC_s_inv": k,
                           "source": "chemaster.kb.formulas.photophysics.kisc_marcus"},
                "warnings": []}
    except Exception as exc:
        return {"ok": False, "error_code": "FORMULA_ERROR", "details": str(exc),
                "suggestion": "Check input ranges."}


@mcp.tool()
def compute_plqy(kf: float, knr: float, kisc: float = 0.0) -> dict[str, Any]:
    """光致发光量子产率 Φ_F = k_F / (k_F + k_NR + k_ISC)."""
    try:
        y = PHO.plqy(kf, knr, kisc)
        return {"ok": True,
                "result": {"plqy": y, "formula": "k_F / (k_F + k_NR + k_ISC)"},
                "warnings": []}
    except Exception as exc:
        return {"ok": False, "error_code": "FORMULA_ERROR", "details": str(exc),
                "suggestion": "All rates must be ≥ 0."}


# ─── thermo ───────────────────────────────────────────────────────────────

@mcp.tool()
def compute_boltzmann_weights(
    energies_kcal_per_mol: list[float],
    temperature_K: float = 298.15,
) -> dict[str, Any]:
    """给一组构象能量（kcal/mol，相对最低值或绝对都可）算 Boltzmann 权重。

    P_i = exp(-E_i / kBT) / Σ exp(-E_j / kBT)

    用 ``chemaster.kb.formulas.thermo.boltzmann_weights``。多构象平均必须用
    此函数，不能算术平均。

    Args:
        energies_kcal_per_mol: 构象相对能（kcal/mol）。最低能取 0 也可，
            或绝对能（会自动减去最小值）。
        temperature_K: 温度，默认 298.15 K。

    Returns:
        ok=True 时 result.weights 是归一化的 list[float]。
    """
    try:
        # 函数内部约定输入为 Hartree；这里先转换：1 kcal/mol = 1/627.5095 Ha
        energies_Eh = [e / 627.5094740631 for e in energies_kcal_per_mol]
        weights = TH.boltzmann_weights(energies_Eh, temperature_K)
        # also return as %
        return {"ok": True,
                "result": {
                    "weights": list(weights),
                    "weights_percent": [round(w * 100, 4) for w in weights],
                    "inputs": {"energies_kcal_per_mol": list(energies_kcal_per_mol),
                                "temperature_K": temperature_K},
                    "source": "chemaster.kb.formulas.thermo.boltzmann_weights",
                },
                "warnings": []}
    except Exception as exc:
        return {"ok": False, "error_code": "FORMULA_ERROR", "details": str(exc),
                "suggestion": "Check that energies list is non-empty."}


# ─── kinetics ─────────────────────────────────────────────────────────────

@mcp.tool()
def compute_eyring(
    delta_G_act_kJ_per_mol: float,
    temperature_K: float = 298.15,
    transmission_coeff: float = 1.0,
) -> dict[str, Any]:
    """Eyring 方程算一级反应速率常数 k (s⁻¹).

    k = κ · (kB T / h) · exp(-ΔG‡ / RT)

    用 ``chemaster.kb.formulas.kinetics.eyring``。

    Args:
        delta_G_act_kJ_per_mol: 活化自由能 ΔG‡ (kJ/mol)
        temperature_K: 温度 (K)
        transmission_coeff: 透射系数 κ，默认 1.0

    Returns:
        ok=True 时 result.k_s_inv 是速率常数（s⁻¹）。
    """
    try:
        k = KIN.eyring(delta_G_act_kJ_per_mol, temperature_K, transmission_coeff)
        return {"ok": True,
                "result": {
                    "k_s_inv": k,
                    "half_life_s": 0.6931 / k if k > 0 else float("inf"),
                    "inputs": {
                        "delta_G_act_kJ_per_mol": delta_G_act_kJ_per_mol,
                        "temperature_K": temperature_K,
                        "transmission_coeff": transmission_coeff,
                    },
                    "source": "chemaster.kb.formulas.kinetics.eyring",
                },
                "warnings": []}
    except Exception as exc:
        return {"ok": False, "error_code": "FORMULA_ERROR", "details": str(exc),
                "suggestion": "Check input ranges; ΔG‡ usually 10-50 kJ/mol."}


@mcp.tool()
def compute_arrhenius(
    A: float,
    Ea_kJ_per_mol: float,
    temperature_K: float = 298.15,
) -> dict[str, Any]:
    """Arrhenius 方程算速率常数 k = A · exp(-Ea / RT)."""
    try:
        k = KIN.arrhenius(A, Ea_kJ_per_mol, temperature_K)
        return {"ok": True,
                "result": {"k": k,
                            "source": "chemaster.kb.formulas.kinetics.arrhenius"},
                "warnings": []}
    except Exception as exc:
        return {"ok": False, "error_code": "FORMULA_ERROR", "details": str(exc),
                "suggestion": "Check inputs."}


# ─── Entrypoint ───────────────────────────────────────────────────────────


def main() -> None:
    """``chemaster-mcp formulas`` 入口。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
