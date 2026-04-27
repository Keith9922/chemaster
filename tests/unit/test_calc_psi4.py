"""tests/unit/test_calc_psi4.py — calc_psi4 MCP 单元测试。

用 unittest.mock.patch 模拟 psi4 函数调用，不真跑 psi4。
psi4 是 C 扩展模块，所以对 psi4.core.get_active_wavefunction 等
compiled 属性用 create=True + 手动赋值 mock。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


# ─── 测试用 H2O XYZ（3 行，不含电荷/自旋行）─────────────────────────────
H2O_XYZ = """O  0.000000  -0.000000   0.117379
H  0.000000   0.757063  -0.469516
H  0.000000  -0.757063  -0.469516"""


class MockWavefunction:
    """模拟 psi4.core.Wavefunction。"""

    def __init__(self):
        self._nbf = 36
        self._n_iter = 12
        self._homo = -0.396  # Hartree
        self._lumo = 0.048   # Hartree
        self._dipole_au = 0.73  # atomic unit

    def basisset(self) -> MagicMock:
        m = MagicMock()
        m.nbf.return_value = self._nbf
        return m

    def nbf(self) -> int:
        return self._nbf

    def iterations(self) -> MagicMock:
        m = MagicMock()
        m.n_scf_iterations.return_value = self._n_iter
        return m

    def epsilon_a(self) -> MagicMock:
        import numpy as np
        arr = np.array([-1.0, -0.6, -0.5, -0.45, -0.42, self._homo,
                         self._lumo, 0.1, 0.2, 0.3])
        m = MagicMock()
        m.to_array.return_value = arr
        return m

    def nalpha(self) -> int:
        return 5  # H2O singlet: 10 electrons → 5 alpha

    def dipole(self) -> float:
        return self._dipole_au


def _mock_wfn() -> MockWavefunction:
    return MockWavefunction()


# ─── Patch helper：避免 AttributeError when patching C extension attrs ──────
def _apply_psi4_patches(test_method):
    """Decorator that uses create=True for psi4.core attrs to avoid AttributeError."""
    return patch("psi4.energy", create=True)(test_method)


class TestSinglePointOK(unittest.TestCase):
    """ok 路径测试。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.energy", create=True)
    def test_ok_basic(
        self, mock_energy, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """正常路径：SCF 收敛，返回能量与附加信息。"""
        mock_energy.return_value = -76.4
        mock_get_wfn.return_value = _mock_wfn()

        from chemaster.mcp.calc_psi4.server import single_point

        result = single_point(H2O_XYZ)

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["energy"]["unit"], "Hartree")
        self.assertAlmostEqual(result["result"]["energy"]["value"], -76.4, places=4)
        self.assertEqual(result["result"]["n_basis_functions"], 36)
        self.assertEqual(result["result"]["n_iterations"], 12)
        self.assertIsNotNone(result["result"]["homo_lumo_gap"])
        self.assertEqual(result["result"]["homo_lumo_gap"]["unit"], "eV")
        self.assertIsNotNone(result["result"]["dipole"])
        self.assertEqual(result["result"]["dipole"]["unit"], "Debye")
        self.assertIn("psi4_version", result["meta"])
        self.assertIn("wall_time_s", result["meta"])
        self.assertIn("output_path", result["meta"])

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.energy", create=True)
    def test_ok_default_args(
        self, mock_energy, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """默认参数（B3LYP-D3(BJ) / def2-TZVP / memory=4GB / threads=4 / SAD）。"""
        mock_energy.return_value = -76.4
        mock_get_wfn.return_value = _mock_wfn()

        from chemaster.mcp.calc_psi4.server import single_point

        result = single_point(H2O_XYZ)

        self.assertTrue(result["ok"])
        mock_set_opts.assert_called_once()
        opts_dict = mock_set_opts.call_args[0][0]
        self.assertEqual(opts_dict["reference"], "rhf")
        self.assertEqual(opts_dict["guess"], "sad")
        self.assertEqual(opts_dict["scf_type"], "df")


class TestSinglePointSCFNotConverged(unittest.TestCase):
    """SCF 不收敛错误路径。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.energy", create=True)
    def test_scf_not_converged(
        self, mock_energy, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """SCF 未收敛 → SCF_NOT_CONVERGED + suggestion。"""
        import psi4

        mock_geom.return_value = MagicMock()
        # psi4.SCFConvergenceError 构造需特定参数，用 __new__ 绕过 __init__
        mock_scf_err = psi4.SCFConvergenceError.__new__(psi4.SCFConvergenceError)
        mock_energy.side_effect = mock_scf_err

        from chemaster.mcp.calc_psi4.server import single_point

        result = single_point(H2O_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "SCF_NOT_CONVERGED")


class TestSinglePointInvalidMultiplicity(unittest.TestCase):
    """INVALID_MULTIPLICITY 错误路径。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    def test_multiplicity_zero(
        self, mock_set_output, mock_set_threads, mock_set_mem, mock_geom
    ):
        """multiplicity=0 非法。"""
        from chemaster.mcp.calc_psi4.server import single_point

        result = single_point(H2O_XYZ, multiplicity=0)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_MULTIPLICITY")
        self.assertIn("multiplicity=0", result["details"])

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    def test_multiplicity_mismatch_even_electrons(
        self, mock_set_output, mock_set_threads, mock_set_mem, mock_geom
    ):
        """偶数电子闭壳层体系（如 H2O，10 电子）不能用 multiplicity=2 → INVALID_MULTIPLICITY。

        H2O 偶数电子（10），multiplicity=2 需要 n_unpaired=1，
        这要求 (10-1)/2 = 4.5 对配对电子，非整数 → 物理上不可能。
        """
        from chemaster.mcp.calc_psi4.server import single_point

        result = single_point(H2O_XYZ, multiplicity=2)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_MULTIPLICITY")
        self.assertIn("不匹配", result["details"])


class TestSinglePointSymmetryC1(unittest.TestCase):
    """验证 symmetry c1 被强制设置（PITFALLS §2.6）。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.energy", create=True)
    def test_symmetry_c1_forced(
        self, mock_energy, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """geometry() 调用包含 'symmetry c1'。"""
        mock_energy.return_value = -76.4
        mock_get_wfn.return_value = _mock_wfn()

        from chemaster.mcp.calc_psi4.server import single_point

        single_point(H2O_XYZ)

        mock_geom.assert_called_once()
        call_str = mock_geom.call_args[0][0]
        self.assertIn("symmetry c1", call_str)


class TestSinglePointUHF(unittest.TestCase):
    """验证 multiplicity ≠ 1 时使用 UHF 参考。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.energy", create=True)
    def test_reference_uhf_for_multiplicity_2(
        self, mock_energy, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """multiplicity=2 时 reference 应为 'uhf'。"""
        mock_energy.return_value = -75.8
        mock_get_wfn.return_value = _mock_wfn()

        from chemaster.mcp.calc_psi4.server import single_point

        # CH3 radical：6 电子 C + 3×H(1) = 9 电子 → doublet multiplicity=2 合法
        ch3_xyz = """C  0.0  0.0  0.0
H  1.0  0.0  0.0
H -0.5  0.87 0.0
H -0.5 -0.87 0.0"""
        result = single_point(ch3_xyz, charge=0, multiplicity=2)

        self.assertTrue(result["ok"])
        mock_set_opts.assert_called_once()
        opts_dict = mock_set_opts.call_args[0][0]
        self.assertEqual(opts_dict["reference"], "uhf")


class TestSinglePointInternalError(unittest.TestCase):
    """PSI4_INTERNAL_ERROR 兜底。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.energy", create=True)
    def test_psi4_internal_error(
        self, mock_energy, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """psi4 内部非 SCF 异常 → PSI4_INTERNAL_ERROR。"""
        mock_energy.side_effect = RuntimeError("Segmentation fault")

        from chemaster.mcp.calc_psi4.server import single_point

        result = single_point(H2O_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "PSI4_INTERNAL_ERROR")
        self.assertIn("Segmentation", result["details"])


class TestOptimizeOK(unittest.TestCase):
    """optimize 正常收敛路径。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.optimize", create=True)
    def test_ok_basic(
        self, mock_optimize, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """正常路径：优化收敛，返回能量、几何、迭代次数。"""
        mock_optimize.return_value = -76.4
        mock_get_wfn.return_value = _mock_wfn()

        mock_mol = MagicMock()
        mock_mol.save_string_xyz.return_value = """3
optimized H2O
O  0.0  0.0  0.0
H  0.9  0.0  0.0
H -0.4  0.8  0.0
"""
        mock_geom.return_value = mock_mol

        from chemaster.mcp.calc_psi4.server import optimize

        result = optimize(H2O_XYZ)

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["final_energy"]["unit"], "Hartree")
        self.assertAlmostEqual(result["result"]["final_energy"]["value"], -76.4, places=4)
        self.assertEqual(result["result"]["n_iterations"], 12)
        self.assertTrue(result["result"]["converged"])
        self.assertIn("optimized_geometry_xyz", result["result"])
        self.assertIn("psi4_version", result["meta"])
        self.assertIn("wall_time_s", result["meta"])
        self.assertIn("output_path", result["meta"])

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.optimize", create=True)
    def test_ok_default_args(
        self, mock_optimize, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """默认参数：tight / internal / max_iter=100 / memory=4GB / threads=4。"""
        mock_optimize.return_value = -76.4
        mock_get_wfn.return_value = _mock_wfn()
        mock_geom.return_value = MagicMock()
        mock_geom.return_value.save_string_xyz.return_value = "3\nok\nO  0 0 0\nH  1 0 0\nH -1 0 0\n"

        from chemaster.mcp.calc_psi4.server import optimize

        result = optimize(H2O_XYZ)

        self.assertTrue(result["ok"])
        mock_set_opts.assert_called_once()
        opts_dict = mock_set_opts.call_args[0][0]
        self.assertEqual(opts_dict["g_convergence"], "gau_tight")
        self.assertEqual(opts_dict["geom_maxiter"], 100)
        self.assertEqual(opts_dict["opt_coordinates"], "INTERNAL")
        self.assertEqual(opts_dict["reference"], "rhf")


class TestOptimizeConvergenceMapping(unittest.TestCase):
    """验证 convergence 参数映射到正确的 g_convergence 值。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.optimize", create=True)
    def test_convergence_loose_maps_to_gau_loose(
        self, mock_optimize, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """convergence='loose' → g_convergence='gau_loose'。"""
        mock_optimize.return_value = -76.4
        mock_get_wfn.return_value = _mock_wfn()
        mock_geom.return_value = MagicMock()
        mock_geom.return_value.save_string_xyz.return_value = "3\nok\nO  0 0 0\nH  1 0 0\nH -1 0 0\n"

        from chemaster.mcp.calc_psi4.server import optimize

        result = optimize(H2O_XYZ, convergence="loose")

        self.assertTrue(result["ok"])
        opts_dict = mock_set_opts.call_args[0][0]
        self.assertEqual(opts_dict["g_convergence"], "gau_loose")

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.optimize", create=True)
    def test_coordinate_system_redundant_internal(
        self, mock_optimize, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """coordinate_system='redundant_internal' → opt_coordinates='REDUNDANT_INTERNAL'。"""
        mock_optimize.return_value = -76.4
        mock_get_wfn.return_value = _mock_wfn()
        mock_geom.return_value = MagicMock()
        mock_geom.return_value.save_string_xyz.return_value = "3\nok\nO  0 0 0\nH  1 0 0\nH -1 0 0\n"

        from chemaster.mcp.calc_psi4.server import optimize

        result = optimize(H2O_XYZ, coordinate_system="redundant_internal")

        self.assertTrue(result["ok"])
        opts_dict = mock_set_opts.call_args[0][0]
        self.assertEqual(opts_dict["opt_coordinates"], "REDUNDANT_INTERNAL")


class TestOptimizeGeometryNotConverged(unittest.TestCase):
    """GEOMETRY_NOT_CONVERGED 错误路径。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.optimize", create=True)
    def test_geometry_not_converged(
        self, mock_optimize, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """达到 max_iter 未收敛 → GEOMETRY_NOT_CONVERGED + suggestion。"""
        import psi4

        mock_mol = MagicMock()
        mock_mol.save_string_xyz.return_value = "3\nnot_converged\nO  0 0 0\nH  1 0 0\nH -1 0 0\n"
        mock_geom.return_value = mock_mol
        mock_opt_err = psi4.OptimizationConvergenceError.__new__(psi4.OptimizationConvergenceError)
        mock_optimize.side_effect = mock_opt_err

        from chemaster.mcp.calc_psi4.server import optimize

        result = optimize(H2O_XYZ, max_iter=50)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "GEOMETRY_NOT_CONVERGED")
        self.assertIn("max_iter=50", result["details"])
        self.assertIn("coordinate_system", result["suggestion"])
        self.assertIn("convergence", result["suggestion"])


class TestOptimizeSCFNotConverged(unittest.TestCase):
    """SCF_NOT_CONVERGED 错误路径（优化过程中某步 SCF 失败）。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.optimize", create=True)
    def test_scf_not_converged(
        self, mock_optimize, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """优化中 SCF 未收敛 → SCF_NOT_CONVERGED + suggestion。"""
        import psi4

        mock_geom.return_value = MagicMock()
        mock_scf_err = psi4.SCFConvergenceError.__new__(psi4.SCFConvergenceError)
        mock_optimize.side_effect = mock_scf_err

        from chemaster.mcp.calc_psi4.server import optimize

        result = optimize(H2O_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "SCF_NOT_CONVERGED")
        self.assertIn("suggestion", result)


class TestOptimizeInvalidMultiplicity(unittest.TestCase):
    """INVALID_MULTIPLICITY 错误路径。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    def test_multiplicity_zero(
        self, mock_set_output, mock_set_threads, mock_set_mem, mock_geom
    ):
        """multiplicity=0 非法。"""
        from chemaster.mcp.calc_psi4.server import optimize

        result = optimize(H2O_XYZ, multiplicity=0)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_MULTIPLICITY")
        self.assertIn("multiplicity=0", result["details"])

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    def test_multiplicity_mismatch(
        self, mock_set_output, mock_set_threads, mock_set_mem, mock_geom
    ):
        """偶电子闭壳层体系（10 电子 H2O）multiplicity=4 非法（n_unpaired=3 → 配对电子 3.5 非整）。"""
        from chemaster.mcp.calc_psi4.server import optimize

        result = optimize(H2O_XYZ, multiplicity=4)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_MULTIPLICITY")


class TestOptimizeSymmetryC1(unittest.TestCase):
    """验证 symmetry c1 被强制设置。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.optimize", create=True)
    def test_symmetry_c1_forced(
        self, mock_optimize, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """geometry() 调用包含 'symmetry c1'。"""
        mock_optimize.return_value = -76.4
        mock_get_wfn.return_value = _mock_wfn()
        mock_geom.return_value = MagicMock()
        mock_geom.return_value.save_string_xyz.return_value = "3\nok\nO  0 0 0\nH  1 0 0\nH -1 0 0\n"

        from chemaster.mcp.calc_psi4.server import optimize

        optimize(H2O_XYZ)

        mock_geom.assert_called_once()
        call_str = mock_geom.call_args[0][0]
        self.assertIn("symmetry c1", call_str)


class TestOptimizeUHF(unittest.TestCase):
    """验证 multiplicity ≠ 1 时使用 UHF 参考。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.core.get_active_wavefunction", create=True)
    @patch("psi4.optimize", create=True)
    def test_reference_uhf_for_multiplicity_2(
        self, mock_optimize, mock_get_wfn, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """multiplicity=2 时 reference 应为 'uhf'。"""
        mock_optimize.return_value = -75.8
        mock_get_wfn.return_value = _mock_wfn()
        mock_geom.return_value = MagicMock()
        mock_geom.return_value.save_string_xyz.return_value = "4\nok\nC  0 0 0\nH  1 0 0\nH -1 0 0\nH  0 1 0\n"

        from chemaster.mcp.calc_psi4.server import optimize

        ch3_xyz = """C  0.0  0.0  0.0
H  1.0  0.0  0.0
H -0.5  0.87 0.0
H -0.5 -0.87 0.0"""
        result = optimize(ch3_xyz, charge=0, multiplicity=2)

        self.assertTrue(result["ok"])
        opts_dict = mock_set_opts.call_args[0][0]
        self.assertEqual(opts_dict["reference"], "uhf")


class TestOptimizeInternalError(unittest.TestCase):
    """PSI4_INTERNAL_ERROR 兜底。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.optimize", create=True)
    def test_psi4_internal_error(
        self, mock_optimize, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """psi4 内部非 SCF/Optimization 异常 → PSI4_INTERNAL_ERROR。"""
        mock_geom.return_value = MagicMock()
        mock_optimize.side_effect = RuntimeError("Segmentation fault")

        from chemaster.mcp.calc_psi4.server import optimize

        result = optimize(H2O_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "PSI4_INTERNAL_ERROR")
        self.assertIn("Segmentation", result["details"])


# ══════════════════════════════════════════════════════════════════════════════
# frequency 工具测试
# ══════════════════════════════════════════════════════════════════════════════

class MockFrequencyWavefunction:
    """模拟 psi4 频率计算的 wavefunction。"""

    def __init__(self, freqs, ir_intensities=None):
        import numpy as np
        self._freqs = np.array(freqs)
        self._ir_intensities = ir_intensities if ir_intensities is not None else [0.0] * len(freqs)
        self._fa = _MockFreqAnalysis(self._ir_intensities)

    def frequencies(self):
        m = MagicMock()
        m.to_array.return_value = self._freqs
        return m

    @property
    def frequency_analysis(self):
        return self._fa


class _MockFreqAnalysis:
    """模拟 wfn.frequency_analysis（dict-like，psi4 版本差异大）。"""

    def __init__(self, ir_intensities):
        import numpy as np
        self._ir = ir_intensities
        self._ir_data = MagicMock()
        self._ir_data.data = np.array(self._ir)

    def __contains__(self, key):
        return key == "IR_intensity"

    def __getitem__(self, key):
        if key == "IR_intensity":
            return self._ir_data
        raise KeyError(key)


class TestFrequencyOK(unittest.TestCase):
    """frequency 正常收敛路径（H2O 真实频率，无虚频）。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_ok_basic(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """正常路径：返回频率、IR 强度、ZPE，无虚频。"""
        import numpy as np

        # H2O 实际频率（cm^-1）：~3657, ~1595, ~3756
        h2o_freqs = np.array([3756.0, 3653.0, 1595.0])
        mock_wfn = MockFrequencyWavefunction(h2o_freqs, ir_intensities=[50.0, 10.0, 0.5])
        mock_freqs.return_value = (-76.4, mock_wfn)
        mock_geom.return_value = MagicMock()

        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ)

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["result"]["frequencies_cm_inv"]), 3)
        self.assertEqual(result["result"]["n_imaginary"], 0)
        self.assertEqual(result["result"]["zpe"]["unit"], "Hartree")
        # ZPE 校验：≈ 0.0205 Hartree（实测 H2O ZPE）
        self.assertAlmostEqual(
            result["result"]["zpe"]["value"], 0.0205, places=3
        )
        self.assertEqual(result["result"]["ir_intensities_km_per_mol"][0], 50.0)
        self.assertEqual(result["result"]["temperature_K"], 298.15)
        self.assertEqual(result["result"]["pressure_atm"], 1.0)
        self.assertEqual(result["warnings"], [])
        self.assertIn("psi4_version", result["meta"])
        self.assertIn("wall_time_s", result["meta"])

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_ok_imaginary_freq_warning(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """虚频存在时：n_imaginary>0 + warnings 填充。"""
        import numpy as np

        # 1 个虚频 + 2 个正频率
        freqs = np.array([-145.0, 1200.0, 3000.0])
        mock_wfn = MockFrequencyWavefunction(freqs, ir_intensities=[10.0, 5.0, 1.0])
        mock_freqs.return_value = (-76.4, mock_wfn)
        mock_geom.return_value = MagicMock()

        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ)

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["n_imaginary"], 1)
        self.assertIn("IMAGINARY_FREQUENCY", result["warnings"][0])
        self.assertIn("n=1", result["warnings"][0])
        self.assertIn("-145.0", result["warnings"][0])

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_ok_multiple_imaginary(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """多个虚频（过渡态场景）。"""
        import numpy as np

        freqs = np.array([-200.0, -50.0, 800.0, 1500.0, 2900.0])
        mock_wfn = MockFrequencyWavefunction(freqs, ir_intensities=[0.0, 0.0, 3.0, 2.0, 1.0])
        mock_freqs.return_value = (-76.4, mock_wfn)
        mock_geom.return_value = MagicMock()

        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ)

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["n_imaginary"], 2)
        self.assertIn("n=2", result["warnings"][0])

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_ok_ir_intensity_fallback(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """IR 强度不可用时 fallback 到 [0.0]*n_freqs。"""
        import numpy as np

        freqs = np.array([1000.0, 2000.0, 3000.0])
        # frequency_analysis 不包含 IR_intensity → fallback
        mock_wfn = MockFrequencyWavefunction(freqs, ir_intensities=None)
        mock_wfn._fa.__contains__ = lambda self, key: False
        mock_freqs.return_value = (-76.4, mock_wfn)
        mock_geom.return_value = MagicMock()

        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ)

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["ir_intensities_km_per_mol"], [0.0, 0.0, 0.0])

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_ok_symmetry_c1_forced(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """frequency 计算也强制 symmetry c1。"""
        import numpy as np

        freqs = np.array([1000.0, 2000.0])
        mock_wfn = MockFrequencyWavefunction(freqs)
        mock_freqs.return_value = (-76.4, mock_wfn)
        mock_geom.return_value = MagicMock()

        from chemaster.mcp.calc_psi4.server import frequency

        frequency(H2O_XYZ)

        mock_geom.assert_called_once()
        call_str = mock_geom.call_args[0][0]
        self.assertIn("symmetry c1", call_str)

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_ok_reference_uhf_for_multiplicity_2(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """multiplicity=2 时 reference 应为 'uhf'。"""
        import numpy as np

        freqs = np.array([500.0, 1000.0, 1500.0])
        mock_wfn = MockFrequencyWavefunction(freqs)
        mock_freqs.return_value = (-75.8, mock_wfn)
        mock_geom.return_value = MagicMock()

        from chemaster.mcp.calc_psi4.server import frequency

        ch3_xyz = """C  0.0  0.0  0.0
H  1.0  0.0  0.0
H -0.5  0.87 0.0
H -0.5 -0.87 0.0"""
        result = frequency(ch3_xyz, charge=0, multiplicity=2)

        self.assertTrue(result["ok"])
        opts_dict = mock_set_opts.call_args[0][0]
        self.assertEqual(opts_dict["reference"], "uhf")


class TestFrequencySCFNotConverged(unittest.TestCase):
    """SCF_NOT_CONVERGED 错误路径。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_scf_not_converged(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """SCF 未收敛 → SCF_NOT_CONVERGED + suggestion。"""
        import psi4

        mock_geom.return_value = MagicMock()
        mock_scf_err = psi4.SCFConvergenceError.__new__(psi4.SCFConvergenceError)
        mock_freqs.side_effect = mock_scf_err

        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "SCF_NOT_CONVERGED")


class TestFrequencyInvalidMultiplicity(unittest.TestCase):
    """INVALID_MULTIPLICITY 错误路径。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    def test_multiplicity_zero(
        self, mock_set_output, mock_set_threads, mock_set_mem, mock_geom
    ):
        """multiplicity=0 非法。"""
        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ, multiplicity=0)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_MULTIPLICITY")

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    def test_multiplicity_mismatch(
        self, mock_set_output, mock_set_threads, mock_set_mem, mock_geom
    ):
        """偶电子闭壳层体系（10 电子 H2O）multiplicity=4 非法。

        multiplicity=4 → n_unpaired=3 → (10-3)%2=1 → 配对电子数非整数。
        """
        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ, multiplicity=4)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_MULTIPLICITY")


