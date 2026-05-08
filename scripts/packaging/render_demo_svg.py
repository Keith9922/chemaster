"""Render the end-to-end demo's key output as SVG / PNG snapshots for the thesis.

Inputs:
- benchmarks/use_cases/end_to_end_demo/run_log.txt
- benchmarks/use_cases/end_to_end_demo/task-*/trajectory.json

Outputs (under benchmarks/use_cases/end_to_end_demo/):
- demo_summary.svg   — Agent summary + Key results table
- demo_steps.svg     — Step-by-step tool calls (compact view)

Used to embed real screenshots into the thesis §4.5.3.
"""
from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DEMO_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "use_cases" / "end_to_end_demo"


def render_summary() -> None:
    task_dirs = sorted(DEMO_DIR.glob("task-*"))
    if not task_dirs:
        raise SystemExit("no task-* dir under demo")
    traj = json.loads((task_dirs[-1] / "trajectory.json").read_text())
    finish = traj.get("finish_payload") or {}
    summary = finish.get("summary", "(no summary)")
    keys = finish.get("key_results") or {}

    console = Console(record=True, width=110)
    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]ChemMaster v0.2.0a1[/]   [dim]MiniMax-M2.7 + psi4 1.10[/]\n"
            f"[dim]Task:[/] {traj.get('task_id', '?')}   "
            f"[dim]Status:[/] [green]{traj.get('status', '?')}[/]   "
            f"[dim]Steps:[/] {len(traj.get('steps', []))}",
            title="End-to-End Demo · Water-dimer binding energy",
            border_style="cyan",
        )
    )
    console.print()
    console.print(Panel(Text(summary, style="white"), title="Agent Summary", border_style="green"))
    console.print()

    table = Table(title="Key Results", border_style="bright_blue", show_lines=True)
    table.add_column("Field", style="bold yellow", no_wrap=True)
    table.add_column("Value", style="bright_white")
    for k, v in keys.items():
        table.add_row(str(k), str(v))
    console.print(table)
    console.print()

    out_svg = DEMO_DIR / "demo_summary.svg"
    console.save_svg(str(out_svg), title="ChemMaster · End-to-End Demo")
    print(f"wrote {out_svg}  ({out_svg.stat().st_size} bytes)")


def render_steps() -> None:
    task_dirs = sorted(DEMO_DIR.glob("task-*"))
    traj = json.loads((task_dirs[-1] / "trajectory.json").read_text())

    console = Console(record=True, width=110)
    console.print()
    console.print(
        Panel.fit(
            "[bold]Agent step trace[/]   [dim](abridged — see trajectory.json for full payloads)[/]",
            border_style="magenta",
        )
    )
    console.print()
    table = Table(border_style="magenta", show_lines=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Tool", style="bold yellow")
    table.add_column("Result", style="white")
    table.add_column("Authority", style="dim cyan")
    for i, step in enumerate(traj.get("steps", []), 1):
        tool = step.get("tool_name") or step.get("type") or "?"
        ok = step.get("ok")
        err = step.get("error_code", "")
        if ok is True:
            res = "[green]OK[/]"
        elif ok is False:
            res = f"[red]✗ {err}[/]"
        else:
            res = "[dim]–[/]"
        auth = step.get("decision_authority", "agent")
        table.add_row(str(i), tool, res, auth)
    console.print(table)
    console.print()

    out_svg = DEMO_DIR / "demo_steps.svg"
    console.save_svg(str(out_svg), title="ChemMaster · Step trace")
    print(f"wrote {out_svg}  ({out_svg.stat().st_size} bytes)")


if __name__ == "__main__":
    render_summary()
    render_steps()
