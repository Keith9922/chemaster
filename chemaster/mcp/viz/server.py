"""chem.viz — 可视化 MCP server (3D 分子结构 + IR 光谱)。

工具：plot_3d（ASE + matplotlib）、plot_ir（高斯展宽光谱）。
"""

from __future__ import annotations

from io import StringIO
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")

from ase.io import read
from ase.visualize.plot import plot_atoms
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chem.viz")


@mcp.tool()
def plot_3d(
    geometry_xyz: str,
    output_path: str,
    title: str | None = None,
    dpi: int = 150,
    figsize_inches: tuple[float, float] = (5.0, 5.0),
) -> dict[str, Any]:
    """渲染分子 3D 结构为 PNG 图片（ASE + matplotlib）。

    Args:
        geometry_xyz: XYZ 格式分子结构字符串。
        output_path: 输出 PNG 路径（调用方指定，不硬编码）。
        title: 可选图片标题。
        dpi: 输出分辨率。
        figsize_inches: 画布尺寸（英寸）。

    Returns:
        ok=True:
          {
            "ok": True,
            "result": {"output_path": str, "n_atoms": int},
            "warnings": [],
            "meta": {"tool": "plot_3d"}
          }
        ok=False:
          {"ok": False, "error_code": "INVALID_GEOMETRY" | "WRITE_ERROR", ...}
    """
    # 解析几何
    try:
        atoms = read(StringIO(geometry_xyz), format="xyz")
    except Exception as e:
        return {
            "ok": False,
            "error_code": "INVALID_GEOMETRY",
            "details": f"ASE failed to parse XYZ: {e}",
            "suggestion": "Provide a valid XYZ format string (line1=n_atoms, line2=comment, line3+=symbol x y z).",
        }

    n_atoms = len(atoms)

    # 渲染
    try:
        fig, ax = plt.subplots(figsize=figsize_inches)
        plot_atoms(atoms, ax, radii=0.5, rotation=("0x,0y,0z"))
        if title:
            ax.set_title(title)
        ax.set_axis_off()
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
    except Exception as e:
        return {
            "ok": False,
            "error_code": "WRITE_ERROR",
            "details": f"Failed to render or save figure: {e}",
            "suggestion": "Check output_path is writable and dpi/figsize are valid.",
        }

    return {
        "ok": True,
        "result": {"output_path": output_path, "n_atoms": n_atoms},
        "warnings": [],
        "meta": {"tool": "plot_3d"},
    }


@mcp.tool()
def plot_ir(
    frequencies_cm_inv: list[float],
    intensities_km_per_mol: list[float],
    output_path: str,
    x_min: float = 400.0,
    x_max: float = 4000.0,
    broadening_cm_inv: float = 10.0,
    dpi: int = 150,
) -> dict[str, Any]:
    """绘制 IR 光谱图（高斯展宽）。

    Args:
        frequencies_cm_inv: 各频率（cm⁻¹），负值（虚频）会被跳过。
        intensities_km_per_mol: 对应峰强（km/mol）。
        output_path: 输出 PNG 路径（调用方指定，不硬编码）。
        x_min: 谱图左界（cm⁻¹）。
        x_max: 谱图右界（cm⁻¹）。
        broadening_cm_inv: 高斯展宽半高宽（cm⁻¹）。
        dpi: 输出分辨率。

    Returns:
        ok=True:
          {
            "ok": True,
            "result": {"output_path": str, "n_peaks_plotted": int},
            "warnings": [],
            "meta": {"tool": "plot_ir"}
          }
        ok=False:
          {"ok": False, "error_code": "INVALID_INPUT" | "WRITE_ERROR", ...}
    """
    if len(frequencies_cm_inv) != len(intensities_km_per_mol):
        return {
            "ok": False,
            "error_code": "INVALID_INPUT",
            "details": "frequencies_cm_inv and intensities_km_per_mol must have same length.",
            "suggestion": "Provide matching length arrays.",
        }

    if not frequencies_cm_inv:
        return {
            "ok": False,
            "error_code": "INVALID_INPUT",
            "details": "Empty frequencies list.",
            "suggestion": "Provide at least one frequency-intensity pair.",
        }

    # 过滤虚频
    n_imaginary = sum(1 for f in frequencies_cm_inv if f < 0)
    warnings: list[str] = []
    if n_imaginary > 0:
        warnings.append(f"IMAGINARY_FREQUENCIES_SKIPPED: n={n_imaginary}")

    freqs = np.array([f for f in frequencies_cm_inv if f >= 0])
    ints = np.array([i for f, i in zip(frequencies_cm_inv, intensities_km_per_mol, strict=False) if f >= 0])

    if freqs.size == 0:
        return {
            "ok": False,
            "error_code": "INVALID_INPUT",
            "details": "No non-negative frequencies after filtering imaginary modes.",
            "suggestion": "Provide at least one real (non-negative) frequency.",
        }

    # 高斯展宽
    x = np.linspace(x_min, x_max, 2000)
    sigma = broadening_cm_inv / (2 * np.sqrt(2 * np.log(2)))  # FWHM -> sigma
    spectrum = np.zeros_like(x)
    for f, i in zip(freqs, ints, strict=False):
        spectrum += i * np.exp(-0.5 * ((x - f) / sigma) ** 2)

    # 绘图
    try:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.fill_between(x, spectrum, alpha=0.4, color="steelblue")
        ax.plot(x, spectrum, color="steelblue", linewidth=1.0)
        ax.set_xlabel("Wavenumber (cm⁻¹)")
        ax.set_ylabel("Intensity (km/mol)")
        ax.set_xlim(x_min, x_max)
        ax.grid(True, alpha=0.3)
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
    except Exception as e:
        return {
            "ok": False,
            "error_code": "WRITE_ERROR",
            "details": f"Failed to render or save spectrum: {e}",
            "suggestion": "Check output_path is writable.",
        }

    return {
        "ok": True,
        "result": {"output_path": output_path, "n_peaks_plotted": int(freqs.size)},
        "warnings": warnings,
        "meta": {"tool": "plot_ir"},
    }


def main() -> None:
    """``chemaster-mcp viz`` 入口。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
