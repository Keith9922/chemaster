#!/usr/bin/env python3
"""真截图采集脚本.

包括：
1. Web UI 真截图：启动 FastAPI → headless Chromium → 真截图 PNG
2. 终端命令真实运行 + 真输出 → 仿终端 PNG（文本真，渲染合成）
3. TUI 通过 Textual run_test 导出 SVG → PNG（Textual 的真实渲染管线）

输出：paper/figures/v3/
"""

from __future__ import annotations

import asyncio
import io
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper" / "figures" / "v3"
OUT.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# 1. Web UI 真截图（Playwright + headless Chromium）
# ════════════════════════════════════════════════════════════════════════════


async def capture_web_screenshot():
    from playwright.async_api import async_playwright

    # 启动 Web 后端
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "chemaster.web.app:create_app", "--factory",
         "--host", "127.0.0.1", "--port", "8765"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=str(ROOT),
    )
    time.sleep(3)  # 等启动

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800})
            page = await context.new_page()

            # 1.1 默认状态截图
            await page.goto("http://127.0.0.1:8765/", timeout=10000)
            await page.wait_for_timeout(2500)  # 等 loadStatus 拉数据
            shot1 = OUT / "fig_web_default.png"
            await page.screenshot(path=str(shot1), full_page=False)
            print(f"  → {shot1}")

            # 1.2 提交一个任务后的状态
            await page.fill("#cmd",
                            "Compute the energy of water using B3LYP/6-31G(d)")
            await page.click("button.btn:has-text('Send')")
            await page.wait_for_timeout(2000)
            shot2 = OUT / "fig_web_submitted.png"
            await page.screenshot(path=str(shot2), full_page=False)
            print(f"  → {shot2}")

            await browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ════════════════════════════════════════════════════════════════════════════
# 2. 终端命令真跑 + 真输出 → 渲染 PNG
# ════════════════════════════════════════════════════════════════════════════


def run_and_capture(cmd: list[str], *, env: dict | None = None,
                    cwd: str | None = None, timeout: int = 600,
                    label: str = "") -> str:
    """真跑命令、捕获真实 stdout/stderr 合并。"""
    print(f"  [run] {label or ' '.join(cmd[:3])} ...")
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        env=env, cwd=cwd, timeout=timeout,
    )
    out = proc.stdout
    if proc.returncode != 0 and proc.stderr:
        out += "\n[stderr]\n" + proc.stderr[-500:]
    return out


