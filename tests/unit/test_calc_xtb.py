"""tests/unit/test_calc_xtb.py — calc_xtb MCP 单元测试。

用 unittest.mock.patch 模拟 subprocess.run 和 shutil.which，
保持测试 < 1s。不真跑 xtb 二进制。
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, mock_open, patch

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "..", "fixtures", "xtb_h2_singlepoint.txt")

H2_XYZ = "2\n\nH  0.0  0.0  0.0\nH  0.74  0.0  0.0\n"

# ─── 真实 xtb 单点输出（H2 gfn2，TOTAL ENERGY = -0.76729349 Eh）─────────────
with open(FIXTURE_PATH) as fh:
    H2_SP_STDOUT = fh.read()


class TestSinglePoint(unittest.TestCase):
    """single_point 工具测试。"""

    def _mock_run(self, returncode=0, stdout="", stderr="", timeout=False):
        """返回一个带 .returncode/.stdout/.stderr 的 mock subprocess result。"""
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_single_point_success(self, mock_which, mock_run):
        """正常路径：xtb 正常运行并收敛。"""
        mock_which.return_value = "/usr/local/bin/xtb"
        mock_run.return_value = self._mock_run(returncode=0, stdout=H2_SP_STDOUT)

        from chemaster.mcp.calc_xtb.server import single_point

        result = single_point(H2_XYZ)

        self.assertTrue(result["ok"])
        # 能量值
        self.assertIsNotNone(result["result"]["energy"])
        self.assertAlmostEqual(
            result["result"]["energy"]["value"],
            -0.76729349,
            places=5,
        )
        self.assertEqual(result["result"]["energy"]["unit"], "Hartree")
        # HOMO-LUMO gap
        self.assertIsNotNone(result["result"]["homo_lumo_gap"])
        self.assertAlmostEqual(result["result"]["homo_lumo_gap"]["value"], 22.63778629, places=4)
        self.assertEqual(result["result"]["homo_lumo_gap"]["unit"], "eV")
        # meta
        self.assertIn("wall_time_s", result["meta"])
        self.assertIn("xtb_version", result["meta"])
        self.assertIn("command", result["meta"])
        self.assertIn("--gfn", result["meta"]["command"])

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_single_point_scf_not_converged(self, mock_which, mock_run):
        """错误路径：SCC 未收敛。"""
        mock_which.return_value = "/usr/bin/xtb"
        not_converged = H2_SP_STDOUT.replace(
            "SCF CONVERGED     =        yes",
            "SCC could not be converged",
        )
        mock_run.return_value = self._mock_run(returncode=0, stdout=not_converged)

        from chemaster.mcp.calc_xtb.server import single_point

        result = single_point(H2_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "SCF_NOT_CONVERGED")

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_single_point_engine_not_found(self, mock_which, mock_run):
        """错误路径：xtb 不在 PATH。"""
        mock_which.return_value = None

        from chemaster.mcp.calc_xtb.server import single_point

        result = single_point(H2_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "ENGINE_NOT_FOUND")
        mock_run.assert_not_called()

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_single_point_invalid_method(self, mock_which, mock_run):
        """错误路径：无效 method 参数。"""
        mock_which.return_value = "/usr/bin/xtb"

        from chemaster.mcp.calc_xtb.server import single_point

        result = single_point(H2_XYZ, method="invalid_method")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_INPUT")

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_single_point_parse_error(self, mock_which, mock_run):
        """错误路径：输出无法解析（损坏输出）。"""
        mock_which.return_value = "/usr/bin/xtb"
        mock_run.return_value = self._mock_run(returncode=0, stdout="garbage output\n")

        from chemaster.mcp.calc_xtb.server import single_point

        result = single_point(H2_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "PARSE_ERROR")

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_single_point_multiplicity_uhf_mapping(self, mock_which, mock_run):
        """验证 multiplicity=1 → --uhf 0，multiplicity=2 → --uhf 1。"""
        mock_which.return_value = "/usr/bin/xtb"
        mock_run.return_value = self._mock_run(returncode=0, stdout=H2_SP_STDOUT)

        from chemaster.mcp.calc_xtb.server import single_point

        result = single_point(H2_XYZ, multiplicity=2)

        self.assertTrue(result["ok"])
        # doublet → UHF 1 → 命令里应有 "--uhf 1"
        self.assertIn("--uhf 1", result["meta"]["command"])

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_single_point_solvent_arg(self, mock_which, mock_run):
        """验证 solvent 参数正确传递为 --alpb。"""
        mock_which.return_value = "/usr/bin/xtb"
        mock_run.return_value = self._mock_run(returncode=0, stdout=H2_SP_STDOUT)

        from chemaster.mcp.calc_xtb.server import single_point

        result = single_point(H2_XYZ, solvent="water")

        self.assertTrue(result["ok"])
        self.assertIn("--alpb water", result["meta"]["command"])


class TestOptimize(unittest.TestCase):
    """optimize 工具测试。"""

    def _mock_run(self, returncode=0, stdout="", stderr=""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def _make_opt_stdout(self, energy: float, gap: float, cycle_count: int = 5) -> str:
        """生成含优化信息的 xtb 输出。"""
        cycles = "\n".join(
            f"     iteration  {i} : time  0.0s, total energy =    {energy:.6f} Eh"
            for i in range(1, cycle_count + 1)
        )
        return (
            f""" {cycles}
              =========================================
               TOTAL ENERGY      =     {energy} Eh
               GRADIENT NORM     =      0.00002276 Eh/α
               HOMO-LUMO GAP     =     {gap} eV
               DIPOLE MOMENT     =      0.00000000 Debye
               SCF CONVERGED     =        yes
              =========================================
