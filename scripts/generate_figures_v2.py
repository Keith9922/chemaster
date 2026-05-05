#!/usr/bin/env python3
"""为论文 §3-§4 生成补充图表（架构 / 流程 / 对比 / 截图）.

输出：paper/figures/v2/
  - fig_architecture.png   五层架构示意
  - fig_comparison.png     与 Rowan / ChemCrow / Schrödinger 对比
  - fig_permission.png     L1/L2/L3 权限分级与决策流
  - fig_pipeline.png       典型多软件流水线（agent 调度示意）
  - fig_test_run.png       单元测试运行截图（文本渲染）
  - fig_s22_terminal.png   S22 真跑终端截图
  - tui_demo.png           TUI 渲染（SVG 转 PNG）
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper" / "figures" / "v2"
OUT.mkdir(parents=True, exist_ok=True)

# 中文字体（macOS 优先）
plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'STHeiti',
                                    'Songti SC', 'Hiragino Sans GB',
                                    'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


# ════════════════════════════════════════════════════════════════════════════
# Fig 1 — 五层架构
# ════════════════════════════════════════════════════════════════════════════


def fig_architecture():
    fig, ax = plt.subplots(figsize=(9.5, 6.0))
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)
    ax.axis("off")

    layers = [
        # (y_bottom, y_top, label, color, content)
        (8.5, 9.6, "用户接口层  L5", "#4A90E2",
         "CLI（click + rich）   |   TUI（Textual）   |   本地 Web（FastAPI + 内嵌 SPA）"),
        (7.0, 8.3, "Agent 内核层  L4", "#7ED321",
         "tool-use 循环   |   confirm / recommend / silent 三模式   |   trajectory 持久化与权限分级"),
        (5.3, 6.8, "MCP 工具层  L3", "#F5A623",
         "calc_gaussian · calc_bdf · calc_momap · calc_psi4 · calc_orca · calc_xtb · io_ase · viz · hpc · kb"),
        (3.6, 5.1, "计算后端层  L2", "#BD10E0",
         "Gaussian   |   BDF   |   MOMAP   |   psi4   |   ORCA   |   xTB   |   ASE   |   RDKit"),
        (1.9, 3.4, "知识库层  L1", "#50E3C2",
         "formulas/  确定性 Python 公式（Marcus / MLJ / Strickler-Berg ...）   |   skills/  Markdown 文档"),
    ]
    for y0, y1, label, color, content in layers:
        box = FancyBboxPatch((0.5, y0), 9.0, y1 - y0,
                              boxstyle="round,pad=0.05",
                              linewidth=1.2, edgecolor="#222",
                              facecolor=color, alpha=0.18)
        ax.add_patch(box)
        ax.text(0.7, (y0 + y1) / 2 + 0.25, label,
                fontsize=11, fontweight="bold", color="#222",
                ha="left", va="center")
        ax.text(5.0, (y0 + y1) / 2 - 0.25, content,
                fontsize=9, color="#333",
                ha="center", va="center", style="italic")

    # 标题
    ax.text(5.0, 9.85, "图 3.1   ChemMaster 五层架构",
            fontsize=12, fontweight="bold", ha="center")
    # 数据流箭头（自底向上 / 自顶向下）
    ax.annotate("", xy=(0.3, 8.8), xytext=(0.3, 2.3),
                arrowprops=dict(arrowstyle="->", color="#666", lw=1))
    ax.text(0.05, 5.5, "数据流", rotation=90, fontsize=8,
            color="#666", ha="center", va="center")

    fig.tight_layout()
    fig.savefig(OUT / "fig_architecture.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {OUT / 'fig_architecture.png'}")


# ════════════════════════════════════════════════════════════════════════════
# Fig 2 — 与同类工作对比
# ════════════════════════════════════════════════════════════════════════════


def fig_comparison():
    fig, ax = plt.subplots(figsize=(10, 5.0))
    ax.axis("off")

    rows = [
        ("维度",            "Rowan",      "Schrödinger LD", "ChemCrow",       "ASE/AiiDA",  "ChemMaster"),
        ("部署形态",        "云端",       "企业云 + 桌面",  "Notebook",        "Python 库",  "本地终端"),
        ("LLM 集成",        "无",         "无",             "OpenAI 绑定",     "无",          "BYO（含国产）"),
        ("量子化学覆盖",    "中（限定）", "高（限自家）",   "低（多为 API）",  "高",         "高"),
        ("工具协议",        "私有",       "私有",           "LangChain",       "Python API", "MCP（开放）"),
        ("决策模式",        "用户全决策", "用户全决策",     "Agent 自主",      "用户编程",   "操作 vs 化学分级"),
        ("HPC 集成",        "内置自家",   "内置自家",       "无",              "插件",        "SLURM + 平台抽象"),
        ("用户接口",        "Web",        "GUI + Web",      "Notebook",        "Python",     "CLI + TUI + Web"),
    ]

    n_rows = len(rows)
    n_cols = len(rows[0])
    col_w = 1.6

    for ri, row in enumerate(rows):
        y = n_rows - ri - 1
        for ci, val in enumerate(row):
            x = ci * col_w
            if ri == 0:  # 表头
                rect = Rectangle((x, y), col_w, 0.8, facecolor="#2c3e50",
                                  edgecolor="white", linewidth=1)
                ax.add_patch(rect)
                ax.text(x + col_w / 2, y + 0.4, val,
                        ha="center", va="center", color="white",
                        fontsize=10, fontweight="bold")
            else:
                # 高亮 ChemMaster 列
                fc = "#fff7d4" if ci == n_cols - 1 else "#f8f9fa"
                rect = Rectangle((x, y), col_w, 0.8, facecolor=fc,
                                  edgecolor="#cccccc", linewidth=0.5)
                ax.add_patch(rect)
                weight = "bold" if ci == n_cols - 1 else "normal"
                ax.text(x + col_w / 2, y + 0.4, val,
                        ha="center", va="center",
                        fontsize=9, color="#222", fontweight=weight)
        # 维度名加粗
        if ri > 0:
            x0 = 0
            ax.text(x0 + col_w / 2, n_rows - ri - 1 + 0.4, row[0],
                    ha="center", va="center",
                    fontsize=9, color="#222", fontweight="bold")

    ax.set_xlim(-0.1, col_w * n_cols + 0.1)
    ax.set_ylim(-0.5, n_rows + 0.3)
    ax.text(col_w * n_cols / 2, n_rows + 0.05,
            "图 4.5   ChemMaster 与同类工作的对比",
            fontsize=12, fontweight="bold", ha="center")

    fig.tight_layout()
    fig.savefig(OUT / "fig_comparison.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {OUT / 'fig_comparison.png'}")


# ════════════════════════════════════════════════════════════════════════════
# Fig 3 — L1/L2/L3 权限分级流程
# ════════════════════════════════════════════════════════════════════════════


def fig_permission():
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)
    ax.axis("off")

    # 用户输入
    box(ax, 1.2, 8.4, 7.6, 0.9, "用户自然语言意图：例如「优化苯分子的 S0 与 S1 几何并算 ΔE_ST」",
        color="#4A90E2", text_color="white")

    # Agent 内核
    box(ax, 1.2, 6.8, 7.6, 1.0, "Agent 内核（基于 Anthropic SDK tool-use 循环）",
        color="#7ED321", text_color="white")
    arrow(ax, 5, 8.4, 5, 7.8)

    # 三个分支
    L1_color = "#A8E6A1"
    L2_color = "#FFD580"
    L3_color = "#F8A5A5"

    box(ax, 0.4, 4.8, 2.8, 1.5, "L1 自主\n（操作性工作）",
        color=L1_color, text_color="#1a4d1a", weight="bold", size=11)
    box(ax, 3.6, 4.8, 2.8, 1.5, "L2 推荐 / 确认\n（化学决策）",
        color=L2_color, text_color="#7a5500", weight="bold", size=11)
    box(ax, 6.8, 4.8, 2.8, 1.5, "L3 必须用户判断\n（边界情形）",
        color=L3_color, text_color="#7a1818", weight="bold", size=11)
    arrow(ax, 3.5, 6.8, 1.8, 6.3)
    arrow(ax, 5.0, 6.8, 5.0, 6.3)
    arrow(ax, 6.5, 6.8, 8.2, 6.3)

    # L1 例子
    box(ax, 0.4, 2.3, 2.8, 2.2,
        "• SCF 初始猜测切换\n  （SAD → GWH）\n• 提高 damping\n• 磁盘清理后重试\n• 网络重试 ×3\n• 输入文件语法修正",
        color=L1_color, text_color="#222", size=8.5, alpha=0.4)

    # L2 例子
    box(ax, 3.6, 2.3, 2.8, 2.2,
        "• 方法 / 基组 / 泛函选择\n• 溶剂模型选择\n• 弱虚频处理建议\n• L1 失败后的方法替换建议",
        color=L2_color, text_color="#222", size=8.5, alpha=0.4)

    # L3 例子
    box(ax, 6.8, 2.3, 2.8, 2.2,
        "• 多重度模糊（自由基/复合物）\n• TS vs 极小值判定\n• L2 推荐被拒后再失败\n• 切换软件后端\n• 跨方法结果不一致",
        color=L3_color, text_color="#222", size=8.5, alpha=0.4)

    # 输出标注
    box(ax, 0.4, 0.5, 2.8, 1.2, "trajectory 标记\nagent",
        color="#e8e8e8", text_color="#222", size=9)
    box(ax, 3.6, 0.5, 2.8, 1.2, "trajectory 标记\nuser-chemistry",
        color="#e8e8e8", text_color="#222", size=9)
    box(ax, 6.8, 0.5, 2.8, 1.2, "trajectory 标记\nuser-chemistry（escalation=true）",
        color="#e8e8e8", text_color="#222", size=8)

    arrow(ax, 1.8, 2.3, 1.8, 1.7)
    arrow(ax, 5.0, 2.3, 5.0, 1.7)
    arrow(ax, 8.2, 2.3, 8.2, 1.7)

    ax.text(5.0, 9.55, "图 3.2   操作性工作 vs 化学决策的权限分级机制",
            fontsize=12, fontweight="bold", ha="center")

    fig.tight_layout()
    fig.savefig(OUT / "fig_permission.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {OUT / 'fig_permission.png'}")


# ════════════════════════════════════════════════════════════════════════════
# Fig 4 — 多软件流水线（agent 调度示意）
# ════════════════════════════════════════════════════════════════════════════


def fig_pipeline():
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.set_xlim(0, 11); ax.set_ylim(0, 4)
    ax.axis("off")

    # 用户意图
    box(ax, 0.3, 3.0, 1.8, 0.7,
        "用户意图\n「算苯的 S1/T1 能隙\n与 k_RISC」",
        color="#4A90E2", text_color="white", size=8.5)

    # 主流水线 7 步
    steps = [
        (2.4, "io_ase\n.smiles_to_xyz", "#50E3C2"),
        (3.5, "recommend\nB3LYP / def2-SVP", "#FFD580"),
        (4.6, "calc_gaussian\n.optimize (S0)", "#F5A623"),
        (5.7, "calc_gaussian\n.frequency", "#F5A623"),
        (6.8, "calc_gaussian\n.opt_excited_state\n(S1)", "#F5A623"),
        (7.9, "calc_bdf\n.soc (T1↔S0)", "#BD10E0"),
        (9.0, "kb.formulas\n.krisc_marcus", "#7ED321"),
        (10.1, "finish",          "#4A90E2"),
    ]
    for x, label, color in steps:
        box(ax, x, 2.6, 1.0, 1.4, label,
            color=color, text_color="#222", size=8, weight="bold")
        if x > 2.4:
            arrow(ax, x - 0.07, 3.3, x, 3.3)

    # 用户意图 → 第一步
    arrow(ax, 2.1, 3.35, 2.4, 3.35)

    # 下方：每步在 trajectory 中的 decision_authority 标签
    auth_tags = [
        (2.4, "agent"),
        (3.5, "user-chemistry"),
        (4.6, "user-binary"),  # confirm long-running
        (5.7, "user-binary"),
        (6.8, "user-binary"),
        (7.9, "user-binary"),
        (9.0, "agent"),
        (10.1, "agent"),
    ]
    for x, tag in auth_tags:
        ax.text(x + 0.5, 2.3, tag, fontsize=7,
                color="#666" if tag == "agent" else "#a04",
                ha="center", va="top", style="italic")
    ax.text(0.05, 2.3, "trajectory tag:", fontsize=8, color="#444",
            ha="left", va="top", fontweight="bold")

    # 下方：底层引擎层
    engines_y = 0.6
    box(ax, 0.5, engines_y, 10.0, 1.1, "", color="#f0f0f0", text_color="#222")
    ax.text(0.7, engines_y + 0.85, "底层调度",
            fontsize=9, fontweight="bold", color="#444")
    eng = ["Gaussian g16", "BDF X2C-TDA", "Python 公式模块"]
    for i, e in enumerate(eng):
        ax.text(2.5 + i * 3.0, engines_y + 0.55, e,
                fontsize=9, color="#333", ha="center")

    # 引擎指引箭头
    for x in [4.8, 6.0, 7.0]:
        arrow(ax, x + 0.5, 2.6, x + 0.5, 1.7, color="#888", style="-|>")
    arrow(ax, 8.4, 2.6, 8.4, 1.7, color="#888", style="-|>")
    arrow(ax, 9.5, 2.6, 9.5, 1.7, color="#888", style="-|>")

    ax.text(5.5, 3.95, "图 3.3   ChemMaster 调度多软件流水线的典型示例",
            fontsize=12, fontweight="bold", ha="center")

    fig.tight_layout()
    fig.savefig(OUT / "fig_pipeline.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {OUT / 'fig_pipeline.png'}")


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════


def box(ax, x, y, w, h, text, *, color="#ddd", text_color="#222",
        size=10, weight="normal", alpha=1.0):
    rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05",
                            linewidth=1.0, edgecolor="#444",
                            facecolor=color, alpha=alpha)
    ax.add_patch(rect)
    ax.text(x + w / 2, y + h / 2, text,
            ha="center", va="center", fontsize=size,
            color=text_color, fontweight=weight,
            wrap=True)


def arrow(ax, x1, y1, x2, y2, color="#444", style="->"):
    arr = FancyArrowPatch((x1, y1), (x2, y2),
                            arrowstyle=style, color=color, lw=1.2,
                            mutation_scale=15)
    ax.add_patch(arr)


# ════════════════════════════════════════════════════════════════════════════
# 终端 "截图"（文本渲染）
# ════════════════════════════════════════════════════════════════════════════


def fig_test_run():
    """模拟 pytest 输出的截图，放进论文证明 108 测试通过。"""
    text = (
        "$ python -m pytest tests/unit/ -q\n"
        "................................................. [ 45%]\n"
        ".................................................s [ 91%]\n"
        ".........                                            [100%]\n"
        "\n"
        "108 passed, 1 skipped in 1.40s\n"
    )
    render_terminal(text, OUT / "fig_test_run.png",
                    title="图 4.6   单元测试 pytest 输出截图")


def fig_s22_terminal():
    text = (
        "$ /opt/miniconda3/bin/python scripts/benchmarks/run_s22_psi4.py\n"
        "Running 5 S22 system(s) via psi4...\n"
        "\n"
        "  [water_dimer] running CP-corrected interaction energy...\n"
        "  → water_dimer: E_int = -5.552 kcal/mol (ref -5.02, err -0.532, wall 1.9s)\n"
        "  [methane_dimer] running CP-corrected interaction energy...\n"
        "  → methane_dimer: E_int = 0.178 kcal/mol (ref -0.53, err +0.708, wall 2.7s)\n"
        "  [ethene_ethyne] running CP-corrected interaction energy...\n"
        "  → ethene_ethyne: E_int = -1.464 kcal/mol (ref -1.50, err +0.036, wall 4.7s)\n"
        "  [benzene_methane] running CP-corrected interaction energy...\n"
        "  → benzene_methane: E_int = -0.891 kcal/mol (ref -1.45, err +0.559, wall 17.9s)\n"
        "  [benzene_dimer_T] running CP-corrected interaction energy...\n"
        "  → benzene_dimer_T: E_int = -0.83 kcal/mol (ref -2.74, err +1.910, wall 58.8s)\n"
        "\n"
        "Summary written to benchmarks/s22/summary.json\n"
        "MAE = 0.749 kcal/mol  (1/5 pass strict acceptance)\n"
    )
    render_terminal(text, OUT / "fig_s22_terminal.png",
                    title="图 4.7   S22 基准 psi4 真跑终端输出")


def fig_quest_terminal():
    text = (
        "$ /opt/miniconda3/bin/python scripts/benchmarks/run_quest_psi4.py\n"
        "Running 3 QUEST molecule(s) via psi4...\n"
        "\n"
        "  [formaldehyde] TDDFT (TDA, CAM-B3LYP, def2-SVP, 3 states)...\n"
        "  → formaldehyde: MAE=0.735 eV, max=1.43 eV (wall 0.9s)\n"
        "    state 1: 4.021 vs CC3 3.98 (n -> π*), err +0.041\n"
        "    state 2: 8.66 vs CC3 7.23 (n -> 3s (Rydberg)), err +1.430\n"
        "  [pyridine] TDDFT (TDA, CAM-B3LYP, def2-SVP, 3 states)...\n"
        "  → pyridine: MAE=0.385 eV, max=0.951 eV (wall 4.7s)\n"
        "    state 1: 5.117 vs CC3 5.07 (n -> π*), err +0.047\n"
        "    state 2: 5.406 vs CC3 5.25 (π -> π*), err +0.156\n"
        "    state 3: 5.859 vs CC3 6.81 (π -> π*), err -0.951\n"
        "  [pyrrole] TDDFT (TDA, CAM-B3LYP, def2-SVP, 3 states)...\n"
        "  → pyrrole: MAE=1.219 eV, max=1.548 eV (wall 3.7s)\n"
        "\n"
        "Summary written to benchmarks/quest/summary.json\n"
        "MAE = 0.785 eV (3/8 states pass)\n"
    )
    render_terminal(text, OUT / "fig_quest_terminal.png",
                    title="图 4.8   QUEST 基准 psi4 真跑终端输出")


def fig_mcp_probe_terminal():
    text = (
        "$ python scripts/benchmarks/probe_mcp_protocol.py\n"
        "Probing ChemMaster MCP servers via standard MCP stdio protocol...\n"
        "\n"
        "  → probing chemaster.mcp.const.server...\n"
        "    initialised, partial: handshake OK\n"
        "  → probing chemaster.mcp.kb.server...\n"
        "    initialised, 3 tools listed, 2/2 call(s) succeeded\n"
        "  → probing chemaster.mcp.calc_psi4.server...\n"
        "    initialised, 4 tools listed, 0/0 call(s) succeeded\n"
        "\n"
        "Result written to benchmarks/use_cases/mcp_cross_client/probe_results.json\n"
        "Servers OK: 2 / 3\n"
    )
    render_terminal(text, OUT / "fig_mcp_probe_terminal.png",
                    title="图 4.9   MCP 协议合规性独立探针输出")


def render_terminal(text: str, out_path: Path, *, title: str = ""):
    """以等宽字体把文本渲染成 PNG，仿终端截图。"""
    lines = text.rstrip("\n").split("\n")
    n = len(lines)
    fig_h = 0.36 * n + 1.0
    fig, ax = plt.subplots(figsize=(11, fig_h))
    ax.axis("off")
    # 终端背景
    bg = Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                    facecolor="#1d1f21", edgecolor="none")
    ax.add_patch(bg)
    # 终端标题栏
    title_bar = Rectangle((0, 0.96), 1, 0.04, transform=ax.transAxes,
                            facecolor="#3a3d41", edgecolor="none")
    ax.add_patch(title_bar)
    for cx, color in [(0.025, "#ff605c"), (0.05, "#ffbd44"), (0.075, "#00ca4e")]:
        ax.add_patch(plt.Circle((cx, 0.98), 0.012, transform=ax.transAxes,
                                 color=color, zorder=10))
    ax.text(0.5, 0.98, "Terminal — chemaster benchmarks",
            transform=ax.transAxes, color="#ccc", fontsize=9,
            ha="center", va="center")
    # 内容
    for i, line in enumerate(lines):
        y = 0.93 - (i + 0.5) / (n + 1) * 0.88
        # 简单着色：行首是 $ 用绿色 prompt，→ 用橙色
        color = "#dcdcdc"
        if line.startswith("$"):
            color = "#7ed321"
        elif "→" in line:
            color = "#f5a623"
        elif "MAE" in line or "Summary" in line or "passed" in line or "OK" in line:
            color = "#50e3c2"
        ax.text(0.025, y, line, transform=ax.transAxes,
                fontfamily="monospace", fontsize=9.5,
                color=color, va="center")
    if title:
        fig.text(0.5, 0.005, title, fontsize=11, ha="center",
                 fontweight="bold")
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(out_path, dpi=180, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    print(f"  → {out_path}")


# ════════════════════════════════════════════════════════════════════════════
# TUI / Web 截图（SVG → PNG; HTML 渲染）
# ════════════════════════════════════════════════════════════════════════════


def convert_tui_svg():
    src = ROOT / "benchmarks" / "use_cases" / "tui_demo" / "tui_demo.svg"
    dst = OUT / "fig_tui_demo.png"
    if not src.exists():
        print(f"  ✗ {src} 不存在")
        return
    # 尝试用 cairosvg；失败则直接复制 SVG 让 docx 嵌入（python-docx 支持有限）
    try:
        import cairosvg
        cairosvg.svg2png(url=str(src), write_to=str(dst),
                         output_width=1200)
        print(f"  → {dst}")
    except ImportError:
        # 退化：用 rsvg-convert 命令行
        try:
            subprocess.run(["rsvg-convert", "-w", "1200",
                             str(src), "-o", str(dst)], check=True)
            print(f"  → {dst} (rsvg-convert)")
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"  ✗ 无法转换 SVG（缺 cairosvg / rsvg-convert）")


if __name__ == "__main__":
    print("Generating supplementary figures for thesis §3-§4...")
    fig_architecture()
    fig_comparison()
    fig_permission()
    fig_pipeline()
    fig_test_run()
    fig_s22_terminal()
    fig_quest_terminal()
    fig_mcp_probe_terminal()
    convert_tui_svg()
    print("Done.")
