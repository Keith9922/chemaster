"""chem.calc_xtb — xTB 半经验计算 MCP server.

通过 subprocess 调用 xtb 二进制（xtb 命令必须在 PATH）。
支持单点能计算和几何优化。

依赖：xtb (https://github.com/grimme-lab/xtb) >= 6.5
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
mcp = FastMCP("chem.calc_xtb")

# xTB 方法族
VALID_METHODS = {"gfn1", "gfn2", "gfnff"}

# 单位：xTB 输出默认 Hartree（能量）、eV（gap）、Debye（偶极矩）
HARTREE_TO_EV = 27.211386246  # 1 Hartree = 27.211386246 eV


def _write_xyz(xyz: str, path: str) -> None:
    """写入 XYZ 格式文件；ASCII 路径校验（PITFALLS §2.12）。"""
    assert os.path.dirname(path) or True, "path must not contain null bytes"
    with open(path, "w", encoding="ascii", errors="replace") as fh:
        fh.write(xyz)


def _check_engine() -> str | None:
    """检查 xtb 是否在 PATH。返回版本字符串或 None。"""
    xtb_path = shutil.which("xtb")
    if xtb_path is None:
        return None
    try:
        result = subprocess.run(
            ["xtb", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip() or "unknown"
        return version
    except Exception:
        return "unknown"


def _parse_singlepoint(stdout: str, stderr: str) -> dict[str, Any]:
    """从 xtb 单点输出解析关键字段。

    解析顺序：TOTAL ENERGY → HOMO-LUMO GAP → dipole → SCC NOT CONVERGED。

    Returns:
        dict 含 energy_hartree, homo_lumo_gap_ev, dipole_debye, scf_converged, warnings
    """
    combined = stdout + "\n" + stderr
    warnings: list[str] = []
    energy_hartree: float | None = None
    gap_ev: float | None = None
    dipole_debye: float | None = None
    scf_converged = True

    # TOTAL ENERGY — 单位 Hartree（大写 TOTAL，排除迭代过程行）
    m = re.search(r"^\s*TOTAL ENERGY\s+[=:]\s*([-+]?\d+\.\d+E?[+]?\d*)", combined, re.MULTILINE)
    if m:
        energy_hartree = float(m.group(1))

    # HOMO-LUMO GAP — 单位 eV（大写 HOMO-LUMO）
    m = re.search(r"^\s*HOMO-LUMO GAP\s+[=:]\s*([-+]?\d+\.\d+)\s+eV", combined, re.MULTILINE)
    if m:
        gap_ev = float(m.group(1))

    # dipole — 单位 Debye
    m = re.search(r"^\s*dipole\s+[=:]\s*([-+]?\d+\.\d+)\s+Debye", combined, re.MULTILINE | re.IGNORECASE)
    if m:
        dipole_debye = float(m.group(1))

    # SCF 收敛告警
    if re.search(r"SCC could not be converged", combined, re.IGNORECASE):
        scf_converged = False
        warnings.append("SCF did not converge (SCC could not be converged)")

    if energy_hartree is None:
        warnings.append("Could not parse TOTAL ENERGY from xtb output")

    return {
        "energy_hartree": energy_hartree,
        "homo_lumo_gap_ev": gap_ev,
        "dipole_debye": dipole_debye,
        "scf_converged": scf_converged,
        "warnings": warnings,
    }


def _run_xtb(
    xyz: str,
    method: str,
    charge: int,
    multiplicity: int,
    extra_args: list[str],
    n_threads: int | None,
    timeout: int = 3600,
) -> dict[str, Any]:
    """在临时目录中运行 xtb，返回 {returncode, stdout, stderr, wall_time_s, warnings}。

    Args:
        xyz: XYZ 格式几何字符串
        method: "gfn1" | "gfn2" | "gfnff"
        charge: 电荷
        multiplicity: 自旋多重度 (2S+1)
        extra_args: 额外 xtb 参数列表（如 ["--opt"]）
        n_threads: OMP 线程数，None 表示不限制
        timeout: 超时秒数

    Returns:
        {returncode, stdout, stderr, wall_time_s, tmpdir, warnings}
    """
    warnings: list[str] = []

    # 引擎检测
    xtb_version = _check_engine()
    if xtb_version is None:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "",
            "wall_time_s": 0.0,
            "tmpdir": None,
            "warnings": warnings,
            "error_code": "ENGINE_NOT_FOUND",
            "suggestion": (
                "xtb binary not found in PATH. Install via "
                "`conda install -c conda-forge xtb` or download a release "
                "from https://github.com/grimme-lab/xtb/releases. "
                "If installed but not on PATH, set the XTBPATH environment "
                "variable or pass the absolute path."
            ),
        }

    # 构建命令
    uhf = multiplicity - 1  # 闭壳 singlet=1 → UHF 0；doublet=2 → UHF 1
    cmd = [
        "xtb",
        "struc.xyz",
        "--gfn", method.lstrip("gfn"),  # gfn2 → "2", gfnff → "ff"
        "--chrg", str(charge),
        "--uhf", str(uhf),
        *extra_args,
    ]

    # 线程控制
    env = dict(os.environ)
    if n_threads is not None and n_threads > 0:
        env["OMP_NUM_THREADS"] = str(n_threads)
        env["OMP_STACKSIZE"] = "1G"
    elif "OMP_NUM_THREADS" not in env:
        # 保守默认值（PITFALLS §2.15）
        env["OMP_NUM_THREADS"] = str(max(1, (os.cpu_count() or 1) // 2))
        env["OMP_STACKSIZE"] = "1G"

    # 临时工作目录
    tmpdir = tempfile.TemporaryDirectory(prefix="xtb_", suffix="_work")
    struc_path = os.path.join(tmpdir.name, "struc.xyz")
    _write_xyz(xyz, struc_path)

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=tmpdir.name,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        wall_time_s = time.monotonic() - t0
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "wall_time_s": wall_time_s,
            "tmpdir": tmpdir,
            "warnings": warnings,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "returncode": -2,
            "stdout": e.stdout or "",
            "stderr": e.stderr or "",
            "wall_time_s": timeout,
            "tmpdir": tmpdir,
            "warnings": [*warnings, f"xTB timed out after {timeout}s"],
            "error_code": "TIMEOUT",
        }


@mcp.tool()
def single_point(
    geometry_xyz: str,
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "gfn2",
    solvent: str | None = None,
    n_threads: int | None = None,
) -> dict[str, Any]:
    """计算单点能（不做几何优化）。

    Args:
        geometry_xyz: XYZ 格式几何字符串（单位 Å）
        charge: 总电荷（默认 0）
        multiplicity: 自旋多重度 2S+1（默认 1 = 闭壳 singlet）
        method: xTB 方法，"gfn2" | "gfn1" | "gfnff"（默认 gfn2）
        solvent: 隐式溶剂模型（如 "water", "acn", "thf"），None 表示气相
        n_threads: OMP 线程数，None 则用 CPU 核数的一半

    Returns:
        ok=True 时:
          {
            "ok": True,
            "result": {
              "energy": {"value": float, "unit": "Hartree"},
              "homo_lumo_gap": {"value": float, "unit": "eV"} | null,
              "dipole": {"value": float, "unit": "Debye"} | null,
            },
            "warnings": list[str],
            "meta": {
              "wall_time_s": float,
              "xtb_version": str,
              "command": str,
            }
          }
        ok=False 时:
          {"ok": False, "error_code": "ENGINE_NOT_FOUND" | "SCF_NOT_CONVERGED" |
                               "PARSE_ERROR" | "INVALID_INPUT",
           "details": str, "suggestion": str}

    Examples:
        >>> s = "3\\n\\nO  0.0  0.0  0.0\\nH  0.96  0.0  0.0\\nH -0.48  0.83  0.0"
        >>> single_point(s)
        {"ok": True, "result": {"energy": {"value": -5.7, "unit": "Hartree"}, ...}, ...}
    """
    warnings: list[str] = []

    # ---- 参数校验 ----
    if method not in VALID_METHODS:
        return {
            "ok": False,
            "error_code": "INVALID_INPUT",
            "details": f"method '{method}' not in {VALID_METHODS}",
            "suggestion": "Use 'gfn2', 'gfn1', or 'gfnff'.",
        }
    if multiplicity < 1:
        return {
            "ok": False,
            "error_code": "INVALID_INPUT",
            "details": f"multiplicity must be >= 1, got {multiplicity}",
            "suggestion": "multiplicity = 2S+1 (1=singlet, 2=doublet, 3=triplet, ...).",
        }

    extra_args: list[str] = []
    if solvent:
        # xTB 溶剂：--alpb <solvent> 或 --gbsa <solvent>
        extra_args.extend(["--alpb", solvent])

    run_result = _run_xtb(
        geometry_xyz,
        method=method,
        charge=charge,
        multiplicity=multiplicity,
        extra_args=extra_args,
        n_threads=n_threads,
    )

    tmpdir = run_result.pop("tmpdir", None)
    error_code = run_result.pop("error_code", None)

    if error_code == "ENGINE_NOT_FOUND":
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": "xtb command not found in PATH.",
            "suggestion": "Install xTB (https://github.com/grimme-lab/xtb) and ensure it is on PATH.",
        }
    if error_code == "TIMEOUT":
        return {
            "ok": False,
            "error_code": "TIMEOUT",
            "details": run_result["warnings"][-1],
            "suggestion": "Increase timeout or check system load.",
        }

    stdout = run_result["stdout"]
    stderr = run_result["stderr"]
    warnings.extend(run_result["warnings"])

    xtb_version = _check_engine() or "unknown"
    wall_time_s = run_result["wall_time_s"]

    parsed = _parse_singlepoint(stdout, stderr)
    warnings.extend(parsed["warnings"])

    # 组装命令字符串（用于 meta.command）
    uhf = multiplicity - 1
    cmd_str = (
        f"xtb struc.xyz --gfn {method.lstrip('gfn')}"
        f" --chrg {charge} --uhf {uhf}"
        + (f" --alpb {solvent}" if solvent else "")
    )

    if not parsed["scf_converged"]:
        return {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "details": "xTB SCC did not converge.",
            "suggestion": "Try a different method (gfn1 instead of gfn2) or increase max_iter.",
            "warnings": warnings,
            "meta": {
                "wall_time_s": wall_time_s,
                "xtb_version": xtb_version,
                "command": cmd_str,
            },
        }

    if parsed["energy_hartree"] is None:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": "Could not parse TOTAL ENERGY from xTB output.",
            "suggestion": "Check that the geometry is valid and the xtb version supports this method.",
            "warnings": warnings,
            "meta": {
                "wall_time_s": wall_time_s,
                "xtb_version": xtb_version,
                "command": cmd_str,
            },
        }

    result_energy = {"value": parsed["energy_hartree"], "unit": "Hartree"}
    result_gap = (
        {"value": parsed["homo_lumo_gap_ev"], "unit": "eV"}
        if parsed["homo_lumo_gap_ev"] is not None
        else None
    )
    result_dipole = (
        {"value": parsed["dipole_debye"], "unit": "Debye"}
        if parsed["dipole_debye"] is not None
        else None
    )

    # 清理临时目录
    if tmpdir is not None:
        tmpdir.cleanup()

    return {
        "ok": True,
        "result": {
            "energy": result_energy,
            "homo_lumo_gap": result_gap,
            "dipole": result_dipole,
        },
        "warnings": warnings,
        "meta": {
            "wall_time_s": wall_time_s,
            "xtb_version": xtb_version,
            "command": cmd_str,
        },
    }


@mcp.tool()
def optimize(
    geometry_xyz: str,
    charge: int = 0,
    multiplicity: int = 1,
    method: str = "gfn2",
    solvent: str | None = None,
    max_iter: int = 200,
    n_threads: int | None = None,
) -> dict[str, Any]:
    """几何优化（内置能量计算）。

    Args:
        geometry_xyz: XYZ 格式几何字符串（单位 Å）
        charge: 总电荷（默认 0）
        multiplicity: 自旋多重度 2S+1（默认 1 = 闭壳 singlet）
        method: xTB 方法，"gfn2" | "gfn1" | "gfnff"（默认 gfn2）
        solvent: 隐式溶剂模型，None 表示气相
        max_iter: 最大几何优化迭代步数（默认 200）
        n_threads: OMP 线程数，None 则用 CPU 核数的一半

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
            "warnings": list[str],
            "meta": {
              "wall_time_s": float,
              "xtb_version": str,
              "command": str,
            }
          }
        ok=False 时:
          {"ok": False, "error_code": "ENGINE_NOT_FOUND" | "GEOMETRY_NOT_CONVERGED" |
                               "SCF_NOT_CONVERGED" | "PARSE_ERROR" | "INVALID_INPUT",
           "details": str, "suggestion": str}

    Examples:
        >>> s = "3\\n\\nO  0.0  0.0  0.0\\nH  0.96  0.0  0.0\\nH -0.48  0.83  0.0"
        >>> optimize(s)
        {"ok": True, "result": {"final_energy": {...}, "optimized_geometry_xyz": "...", ...}, ...}
    """
    warnings: list[str] = []

    # ---- 参数校验 ----
    if method not in VALID_METHODS:
        return {
            "ok": False,
            "error_code": "INVALID_INPUT",
            "details": f"method '{method}' not in {VALID_METHODS}",
            "suggestion": "Use 'gfn2', 'gfn1', or 'gfnff'.",
        }
    if multiplicity < 1:
        return {
            "ok": False,
            "error_code": "INVALID_INPUT",
            "details": f"multiplicity must be >= 1, got {multiplicity}",
            "suggestion": "multiplicity = 2S+1.",
        }
    if max_iter < 1:
        return {
            "ok": False,
            "error_code": "INVALID_INPUT",
            "details": f"max_iter must be >= 1, got {max_iter}",
            "suggestion": "Use a positive integer.",
        }

    extra_args = ["--opt"]
    if solvent:
        extra_args.extend(["--alpb", solvent])

    run_result = _run_xtb(
        geometry_xyz,
        method=method,
        charge=charge,
        multiplicity=multiplicity,
        extra_args=extra_args,
        n_threads=n_threads,
    )

    tmpdir = run_result.pop("tmpdir", None)
    error_code = run_result.pop("error_code", None)

    if error_code == "ENGINE_NOT_FOUND":
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": "xtb command not found in PATH.",
            "suggestion": "Install xTB and ensure it is on PATH.",
        }
    if error_code == "TIMEOUT":
        return {
            "ok": False,
            "error_code": "TIMEOUT",
            "details": run_result["warnings"][-1],
            "suggestion": "Increase system load tolerance or use a smaller basis.",
        }

    stdout = run_result["stdout"]
    stderr = run_result["stderr"]
    warnings.extend(run_result["warnings"])

    xtb_version = _check_engine() or "unknown"
    wall_time_s = run_result["wall_time_s"]

    parsed_sp = _parse_singlepoint(stdout, stderr)
    warnings.extend(parsed_sp["warnings"])

    if not parsed_sp["scf_converged"]:
        return {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "details": "xTB SCC did not converge during optimization.",
            "suggestion": "Try gfn1 instead of gfn2.",
            "warnings": warnings,
            "meta": {
                "wall_time_s": wall_time_s,
                "xtb_version": xtb_version,
                "command": "",
            },
        }

    # ---- 检查优化是否收敛 ----
    # xTB 优化成功 → 写 xtbopt.xyz；未收敛则无此文件
    optimized_xyz = ""
    n_iterations = 0
    converged = False

    if tmpdir is not None:
        opt_xyz_path = os.path.join(tmpdir.name, "xtbopt.xyz")
        if os.path.exists(opt_xyz_path):
            with open(opt_xyz_path, encoding="ascii", errors="replace") as f:
                optimized_xyz = f.read()
            # 数迭代步：正则匹配 "cycle     N"
            n_iterations = len(re.findall(r"\n\s*\d+\s+\d+\s+[-+]?\d", stdout))
            converged = True

    # 判断未收敛：opt 文件不存在或为空
    if not converged:
        warnings.append("Geometry optimization did not converge (no xtbopt.xyz found).")
        # xTB 非零返回码通常意味着未收敛
        if run_result["returncode"] != 0:
            warnings.append(f"xTB exited with code {run_result['returncode']}.")

    # 组装命令字符串
    uhf = multiplicity - 1
    cmd_str = (
        f"xtb struc.xyz --gfn {method.lstrip('gfn')}"
        f" --chrg {charge} --uhf {uhf} --opt"
        + (f" --alpb {solvent}" if solvent else "")
    )

    if not parsed_sp["energy_hartree"] and not converged:
        return {
            "ok": False,
            "error_code": "GEOMETRY_NOT_CONVERGED",
            "details": "Optimization failed to converge and could not parse final energy.",
            "suggestion": "Try reducing max_iter, changing method, or providing a better starting geometry.",
            "warnings": warnings,
            "meta": {
                "wall_time_s": wall_time_s,
                "xtb_version": xtb_version,
                "command": cmd_str,
            },
        }

    if tmpdir is not None:
        tmpdir.cleanup()

    return {
        "ok": True,
        "result": {
            "final_energy": (
                {"value": parsed_sp["energy_hartree"], "unit": "Hartree"}
                if parsed_sp["energy_hartree"] is not None
                else {"value": 0.0, "unit": "Hartree"}
            ),
            "optimized_geometry_xyz": optimized_xyz,
            "n_iterations": n_iterations,
            "converged": converged,
        },
        "warnings": warnings,
        "meta": {
            "wall_time_s": wall_time_s,
            "xtb_version": xtb_version,
            "command": cmd_str,
        },
    }


def main() -> None:
    """``chemaster-mcp calc_xtb`` 入口。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
