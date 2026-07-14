"""mcp.io_ase 单元测试。"""

from __future__ import annotations

from chemaster.mcp.io_ase import server as S

# ------------------------------------------------------------------
# smiles_to_xyz
# ------------------------------------------------------------------

def test_smiles_to_xyz_water():
    """H2O SMILES 能正确生成 3 原子 XYZ。"""
    result = S.smiles_to_xyz("O", embed_seed=42)
    assert result["ok"] is True
    assert result["result"]["n_atoms"] == 3
    assert result["result"]["formula"] == "H2O"
    assert "O" in result["result"]["xyz"]
    assert "H" in result["result"]["xyz"]
    assert result["meta"]["smiles"] == "O"
    assert result["meta"]["embed_seed"] == 42
    assert result["warnings"] == []


def test_smiles_to_xyz_invalid():
    """非法 SMILES 返回 INVALID_SMILES。"""
    result = S.smiles_to_xyz("C%")
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_SMILES"


def test_smiles_to_xyz_benzene():
    """苯 SMILES 生成 12 原子。"""
    result = S.smiles_to_xyz("c1ccccc1", embed_seed=7)
    assert result["ok"] is True
    assert result["result"]["n_atoms"] == 12
    assert result["result"]["formula"] == "C6H6"


# ------------------------------------------------------------------
# xyz_to_smiles
# ------------------------------------------------------------------

def test_xyz_to_smiles_water():
    """水 XYZ 能正确转出 SMILES。"""
    xyz = "3\nWater\nO 0.000000 0.000000 0.117836\nH 0.000000 0.757063 -0.471344\nH 0.000000 -0.757063 -0.471344\n"
    result = S.xyz_to_smiles(xyz)
    assert result["ok"] is True
    assert "O" in result["result"]["canonical_smiles"]
    assert "H" in result["result"]["canonical_smiles"]
    assert result["result"]["smiles"] != ""
    assert result["meta"]["n_atoms"] == 3


def test_xyz_to_smiles_invalid():
    """格式错误的 XYZ 返回 INVALID_XYZ。"""
    result = S.xyz_to_smiles("not an xyz block at all")
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_XYZ"


def test_xyz_to_smiles_wrong_line_count():
    """行数不足的 XYZ 返回 INVALID_XYZ。"""
    result = S.xyz_to_smiles("3\nshort\nO 0 0 0")
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_XYZ"


# ------------------------------------------------------------------
# parse_geometry
# ------------------------------------------------------------------

def test_parse_geometry_xyz():
    """XYZ 格式解析返回标准化 XYZ。"""
    content = "3\nWater\nO 0.0 0.0 0.0\nH 0.8 0.0 0.0\nH 0.0 0.8 0.0\n"
    result = S.parse_geometry(content, format="xyz")
    assert result["ok"] is True
    assert result["result"]["n_atoms"] == 3
    assert result["result"]["xyz"].startswith("3\n")
    assert result["meta"]["format"] == "xyz"
    assert result["meta"]["original_format"] == "xyz"


def test_parse_geometry_unsupported_format():
    """不支持的格式返回 UNSUPPORTED_FORMAT。"""
    result = S.parse_geometry("some content", format="pdb")
    assert result["ok"] is False
    assert result["error_code"] == "UNSUPPORTED_FORMAT"


def test_parse_geometry_parse_error():
    """解析失败返回 PARSE_ERROR。"""
    content = "not valid mol content"
    result = S.parse_geometry(content, format="mol")
    assert result["ok"] is False
    assert result["error_code"] == "PARSE_ERROR"


# ------------------------------------------------------------------
# lookup_by_name
# ------------------------------------------------------------------

def test_lookup_water():
    """water 查找返回正确的 XYZ 和属性。"""
    result = S.lookup_by_name("water")
    assert result["ok"] is True
    assert result["result"]["smiles"] == "O"
    assert result["result"]["formula"] == "H2O"
    assert result["result"]["charge"] == 0
    assert result["result"]["multiplicity"] == 1
    assert "O" in result["result"]["xyz"]
    assert "H" in result["result"]["xyz"]


def test_lookup_h2o_alias():
    """h2o 别名也能找到 water。"""
    result = S.lookup_by_name("h2o")
    assert result["ok"] is True
    assert result["result"]["formula"] == "H2O"


def test_lookup_ch4():
    """甲烷查找。"""
    result = S.lookup_by_name("ch4")
    assert result["ok"] is True
    assert result["result"]["formula"] == "CH4"
    assert result["result"]["smiles"] == "C"


