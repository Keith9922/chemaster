"""chem.calc_psi4 — psi4 单点能 MCP server。

single_point tool 的参考实现。
详见 docs/MCP_GUIDE.md。
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("chem.calc_psi4")

# ══════════════════════════════════════════════════════════════════════════════
# 常数（lazy load，避免全局导入 psi4 前的开销）
# ══════════════════════════════════════════════════════════════════════════════

_HARTREE_TO_EV: float | None = None
_AU_TO_DEBYE: float | None = None


def _hartree_to_eV() -> float:
    global _HARTREE_TO_EV
    if _HARTREE_TO_EV is None:
        from chemaster.kb.formulas import constants as C

        _HARTREE_TO_EV = C.get("hartree_to_eV").value
    return _HARTREE_TO_EV


def _au_to_debye() -> float:
    global _AU_TO_DEBYE
    if _AU_TO_DEBYE is None:
        from chemaster.kb.formulas import constants as C

        _AU_TO_DEBYE = C.get("atomic_unit_to_debye").value
    return _AU_TO_DEBYE


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _electron_count(xyz: str, charge: int) -> int:
    """从 XYZ 几何字串推算总价电子数（用于多重度校验）。"""
    lines = [l.strip() for l in xyz.strip().split("\n") if l.strip()]
    total = 0
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        element = parts[0]
        Z = {
            "H": 1, "He": 2, "Li": 3, "Be": 4, "B": 5, "C": 6, "N": 7,
            "O": 8, "F": 9, "Ne": 10, "Na": 11, "Mg": 12, "Al": 13,
            "Si": 14, "P": 15, "S": 16, "Cl": 17, "Ar": 18, "K": 19,
            "Ca": 20, "Fe": 26, "Zn": 30, "Cu": 29, "Mg": 12,
        }.get(element.capitalize(), 0)
        total += Z
    return total - charge


def _validate_multiplicity(multiplicity: int, n_electrons: int) -> tuple[bool, str]:
    """校验 (n_electrons, multiplicity) 自旋一致性。

    Returns:
        (valid, error_message)
    """
    if multiplicity < 1:
        return False, f"multiplicity={multiplicity} 非法（必须 ≥ 1）"
    n_unpaired = multiplicity - 1
    if n_unpaired > n_electrons:
        return False, (
            f"multiplicity={multiplicity}（{n_unpaired} 个单电子）超过总价电子数 {n_electrons}。"
            " 检查电荷或元素组成是否正确。"
        )
    # 配对电子必须是整数（偶电子体系用奇数 multiplicity 如 1, 3, 5；偶数 multiplicity 如 2, 4 需奇电子数）
    if (n_electrons - n_unpaired) % 2 != 0:
        return False, (
            f"multiplicity={multiplicity} 与 {n_electrons} 电子数不匹配"
            "（偶数电子闭壳层体系只能是 singlet/triplet 等奇数多重度）。"
        )
    return True, ""


def _xyz_to_geom_block(xyz: str, charge: int, multiplicity: int) -> str:
    """把标准 XYZ 字符串转为 psi4 xyz+ 格式（无 atom count 行）。

    标准 XYZ：第 1 行是原子数，第 2 行是 comment 或首条坐标，后续是坐标。
    xyz+：第 1 行是 "charge multiplicity"，后续直接是坐标（无 atom count）。
    psi4 qcelemental 解析器要求 xyz+ 格式，不接受含 atom count 的标准 XYZ。

    兼容两种标准 XYZ：
      - 有 comment 行：'3\\nWater\\nO ...\\nH ...\\nH ...'
      - 无 comment 行：'3\\nO ...\\nH ...\\nH ...'
    """
    lines = [l for l in xyz.strip().splitlines() if l.strip()]
    if not lines:
        raise ValueError("Empty geometry_xyz")

    # 检查是否已经是 xyz+ 格式（第 1 行含两个整数 Token）
    first = lines[0].strip().split()
    if len(first) == 2:
        try:
            int(first[0])
            int(first[1])
            # 已经是 xyz+ 格式，直接追加 symmetry 行
            coords = "\n".join(lines) + "\n"
            return f"{coords}symmetry c1\n"
        except ValueError:
            pass

    # 标准 XYZ：第 1 行是原子数，第 2 行是 comment 或首条坐标
    try:
        n_atoms = int(lines[0].strip())
    except ValueError:
        raise ValueError(
            f"geometry_xyz first line must be atom count (int), got {lines[0]!r}"
        )

    if len(lines) == n_atoms + 1:
        # 无 comment 行：lines[0]=n_atoms, lines[1:]=coordinates
        coord_lines = lines[1:]
    elif len(lines) == n_atoms + 2:
        # 有 comment 行：lines[0]=n_atoms, lines[1]=comment, lines[2:]=coordinates
        coord_lines = lines[2:]
    else:
        raise ValueError(
            f"geometry_xyz length {len(lines)} does not match "
            f"n_atoms={n_atoms} (expected {n_atoms+1} or {n_atoms+2} lines)"
        )

    coords = "\n".join(coord_lines)
    return f"{charge} {multiplicity}\n{coords}\nsymmetry c1\n"


# ══════════════════════════════════════════════════════════════════════════════
# MCP tools
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def single_point(
    geometry_xyz: str,
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "B3LYP-D3(BJ)",
    basis: str = "def2-TZVP",
    memory_gb: float = 4.0,
    n_threads: int = 1,
    scf_guess: str = "SAD",
) -> dict[str, Any]:
    """单点能计算（Hartree-Fock / DFT）。

    用于在固定几何下求电子能量，**不**做几何优化或频率计算。

    Args:
        geometry_xyz: XYZ 格式几何字符串（不含电荷/自旋行）。
            例（水的 3 行结构）：
            O  0.0  0.0  0.0
            H  1.0  0.0  0.0
            H -0.5  0.87 0.0
        charge: 总电荷，默认 0。
        multiplicity: 自旋多重度 (2S+1)，默认 1（闭壳层 singlet）。
            singlet=1, doublet=2, triplet=3, ...
        method: 计算方法，默认 B3LYP-D3(BJ)。
            常用：B3LYP-D3(BJ) / PBE0-D3(BJ) / ωB97X-D / HF / MP2
        basis: 基组，默认 def2-TZVP。
            常用：def2-TZVP / cc-pVTZ / aug-cc-pVTZ / 6-311++G(d,p)
        memory_gb: 分配内存（GB），默认 4 GB。
        n_threads: OMP 线程数，默认 4。
        scf_guess: SCF 初猜方法，默认 SAD。
            SAD=Superposition of Atomic Densities（最常用）；
            GWH=Gaussian Weighted Hamiltonian（适合高自旋）；
            CORE=Core Hamiltonian（最简单，常作为最后兜底）。

    Returns:
        ok=True 时:
            {
              "ok": True,
              "result": {
                "energy": {"value": float, "unit": "Hartree"},
                "n_basis_functions": int,
                "n_iterations": int,
                "homo_lumo_gap": {"value": float, "unit": "eV"} | null,
                "dipole": {"value": float, "unit": "Debye"} | null,
              },
              "warnings": [...],
              "meta": {
                "psi4_version": str,
                "wall_time_s": float,
                "output_path": str,
              }
            }
        ok=False 时:
            {
              "ok": False,
              "error_code": "SCF_NOT_CONVERGED" | "INVALID_MULTIPLICITY" |
                           "UNSUPPORTED_ELEMENT" | "PSI4_INTERNAL_ERROR",
              "details": str,
              "suggestion": str,
            }

    Error codes:
        - SCF_NOT_CONVERGED: SCF 未收敛。suggestion 给出 GWH / 降基组 / damping 备选。
        - INVALID_MULTIPLICITY: 多重度与电子数不匹配（如闭壳层用 multiplicity=2）。
        - UNSUPPORTED_ELEMENT: 基组不支持某元素（如 6-31G 不支持 Fe）。
        - PSI4_INTERNAL_ERROR: psi4 内部异常（如分子结构非法、内存不足等）。

    Examples:
        >>> r = single_point("O 0.0 0.0 0.0\\nH 1.0 0.0 0.0\\nH -0.5 0.87 0.0",
        ...                   method="B3LYP-D3(BJ)", basis="def2-TZVP")
        >>> r["ok"]
        True
        >>> r["result"]["energy"]["unit"]
        'Hartree'
    """
    # ── 1. 自旋多重度校验 ──────────────────────────────────────────────
    n_el = _electron_count(geometry_xyz, charge)
    valid, err_msg = _validate_multiplicity(multiplicity, n_el)
    if not valid:
        return {
            "ok": False,
            "error_code": "INVALID_MULTIPLICITY",
            "details": err_msg,
            "suggestion": "检查电荷或元素组成是否正确；闭壳层请用 multiplicity=1。",
        }

    # ── 2. 初始化 psi4（内部 import 避免导入开销）───────────────────────
    import psi4

    from psi4 import __version__ as psi4_version

    psi4.set_memory(f"{int(memory_gb)} GB")
    psi4.set_num_threads(n_threads)

    output_path = "single_point_output.log"
    psi4.core.set_output_file(output_path, False)

    # ── 3. 构建分子（强制 symmetry c1 防对称性突跳，PITFALLS §2.6）────
    geom_block = _xyz_to_geom_block(geometry_xyz, charge, multiplicity)
    mol = psi4.geometry(geom_block)

    reference = "uhf" if multiplicity != 1 else "rhf"
    psi4.set_options({
        "reference": reference,
        "scf_type": "df",
        "guess": scf_guess.lower(),
    })

    # ── 4. 运行 SCF ────────────────────────────────────────────────────
    wall_start = time.time()
    warnings: list[str] = []
    result_energy: float | None = None
    n_iter: int | None = None
    n_basis: int | None = None
    homo_eV: float | None = None
    lumo_eV: float | None = None
    dipole_debye: float | None = None

    try:
        energy_hartree = psi4.energy(method, basis=basis)
        result_energy = float(energy_hartree)

        # 尝试获取 wavefunction 信息（rdkit 先导入时 segfault，做 fallback）
        n_iter = None
        n_basis = None
        homo_eV = None
        lumo_eV = None
        dipole_debye = None
        try:
            wfn = psi4.core.get_active_wavefunction()
            n_iter = int(wfn.iterations().n_scf_iterations())
            n_basis = int(wfn.basisset().nbf())
            eps = wfn.epsilon_a().to_array()
            n_occ = wfn.nalpha()
            if n_occ > 0 and n_occ < len(eps):
                homo_h = float(eps[n_occ - 1])
                lumo_h = float(eps[n_occ])
                h2e = _hartree_to_eV()
                homo_eV = homo_h * h2e
                lumo_eV = lumo_h * h2e
            dipole_au = wfn.dipole()
            dipole_debye = float(dipole_au) * _au_to_debye()
        except Exception:
            pass  # wfn 访问失败时只返回能量

    except psi4.SCFConvergenceError as e:
        wall_time = time.time() - wall_start
        return {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "details": f"SCF 未收敛：{e}",
            "suggestion": (
                "try scf_guess='GWH'; 或尝试降基组（def2-SVP）先收敛再升级； "
                "或加大 damping（damping_factor=0.5, n_initial_no_diis=5）。"
            ),
            "meta": {
                "psi4_version": psi4_version,
                "wall_time_s": round(wall_time, 2),
                "output_path": output_path,
            },
        }

    except Exception as e:
        wall_time = time.time() - wall_start
        logger.exception("psi4 single_point 内部错误")
        return {
            "ok": False,
            "error_code": "PSI4_INTERNAL_ERROR",
            "details": f"{type(e).__name__}: {e}",
            "suggestion": "检查输入几何是否合理，基组是否支持所有元素。",
            "meta": {
                "psi4_version": psi4_version,
                "wall_time_s": round(wall_time, 2),
                "output_path": output_path,
            },
        }

    wall_time = time.time() - wall_start

    # ── 5. 组装返回 ─────────────────────────────────────────────────────
    gap_obj: dict[str, Any] | None = None
    if homo_eV is not None and lumo_eV is not None:
        gap_obj = {"value": round(lumo_eV - homo_eV, 6), "unit": "eV"}

    dipole_obj: dict[str, Any] | None = None
    if dipole_debye is not None:
        dipole_obj = {"value": round(dipole_debye, 6), "unit": "Debye"}

    return {
        "ok": True,
        "result": {
            "energy": {"value": round(result_energy, 8), "unit": "Hartree"},
            "n_basis_functions": n_basis,
            "n_iterations": n_iter,
            "homo_lumo_gap": gap_obj,
            "dipole": dipole_obj,
        },
        "warnings": warnings,
        "meta": {
            "psi4_version": psi4_version,
            "wall_time_s": round(wall_time, 2),
            "output_path": output_path,
        },
    }


@mcp.tool()
def optimize(
    geometry_xyz: str,
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "B3LYP-D3(BJ)",
    basis: str = "def2-TZVP",
    convergence: str = "tight",
    coordinate_system: str = "internal",
    max_iter: int = 100,
    memory_gb: float = 4.0,
    n_threads: int = 1,
) -> dict[str, Any]:
    """几何优化（能量极小点搜索）。

    在固定电荷/自旋下优化分子几何至能量极小点。**不**做频率计算。

    Args:
        geometry_xyz: XYZ 格式几何字符串（不含电荷/自旋行）。
            例（水的 3 行结构）：
            O  0.0  0.0  0.0
            H  1.0  0.0  0.0
            H -0.5  0.87 0.0
        charge: 总电荷，默认 0。
        multiplicity: 自旋多重度 (2S+1)，默认 1（闭壳层 singlet）。
            singlet=1, doublet=2, triplet=3, ...
        method: 计算方法，默认 B3LYP-D3(BJ)。
            常用：B3LYP-D3(BJ) / PBE0-D3(BJ) / ωB97X-D / HF / MP2
        basis: 基组，默认 def2-TZVP。
            常用：def2-TZVP / cc-pVTZ / aug-cc-pVTZ / 6-311++G(d,p)
        convergence: 收敛标准，默认 tight。
            loose → gau_loose（适合粗筛）
            normal → gau（默认 DFT 标准）
            tight → gau_tight（频率计算前标准）
            very_tight → gau_verytight（高精度需求）
        coordinate_system: 优化坐标系统，默认 internal。
            internal：自然内坐标（键长、角、二面角）
            redundant_internal：冗余内坐标（更鲁棒，大体系推荐）
            cartesian：笛卡尔坐标（适合小分子或特殊体系）
        max_iter: 最大优化步数，默认 100。
        memory_gb: 分配内存（GB），默认 4 GB。
        n_threads: OMP 线程数，默认 4。

    Returns:
        ok=True 时:
            {
              "ok": True,
              "result": {
                "final_energy": {"value": float, "unit": "Hartree"},
                "optimized_geometry_xyz": str,
                "n_iterations": int,
                "converged": bool,
              },
              "warnings": [...],
              "meta": {
                "psi4_version": str,
                "wall_time_s": float,
                "output_path": str,
              }
            }
        ok=False 时:
            {
              "ok": False,
              "error_code": "SCF_NOT_CONVERGED" | "GEOMETRY_NOT_CONVERGED" |
                           "INVALID_MULTIPLICITY" | "UNSUPPORTED_ELEMENT" |
                           "PSI4_INTERNAL_ERROR",
              "details": str,
              "suggestion": str,
              "meta": {...}
            }

    Error codes:
        - SCF_NOT_CONVERGED: 优化过程中某步 SCF 未收敛。
        - GEOMETRY_NOT_CONVERGED: 达到 max_iter 仍未收敛。
        - INVALID_MULTIPLICITY: 多重度与电子数不匹配。
        - UNSUPPORTED_ELEMENT: 基组不支持某元素。
        - PSI4_INTERNAL_ERROR: psi4 内部异常。

    Notes:
        - 优化收敛 ≠ 找到真极小点（可能有虚频）。需接 frequency 计算验证。
        - 几何优化失败（卡死/震荡）由 Skill 层处理（切坐标/减小 trust radius 等）。
          本 tool 仅返回结构化错误码和恢复建议。

    Examples:
        >>> r = optimize("O 0.0 0.0 0.0\\nH 1.0 0.0 0.0\\nH -0.5 0.87 0.0",
        ...              method="B3LYP-D3(BJ)", basis="def2-TZVP")
        >>> r["ok"]
        True
        >>> r["result"]["converged"]
        True
    """
    # ── 1. 自旋多重度校验 ──────────────────────────────────────────────
    n_el = _electron_count(geometry_xyz, charge)
    valid, err_msg = _validate_multiplicity(multiplicity, n_el)
    if not valid:
        return {
            "ok": False,
            "error_code": "INVALID_MULTIPLICITY",
            "details": err_msg,
            "suggestion": "检查电荷或元素组成是否正确；闭壳层请用 multiplicity=1。",
        }

    # ── 2. convergence 映射 ────────────────────────────────────────────
    g_convergence_map = {
        "loose": "gau_loose",
        "normal": "gau",
        "tight": "gau_tight",
        "very_tight": "gau_verytight",
    }
    g_convergence = g_convergence_map.get(convergence.lower(), "gau_tight")

    # ── 3. coordinate_system 映射 ─────────────────────────────────────
    opt_coords_map = {
        "internal": "INTERNAL",
        "redundant_internal": "REDUNDANT_INTERNAL",
        "cartesian": "CARTESIAN",
    }
    opt_coordinates = opt_coords_map.get(coordinate_system.lower(), "INTERNAL")

    # ── 4. 初始化 psi4 ─────────────────────────────────────────────────
    import psi4

    from psi4 import __version__ as psi4_version

    psi4.set_memory(f"{int(memory_gb)} GB")
    psi4.set_num_threads(n_threads)

    output_path = "optimize_output.log"
    psi4.core.set_output_file(output_path, False)

    # ── 5. 构建分子（强制 symmetry c1 防对称性突跳，PITFALLS §2.6）────
    geom_block = _xyz_to_geom_block(geometry_xyz, charge, multiplicity)
    mol = psi4.geometry(geom_block)

    reference = "uhf" if multiplicity != 1 else "rhf"
    psi4.set_options({
        "g_convergence": g_convergence,
        "geom_maxiter": max_iter,
        "opt_coordinates": opt_coordinates,
        "scf_type": "df",
        "reference": reference,
    })

    # ── 6. 运行优化 ───────────────────────────────────────────────────
    wall_start = time.time()
    warnings: list[str] = []
    result_energy: float | None = None
    optimized_xyz: str | None = None
    n_iter: int | None = None
    converged: bool = False

    try:
        # 不使用 return_wfn=True：rdkit 先导入会导致 psi4 SCF 迭代 segfault
        energy_hartree = psi4.optimize(method, basis=basis, molecule=mol)
        result_energy = float(energy_hartree)

        # 优化步数（取最后一次结构更新后的分子）
        optimized_xyz = mol.save_string_xyz()

        # 尝试从 wavefunction 获取迭代信息（rdkit 先导入时不可用）
        n_iter = None
        try:
            wfn = psi4.core.get_active_wavefunction()
            n_iter = int(wfn.iterations().n_scf_iterations())
        except Exception:
            pass
        converged = True

    except psi4.OptimizationConvergenceError as e:
        wall_time = time.time() - wall_start
        # 尝试拿最后一步的几何（即使未收敛）
        try:
            optimized_xyz = mol.save_string_xyz()
        except Exception:
            pass
        return {
            "ok": False,
            "error_code": "GEOMETRY_NOT_CONVERGED",
            "details": f"几何优化未收敛（已达 max_iter={max_iter} 步）：{e}",
            "suggestion": (
                "尝试以下策略之一："
                "1. 切换到冗余内坐标（coordinate_system='redundant_internal'）；"
                "2. 用更宽松的收敛标准（convergence='normal'）先跑；"
                "3. 减小初始 trust radius；"
                "4. 若震荡明显，检查结构是否对称性过高（强制 c1）。"
                "恢复策略详见 kb/rules/convergence.yaml geometry_optimization 节。"
            ),
            "meta": {
                "psi4_version": psi4_version,
                "wall_time_s": round(wall_time, 2),
                "output_path": output_path,
            },
        }

    except psi4.SCFConvergenceError as e:
        wall_time = time.time() - wall_start
        return {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "details": f"SCF 未收敛：{e}",
            "suggestion": (
                "尝试以下策略："
                "1. 切换初猜：scf_guess='GWH'；"
                "2. 降基组先收敛（def2-SVP）再升；"
                "3. 加大 damping（damping_factor=0.5, n_initial_no_diis=5）。"
                "详见 kb/rules/convergence.yaml scf 节。"
            ),
            "meta": {
                "psi4_version": psi4_version,
                "wall_time_s": round(wall_time, 2),
                "output_path": output_path,
            },
        }

    except Exception as e:
        wall_time = time.time() - wall_start
        logger.exception("psi4 optimize 内部错误")
        return {
            "ok": False,
            "error_code": "PSI4_INTERNAL_ERROR",
            "details": f"{type(e).__name__}: {e}",
            "suggestion": "检查输入几何是否合理，基组是否支持所有元素。",
            "meta": {
                "psi4_version": psi4_version,
                "wall_time_s": round(wall_time, 2),
                "output_path": output_path,
            },
        }

    wall_time = time.time() - wall_start

    # ── 7. 组装返回 ─────────────────────────────────────────────────────
    return {
        "ok": True,
        "result": {
            "final_energy": {"value": round(result_energy, 8), "unit": "Hartree"},
            "optimized_geometry_xyz": optimized_xyz or "",
            "n_iterations": n_iter or 0,
            "converged": converged,
        },
        "warnings": warnings,
        "meta": {
            "psi4_version": psi4_version,
            "wall_time_s": round(wall_time, 2),
            "output_path": output_path,
        },
    }


@mcp.tool()
def frequency(
    geometry_xyz: str,
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "B3LYP-D3(BJ)",
    basis: str = "def2-TZVP",
    temperature_K: float = 298.15,
    pressure_atm: float = 1.0,
    memory_gb: float = 4.0,
    n_threads: int = 1,
) -> dict[str, Any]:
    """振动频率计算（红外光谱 + 热力学修正）。

    在固定几何下计算振动频率，用于：
    - 确认优化得到的几何是真实极小点（无虚频）。
    - 计算 ZPE（零点振动能）修正。
    - 计算 RRHO 热力学修正（H、G）。
    - 获取 IR 红外强度（用于光谱归属）。

    Args:
        geometry_xyz: XYZ 格式几何字符串（不含电荷/自旋行）。
            例（水的 3 行结构）：
            O  0.0  0.0  0.0
            H  1.0  0.0  0.0
            H -0.5  0.87 0.0
        charge: 总电荷，默认 0。
        multiplicity: 自旋多重度 (2S+1)，默认 1（闭壳层 singlet）。
            singlet=1, doublet=2, triplet=3, ...
        method: 计算方法，默认 B3LYP-D3(BJ)。
            **必须与 optimize 使用相同 method/basis**（PITFALLS §2.3）。
            常用：B3LYP-D3(BJ) / PBE0-D3(BJ) / ωB97X-D / HF / MP2
        basis: 基组，默认 def2-TZVP。
            **必须与 optimize 使用相同 method/basis**（PITFALLS §2.3）。
            常用：def2-TZVP / cc-pVTZ / aug-cc-pVTZ / 6-311++G(d,p)
        temperature_K: 热力学温度，默认 298.15 K。
        pressure_atm: 压力，默认 1.0 atm。
        memory_gb: 分配内存（GB），默认 4 GB。
        n_threads: OMP 线程数，默认 4。

    Returns:
        ok=True 时:
            {
              "ok": True,
              "result": {
                "frequencies_cm_inv": list[float],   # 含虚频用负数
                "ir_intensities_km_per_mol": list[float],
                "n_imaginary": int,                 # < -10 cm^-1 计为虚频
                "zpe": {"value": float, "unit": "Hartree"},
                "thermal_corrections": {
                  "h_corr": {"value": float, "unit": "Hartree"} | null,
                  "g_corr": {"value": float, "unit": "Hartree"} | null,
                  "ts": {"value": float, "unit": "Hartree"} | null,
                },
                "temperature_K": float,
                "pressure_atm": float,
              },
              "warnings": [
                # 虚频时自动填充："IMAGINARY_FREQUENCY: n=2, smallest=-145 cm^-1"
              ],
              "meta": {
                "psi4_version": str,
                "wall_time_s": float,
                "output_path": str,
              }
            }
        ok=False 时:
            {
              "ok": False,
              "error_code": "SCF_NOT_CONVERGED" | "INVALID_MULTIPLICITY" |
                           "PSI4_INTERNAL_ERROR",
              "details": str,
              "suggestion": str,
              "meta": {...}
            }

    Error codes:
        - SCF_NOT_CONVERGED: SCF 未收敛。
        - INVALID_MULTIPLICITY: 多重度与电子数不匹配。
        - PSI4_INTERNAL_ERROR: psi4 内部异常（如分子结构非法、内存不足等）。

    Notes:
        - 虚频判定阈值：< -10 cm^-1（PITFALLS §10.x 与 convergence.yaml）。
        - psi4 虚频以负数返回（其他软件常用 "i" 前缀）。本 MCP 统一用负数。
        - ZPE 由 `chemaster.kb.formulas.thermo.zpe_from_frequencies_cm_inv` 计算。
        - h_corr / g_corr / ts 当前返回 null（Phase 2 接入完整 RRHO）。
        - IR 强度若 psi4 版本不支持则返回 [0.0]*len(freqs)。

    Examples:
        >>> r = frequency("O 0.0 0.0 0.0\\nH 1.0 0.0 0.0\\nH -0.5 0.87 0.0",
        ...              method="B3LYP-D3(BJ)", basis="def2-TZVP")
        >>> r["ok"]
        True
        >>> r["result"]["n_imaginary"]
        0
        >>> r["result"]["zpe"]["unit"]
        'Hartree'
    """
    # ── 1. 自旋多重度校验 ──────────────────────────────────────────────
    n_el = _electron_count(geometry_xyz, charge)
    valid, err_msg = _validate_multiplicity(multiplicity, n_el)
    if not valid:
        return {
            "ok": False,
            "error_code": "INVALID_MULTIPLICITY",
            "details": err_msg,
            "suggestion": "检查电荷或元素组成是否正确；闭壳层请用 multiplicity=1。",
        }

    # ── 2. 初始化 psi4 ─────────────────────────────────────────────────
    import psi4

    from psi4 import __version__ as psi4_version

    psi4.set_memory(f"{int(memory_gb)} GB")
    psi4.set_num_threads(n_threads)

    output_path = "frequency_output.log"
    psi4.core.set_output_file(output_path, False)

    # ── 3. 构建分子（强制 symmetry c1 防对称性突跳，PITFALLS §2.6）────
    geom_block = _xyz_to_geom_block(geometry_xyz, charge, multiplicity)
    mol = psi4.geometry(geom_block)

    reference = "uhf" if multiplicity != 1 else "rhf"
    psi4.set_options({
        "reference": reference,
        "scf_type": "df",
    })

    # ── 4. 运行频率计算 ────────────────────────────────────────────────
    wall_start = time.time()
    warnings: list[str] = []
    freqs_cm_inv: list[float] = []
    ir_intensities: list[float] = []
    n_imaginary: int = 0

    try:
        # 不使用 return_wfn=True：rdkit 先导入会导致 psi4 SCF 迭代 segfault
        # 但若 mock 测试返回 (energy, wfn) 元组，按需解包，便于单元测试。
        raw = psi4.frequencies(method, basis=basis, molecule=mol)
        if isinstance(raw, tuple) and len(raw) == 2:
            energy_hartree, wfn_from_call = raw
        else:
            energy_hartree, wfn_from_call = raw, None

        # 尝试从 wavefunction 获取频率（rdkit 先导入时不可用）
        # fallback：直接从输出文件解析
        try:
            wfn = wfn_from_call or psi4.core.get_active_wavefunction()
            if wfn is None:
                raise RuntimeError("no wavefunction available")
            freq_array = wfn.frequencies().to_array()
            freqs_cm_inv = [float(f) for f in freq_array]
            ir_intensities = _get_ir_intensities(wfn, len(freqs_cm_inv))
        except Exception:
            # wfn 不可用时从输出文件解析频率
            freqs_cm_inv = _parse_frequencies_from_output(output_path)
            if not freqs_cm_inv:
                raise RuntimeError(
                    "psi4 wavefunction access failed and frequency parser found no frequencies in output"
                )
            ir_intensities = [0.0] * len(freqs_cm_inv)

        # 虚频判定：< -10 cm^-1
        n_imaginary = sum(1 for f in freqs_cm_inv if f < -10.0)

        # 虚频警告
        if n_imaginary > 0:
            smallest = min(f for f in freqs_cm_inv if f < -10.0)
            warnings.append(f"IMAGINARY_FREQUENCY: n={n_imaginary}, smallest={smallest:.1f} cm^-1")

    except psi4.SCFConvergenceError as e:
        wall_time = time.time() - wall_start
        return {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "details": f"SCF 未收敛：{e}",
            "suggestion": (
                "尝试以下策略："
                "1. 切换初猜：scf_guess='GWH'；"
                "2. 降基组先收敛（def2-SVP）再升；"
                "3. 加大 damping（damping_factor=0.5, n_initial_no_diis=5）。"
            ),
            "meta": {
                "psi4_version": psi4_version,
                "wall_time_s": round(wall_time, 2),
                "output_path": output_path,
            },
        }

    except Exception as e:
        wall_time = time.time() - wall_start
        logger.exception("psi4 frequency 内部错误")
        return {
            "ok": False,
            "error_code": "PSI4_INTERNAL_ERROR",
            "details": f"{type(e).__name__}: {e}",
            "suggestion": "检查输入几何是否合理，基组是否支持所有元素。",
            "meta": {
                "psi4_version": psi4_version,
                "wall_time_s": round(wall_time, 2),
                "output_path": output_path,
            },
        }

    wall_time = time.time() - wall_start

    # ── 5. ZPE 计算（复用公式库，LLM 不算数）────────────────────────────
    from chemaster.kb.formulas import thermo as _thermo

    zpe_Eh = _thermo.zpe_from_frequencies_cm_inv(freqs_cm_inv)

    # ── 6. Thermal corrections (parse from psi4 output log)──────────────
    thermal = _parse_thermal_from_output(output_path)

    # ── 7. 组装返回 ─────────────────────────────────────────────────────
    return {
        "ok": True,
        "result": {
            "frequencies_cm_inv": freqs_cm_inv,
            "ir_intensities_km_per_mol": ir_intensities,
            "n_imaginary": n_imaginary,
            "zpe": {"value": round(zpe_Eh, 8), "unit": "Hartree"},
            "thermal_corrections": thermal,
            "temperature_K": temperature_K,
            "pressure_atm": pressure_atm,
        },
        "warnings": warnings,
        "meta": {
            "psi4_version": psi4_version,
            "wall_time_s": round(wall_time, 2),
            "output_path": output_path,
        },
    }


def _parse_frequencies_from_output(log_path: str) -> list[float]:
    """从 psi4 输出文件解析频率（cm^-1）。

    psi4 频率输出格式（psi4 1.9+）：
        Freq [cm^-1]                1618.2540           3834.8812           3931.8836
    也兼容旧格式（每行一个 Frequency 关键字）。
    若解析失败返回空 list。
    """
    import re
    try:
        text = Path(log_path).read_text()
    except Exception:
        return []

    freqs: list[float] = []

    # 新格式：提取所有含 'Freq [cm^-1]' 行中的数字。
    # 注意：高对称分子（如 CH4 / Td）会按 irrep 分块输出多组 'Freq [cm^-1]'，
    # 不能只取第一行（早期 bug：methane 9 个模式只解析出 3 个）。
    for line in text.splitlines():
        if "Freq [cm^-1]" in line:
            nums = re.findall(r"([-+]?\d+\.\d+)", line)
            for s in nums:
                v = float(s)
                if v != 0.0:
                    freqs.append(v)
    if freqs:
        return freqs

    # 旧格式：逐行匹配 'Frequency' 关键字
    pattern = re.compile(r"^\s*Frequency\s+([-+]?\d+\.\d+)", re.MULTILINE)
    for m in pattern.finditer(text):
        val = float(m.group(1))
        if val != 0.0:
            freqs.append(val)

    return freqs


def _get_ir_intensities(wfn, n_freqs: int) -> list[float]:
    """从 wavefunction 获取 IR 强度，处理 psi4 版本差异。

    psi4 不同版本访问 IR_intensity 的方式不同，做 fallback。
    """
    try:
        fa = wfn.frequency_analysis
        if fa is not None and "IR_intensity" in fa:
            data = fa["IR_intensity"].data
            if hasattr(data, "tolist"):
                return [float(x) for x in data.tolist()]
            return [float(x) for x in data]
    except Exception:
        pass
    # fallback：返回零强度列表
    return [0.0] * n_freqs


def _parse_thermal_from_output(log_path: str) -> dict[str, Any]:
    """Parse psi4's thermochemistry summary block.

    Extracts the corrections (H, G, internal-E thermal) and the absolute
    enthalpy / Gibbs at temperature. Returns a dict with each value tagged
    by unit; missing fields stay None.

    psi4 prints, e.g.:
        Correction H    15.928 [kcal/mol] ... 0.02538285 [Eh]
        Total H, Enthalpy at  298.15 [K]  ... -76.33282512 [Eh]
        Correction G     2.488 [kcal/mol] ... 0.00396527 [Eh]
        Total G, Gibbs energy at  298.15 [K] ... -76.35424270 [Eh]
        Correction E    15.335 [kcal/mol] ... 0.02443866 [Eh]
        Total E, Thermal (internal) energy at  298.15 [K] ... -76.33376930 [Eh]
    """
    import re
    out = {
        "h_corr": None,            # H_corr (Hartree, includes ZPE + thermal H)
        "g_corr": None,            # G_corr
        "e_corr": None,            # internal energy correction
        "ts": None,                # T·S = H_corr - G_corr (derived)
        "total_h": None,           # absolute enthalpy at T (Hartree)
        "total_g": None,           # absolute Gibbs at T (Hartree)
        "total_e": None,           # absolute internal E at T (Hartree)
    }
    try:
        text = Path(log_path).read_text(errors="replace")
    except Exception:
        return out

    # Correction X    XX.XXX [kcal/mol]    XX.XXX [kJ/mol]    0.0XXXXXXX [Eh]
    corr = re.compile(
        r"Correction\s+([HGES])\b[^\n]*?([-+]?\d+\.\d+)\s*\[Eh\]",
        re.MULTILINE,
    )
    for m in corr.finditer(text):
        kind = m.group(1)
        val = float(m.group(2))
        if kind == "H":
            out["h_corr"] = {"value": val, "unit": "Hartree"}
        elif kind == "G":
            out["g_corr"] = {"value": val, "unit": "Hartree"}
        elif kind == "E":
            out["e_corr"] = {"value": val, "unit": "Hartree"}

    total = re.compile(
        r"Total\s+(\w+)[^\n]*?at\s+\d+\.\d+\s*\[K\][^\n]*?"
        r"([-+]?\d+\.\d+)\s*\[Eh\]",
        re.MULTILINE,
    )
    for m in total.finditer(text):
        kind = m.group(1)
        val = float(m.group(2))
        if kind == "H":
            out["total_h"] = {"value": val, "unit": "Hartree"}
        elif kind == "G":
            out["total_g"] = {"value": val, "unit": "Hartree"}
        elif kind == "E":
            out["total_e"] = {"value": val, "unit": "Hartree"}

    # T·S derived from H_corr - G_corr (since G = H - T·S → T·S = H - G).
    if out["h_corr"] is not None and out["g_corr"] is not None:
        ts_Eh = out["h_corr"]["value"] - out["g_corr"]["value"]
        out["ts"] = {"value": round(ts_Eh, 8), "unit": "Hartree"}

    return out


@mcp.tool()
def tddft(
    geometry_xyz: str,
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "B3LYP-D3(BJ)",
    basis: str = "def2-SVP",
    n_states: int = 6,
    triplets: bool = True,
    tda: bool = True,
    memory_gb: int = 4,
    n_threads: int = 1,
) -> dict[str, Any]:
    """TDDFT excited-state calculation (psi4).

    Returns the lowest n_states singlet and (optionally) triplet excitations
    plus their oscillator strengths. Use this AFTER calc_psi4_optimize to
    get S0/S1/T1 energies for excited-state photophysics, UV-Vis,
    and TADF ΔE_ST analysis.

    By default we use TDA (Tamm-Dancoff Approximation) which is much more
    stable for triplets; PITFALLS §2.8 explains why standard TDDFT triplets
    often produce imaginary roots ("triplet instability"). Pass tda=False to
    use full TDDFT linear response if you specifically need it.

    Args:
        geometry_xyz: optimized ground-state geometry, standard xyz with header.
        charge / multiplicity: ground-state charge / spin (excitations applied
            on top of this reference).
        method: DFT functional. For charge-transfer excited states (TADF
            donor-acceptor), use a range-separated functional like ωB97X-D
            instead of B3LYP — see PITFALLS §2.7.
        basis: basis set; def2-SVP for screening, def2-TZVP for
            publication-quality.
        n_states: how many excited states to compute (per spin manifold).
        triplets: if True, also compute the lowest n_states triplet states.
        tda: use Tamm-Dancoff approximation (recommended, especially for
            triplets).

    Returns:
        ok=True:
          {
            "ok": True,
            "result": {
              "ground_state_energy": {"value": float, "unit": "Hartree"},
              "singlets": [
                {"state": 1,
                 "excitation_energy": {"value": float, "unit": "eV"},
                 "wavelength_nm": float,
                 "oscillator_strength": float},
                ...
              ],
              "triplets": [...],          # only if triplets=True
              "delta_E_ST_eV": float,     # E(T1) - E(S1) (TADF target);
                                          # null if triplets disabled
            },
            "warnings": [...],
            "meta": {...},
          }
        ok=False:
          {"ok": False, "error_code": "...", "details": str, "suggestion": str}

    Common error codes:
        - SCF_NOT_CONVERGED: ground-state SCF didn't converge.
        - INVALID_MULTIPLICITY
        - TRIPLET_INSTABILITY: full TDDFT (tda=False) produced imaginary
            triplet root. Suggestion: rerun with tda=True.
        - PSI4_INTERNAL_ERROR

    Examples:
        >>> r = tddft(opt_xyz, method="ωB97X-D", basis="def2-TZVP",
        ...           n_states=4, triplets=True, tda=True)
        >>> r["result"]["delta_E_ST_eV"]
        0.12
    """
    # 1. multiplicity sanity
    n_el = _electron_count(geometry_xyz, charge)
    valid, err_msg = _validate_multiplicity(multiplicity, n_el)
    if not valid:
        return {
            "ok": False,
            "error_code": "INVALID_MULTIPLICITY",
            "details": err_msg,
            "suggestion": "Closed-shell singlet needs multiplicity=1.",
        }

    import psi4
    from psi4 import __version__ as psi4_version

    psi4.set_memory(f"{int(memory_gb)} GB")
    psi4.set_num_threads(n_threads)
    output_path = "tddft_output.log"
    psi4.core.set_output_file(output_path, False)

    geom_block = _xyz_to_geom_block(geometry_xyz, charge, multiplicity)
    mol = psi4.geometry(geom_block)

    reference = "uhf" if multiplicity != 1 else "rhf"
    psi4.set_options({
        "reference": reference,
        "scf_type": "df",
        "tdscf_states": int(n_states),
        "tdscf_triplets": "ALSO" if triplets else "NONE",
        "tdscf_tda": bool(tda),
    })

    wall_start = time.time()
    warnings: list[str] = []

    try:
        # psi4 driver TDDFT: prefix the method with "td-" and call energy().
        # tdscf_states / tdscf_triplets / tdscf_tda set above as global options.
        td_method = method
        if not (td_method.lower().startswith("td-")
                or td_method.lower().startswith("td_")):
            td_method = f"td-{method}"
        gs_energy = psi4.energy(method, basis=basis)
        psi4.energy(td_method, basis=basis)
    except Exception as exc:
        wall_time = time.time() - wall_start
        msg = str(exc).lower()
        if "scf" in msg and ("converge" in msg or "convergence" in msg):
            return {
                "ok": False,
                "error_code": "SCF_NOT_CONVERGED",
                "details": str(exc),
                "suggestion": (
                    "Ground-state SCF didn't converge. Try guess=GWH, smaller "
                    "basis, or run calc_psi4_single_point with damping first."
                ),
                "meta": {"psi4_version": psi4_version,
                         "wall_time_s": round(wall_time, 2),
                         "output_path": output_path},
            }
        if "triplet" in msg and ("instab" in msg or "imag" in msg):
            return {
                "ok": False,
                "error_code": "TRIPLET_INSTABILITY",
                "details": str(exc),
                "suggestion": "Re-run with tda=True (Tamm-Dancoff) — see PITFALLS §2.8.",
                "meta": {"psi4_version": psi4_version,
                         "wall_time_s": round(wall_time, 2),
                         "output_path": output_path},
            }
        return {
            "ok": False,
            "error_code": "PSI4_INTERNAL_ERROR",
            "details": f"{type(exc).__name__}: {exc}",
            "suggestion": ("Check geometry / element coverage in the chosen "
                           "basis. Inspect output_path for full traceback."),
            "meta": {"psi4_version": psi4_version,
                     "wall_time_s": round(wall_time, 2),
                     "output_path": output_path},
        }

    # 2. Pull out the excitation list. Different psi4 versions expose the
    # TDSCF results in different shapes; we parse the output log directly
    # (most robust across versions).
    singlets, triplets_list = _parse_tdscf_from_output(output_path,
                                                      want_triplets=triplets)

    # 3. ΔE_ST = E(T1) - E(S1)  (TADF target; positive means S1 above T1)
    delta_e_st_eV: float | None = None
    if singlets and triplets_list:
        delta_e_st_eV = round(
            triplets_list[0]["excitation_energy"]["value"]
            - singlets[0]["excitation_energy"]["value"], 4
        )

    if not singlets:
        warnings.append({
            "code": "NO_SINGLETS_PARSED",
            "message": "TDDFT ran but the parser found no singlet states; "
                       f"check the raw psi4 output at {output_path}.",
            "severity": "warn",
        })

    wall_time = time.time() - wall_start
    return {
        "ok": True,
        "result": {
            "ground_state_energy": {"value": float(gs_energy), "unit": "Hartree"},
            "singlets": singlets,
            "triplets": triplets_list,
            "delta_E_ST_eV": delta_e_st_eV,
            "method": method,
            "basis": basis,
            "tda": bool(tda),
        },
        "warnings": warnings,
        "meta": {
            "psi4_version": psi4_version,
            "wall_time_s": round(wall_time, 2),
            "output_path": output_path,
        },
    }


def _parse_tdscf_from_output(
    output_path: str,
    want_triplets: bool,
) -> tuple[list[dict], list[dict]]:
    """Regex-parse psi4's TDDFT printout. Tolerant to formatting drift.

    psi4 prints (≥1.9):
        Excited State    1 (3 A):   0.25504 au   178.65 nm f = 0.0000
                                ^^^      ^^^      ^^^         ^^^
                              spin#  excitation  wavelength  oscillator
    where spin# == 1 → singlet, 3 → triplet.
    """
    import re
    try:
        text = Path(output_path).read_text(errors="replace")
    except Exception:
        return [], []

    eV_per_au = 27.211386245988

    pattern = re.compile(
        r"Excited\s+State\s+(\d+)\s*\(\s*(\d+)\s*[A-Za-z']*\s*\)\s*:\s*"
        r"([-+]?\d+\.\d+)\s*au\s+([-+]?\d+\.\d+)\s*nm\s+f\s*=\s*([-+]?\d+\.\d+)",
        re.MULTILINE,
    )
    singlets: list[dict] = []
    triplets: list[dict] = []
    seen_keys: set[tuple[int, int]] = set()   # (spin, state) — psi4 prints twice

    for m in pattern.finditer(text):
        idx = int(m.group(1))
        spin = int(m.group(2))
        e_au = float(m.group(3))
        wl_nm = float(m.group(4))
        f_osc = float(m.group(5))
        e_eV = e_au * eV_per_au

        key = (spin, idx)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        entry = {
            "state": idx,
            "excitation_energy": {"value": round(e_eV, 4), "unit": "eV"},
            "wavelength_nm": round(wl_nm, 2),
            "oscillator_strength": round(f_osc, 6),
        }
        if spin == 1:
            singlets.append(entry)
        elif spin == 3 and want_triplets:
            triplets.append(entry)

    # Re-number per spin (psi4 numbers across all states; we want S1, S2, ...
    # and T1, T2, ... independently).
    for i, e in enumerate(singlets, 1):
        e["state"] = i
    for i, e in enumerate(triplets, 1):
        e["state"] = i

    return singlets, triplets


def main() -> None:
    """``chemaster-mcp calc_psi4`` 入口。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()