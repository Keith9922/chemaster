"""chem.io_ase — 分子结构 IO MCP server。

用 RDKit/ASE 实现 SMILES ↔ XYZ ↔ 内置分子库。
详见 docs/MCP_GUIDE.md。
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors

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


def _load_tadf_anchors() -> dict[str, dict[str, Any]]:
    """Lazy-load benchmark molecules from benchmarks/*/*.xyz.

    Scans every sub-directory under ``benchmarks/`` for ``*.xyz`` files
    and registers them by their stem (case-insensitive). A matching
    ``<name>.yaml`` next to the xyz is parsed for charge / multiplicity /
    smiles / formula. Pre-computed geometries skip slow RDKit ETKDG
    embeddings for 80+ atom molecules.

    Currently picks up:
      - benchmarks/tadf-literature/{4CzIPN,DMAC-BP,DMAC-DPS}.xyz
      - benchmarks/momap-jingti/jingti.xyz (师姐 reference, 46 atoms)
    """
    from pathlib import Path

    import yaml

    anchors: dict[str, dict[str, Any]] = {}
    here = Path(__file__).resolve()
    repo_root = next(
        (p for p in here.parents if (p / "benchmarks").is_dir()), None
    )
    if repo_root is None:
        return anchors
    bench_root = repo_root / "benchmarks"
    if not bench_root.is_dir():
        return anchors

    for xyz_file in sorted(bench_root.rglob("*.xyz")):
        # Skip "raw" / scratch directories.
        if "raw" in xyz_file.parts:
            continue
        name = xyz_file.stem
        try:
            xyz = xyz_file.read_text()
        except Exception:
            continue
        meta_file = xyz_file.with_suffix(".yaml")
        smiles = ""
        formula = ""
        charge = 0
        multiplicity = 1
        if meta_file.is_file():
            try:
                meta = yaml.safe_load(meta_file.read_text()) or {}
                smiles = meta.get("smiles", "") or ""
                charge = int(meta.get("charge", 0) or 0)
                multiplicity = int(meta.get("multiplicity", 1) or 1)
                formula = meta.get("name", "") or meta.get("formula", "") or ""
            except Exception:
                pass
        if not formula:
            formula = name
        anchors[name.lower()] = {
            "smiles": smiles,
            "xyz": xyz,
            "formula": formula,
            "charge": charge,
            "multiplicity": multiplicity,
        }
    return anchors


# Merge TADF anchor library into the builtin lookup. Done at import time
# so the dict is hot when MCP starts.
# NOTE: anchors must NOT override curated _BUILTIN_MOLECULES entries —
# the unit test test_lookup_case_insensitive locks the formula of common
# small molecules ("AMMONIA" -> "NH3"). New xyz dropped under benchmarks/
# (e.g. benchmarks/quest/inputs/ammonia.xyz) would otherwise overwrite
# the curated formula with the file stem.
for _name, _data in _load_tadf_anchors().items():
    if _name not in _BUILTIN_MOLECULES:
        _BUILTIN_MOLECULES[_name] = _data


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


@mcp.tool()
def compute_descriptors(
    geometry_xyz: str,
    bonds: list[list[int]] | None = None,
    angles: list[list[int]] | None = None,
    dihedrals: list[list[int]] | None = None,
) -> dict[str, Any]:
    """Compute deterministic geometry descriptors (bond lengths, bond angles,
    dihedrals) from an XYZ block.

    **Use this whenever you need to report a bond length, angle, or
    dihedral**. Do NOT compute these yourself from coordinates — LLMs
    routinely get these arithmetic operations subtly wrong (this is the
    "LLM doesn't do math" rule from CLAUDE.md §5.1, applied to geometry).

    Atom indices are **0-based** and refer to the order atoms appear in
    the input XYZ. Standard XYZ (with header) and bare coordinate-only
    input both work.

    Args:
        geometry_xyz: standard XYZ string (with the count header) or
            a coordinate-only block.
        bonds: list of [i, j] pairs — bond length between atoms i and j.
        angles: list of [i, j, k] triples — angle at vertex j (i-j-k).
        dihedrals: list of [i, j, k, l] quadruples — torsion i-j-k-l.

    Returns:
        ok=True:
          {
            "ok": True,
            "result": {
              "bonds": [
                {"indices": [i, j], "elements": ["X", "Y"],
                 "value": float, "unit": "Å"},
                ...
              ],
              "angles": [
                {"indices": [i, j, k], "elements": ["X", "Y", "Z"],
                 "value": float, "unit": "deg"},
                ...
              ],
              "dihedrals": [
                {"indices": [i, j, k, l], "elements": [...],
                 "value": float, "unit": "deg"},
                ...
              ],
            },
            "warnings": [],
            "meta": {"n_atoms": int}
          }
        ok=False:
          {"ok": False, "error_code": "INVALID_INDEX" | "INVALID_GEOMETRY",
           "details": str, "suggestion": str}

    Examples:
        >>> # H2O angle (atom 0 = O, atoms 1 and 2 = H)
        >>> r = compute_descriptors(
        ...     "3\\nO 0 0 0.117\\nH 0 0.757 -0.471\\nH 0 -0.757 -0.471",
        ...     bonds=[[0, 1], [0, 2]],
        ...     angles=[[1, 0, 2]])
        >>> r["result"]["bonds"][0]["value"]   # O-H1 bond length
        0.958...
        >>> r["result"]["angles"][0]["value"]  # H1-O-H2 angle
        104.5...
    """
    import math

    # ── parse XYZ ────────────────────────────────────────────────────
    lines = [ln for ln in geometry_xyz.strip().splitlines() if ln.strip()]
    if not lines:
        return {
            "ok": False,
            "error_code": "INVALID_GEOMETRY",
            "details": "Empty geometry_xyz.",
            "suggestion": "Pass a non-empty XYZ block.",
        }

    # Try standard XYZ format (count header + optional comment + coords)
    coord_lines: list[str]
    try:
        n_decl = int(lines[0].strip())
        if len(lines) == n_decl + 1:
            coord_lines = lines[1:]
        elif len(lines) == n_decl + 2:
            coord_lines = lines[2:]
        else:
            # Header doesn't match; treat all lines as coords
            coord_lines = lines
    except ValueError:
        # First line isn't an integer; treat as coordinate-only
        coord_lines = lines

    elements: list[str] = []
    coords: list[tuple[float, float, float]] = []
    for line in coord_lines:
        parts = line.split()
        if len(parts) < 4:
            return {
                "ok": False,
                "error_code": "INVALID_GEOMETRY",
                "details": f"Bad coordinate line: {line!r}",
                "suggestion": "Each coord line must be 'Element x y z'.",
            }
        try:
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            return {
                "ok": False,
                "error_code": "INVALID_GEOMETRY",
                "details": f"Non-numeric coordinates in: {line!r}",
                "suggestion": "Coordinates must be floats.",
            }
        elements.append(parts[0])
        coords.append((x, y, z))

    n = len(coords)

    def _check_idx(idx: int) -> str | None:
        if not (0 <= idx < n):
            return f"Atom index {idx} out of range [0, {n - 1}]."
        return None

    def _vec(i: int, j: int) -> tuple[float, float, float]:
        return (coords[j][0] - coords[i][0],
                coords[j][1] - coords[i][1],
                coords[j][2] - coords[i][2])

    def _norm(v: tuple[float, float, float]) -> float:
        return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)

    def _dot(a, b) -> float:
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    def _cross(a, b) -> tuple[float, float, float]:
        return (a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    bond_results: list[dict[str, Any]] = []
    for pair in (bonds or []):
        if len(pair) != 2:
            return {"ok": False, "error_code": "INVALID_INDEX",
                    "details": f"bonds entry must be [i, j], got {pair!r}",
                    "suggestion": "Pass exactly two indices per bond."}
        i, j = pair
        for v in (i, j):
            err = _check_idx(v)
            if err:
                return {"ok": False, "error_code": "INVALID_INDEX",
                        "details": err, "suggestion": f"Use 0-based indices in [0, {n - 1}]."}
        d = _norm(_vec(i, j))
        bond_results.append({
            "indices": [i, j],
            "elements": [elements[i], elements[j]],
            "value": round(d, 4),
            "unit": "Å",
        })

    angle_results: list[dict[str, Any]] = []
    for triple in (angles or []):
        if len(triple) != 3:
            return {"ok": False, "error_code": "INVALID_INDEX",
                    "details": f"angles entry must be [i, j, k], got {triple!r}",
                    "suggestion": "Pass exactly three indices per angle (vertex is the middle one)."}
        i, j, k = triple
        for v in (i, j, k):
            err = _check_idx(v)
            if err:
                return {"ok": False, "error_code": "INVALID_INDEX",
                        "details": err, "suggestion": f"Use 0-based indices in [0, {n - 1}]."}
        ji = _vec(j, i)
        jk = _vec(j, k)
        nji, njk = _norm(ji), _norm(jk)
        if nji == 0 or njk == 0:
            return {"ok": False, "error_code": "INVALID_GEOMETRY",
                    "details": f"Degenerate angle at indices {triple}: zero-length bond vector.",
                    "suggestion": "Check geometry — atoms must be distinct."}
        cos_t = max(-1.0, min(1.0, _dot(ji, jk) / (nji * njk)))
        ang_deg = math.degrees(math.acos(cos_t))
        angle_results.append({
            "indices": [i, j, k],
            "elements": [elements[i], elements[j], elements[k]],
            "value": round(ang_deg, 3),
            "unit": "deg",
        })

    dihedral_results: list[dict[str, Any]] = []
    for quad in (dihedrals or []):
        if len(quad) != 4:
            return {"ok": False, "error_code": "INVALID_INDEX",
                    "details": f"dihedrals entry must be [i, j, k, l], got {quad!r}",
                    "suggestion": "Pass exactly four indices per dihedral."}
        i, j, k, m = quad
        for v in (i, j, k, m):
            err = _check_idx(v)
            if err:
                return {"ok": False, "error_code": "INVALID_INDEX",
                        "details": err, "suggestion": f"Use 0-based indices in [0, {n - 1}]."}
        b1 = _vec(j, i)   # i - j
        b2 = _vec(j, k)   # k - j
        b3 = _vec(k, m)   # m - k
        n1 = _cross(b1, b2)
        n2 = _cross(b2, b3)
        nn1, nn2 = _norm(n1), _norm(n2)
        if nn1 == 0 or nn2 == 0:
            return {"ok": False, "error_code": "INVALID_GEOMETRY",
                    "details": f"Degenerate dihedral at {quad}: collinear atoms.",
                    "suggestion": "Pick four atoms whose central bonds aren't collinear."}
        b2_norm = _norm(b2)
        m1 = _cross(n1, (b2[0] / b2_norm, b2[1] / b2_norm, b2[2] / b2_norm))
        x = _dot(n1, n2) / (nn1 * nn2)
        y = _dot(m1, n2) / (nn2)  # (n1 × b2_hat) · n2 / |n2|
        # IUPAC dihedral: signed angle, [-180, 180]
        dih_deg = math.degrees(math.atan2(y, x))
        dihedral_results.append({
            "indices": [i, j, k, m],
            "elements": [elements[i], elements[j], elements[k], elements[m]],
            "value": round(dih_deg, 3),
            "unit": "deg",
        })

    return {
        "ok": True,
        "result": {
            "bonds": bond_results,
            "angles": angle_results,
            "dihedrals": dihedral_results,
        },
        "warnings": [],
        "meta": {"n_atoms": n},
    }


def main() -> None:
    """``chemaster-mcp io_ase`` 入口。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
