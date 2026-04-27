"""chem.parse_cclib — 计算化学输出文件解析 MCP server.

用 cclib 解析 psi4 / ORCA / Gaussian / xTB 等主流量化软件的输出文件，
提取几何、能量、轨道、振动频率等结构化数据。

依赖：cclib >= 1.8
"""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

import cclib  # noqa: E402

logger = logging.getLogger(__name__)
mcp = FastMCP("chem.parse_cclib")

# cclib 内部 scfenergies / moenergies 单位为 eV（data.py line 63）
# pylint: disable=no-member  # ccData attributes are dynamic

# 标准元素符号表（1-indexed，0 为占位）
_ELEMENTS = [
    "", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
]


def _build_xyz(atomnos: Any, atomcoords: Any) -> str:
    """把 cclib 的 atomnos + atomcoords 组成 XYZ 格式字符串。

    Args:
        atomnos: 原子序数数组（numpy.ndarray）
        atomcoords: 所有构型的坐标数组（numpy.ndarray，[-1] 取最后一步）

    Returns:
        XYZ 格式字符串（单位 Å）
    """
    import numpy as np

    coords = np.asarray(atomcoords)
    final = coords[-1]  # 取最终构型
    lines = [str(len(atomnos)), ""]
    for num, (x, y, z) in zip(atomnos, final):
        elem = _ELEMENTS[int(num)] if int(num) < len(_ELEMENTS) else f"X{int(num)}"
        lines.append(f"{elem:>3s}  {x:12.6f}  {y:12.6f}  {z:12.6f}")
    return "\n".join(lines)


def _detect_converged(data: Any) -> bool:
    """判断几何优化是否收敛。"""
    import numpy as np
    from cclib.parser import data as d

    if getattr(data, "optdone", False):
        return True
    optstatus = getattr(data, "optstatus", None)
    if optstatus is not None:
        return bool(np.any(optstatus & d.OPT_DONE))
    return True  # 无优化记录 → 单点，默认收敛


@mcp.tool()
def parse_output(output_path: str, engine: str = "auto") -> dict[str, Any]:
    """解析量化软件输出文件，提取结构化计算结果。

    Args:
        output_path: 输出文件路径（支持 psi4 / ORCA / Gaussian / xTB 等）。
        engine: "auto" 让 cclib 自动检测；也可指定 "psi4" / "orca" /
                 "gaussian" / "gamess" / "xtb"。

    Returns:
        ok=True 时:
          {
            "ok": True,
            "result": {
              "engine": str,           # 检测到的引擎名
              "engine_version": str,   # 版本字符串
              "scfenergies": [{"value": float, "unit": "eV"}],
              "final_energy": {"value": float, "unit": str},
              "geometry_xyz": str,     # 最终几何，XYZ 格式（Å）
              "homo_lumo_gap": {"value": float, "unit": "eV"} | null,
              "n_atoms": int,
              "charge": int,
              "multiplicity": int,
              "converged": bool,
              "frequencies_cm_inv": [{"value": float}] | null,
              "zpe": {"value": float, "unit": str} | null,
            },
            "warnings": list[str],
            "meta": {"output_path": str, "file_size_kb": float}
          }
        ok=False 时:
          {"ok": False, "error_code": "FILE_NOT_FOUND" | "PARSE_ERROR" | "UNSUPPORTED_ENGINE",
           "details": str, "suggestion": str}

    Examples:
        >>> parse_output("h2o.out")
        {"ok": True, "result": {"n_atoms": 3, ...}, ...}
    """
    warnings: list[str] = []
    meta_file_size_kb: float = 0.0

    # ---- 文件存在性检查 ----
    if not os.path.exists(output_path):
        return {
            "ok": False,
            "error_code": "FILE_NOT_FOUND",
            "details": f"File not found: {output_path}",
            "suggestion": "Check that the path is correct and the file is readable.",
        }

    try:
        meta_file_size_kb = os.path.getsize(output_path) / 1024.0
    except OSError as e:
        warnings.append(f"Could not determine file size: {e}")

    # ---- 调用 cclib 解析 ----
    try:
        if engine == "auto":
            ccdata = cclib.io.ccread(output_path)
        else:
            ccdata = cclib.io.ccread(output_path, engine=engine)
    except Exception as e:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": f"{type(e).__name__}: {e}",
            "suggestion": "Ensure the file is a valid computational chemistry output log.",
        }

    if ccdata is None:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": "cclib.ccread returned None — file format not recognized.",
            "suggestion": "Try specifying engine='psi4' / 'orca' / 'gaussian' explicitly.",
        }

    # ---- 引擎信息 ----
    engine_name = type(ccdata).__name__.replace("ccData", "")
    if engine_name == "ccData":
        engine_name = getattr(ccdata, "metadata", {}).get("package", "unknown")
    engine_version = str(
        getattr(ccdata, "metadata", {}).get("package_version", "unknown")
    )

    # ---- scfenergies ----
    import numpy as np

    scfenergies: list[dict[str, Any]] = []
    scf_raw = getattr(ccdata, "scfenergies", None)
    if scf_raw is not None:
        scfenergies = [{"value": float(v), "unit": "eV"} for v in scf_raw]

    # ---- final_energy ----
    final_energy: dict[str, Any] | None = None
    if scf_raw is not None and len(scf_raw) > 0:
        final_energy = {"value": float(scf_raw[-1]), "unit": "eV"}

    # ---- geometry_xyz ----
    geometry_xyz = ""
    if hasattr(ccdata, "atomnos") and hasattr(ccdata, "atomcoords"):
        geometry_xyz = _build_xyz(ccdata.atomnos, ccdata.atomcoords)

    # ---- 基本属性 ----
    n_atoms = int(getattr(ccdata, "natom", 0))
    charge = int(getattr(ccdata, "charge", 0))
    multiplicity = int(getattr(ccdata, "mult", 1))

    # ---- homo_lumo_gap ----
    homo_lumo_gap: dict[str, Any] | None = None
    moenergies = getattr(ccdata, "moenergies", None)
    homos = getattr(ccdata, "homos", None)
    if moenergies is not None and homos is not None and len(homos) > 0:
        try:
            homo_idx = int(homos[0])
            mo_arr = np.asarray(moenergies[0])
            lumo_idx = homo_idx + 1
            if lumo_idx < len(mo_arr):
                gap_ev = float(mo_arr[lumo_idx] - mo_arr[homo_idx])
                homo_lumo_gap = {"value": gap_ev, "unit": "eV"}
        except (IndexError, ValueError) as exc:
            warnings.append(f"Could not compute HOMO-LUMO gap: {exc}")

    # ---- converged ----
    converged = _detect_converged(ccdata)

    # ---- frequencies_cm_inv ----
    frequencies_cm_inv: list[dict[str, float]] | None = None
    vibfreqs = getattr(ccdata, "vibfreqs", None)
    if vibfreqs is not None:
        frequencies_cm_inv = [{"value": float(f)} for f in vibfreqs]

    # ---- zpe ----
    zpe: dict[str, Any] | None = None
    zpve = getattr(ccdata, "zpve", None)
    if zpve is not None:
        zpe = {"value": float(zpve), "unit": "hartree/particle"}

    result = {
        "engine": engine_name,
        "engine_version": engine_version,
        "scfenergies": scfenergies,
        "final_energy": final_energy,
        "geometry_xyz": geometry_xyz,
        "homo_lumo_gap": homo_lumo_gap,
        "n_atoms": n_atoms,
        "charge": charge,
        "multiplicity": multiplicity,
        "converged": converged,
        "frequencies_cm_inv": frequencies_cm_inv,
        "zpe": zpe,
    }

    return {
        "ok": True,
        "result": result,
        "warnings": warnings,
        "meta": {"output_path": output_path, "file_size_kb": meta_file_size_kb},
    }


