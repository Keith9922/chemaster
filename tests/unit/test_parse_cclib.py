"""tests/unit/test_parse_cclib.py — parse_cclib MCP 单元测试。

用 unittest.mock.patch 模拟 cclib.io.ccread，保持测试 < 1s。
每个 tool 配：1 个正常路径 + 1 个错误路径。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import cclib
import numpy as np


class MockccData:
    """构造一个假 ccData 对象，模拟 cclib 解析结果。"""

    def __init__(self, **attrs):
        for k, v in attrs.items():
            setattr(self, k, v)


class TestParseOutput(unittest.TestCase):
    """parse_output 工具测试。"""

    def _make_mock_ccdata(self) -> MockccData:
        return MockccData(
            natom=3,
            charge=0,
            mult=1,
            scfenergies=np.array([-75.0, -75.5, -75.8]),  # eV
            final_energy=None,  # not a real attr, final_energy is derived
            moenergies=[np.array([
                -20.1, -15.3, -12.0, -10.5, -8.2,  # HOMO-4 … HOMO
                -5.1, -3.8, -1.2, 0.5, 2.3,  # LUMO … LUMO+4
            ])],
            homos=np.array([4]),  # HOMO 索引 = 4
            mosyms=[["A1", "A1", "B2", "B1", "A2", "B2", "A1", "B2", "A1", "B1"]],
            atomnos=np.array([8, 1, 1]),  # H2O
            atomcoords=np.array([[[0.0, 0.0, 0.0],
                                  [0.96, 0.0, 0.0],
                                  [-0.48, 0.83, 0.0]]]),
            vibfreqs=np.array([1600.0, 3800.0, 3900.0]),  # cm^-1
            zpve=0.0213,  # hartree/particle
            optdone=True,
            optstatus=None,
            metadata={"package": "psi4", "package_version": "1.9.0"},
        )

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    def test_parse_output_success(self, mock_getsize, mock_exists, mock_ccread):
        """正常路径：文件存在且 cclib 解析成功。"""
        mock_exists.return_value = True
        mock_getsize.return_value = 4096
        mock_ccread.return_value = self._make_mock_ccdata()

        from chemaster.mcp.parse_cclib.server import parse_output

        result = parse_output("h2o.out")

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["engine"], "Mock")
        self.assertEqual(result["result"]["engine_version"], "1.9.0")
        self.assertEqual(result["result"]["n_atoms"], 3)
        self.assertEqual(result["result"]["charge"], 0)
        self.assertEqual(result["result"]["multiplicity"], 1)
        self.assertTrue(result["result"]["converged"])
        # scfenergies 长度
        self.assertEqual(len(result["result"]["scfenergies"]), 3)
        # final_energy = scfenergies[-1]
        self.assertAlmostEqual(result["result"]["final_energy"]["value"], -75.8, places=3)
        # geometry_xyz
        xyz = result["result"]["geometry_xyz"]
        self.assertTrue(xyz.startswith("3\n\n  O"))
        # homo_lumo_gap
        gap = result["result"]["homo_lumo_gap"]
        self.assertIsNotNone(gap)
        self.assertAlmostEqual(gap["value"], 3.1, places=1)  # ~3.1 eV
        # frequencies
        self.assertEqual(len(result["result"]["frequencies_cm_inv"]), 3)
        # zpe
        self.assertIsNotNone(result["result"]["zpe"])
        self.assertEqual(result["result"]["zpe"]["unit"], "hartree/particle")
        # meta
        self.assertEqual(result["meta"]["file_size_kb"], 4.0)
        mock_ccread.assert_called_once_with("h2o.out")

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    def test_parse_output_file_not_found(self, mock_exists, mock_ccread):
        """错误路径：文件不存在。"""
        mock_exists.return_value = False

        from chemaster.mcp.parse_cclib.server import parse_output

        result = parse_output("/nonexistent/file.out")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "FILE_NOT_FOUND")
        self.assertIn("not found", result["details"])
        mock_ccread.assert_not_called()

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    def test_parse_output_cclib_returns_none(self, mock_getsize, mock_exists, mock_ccread):
        """错误路径：cclib 无法识别文件格式。"""
        mock_exists.return_value = True
        mock_getsize.return_value = 512
        mock_ccread.return_value = None

        from chemaster.mcp.parse_cclib.server import parse_output

        result = parse_output("unknown_format.dat")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "PARSE_ERROR")
        self.assertIn("None", result["details"])

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    def test_parse_output_exception(self, mock_getsize, mock_exists, mock_ccread):
        """错误路径：cclib 解析时抛出异常。"""
        mock_exists.return_value = True
        mock_getsize.return_value = 512
        mock_ccread.side_effect = RuntimeError("unexpected error")

        from chemaster.mcp.parse_cclib.server import parse_output

        result = parse_output("corrupt.out")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "PARSE_ERROR")
        self.assertIn("RuntimeError", result["details"])

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    def test_parse_output_no_homo_lumo(self, mock_getsize, mock_exists, mock_ccread):
        """边界：输出无轨道能量，homo_lumo_gap 应为 null。"""
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        ccdata = MockccData(
            natom=2,
            charge=0,
            mult=1,
            scfenergies=np.array([-10.0]),
            moenergies=[np.array([])],  # 空轨道列表
            homos=np.array([]),  # 空
            atomnos=np.array([1, 1]),
            atomcoords=np.array([[[0.0, 0.0, 0.0], [0.74, 0.0, 0.0]]]),
            metadata={"package": "xtb", "package_version": "6.7.1"},
            optdone=False,
            optstatus=None,
        )
        mock_ccread.return_value = ccdata

        from chemaster.mcp.parse_cclib.server import parse_output

        result = parse_output("h2.out")

        self.assertTrue(result["ok"])
        self.assertIsNone(result["result"]["homo_lumo_gap"])

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    def test_parse_output_no_frequencies(self, mock_getsize, mock_exists, mock_ccread):
        """边界：单点计算无振动频率，frequencies_cm_inv 应为 null。"""
        mock_exists.return_value = True
        mock_getsize.return_value = 512
        ccdata = MockccData(
            natom=3,
            charge=0,
            mult=1,
            scfenergies=np.array([-75.0]),
            moenergies=[np.array([-10.0, -5.0, 2.0])],
            homos=np.array([0]),
            atomnos=np.array([8, 1, 1]),
            atomcoords=np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [-0.5, 0.86, 0.0]]]),
            vibfreqs=None,  # 无频率
            zpve=None,  # 无 ZPE
            metadata={"package": "orca", "package_version": "5.0"},
            optdone=False,
            optstatus=None,
        )
        mock_ccread.return_value = ccdata

        from chemaster.mcp.parse_cclib.server import parse_output

        result = parse_output("h2o_sp.out")

        self.assertTrue(result["ok"])
        self.assertIsNone(result["result"]["frequencies_cm_inv"])
        self.assertIsNone(result["result"]["zpe"])


class TestExtractOrbitals(unittest.TestCase):
    """extract_orbitals 工具测试。"""

    def _make_mock_ccdata(self) -> MockccData:
        energies = np.array([
            -20.1, -18.5, -15.3, -12.0, -10.5,  # HOMO-4 … HOMO-1
            -8.2,   # HOMO
            -5.1, -3.8, -1.2, 0.5, 2.3, 3.8,  # LUMO+1 … LUMO+6
        ])
        symmetries = ["A1", "B2", "A1", "B1", "B2", "A2",
                      "B2", "A1", "B2", "A1", "B1", "A2", "B2"]
        return MockccData(
            moenergies=[energies],
            mosyms=[symmetries],
            homos=np.array([5]),  # HOMO 索引 = 5，能量 -8.2 eV
            metadata={"package": "psi4", "package_version": "1.9.0"},
        )

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    def test_extract_orbitals_success(self, mock_exists, mock_ccread):
        """正常路径：成功提取 HOMO 周围 ±3 个轨道。"""
        mock_exists.return_value = True
        mock_ccread.return_value = self._make_mock_ccdata()

        from chemaster.mcp.parse_cclib.server import extract_orbitals

        result = extract_orbitals("h2o.out", n_around_homo=3)

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["engine"], "Mock")
        self.assertEqual(result["result"]["homo_index"], 5)
        # ±3 → indices 2,3,4,5,6,7,8
        self.assertEqual(len(result["result"]["orbitals"]), 7)
        # 检查 HOMO 能量
        homo_orb = next(o for o in result["result"]["orbitals"] if o["index"] == 5)
        self.assertAlmostEqual(homo_orb["energy"], -8.2, places=2)
        self.assertEqual(homo_orb["symmetry"], "A2")
        # 检查单位
        self.assertEqual(result["result"]["orbitals"][0]["unit"], "eV")
        mock_ccread.assert_called_once_with("h2o.out")

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    def test_extract_orbitals_file_not_found(self, mock_exists, mock_ccread):
        """错误路径：文件不存在。"""
        mock_exists.return_value = False

        from chemaster.mcp.parse_cclib.server import extract_orbitals

        result = extract_orbitals("/missing/orca.out")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "FILE_NOT_FOUND")
        mock_ccread.assert_not_called()

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    def test_extract_orbitals_no_orbital_data(self, mock_exists, mock_ccread):
        """错误路径：输出不含轨道信息。"""
        mock_exists.return_value = True
        mock_ccread.return_value = MockccData(
            moenergies=None,
            homos=np.array([3]),
            metadata={"package": "xtb", "package_version": "6.7"},
        )

        from chemaster.mcp.parse_cclib.server import extract_orbitals

        result = extract_orbitals("xtb.out")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "PARSE_ERROR")
        self.assertIn("moenergies or homos", result["details"])

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    def test_extract_orbitals_cclib_exception(self, mock_exists, mock_ccread):
        """错误路径：cclib 解析抛出异常。"""
        mock_exists.return_value = True
        mock_ccread.side_effect = OSError("read error")

        from chemaster.mcp.parse_cclib.server import extract_orbitals

        result = extract_orbitals("corrupt.log")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "PARSE_ERROR")
        self.assertIn("OSError", result["details"])

    @patch.object(cclib.io, "ccread")
    @patch("os.path.exists")
    def test_extract_orbitals_boundary_at_start(self, mock_exists, mock_ccread):
        """边界：HOMO 靠近轨道列表开头（索引 0）。"""
        mock_exists.return_value = True
        mock_ccread.return_value = MockccData(
            moenergies=[np.array([-5.0, -3.0, -1.0, 2.0])],  # 仅 4 个轨道
            mosyms=[["A", "B", "A", "B"]],
            homos=np.array([0]),  # HOMO 索引 = 0
            metadata={"package": "orca", "package_version": "5.0"},
        )

        from chemaster.mcp.parse_cclib.server import extract_orbitals

        result = extract_orbitals("tiny.out", n_around_homo=3)

        self.assertTrue(result["ok"])
        # lo = max(0, 0-3) = 0, hi = min(3, 0+3) = 3
        self.assertEqual(len(result["result"]["orbitals"]), 4)


if __name__ == "__main__":
    unittest.main()
