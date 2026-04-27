"""mcp.viz 单元测试。"""

from __future__ import annotations

import os

import pytest

from chemaster.mcp.viz import server as S


# ------------------------------------------------------------------
# plot_3d
# ------------------------------------------------------------------

def test_plot_3d_ok(tmp_path):
    """H2 最简 XYZ 能渲染为 PNG，文件存在且 n_atoms=2。"""
    xyz = "2\n\nH 0 0 0\nH 0 0 0.74"
    out = str(tmp_path / "h2.png")
    result = S.plot_3d(geometry_xyz=xyz, output_path=out)
    assert result["ok"] is True
    assert result["result"]["output_path"] == out
    assert result["result"]["n_atoms"] == 2
    assert result["warnings"] == []
    assert os.path.exists(out)


def test_plot_3d_invalid_geometry():
    """非法 XYZ 字符串返回 INVALID_GEOMETRY。"""
    result = S.plot_3d(geometry_xyz="abc", output_path="/tmp/x.png")
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_GEOMETRY"


def test_plot_3d_with_title(tmp_path):
    """带 title 参数渲染成功。"""
    xyz = "2\nHydrogen\nH 0 0 0\nH 0 0 0.74"
    out = str(tmp_path / "h2_title.png")
    result = S.plot_3d(geometry_xyz=xyz, output_path=out, title="H2 molecule")
    assert result["ok"] is True
    assert os.path.exists(out)


# ------------------------------------------------------------------
# plot_ir
# ------------------------------------------------------------------

def test_plot_ir_ok(tmp_path):
    """H2O 三频率能渲染为 PNG，文件大小 > 0。"""
    # ~3400, ~1600, ~400 cm⁻¹（典型 H2O IR 峰）
    freqs = [3400.0, 1600.0, 400.0]
    ints = [20.0, 50.0, 10.0]
    out = str(tmp_path / "h2o_ir.png")
    result = S.plot_ir(
        frequencies_cm_inv=freqs,
        intensities_km_per_mol=ints,
        output_path=out,
    )
    assert result["ok"] is True
    assert result["result"]["output_path"] == out
    assert result["result"]["n_peaks_plotted"] == 3
    assert result["warnings"] == []
    assert os.path.getsize(out) > 0


def test_plot_ir_imaginary_freq_skipped(tmp_path):
    """虚频（负值）被跳过，warnings 包含 IMAGINARY_FREQUENCIES_SKIPPED。"""
    freqs = [-100.0, 1000.0, 3000.0]
    ints = [5.0, 30.0, 15.0]
    out = str(tmp_path / "h2o_imag.png")
    result = S.plot_ir(
        frequencies_cm_inv=freqs,
        intensities_km_per_mol=ints,
        output_path=out,
    )
    assert result["ok"] is True
    assert result["result"]["n_peaks_plotted"] == 2  # 只剩 2 个实频
    assert any("IMAGINARY_FREQUENCIES_SKIPPED" in w for w in result["warnings"])
    assert os.path.getsize(out) > 0


def test_plot_ir_mismatched_lengths():
    """频率和强度长度不一致返回 INVALID_INPUT。"""
    result = S.plot_ir(
        frequencies_cm_inv=[1000.0, 2000.0],
        intensities_km_per_mol=[10.0],  # 少一个
        output_path="/tmp/x.png",
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_INPUT"


def test_plot_ir_empty_list():
    """空频率列表返回 INVALID_INPUT。"""
    result = S.plot_ir(
        frequencies_cm_inv=[],
        intensities_km_per_mol=[],
        output_path="/tmp/x.png",
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_INPUT"


def test_plot_ir_all_imaginary():
    """全部为虚频时返回 INVALID_INPUT（过滤后无有效频率）。"""
    result = S.plot_ir(
        frequencies_cm_inv=[-500.0, -200.0],
        intensities_km_per_mol=[10.0, 20.0],
        output_path="/tmp/x.png",
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_INPUT"
