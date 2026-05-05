#!/usr/bin/env python3
"""无头模式启动 TUI，注入若干模拟事件，导出 SVG 截图.

证明 TUI 能真实渲染 chat / recommend 卡片 / 任务面板。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "benchmarks" / "use_cases" / "tui_demo"
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def run_capture() -> int:
    from chemaster.tui.app import ChemMasterApp
    from textual.widgets import RichLog, Input, Static

    app = ChemMasterApp(agent=None)

    async with app.run_test(size=(120, 32)) as pilot:
        # Wait briefly for compose
        await pilot.pause()

        # Inject some chat content to demonstrate rendering
        chat: RichLog = app.query_one("#chat", RichLog)
        chat.write("[b cyan]>[/b cyan] Compute the energy of water using B3LYP/6-31G(d)")
        chat.write("[dim]starting agent task at 18:35:12[/dim]")
        chat.write("[on cyan][b]RECOMMEND[/b][/on cyan] method for ground-state opt")
        chat.write("  → [b green]B3LYP-D3(BJ) / def2-TZVP[/b green]")
        chat.write("  why: organic neutral closed-shell molecule, ≤ 50 atoms;")
        chat.write("       D3(BJ) dispersion fixes B3LYP underestimation of weak interactions.")
        chat.write("  alternatives: ωB97X-D / def2-TZVP — for CT systems")
        chat.write("                B3LYP / 6-31G(d) — quick screening only")
        chat.write("  type [b]a[/b] to accept, [b]m <value>[/b] to modify, or anything else to cancel")
        chat.write("[dim]→ accepted[/dim]")
        chat.write("[on yellow][b]CONFIRM[/b][/on yellow] [b]calc_psi4_optimize[/b] — long-running (>30 s expected)")
        chat.write("  args: {'method': 'B3LYP-D3BJ', 'basis': 'def2-TZVP', 'charge': 0, 'multiplicity': 1}")
        chat.write("  type [b]a[/b] to approve, [b]r[/b] to reject")
        chat.write("[dim]→ approved[/dim]")
        chat.write("[OK] calc_psi4_optimize")
        chat.write("  final_energy: -76.4214 Hartree")
        chat.write("  converged: true")
        chat.write("  wall_time_s: 12.3")
        chat.write("[green]✓ task done[/green] (status=completed)")
        chat.write("[b]Summary:[/b] Optimized water at B3LYP-D3(BJ)/def2-TZVP. Final energy −76.4214 Hartree; no imaginary frequencies.")

        app._task_history.append({"task": "Compute energy of water (B3LYP/6-31G(d))",
                                   "ok": True})
        app._refresh_panels()

        await pilot.pause()
        await pilot.pause()  # extra cycle for refresh

        # Export the rendered screen as SVG (Textual's built-in)
        svg_path = OUT_DIR / "tui_demo.svg"
        app.save_screenshot(str(svg_path))
        print(f"  → saved {svg_path}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_capture()))