def render_terminal_png(text: str, out_path: Path, *,
                         title: str = "Terminal", max_lines: int = 35):
    """把真实命令输出渲染成 PNG（仿终端外观，文字真）.

    重要：长行会按字符宽度换行处理，避免溢出终端背景。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    # 1. 长行按宽度软换行（≈ 110 字符）
    raw_lines = text.rstrip("\n").split("\n")
    wrap_width = 110
    wrapped: list[str] = []
    for line in raw_lines:
        if len(line) <= wrap_width:
            wrapped.append(line)
        else:
            # 按字符切，保持缩进
            for i in range(0, len(line), wrap_width):
                seg = line[i: i + wrap_width]
                if i > 0:
                    seg = "    " + seg  # 续行缩进
                wrapped.append(seg)
    lines = wrapped

    # 2. 截取过长输出
    if len(lines) > max_lines:
        head = lines[: max_lines // 2 - 1]
        tail = lines[-(max_lines // 2 - 1):]
        lines = (head
                 + ["...", f"[truncated {len(lines) - max_lines + 2} lines]",
                    "..."]
                 + tail)

    n = len(lines)
    # 行高约 18 px @ 180 dpi → 0.10 inch
    fig_h = 0.22 * n + 0.5
    fig, ax = plt.subplots(figsize=(13.5, fig_h))
    ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    # 终端背景占满整个 axes
    bg = Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                    facecolor="#1d1f21", edgecolor="none", zorder=1)
    ax.add_patch(bg)
    title_bar = Rectangle((0, 0.96), 1, 0.04, transform=ax.transAxes,
                            facecolor="#3a3d41", edgecolor="none", zorder=2)
    ax.add_patch(title_bar)
    for cx, color in [(0.015, "#ff605c"), (0.030, "#ffbd44"),
                      (0.045, "#00ca4e")]:
        ax.add_patch(plt.Circle((cx, 0.98), 0.010,
                                 transform=ax.transAxes, color=color,
                                 zorder=10))
    ax.text(0.5, 0.98, title, transform=ax.transAxes,
            color="#ccc", fontsize=9, ha="center", va="center", zorder=10)

    for i, line in enumerate(lines):
        y = 0.93 - (i + 0.5) / (n + 1) * 0.88
        color = "#dcdcdc"
        s = line.strip()
        if s.startswith("$") or s.startswith(">>>"):
            color = "#7ed321"
        elif "→" in line or "✓" in line:
            color = "#f5a623"
        elif ("MAE =" in line or "passed" in line.lower()
              or "Summary" in line or s.startswith("OK")):
            color = "#50e3c2"
        elif "ERROR" in line or "FAIL" in line or "✗" in line:
            color = "#ff605c"
        ax.text(0.012, y, line, transform=ax.transAxes,
                fontfamily="monospace", fontsize=8.5,
                color=color, va="center",
                zorder=5)
    # 重要：取消 tight_layout，确保 axes 撑满整张画布
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(out_path, dpi=180, bbox_inches="tight",
                facecolor="#1d1f21", pad_inches=0.05)
    plt.close(fig)


def capture_real_runs():
    """真跑 4 个命令，把真实输出渲染成图。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    # 2.1 完整单元测试（用 conda Python，才能加载 psi4/pint/rdkit/ase）
    out = run_and_capture(
        ["/opt/miniconda3/bin/python", "-m", "pytest",
         "tests/unit/", "-q", "--tb=no"],
        env=env, cwd=str(ROOT), label="pytest tests/unit/ (full)",
    )
    full = "$ /opt/miniconda3/bin/python -m pytest tests/unit/ -q\n" + out
    render_terminal_png(full, OUT / "fig_real_pytest.png",
                         title="Terminal — pytest tests/unit/ (full suite)",
                         max_lines=18)
    print(f"  → {OUT / 'fig_real_pytest.png'}")

    # 2.2 S22 真跑（只跑 water_dimer 节省时间）
    out = run_and_capture(
        ["/opt/miniconda3/bin/python",
         "scripts/benchmarks/run_s22_psi4.py", "water_dimer"],
        cwd=str(ROOT), timeout=300, label="run_s22_psi4 water_dimer",
    )
    full = ("$ /opt/miniconda3/bin/python "
            "scripts/benchmarks/run_s22_psi4.py water_dimer\n" + out)
    render_terminal_png(full, OUT / "fig_real_s22.png",
                         title="Terminal — run_s22_psi4.py water_dimer")
    print(f"  → {OUT / 'fig_real_s22.png'}")

    # 2.3 工程指标真跑
    out = run_and_capture(
        [sys.executable, "scripts/benchmarks/run_engineering_real.py"],
        env=env, cwd=str(ROOT), timeout=120,
        label="run_engineering_real",
    )
    # 删掉 INFO 噪声
    out = "\n".join(l for l in out.split("\n")
                     if "INFO" not in l and "Tool registry" not in l)
    full = "$ python scripts/benchmarks/run_engineering_real.py\n" + out
    render_terminal_png(full, OUT / "fig_real_engineering.png",
                         title="Terminal — run_engineering_real.py",
                         max_lines=40)
    print(f"  → {OUT / 'fig_real_engineering.png'}")

    # 2.4 MCP 探针真跑
    out = run_and_capture(
        [sys.executable, "scripts/benchmarks/probe_mcp_protocol.py"],
        env=env, cwd=str(ROOT), timeout=60, label="probe_mcp_protocol",
    )
    out = "\n".join(l for l in out.split("\n")
                     if "INFO" not in l and "WARNING" not in l)
    full = "$ python scripts/benchmarks/probe_mcp_protocol.py\n" + out
    render_terminal_png(full, OUT / "fig_real_mcp_probe.png",
                         title="Terminal — probe_mcp_protocol.py",
                         max_lines=40)
    print(f"  → {OUT / 'fig_real_mcp_probe.png'}")


# ════════════════════════════════════════════════════════════════════════════
# 3. TUI 通过 Textual 的渲染管线导出（依然是真渲染，不是真屏幕截图）
# ════════════════════════════════════════════════════════════════════════════


def copy_tui_png():
    """复用之前生成的 TUI SVG → PNG（这是 Textual 自身导出的，是真渲染）."""
    src = ROOT / "benchmarks" / "use_cases" / "tui_demo" / "tui_demo.svg"
    dst = OUT / "fig_tui_textual_render.png"
    if src.exists():
        try:
            subprocess.run(["rsvg-convert", "-w", "1400",
                             str(src), "-o", str(dst)], check=True)
            print(f"  → {dst} (Textual 渲染管线导出)")
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            print(f"  ✗ TUI 导出失败: {e}")
    else:
        print(f"  ✗ {src} 不存在")


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════


def main():
    print("=" * 60)
    print("Real screenshot acquisition")
    print("=" * 60)
    print()

    print("[1] Web 端真截图（Playwright + headless Chromium）...")
    asyncio.run(capture_web_screenshot())
    print()

    print("[2] 终端命令真跑 + 真输出渲染...")
    capture_real_runs()
    print()

    print("[3] TUI 渲染（Textual 自身导出管线）...")
    copy_tui_png()
    print()

    print("Done. Output dir:", OUT)


if __name__ == "__main__":
    main()