class TestFrequencyInternalError(unittest.TestCase):
    """PSI4_INTERNAL_ERROR 兜底。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_psi4_internal_error(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """psi4 内部非 SCF 异常 → PSI4_INTERNAL_ERROR。"""
        mock_geom.return_value = MagicMock()
        mock_freqs.side_effect = RuntimeError("Segmentation fault")

        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "PSI4_INTERNAL_ERROR")
        self.assertIn("Segmentation", result["details"])


class TestFrequencyThermalCorrectionsPlaceholder(unittest.TestCase):
    """thermal_corrections 当前返回 null（Phase 2 前置检查）。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_thermal_corrections_are_null(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """Phase 2 接入完整 RRHO 前，h_corr/g_corr/ts 均为 null。"""
        import numpy as np

        freqs = np.array([1000.0, 2000.0, 3000.0])
        mock_wfn = MockFrequencyWavefunction(freqs)
        mock_freqs.return_value = (-76.4, mock_wfn)
        mock_geom.return_value = MagicMock()

        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ)

        self.assertTrue(result["ok"])
        tc = result["result"]["thermal_corrections"]
        self.assertIsNone(tc["h_corr"])
        self.assertIsNone(tc["g_corr"])
        self.assertIsNone(tc["ts"])


class TestFrequencyZPECalculation(unittest.TestCase):
    """ZPE 计算精度校验（H2O 频率 → ≈0.0205 Hartree）。"""

    @patch("psi4.geometry", create=True)
    @patch("psi4.set_options", create=True)
    @patch("psi4.set_memory", create=True)
    @patch("psi4.set_num_threads", create=True)
    @patch("psi4.core.set_output_file", create=True)
    @patch("psi4.frequencies", create=True)
    def test_zpe_approx_h2o(
        self, mock_freqs, mock_set_output,
        mock_set_threads, mock_set_mem, mock_set_opts, mock_geom
    ):
        """H2O 频率 [3756, 3653, 1595] cm^-1 → ZPE ≈ 0.0205 Hartree。"""
        import numpy as np

        # 来自真实 H2O B3LYP/def2-TZVP 频率计算
        freqs = np.array([3756.0, 3653.0, 1595.0])
        mock_wfn = MockFrequencyWavefunction(freqs)
        mock_freqs.return_value = (-76.4, mock_wfn)
        mock_geom.return_value = MagicMock()

        from chemaster.mcp.calc_psi4.server import frequency

        result = frequency(H2O_XYZ)

        self.assertTrue(result["ok"])
        # ZPE = 0.5 * (3756 + 3653 + 1595) / hartree_to_cm_inv
        # hartree_to_cm_inv ≈ 219474.63
        # ZPE_cm_inv = 4502 cm^-1
        # ZPE_Eh = 4502 / 219474.63 ≈ 0.02051
        self.assertAlmostEqual(
            result["result"]["zpe"]["value"], 0.0205, places=3
        )


if __name__ == "__main__":
    unittest.main()