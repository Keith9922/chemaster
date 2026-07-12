"""chem.calc_psi4 — psi4 单点能 MCP server。

single_point tool 的参考实现。
详见 docs/MCP_GUIDE.md。
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from chemaster.mcp.calc_psi4.parsers import (
    get_ir_intensities as _get_ir_intensities,
)
from chemaster.mcp.calc_psi4.parsers import (
    parse_frequencies_from_output as _parse_frequencies_from_output,
)
from chemaster.mcp.calc_psi4.parsers import (
    parse_opt_iterations_from_output as _parse_opt_iterations_from_output,
)
from chemaster.mcp.calc_psi4.parsers import (
    parse_tdscf_from_output as _parse_tdscf_from_output,
)
from chemaster.mcp.calc_psi4.parsers import (
    parse_thermal_from_output as _parse_thermal_from_output,
)

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
    lines = [ln.strip() for ln in xyz.strip().split("\n") if ln.strip()]
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
            "Ca": 20, "Fe": 26, "Zn": 30, "Cu": 29,
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
    lines = [ln for ln in xyz.strip().splitlines() if ln.strip()]
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
        ) from None

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


def _psi4_session(
    geometry_xyz: str,
    charge: int,
    multiplicity: int,
    memory_gb: float,
    n_threads: int,
    log_name: str,
    options: dict[str, Any],
):
    """为一次工具调用准备隔离的 psi4 会话。

    psi4 的 options / scratch 是进程级全局状态：不重置的话，同进程里上一个
    工具设置的选项会泄漏进来（实测：TD-opt 留下的 optking + tdscf 选项会毒化
    随后的普通 tddft 调用，表现为依赖测试顺序的失败）。

    输出日志写到每次调用独立的临时目录——并发调用不会互相覆盖，CWD 也不再
    被 *_output.log 弄脏。

    Returns:
        (psi4 module, psi4 version str, molecule handle, output log path)
    """
    import psi4
    from psi4 import __version__ as psi4_version

    try:
        psi4.core.clean()  # 清掉上一次计算的 scratch
    except Exception:
        pass
    psi4.core.clean_options()  # 所有选项回到 psi4 默认值

    psi4.set_memory(f"{int(memory_gb)} GB")
    psi4.set_num_threads(n_threads)

    out_dir = Path(tempfile.mkdtemp(prefix="chemaster_psi4_"))
    output_path = str(out_dir / log_name)
    psi4.core.set_output_file(output_path, False)

    # 强制 symmetry c1 防对称性突跳（PITFALLS §2.6）。
    # psi4.geometry() 会以副作用方式设置全局 active molecule。
    geom_block = _xyz_to_geom_block(geometry_xyz, charge, multiplicity)
    mol = psi4.geometry(geom_block)

    psi4.set_options(options)
    return psi4, psi4_version, mol, output_path


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
    reference = "uhf" if multiplicity != 1 else "rhf"
    psi4, psi4_version, _mol, output_path = _psi4_session(
        geometry_xyz, charge, multiplicity, memory_gb, n_threads,
        "single_point_output.log",
        {
            "reference": reference,
            "scf_type": "df",
            "guess": scf_guess.lower(),
        },
    )

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
    reference = "uhf" if multiplicity != 1 else "rhf"
    # `mol` is needed downstream by psi4.optimize() and mol.save_string_xyz().
    psi4, psi4_version, mol, output_path = _psi4_session(
        geometry_xyz, charge, multiplicity, memory_gb, n_threads,
        "optimize_output.log",
        {
            "g_convergence": g_convergence,
            "geom_maxiter": max_iter,
            "opt_coordinates": opt_coordinates,
            "scf_type": "df",
            "reference": reference,
        },
    )

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
    reference = "uhf" if multiplicity != 1 else "rhf"
    # `mol` is needed downstream as the `molecule=` arg of psi4.frequencies().
    psi4, psi4_version, mol, output_path = _psi4_session(
        geometry_xyz, charge, multiplicity, memory_gb, n_threads,
        "frequency_output.log",
        {
            "reference": reference,
            "scf_type": "df",
        },
    )

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
        # `energy_hartree` is captured for symmetry only — the wfn already
        # carries it. Real callers should use wfn.energy().
        if isinstance(raw, tuple) and len(raw) == 2:
            _, wfn_from_call = raw
        else:
            wfn_from_call = None

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
                ) from None
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

    reference = "uhf" if multiplicity != 1 else "rhf"
    psi4, psi4_version, _mol, output_path = _psi4_session(
        geometry_xyz, charge, multiplicity, memory_gb, n_threads,
        "tddft_output.log",
        {
            "reference": reference,
            "scf_type": "df",
            "tdscf_states": int(n_states),
            "tdscf_triplets": "ALSO" if triplets else "NONE",
            "tdscf_tda": bool(tda),
        },
    )

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


@mcp.tool()
def optimize_excited_state(
    geometry_xyz: str,
    target_state: int = 1,
    target_spin: str = "singlet",
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "B3LYP-D3(BJ)",
    basis: str = "def2-SVP",
    n_states: int = 3,
    convergence: str = "normal",
    coordinate_system: str = "internal",
    max_iter: int = 100,
    memory_gb: float = 4.0,
    n_threads: int = 1,
) -> dict[str, Any]:
    """Excited-state geometry optimization (TDA only, psi4).

    Optimizes a TDA excited-state root via psi4's `td-{method}` driver +
    finite-difference gradients (psi4 1.10 has no analytic TDDFT gradient,
    so this falls back to FD — slow but works for small/medium molecules).

    Use this AFTER `optimize` (ground state) to get **adiabatic** S1/T1
    geometries. Adiabatic ΔE_ST = E(T1@T1_geom) - E(S1@S1_geom) is the
    physically correct singlet-triplet gap for TADF, vs the *vertical*
    ΔE_ST you get from one-shot `tddft` on the S0 geometry.

    Args:
        geometry_xyz: starting geometry (usually the optimized S0 geometry).
        target_state: which excited root to optimize (1 = S1 / T1, 2 = S2 / T2,
            ...). Must satisfy 1 ≤ target_state ≤ n_states.
        target_spin: "singlet" or "triplet". For triplet opt, the underlying
            TDA reference stays restricted (RHF) but `tdscf_triplets="ONLY"`
            is used; the final wavefunction represents the triplet excited
            state on top of the closed-shell GS.
        charge / multiplicity: GROUND state charge / multiplicity. The
            excited state is built on top of this reference. Triplet excited
            states require multiplicity=1 (closed-shell GS).
        method: DFT functional. `td-{method}` is sent to the driver. For
            charge-transfer states (TADF donor-acceptor), prefer ωB97X-D
            over B3LYP — see PITFALLS §2.7.
        basis: basis set; def2-SVP for screening, def2-TZVP for publication.
        n_states: how many excited roots TDDFT should solve at each opt
            step. Must be ≥ target_state. More states cost more memory but
            stabilize root following.
        convergence: opt convergence preset (loose / normal / tight /
            very_tight). normal is recommended for excited states because
            tight + finite-difference gradients = very slow.
        coordinate_system: internal / redundant_internal / cartesian.
        max_iter: max optimization steps.
        memory_gb / n_threads: as for `optimize`.

    Returns:
        ok=True:
          {
            "ok": True,
            "result": {
              "target_state": int,
              "target_spin": str,
              "final_total_energy": {"value": float, "unit": "Hartree"},
                  # GROUND-STATE energy at the optimized excited-state geometry
                  # (psi4's td-{method} driver returns E_GS, not E_S1!).
                  # To get the absolute S1/T1 energy:
                  #   E_excited_abs = final_total_energy
                  #                 + excitation_energy_at_opt / hartree_to_eV
              "excitation_energy_at_opt": {"value": float, "unit": "eV"} | null,
                  # E(target) - E(GS) at the OPTIMIZED excited-state geometry;
                  # subtract from the vertical excitation to get the geometry-
                  # relaxation contribution (ΔE_relax = ΔE_vert − ΔE_adiab)
                  # which is what feeds into the Stokes shift.
                  # null if not parseable
              "optimized_geometry_xyz": str,
              "n_iterations": int,
              "converged": bool,
            },
            "warnings": [...],
            "meta": {...},
          }
        ok=False:
          {"ok": False, "error_code": "...", "details": str, "suggestion": str}

    Error codes:
        - INVALID_TARGET_STATE: target_state out of range or n_states < target_state.
        - SCF_NOT_CONVERGED, GEOMETRY_NOT_CONVERGED, INVALID_MULTIPLICITY,
          PSI4_INTERNAL_ERROR (same semantics as `optimize`).
        - TDDFT_GRADIENT_UNAVAILABLE: tda=False was requested or analytic
          gradient missing for this combination. Currently we always use TDA
          (psi4 1.10 supports TDA gradients only; full TDDFT gradients are
          NYI). Suggestion: stick with TDA.

    Notes:
        - Cost: psi4 1.10 uses finite-difference gradients (3-point), so each
          opt step costs ~3·N_atom TDDFT energies. For 3-atom H2O at sto-3g
          this finishes in ~10 s; for a 50-atom TADF at def2-SVP this is
          1-2 hours. Plan accordingly.
        - The `tda` flag is forced True. Full TDDFT (RPA) opt is not
          supported by psi4 1.10.
        - **Starting-geometry sensitivity**: if the GS-optimized geometry is
          a stationary point on the excited-state PES (common when the GS and
          S1/T1 minima share a high-symmetry geometry), OPTKING may converge
          in 1 step without actually relaxing on the excited state. For
          molecules known to break symmetry on excitation (e.g. HCHO S1
          pyramidalizes), pre-perturb the input geometry slightly along the
          expected distortion mode (~0.2 Å on relevant atoms) to nudge the
          optimizer onto the excited-state PES. The ``n_iterations`` field
          can be used to detect this: ``< 3`` macro steps from a GS-optimized
          start usually means the optimizer never left the GS minimum.
        - To recover the S1 → S0 emission (Stokes-shifted) energy in eV:
          ``E_emission_eV = excitation_energy_at_opt["value"]``
          (this is the vertical S1→S0 gap *at the S1 geometry*).

    Examples:
        >>> r = optimize_excited_state(
        ...     opt_xyz, target_state=1, target_spin="singlet",
        ...     method="ωB97X-D", basis="def2-SVP", n_states=3)
        >>> r["result"]["converged"]
        True
        >>> r["result"]["target_state"]
        1
    """
    # ── 1. arg sanity ──────────────────────────────────────────────────
    if target_spin not in ("singlet", "triplet"):
        return {
            "ok": False,
            "error_code": "INVALID_TARGET_STATE",
            "details": f"target_spin must be 'singlet' or 'triplet', got {target_spin!r}",
            "suggestion": "Use target_spin='singlet' for S1/S2/..., 'triplet' for T1/T2/...",
        }
    if target_state < 1 or target_state > n_states:
        return {
            "ok": False,
            "error_code": "INVALID_TARGET_STATE",
            "details": (
                f"target_state={target_state} is out of range "
                f"[1, n_states={n_states}]."
            ),
            "suggestion": (
                "Set n_states ≥ target_state. For TADF S1 opt use "
                "target_state=1, n_states=3 (extra states stabilize root following)."
            ),
        }

    n_el = _electron_count(geometry_xyz, charge)
    valid, err_msg = _validate_multiplicity(multiplicity, n_el)
    if not valid:
        return {
            "ok": False,
            "error_code": "INVALID_MULTIPLICITY",
            "details": err_msg,
            "suggestion": "Excited-state opt requires a closed-shell GS reference (multiplicity=1).",
        }
    if multiplicity != 1:
        return {
            "ok": False,
            "error_code": "INVALID_MULTIPLICITY",
            "details": (
                f"Excited-state TDA opt requires closed-shell singlet GS "
                f"(multiplicity=1); got multiplicity={multiplicity}."
            ),
            "suggestion": (
                "For open-shell GS (radicals, high-spin) use a different workflow; "
                "TDA on top of UHF is not supported by this MCP."
            ),
        }

    # ── 2. convergence + coords mapping (same as `optimize`) ──────────
    g_convergence_map = {
        "loose": "gau_loose", "normal": "gau",
        "tight": "gau_tight", "very_tight": "gau_verytight",
    }
    g_convergence = g_convergence_map.get(convergence.lower(), "gau")
    opt_coords_map = {
        "internal": "INTERNAL",
        "redundant_internal": "REDUNDANT_INTERNAL",
        "cartesian": "CARTESIAN",
    }
    opt_coordinates = opt_coords_map.get(coordinate_system.lower(), "INTERNAL")

    # Pass tdscf_states as a length-1 list matching c1 symmetry's single irrep.
    # Plain int triggers psi4's internal expansion which can mis-fire
    # during the FD-gradient driver loop and yield ValidationError
    # "States requested ([3, 3]) do not match number of irreps (1)".
    psi4, psi4_version, mol, output_path = _psi4_session(
        geometry_xyz, charge, multiplicity, memory_gb, n_threads,
        "optimize_es_output.log",
        {
            "reference": "rhf",
            "scf_type": "df",
            "tdscf_states": [int(n_states)],
            "tdscf_tda": True,
            "tdscf_triplets": "ONLY" if target_spin == "triplet" else "NONE",
            "follow_root": int(target_state),
            "g_convergence": g_convergence,
            "geom_maxiter": int(max_iter),
            "opt_coordinates": opt_coordinates,
        },
    )

    wall_start = time.time()
    warnings: list[str] = []
    final_total_energy: float | None = None
    optimized_xyz: str | None = None
    converged = False

    try:
        td_method = method if method.lower().startswith("td-") else f"td-{method}"
        e_total = psi4.optimize(td_method, basis=basis, molecule=mol)
        final_total_energy = float(e_total)
        optimized_xyz = mol.save_string_xyz()
        converged = True
    except psi4.OptimizationConvergenceError as e:
        wall_time = time.time() - wall_start
        try:
            optimized_xyz = mol.save_string_xyz()
        except Exception:
            pass
        return {
            "ok": False,
            "error_code": "GEOMETRY_NOT_CONVERGED",
            "details": f"Excited-state optimization did not converge: {e}",
            "suggestion": (
                "Excited-state PES is often shallower / has more saddles. Try: "
                "(1) loosen convergence to 'normal'; "
                "(2) start from a slightly distorted geometry "
                "(displace along the dominant TDDFT NTO); "
                "(3) reduce trust radius."
            ),
            "meta": {"psi4_version": psi4_version,
                     "wall_time_s": round(wall_time, 2),
                     "output_path": output_path},
        }
    except psi4.SCFConvergenceError as e:
        wall_time = time.time() - wall_start
        return {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "details": f"GS SCF did not converge during excited-state opt: {e}",
            "suggestion": (
                "Try guess=GWH, switch to def2-SVP first, or pre-converge with "
                "calc_psi4_single_point + damping."
            ),
            "meta": {"psi4_version": psi4_version,
                     "wall_time_s": round(wall_time, 2),
                     "output_path": output_path},
        }
    except Exception as exc:
        wall_time = time.time() - wall_start
        msg = str(exc).lower()
        if "index" in msg and "out of bounds" in msg:
            return {
                "ok": False,
                "error_code": "INVALID_TARGET_STATE",
                "details": (
                    f"psi4's TDA Davidson solver returned fewer roots than "
                    f"requested (n_states={n_states}). This usually means the "
                    f"system has fewer accessible excitations than n_states "
                    f"(common for very small systems or minimal basis)."
                ),
                "suggestion": (
                    "Reduce n_states, or use a larger basis (def2-SVP instead "
                    "of sto-3g)."
                ),
                "meta": {"psi4_version": psi4_version,
                         "wall_time_s": round(wall_time, 2),
                         "output_path": output_path},
            }
        logger.exception("psi4 optimize_excited_state internal error")
        return {
            "ok": False,
            "error_code": "PSI4_INTERNAL_ERROR",
            "details": f"{type(exc).__name__}: {exc}",
            "suggestion": (
                "Inspect the psi4 output log; common causes are missing TDA "
                "gradient for the chosen functional, basis without ECP for "
                "heavy atoms, or symmetry mishandling."
            ),
            "meta": {"psi4_version": psi4_version,
                     "wall_time_s": round(wall_time, 2),
                     "output_path": output_path},
        }

    wall_time = time.time() - wall_start

    # ── 3. parse the LAST TDDFT block from the log to get E_excitation
    # at the converged geometry.
    singlets, triplets = _parse_tdscf_from_output(
        output_path, want_triplets=(target_spin == "triplet")
    )
    pool = triplets if target_spin == "triplet" else singlets
    e_excitation_eV: float | None = None
    if pool and len(pool) >= target_state:
        e_excitation_eV = pool[target_state - 1]["excitation_energy"]["value"]

    # ── 4. opt iteration count from log ──────────────────────────────
    n_iter = _parse_opt_iterations_from_output(output_path)

    return {
        "ok": True,
        "result": {
            "target_state": target_state,
            "target_spin": target_spin,
            "final_total_energy": {
                "value": round(final_total_energy, 8), "unit": "Hartree"
            },
            "excitation_energy_at_opt": (
                {"value": round(e_excitation_eV, 4), "unit": "eV"}
                if e_excitation_eV is not None else None
            ),
            "optimized_geometry_xyz": optimized_xyz or "",
            "n_iterations": n_iter,
            "converged": converged,
            "method": method,
            "basis": basis,
            "tda": True,
        },
        "warnings": warnings,
        "meta": {
            "psi4_version": psi4_version,
            "wall_time_s": round(wall_time, 2),
            "output_path": output_path,
        },
    }


def main() -> None:
    """``chemaster-mcp calc_psi4`` 入口。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
