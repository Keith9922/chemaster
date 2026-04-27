"""mcp.io_ase 单元测试。"""

from __future__ import annotations

import pytest

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