@mcp.tool()
def extract_orbitals(output_path: str, n_around_homo: int = 5) -> dict[str, Any]:
    """提取 HOMO 附近 ±n 个分子轨道的能量与对称性。

    Args:
        output_path: 输出文件路径。
        n_around_homo: 提取 HOMO 两侧各多少个轨道（默认 5，即 HOMO-4 … LUMO+4）。

    Returns:
        ok=True 时:
          {
            "ok": True,
            "result": {
              "engine": str,
              "homo_index": int,
              "orbitals": [
                {"index": int, "energy": float, "unit": "eV", "symmetry": str}
              ]
            },
            "warnings": list[str],
            "meta": {"output_path": str}
          }
        ok=False 时:
          {"ok": False, "error_code": "FILE_NOT_FOUND" | "PARSE_ERROR",
           "details": str, "suggestion": str}

    Examples:
        >>> extract_orbitals("h2o.out", n_around_homo=3)
        {"ok": True, "result": {"homo_index": 12, "orbitals": [...]}, ...}
    """
    warnings: list[str] = []

    if not os.path.exists(output_path):
        return {
            "ok": False,
            "error_code": "FILE_NOT_FOUND",
            "details": f"File not found: {output_path}",
            "suggestion": "Check that the path is correct.",
        }

    try:
        ccdata = cclib.io.ccread(output_path)
    except Exception as e:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": f"{type(e).__name__}: {e}",
            "suggestion": "Failed to parse the output file.",
        }

    if ccdata is None:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": "cclib.ccread returned None.",
            "suggestion": "Specify engine explicitly if known.",
        }

    moenergies = getattr(ccdata, "moenergies", None)
    mosyms = getattr(ccdata, "mosyms", None)
    homos = getattr(ccdata, "homos", None)

    if moenergies is None or homos is None:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": "moenergies or homos not found in output.",
            "suggestion": "Ensure the output contains orbital energies (e.g., from a DFT or HF calculation).",
        }

    try:
        homo_idx = int(homos[0])
    except (IndexError, ValueError) as e:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": f"Could not read HOMO index: {e}",
            "suggestion": "Check that homos attribute is valid.",
        }

    # moenergies / mosyms 都是 list of arrays（不同迭代层级），取第一套
    mo_arr = moenergies[0]
    sym_arr = mosyms[0] if mosyms and len(mosyms) > 0 else ["A"] * len(mo_arr)

    n_total = len(mo_arr)
    lo = max(0, homo_idx - n_around_homo)
    hi = min(n_total - 1, homo_idx + n_around_homo)

    orbitals: list[dict[str, Any]] = []
    for i in range(lo, hi + 1):
        sym = sym_arr[i] if i < len(sym_arr) else "A"
        orbitals.append({
            "index": int(i),
            "energy": float(mo_arr[i]),
            "unit": "eV",
            "symmetry": str(sym),
        })

    engine_name = type(ccdata).__name__.replace("ccData", "")
    if engine_name == "ccData":
        engine_name = getattr(ccdata, "metadata", {}).get("package", "unknown")

    return {
        "ok": True,
        "result": {
            "engine": engine_name,
            "homo_index": homo_idx,
            "orbitals": orbitals,
        },
        "warnings": warnings,
        "meta": {"output_path": output_path},
    }


def main() -> None:
    """``chemaster-mcp parse_cclib`` 入口。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