"""
        )

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_optimize_success(self, mock_which, mock_run):
        """正常路径：优化收敛，xtbopt.xyz 存在。"""
        mock_which.return_value = "/usr/bin/xtb"
        opt_stdout = self._make_opt_stdout(energy=-0.9, gap=15.0)
        mock_run.return_value = self._mock_run(returncode=0, stdout=opt_stdout)

        from chemaster.mcp.calc_xtb.server import optimize

        # mock xtbopt.xyz 内容
        opt_xyz = "2\n\nH  0.0  0.0  0.0\nH  0.75  0.0  0.0\n"

        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=opt_xyz)):
                result = optimize(H2_XYZ)

        self.assertTrue(result["ok"])
        self.assertTrue(result["result"]["converged"])
        self.assertEqual(result["result"]["final_energy"]["unit"], "Hartree")
        self.assertIn("optimized_geometry_xyz", result["result"])
        self.assertIn("--opt", result["meta"]["command"])

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_optimize_not_converged(self, mock_which, mock_run):
        """错误路径：优化未收敛（xtbopt.xyz 不存在）。"""
        mock_which.return_value = "/usr/bin/xtb"
        # SCC 收敛但优化未完成
        opt_stdout = self._make_opt_stdout(energy=-0.5, gap=10.0)
        mock_run.return_value = self._mock_run(returncode=0, stdout=opt_stdout)

        from chemaster.mcp.calc_xtb.server import optimize

        result = optimize(H2_XYZ)

        # 此时 converged=False，但仍返回 ok（因为 SCF 收敛了）
        self.assertTrue(result["ok"])
        self.assertFalse(result["result"]["converged"])
        self.assertIn("did not converge", result["warnings"][0])

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_optimize_engine_not_found(self, mock_which, mock_run):
        """错误路径：xtb 不在 PATH。"""
        mock_which.return_value = None

        from chemaster.mcp.calc_xtb.server import optimize

        result = optimize(H2_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "ENGINE_NOT_FOUND")

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_optimize_invalid_multiplicity(self, mock_which, mock_run):
        """错误路径：multiplicity < 1。"""
        mock_which.return_value = "/usr/bin/xtb"

        from chemaster.mcp.calc_xtb.server import optimize

        result = optimize(H2_XYZ, multiplicity=0)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_INPUT")

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_optimize_scf_not_converged(self, mock_which, mock_run):
        """错误路径：SCF 未收敛导致优化失败。"""
        mock_which.return_value = "/usr/bin/xtb"
        not_converged = H2_SP_STDOUT.replace(
            "SCF CONVERGED     =        yes",
            "SCC could not be converged",
        )
        mock_run.return_value = self._mock_run(returncode=0, stdout=not_converged)

        from chemaster.mcp.calc_xtb.server import optimize

        result = optimize(H2_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "SCF_NOT_CONVERGED")

    @patch("subprocess.run")
    @patch("shutil.which")
    def test_optimize_timeout(self, mock_which, mock_run):
        """错误路径：超时。"""
        mock_which.return_value = "/usr/bin/xtb"
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("xtb", 3600)

        from chemaster.mcp.calc_xtb.server import optimize

        result = optimize(H2_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
