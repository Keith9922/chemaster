"""chem.io_ase — 分子结构 IO MCP server。

用 RDKit/ASE 实现 SMILES ↔ XYZ ↔ 内置分子库。
详见 docs/MCP_GUIDE.md。
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem import rdMolDescriptors

logger = logging.getLogger(__name__)
mcp = FastMCP("chem.io_ase")

# 内置小分子库（xyz 格式：n\nElement x y z\n无 comment 行 —— qcelemental 无法解析含 comment 的标准 xyz）
_BUILTIN_MOLECULES: dict[str, dict[str, Any]] = {
    "water": {
        "smiles": "O",
        "xyz": "3\nO 0.000000 0.000000 0.117836\nH 0.000000 0.757063 -0.471344\nH 0.000000 -0.757063 -0.471344\n",
        "formula": "H2O",
        "charge": 0,
        "multiplicity": 1,
    },
    "h2o": {
        "smiles": "O",
        "xyz": "3\nO 0.000000 0.000000 0.117836\nH 0.000000 0.757063 -0.471344\nH 0.000000 -0.757063 -0.471344\n",
        "formula": "H2O",
        "charge": 0,
        "multiplicity": 1,
    },
    "methane": {
        "smiles": "C",
        "xyz": "5\nC 0.000000 0.000000 0.000000\nH 0.629118 0.629118 0.629118\nH -0.629118 -0.629118 0.629118\nH 0.629118 -0.629118 -0.629118\nH -0.629118 0.629118 -0.629118\n",
        "formula": "CH4",
        "charge": 0,
        "multiplicity": 1,
    },
    "ch4": {
        "smiles": "C",
        "xyz": "5\nC 0.000000 0.000000 0.000000\nH 0.629118 0.629118 0.629118\nH -0.629118 -0.629118 0.629118\nH 0.629118 -0.629118 -0.629118\nH -0.629118 0.629118 -0.629118\n",
        "formula": "CH4",
        "charge": 0,
        "multiplicity": 1,
    },
    "ammonia": {
        "smiles": "N",
        "xyz": "4\nN 0.000000 0.000000 0.117489\nH 0.000000 0.938074 -0.313304\nH 0.812234 -0.469037 -0.313304\nH -0.812234 -0.469037 -0.313304\n",
        "formula": "NH3",
        "charge": 0,
        "multiplicity": 1,
    },
    "nh3": {
        "smiles": "N",
        "xyz": "4\nN 0.000000 0.000000 0.117489\nH 0.000000 0.938074 -0.313304\nH 0.812234 -0.469037 -0.313304\nH -0.812234 -0.469037 -0.313304\n",
        "formula": "NH3",
        "charge": 0,
        "multiplicity": 1,
    },
    "co2": {
        "smiles": "O=C=O",
        "xyz": "3\nC 0.000000 0.000000 0.000000\nO 0.000000 0.000000 1.160312\nO 0.000000 0.000000 -1.160312\n",
        "formula": "CO2",
        "charge": 0,
        "multiplicity": 1,
    },
    "benzene": {
        "smiles": "c1ccccc1",
        # 6 C + 6 H, planar D6h. C-C 1.396 Å, C-H 1.083 Å.
        # The previous entry was malformed (header said 12, body had 22 lines).
        "xyz": (
            "12\n"
            "benzene\n"
            "C  1.396000  0.000000  0.000000\n"
            "C  0.698000  1.208679  0.000000\n"
            "C -0.698000  1.208679  0.000000\n"
            "C -1.396000  0.000000  0.000000\n"
            "C -0.698000 -1.208679  0.000000\n"
            "C  0.698000 -1.208679  0.000000\n"
            "H  2.479000  0.000000  0.000000\n"
            "H  1.239500  2.146548  0.000000\n"
            "H -1.239500  2.146548  0.000000\n"
            "H -2.479000  0.000000  0.000000\n"
            "H -1.239500 -2.146548  0.000000\n"
            "H  1.239500 -2.146548  0.000000\n"
        ),
        "formula": "C6H6",
        "charge": 0,
        "multiplicity": 1,
    },
    "ethanol": {
        "smiles": "CCO",
        "xyz": "9\nC 0.000000 0.000000 0.000000\nC 1.520000 0.000000 0.000000\nO 2.100000 1.225000 0.000000\nH -0.350000 1.025000 0.000000\nH -0.350000 -0.512500 0.890000\nH -0.350000 -0.512500 -0.890000\nH 1.870000 -0.512500 0.890000\nH 1.870000 -0.512500 -0.890000\nH 3.080000 1.225000 0.000000\n",
        "formula": "C2H6O",
        "charge": 0,
        "multiplicity": 1,
    },
}


def _mol_to_xyz(mol: Chem.Mol, title: str = "") -> str:
    """把 RDKit Mol 对象转成 XYZ 格式字符串（psi4 兼容，无 comment 行）。

    note: 不输出 comment 行（第 2 行），因为 qcelemental 的 xyz parser
    无法处理含 comment 的 xyz（会把 comment 当分子式解析导致错误）。
    psi4.optimize 返回的 mol.save_string_xyz() 输出格式是 psi4 自定义 XYZ+
   （以 'charge multiplicity' 开头），两种格式不兼容但可接受。
    """
    conf = mol.GetConformer(0)
    symbols = [a.GetSymbol() for a in mol.GetAtoms()]
    n = len(symbols)
    lines = [f"{n}"]
    # 不写 comment 行：psi4 qcelemental 无法解析含 comment 的标准 xyz
    for i, (x, y, z) in enumerate(conf.GetPositions()):
        lines.append(f"{symbols[i]} {x:.6f} {y:.6f} {z:.6f}")
    return "\n".join(lines) + "\n"


@mcp.tool()
def smiles_to_xyz(
    smiles: str, embed_seed: int = 42, optimize_force_field: str = "UFF"
) -> dict[str, Any]:
    """用 RDKit ETKDG 生成 3D 几何结构并优化。

    Args:
        smiles: SMILES 字符串（大小写敏感）。
        embed_seed: 随机种子，保证可复现。
        optimize_force_field: 力场名，目前支持 "UFF"。

    Returns:
        ok=True:
          {
            "ok": True,
            "result": {
              "xyz": str,       # XYZ 格式字符串
              "n_atoms": int,
              "formula": str,
            },
            "warnings": list[str],
            "meta": {"smiles": str, "embed_seed": int}
          }
        ok=False:
          {"ok": False, "error_code": "INVALID_SMILES" | "EMBEDDING_FAILED",
           "details": "...", "suggestion": "..."}
    """
    warnings: list[str] = []

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {
            "ok": False,
            "error_code": "INVALID_SMILES",
            "details": f"Cannot parse SMILES: {smiles!r}",
            "suggestion": "Check SMILES syntax (valence, aromaticity).",
        }

    try:
        ok = AllChem.EmbedMolecule(mol, randomSeed=embed_seed)
    except Exception as e:
        return {
            "ok": False,
            "error_code": "EMBEDDING_FAILED",
            "details": f"{type(e).__name__}: {e}",
            "suggestion": "Try a different SMILES or embed_seed.",
        }

    if ok == -1:
        return {
            "ok": False,
            "error_code": "EMBEDDING_FAILED",
            "details": f"ETKDG embedding failed for: {smiles!r}",
            "suggestion": "Try a different SMILES or increase embed_seed.",
        }

    # 加显式 H（用于 UFF 优化和原子数计算），之后从 xyz 中保留
    mol = AllChem.AddHs(mol)

    # UFF 优化
    ok_opt = AllChem.UFFOptimizeMolecule(mol)
    if ok_opt != 0:
        warnings.append("UFF optimization did not fully converge.")

    xyz = _mol_to_xyz(mol, title=f"from_smiles:{smiles}")
    formula = rdMolDescriptors.CalcMolFormula(mol)
    n_atoms = mol.GetNumAtoms()

    return {
        "ok": True,
        "result": {
            "xyz": xyz,
            "n_atoms": n_atoms,
            "formula": formula,
        },
        "warnings": warnings,
        "meta": {"smiles": smiles, "embed_seed": embed_seed},
    }


@mcp.tool()
def xyz_to_smiles(xyz: str) -> dict[str, Any]:
    """把 XYZ 字符串转成 SMILES（通过 RDKit）。

    Args:
        xyz: XYZ 格式字符串（必须含 n_atoms 行和坐标）。

    Returns:
        ok=True:
          {
            "ok": True,
            "result": {
              "smiles": str,          # 非规范 SMILES
              "canonical_smiles": str,
            },
            "warnings": list[str],
            "meta": {"n_atoms": int}
          }
        ok=False:
          {"ok": False, "error_code": "INVALID_XYZ",
           "details": "...", "suggestion": "..."}
    """
    try:
        lines = xyz.strip().splitlines()
        n = int(lines[0].strip())
        if len(lines) < n + 2:
            raise ValueError(f"Expected {n + 2} lines, got {len(lines)}")
        block = "\n".join(lines[: n + 2])
        mol = Chem.MolFromXYZBlock(block)
    except Exception as e:
        return {
            "ok": False,
            "error_code": "INVALID_XYZ",
            "details": f"{type(e).__name__}: {e}",
            "suggestion": "XYZ block must start with atom count, then comment line, then coordinates.",
        }

    if mol is None or mol.GetNumAtoms() == 0:
        return {
            "ok": False,
            "error_code": "INVALID_XYZ",
            "details": "RDKit failed to parse the XYZ block.",
            "suggestion": "Check atom symbols and coordinate format.",
        }

    smiles = Chem.MolToSmiles(mol)
    canonical_smiles = Chem.MolToSmiles(mol, canonical=True)

    return {
        "ok": True,
        "result": {
            "smiles": smiles,
            "canonical_smiles": canonical_smiles,
        },
        "warnings": [],
        "meta": {"n_atoms": mol.GetNumAtoms()},
    }


@mcp.tool()
def parse_geometry(content: str, format: str) -> dict[str, Any]:
    """解析分子几何到标准化 XYZ 字符串。

    Args:
        content: 文件内容字符串。
        format: 输入格式，"xyz" | "mol" | "sdf"。

    Returns:
        ok=True:
          {
            "ok": True,
            "result": {
              "xyz": str,       # 标准化 XYZ 格式
              "n_atoms": int,
              "formula": str,
            },
            "warnings": list[str],
            "meta": {"format": str, "original_format": str}
          }
        ok=False:
          {"ok": False, "error_code": "UNSUPPORTED_FORMAT" | "PARSE_ERROR",
           "details": "...", "suggestion": "..."}
    """
    SUPPORTED = {"xyz", "mol", "sdf"}
    if format not in SUPPORTED:
        return {
            "ok": False,
            "error_code": "UNSUPPORTED_FORMAT",
            "details": f"Format {format!r} not supported. Choose from: {SUPPORTED}",
            "suggestion": "Use format='xyz', 'mol', or 'sdf'.",
        }

    mol = None
    try:
        if format == "xyz":
            mol = Chem.MolFromXYZBlock(content)
        elif format == "mol":
            mol = Chem.MolFromMolBlock(content)
        elif format == "sdf":
            mol = Chem.MolFromMolBlock(content)  # SDF 也用 MolFromMolBlock
    except Exception as e:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": f"{type(e).__name__}: {e}",
            "suggestion": "Check the content format.",
        }

    if mol is None or mol.GetNumAtoms() == 0:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": "RDKit returned None for the given content.",
            "suggestion": "Verify the content is valid for the specified format.",
        }

    try:
        Chem.SanitizeMol(mol)
    except Exception as e:
        return {
            "ok": False,
            "error_code": "PARSE_ERROR",
            "details": f"Sanitization failed: {type(e).__name__}: {e}",
            "suggestion": "Check atom valences and connectivity.",
        }

    xyz = _mol_to_xyz(mol, title=f"from_{format}")
    formula = rdMolDescriptors.CalcMolFormula(mol)
    n_atoms = mol.GetNumAtoms()

    return {
        "ok": True,
        "result": {
            "xyz": xyz,
            "n_atoms": n_atoms,
            "formula": formula,
        },
        "warnings": [],
        "meta": {"format": "xyz", "original_format": format},
    }


@mcp.tool()
def lookup_by_name(name: str) -> dict[str, Any]:
    """在内置小分子库中按名称查找。

    Args:
        name: 分子名（大小写不敏感）。支持别名。
              已知：water/h2o, methane/ch4, ammonia/nh3,
              co2, benzene, ethanol。

    Returns:
        ok=True:
          {
            "ok": True,
            "result": {
              "xyz": str,
              "smiles": str,
              "formula": str,
              "charge": int,
              "multiplicity": int,
            },
            "warnings": list[str],
            "meta": {"name": str}
          }
        ok=False:
          {"ok": False, "error_code": "NAME_NOT_FOUND",
           "details": "...", "suggestion": "..."}
    """
    key = name.lower().strip()
    if key not in _BUILTIN_MOLECULES:
        available = list(_BUILTIN_MOLECULES.keys())
        return {
            "ok": False,
            "error_code": "NAME_NOT_FOUND",
            "details": f"Molecule {name!r} not found in builtin library.",
            "suggestion": f"Available: {available}",
        }

    data = _BUILTIN_MOLECULES[key]
    return {
        "ok": True,
        "result": {
            "xyz": data["xyz"],
            "smiles": data["smiles"],
            "formula": data["formula"],
            "charge": data["charge"],
            "multiplicity": data["multiplicity"],
        },
        "warnings": [],
        "meta": {"name": name},
    }


def main() -> None:
    """``chemaster-mcp io_ase`` 入口。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