def test_lookup_benzene():
    """苯查找。"""
    result = S.lookup_by_name("benzene")
    assert result["ok"] is True
    assert result["result"]["formula"] == "C6H6"


def test_lookup_name_not_found():
    """未知名称返回 NAME_NOT_FOUND。"""
    result = S.lookup_by_name("not_a_molecule")
    assert result["ok"] is False
    assert result["error_code"] == "NAME_NOT_FOUND"


def test_lookup_case_insensitive():
    """查找大小写不敏感。"""
    result = S.lookup_by_name("AMMONIA")
    assert result["ok"] is True
    assert result["result"]["formula"] == "NH3"


# ──────────────────────────────────────────────────────────────────────
# compute_descriptors — bond lengths / angles / dihedrals from XYZ
# ──────────────────────────────────────────────────────────────────────


# Optimized H2O at B3LYP-D3(BJ)/def2-TZVP from the chemaster Agent demo.
_H2O_OPT = """3
H2O B3LYP-D3(BJ)/def2-TZVP
O  0.000000000000   0.000000000000   0.065401292884
H  0.000000000000   0.765035071022  -0.518982989229
H  0.000000000000  -0.765035071024  -0.518982989229"""


def test_compute_descriptors_h2o_geometry():
    """B3LYP H2O: O-H ≈ 0.96 Å, H-O-H ≈ 105°.

    These numbers are deterministic geometry — the LLM Agent reading them
    must match the values from this tool exactly, not its own arithmetic.
    """
    r = S.compute_descriptors(_H2O_OPT, bonds=[[0, 1], [0, 2]], angles=[[1, 0, 2]])
    assert r["ok"], r
    assert len(r["result"]["bonds"]) == 2
    assert r["result"]["bonds"][0]["unit"] == "Å"
    # Both O-H bonds are symmetric → identical to 4 dp
    assert r["result"]["bonds"][0]["value"] == r["result"]["bonds"][1]["value"]
    assert abs(r["result"]["bonds"][0]["value"] - 0.9627) < 1e-3
    assert r["result"]["angles"][0]["unit"] == "deg"
    # Hand-calc check: 105.25° (this is the bug that caught our LLM)
    assert abs(r["result"]["angles"][0]["value"] - 105.25) < 0.05
    assert r["result"]["angles"][0]["elements"] == ["H", "O", "H"]


def test_compute_descriptors_dihedral_h2o2():
    """H2O2: H-O-O-H dihedral is well-defined and non-zero."""
    h2o2 = """4
H2O2 idealised
O  0.000  0.000  0.0
O  1.475  0.000  0.0
H -0.388  0.939  0.0
H  1.863  0.469  0.812"""
    r = S.compute_descriptors(h2o2, dihedrals=[[2, 0, 1, 3]])
    assert r["ok"]
    val = r["result"]["dihedrals"][0]["value"]
    assert -180 < val <= 180
    assert abs(val) > 30   # Real, non-collinear dihedral


def test_compute_descriptors_invalid_index():
    """Out-of-range atom index → INVALID_INDEX."""
    r = S.compute_descriptors(_H2O_OPT, bonds=[[0, 99]])
    assert r["ok"] is False
    assert r["error_code"] == "INVALID_INDEX"


def test_compute_descriptors_bad_arity():
    """bond [i] (only one index) → INVALID_INDEX."""
    r = S.compute_descriptors(_H2O_OPT, bonds=[[0]])
    assert r["ok"] is False
    assert r["error_code"] == "INVALID_INDEX"
    assert "two indices" in r["suggestion"].lower()


def test_compute_descriptors_no_descriptors_requested():
    """Empty inputs return empty lists, not an error."""
    r = S.compute_descriptors(_H2O_OPT)
    assert r["ok"]
    assert r["result"]["bonds"] == []
    assert r["result"]["angles"] == []
    assert r["result"]["dihedrals"] == []
    assert r["meta"]["n_atoms"] == 3


def test_compute_descriptors_bare_coords():
    """Coord-only input (no header) also works."""
    bare = "O 0 0 0\nH 0.96 0 0\nH -0.24 0.93 0"
    r = S.compute_descriptors(bare, bonds=[[0, 1]], angles=[[1, 0, 2]])
    assert r["ok"]
    assert abs(r["result"]["bonds"][0]["value"] - 0.96) < 1e-3
