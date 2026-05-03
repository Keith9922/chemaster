"""Textual TUI 主入口 —— 三段式 Planner / ConfirmationLoop / Executor 接通版。

布局：
- 左：对话流（RichLog）
- 右：任务面板（Active Tasks / Recent Runs / Engine Status）
- 底部：输入框（自然语言意图）
- 模态：PlanCard（A/E/R/Q）

Phase 1 工作：把 H2O 案例从输入到产出 report.md 完整跑通。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from chemaster.agent.confirmation import ConfirmationLoop
from chemaster.agent.executor import Executor
from chemaster.agent.planner import Planner
from chemaster.tui.widgets.plan_card import PlanCard


class ChemMasterApp(App):
    """ChemMaster TUI 主类。"""

    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #chat { width: 3fr; border: round $primary; padding: 0 1; }
    #side { width: 1fr; }
    #side > Static {
        border: round $secondary;
        padding: 0 1;
        height: auto;
        margin-bottom: 1;
    }
    Input { dock: bottom; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear chat"),
    ]

    def __init__(self, runs_dir: str | Path = "./runs") -> None:
        super().__init__()
        self._runs_dir = Path(runs_dir)
        self._planner = Planner()
        self._loop = ConfirmationLoop()
        self._executor: Executor | None = None  # lazy init（避免 import 时加载 psi4）

    # ──────────────────────────────────────────────────────────────────
    # Compose
    # ──────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, name="ChemMaster")
        with Horizontal(id="main"):
            yield RichLog(id="chat", highlight=True, markup=True, wrap=True)
            with Vertical(id="side"):
                yield Static("[bold]Active task[/bold]\n(idle)", id="active_task")
                yield Static("[bold]Recent runs[/bold]\n" + self._scan_runs(),
                             id="recent_runs")
                yield Static("[bold]Engines[/bold]\n" + self._scan_engines(),
                             id="engines")
        yield Input(placeholder="问点什么…  比如：算 H2O 的能量")
        yield Footer()

    def on_mount(self) -> None:
        chat = self.query_one("#chat", RichLog)
        chat.write(
            "[bold]ChemMaster[/bold] 已就绪。"
            "Phase 1 — Planner → ConfirmationLoop → Executor 三段式已接通。\n"
            "试试输入：[cyan]算 H2O 的能量[/cyan]，回车提交。"
        )

    # ──────────────────────────────────────────────────────────────────
    # Input → Plan → Modal → Execute
    # ──────────────────────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        chat = self.query_one("#chat", RichLog)
        text = (event.value or "").strip()
        event.input.value = ""
        if not text:
            return

        chat.write(f"[cyan]> {text}[/cyan]")

        # 1. Planner
        try:
            plan = self._planner.create_plan(text)
        except NotImplementedError as e:
            chat.write(f"[yellow]⚠ Planner: {e}[/yellow]")
            chat.write("[dim]Phase 2 接 LLM Planner 后任意意图都能 plan。[/dim]")
            return

        # 2. ConfirmationLoop（PlanCard 模态弹窗）
        chat.write(f"[dim]生成 Plan，task_id={plan.task_id}[/dim]")
        approved = await self.push_screen_wait(PlanCard(plan, self._loop))

        if approved is None:
            chat.write("[yellow]Plan 已拒绝。[/yellow]")
            return

        chat.write("[green]✓ Plan accepted. Executing…[/green]")
        active = self.query_one("#active_task", Static)
        active.update(f"[bold]Active task[/bold]\n{plan.task_id}\nrunning…")

        # 3. Executor —— 放到 worker 里，避免 UI 卡死
        if self._executor is None:
            self._executor = Executor(runs_dir=self._runs_dir)

        executor = self._executor

        def _run() -> dict:
            return executor.run(approved)

        try:
            result = await asyncio.to_thread(_run)
        except Exception as exc:  # noqa: BLE001
            chat.write(f"[red]Executor crashed: {type(exc).__name__}: {exc}[/red]")
            active.update("[bold]Active task[/bold]\n(idle)")
            return

        active.update("[bold]Active task[/bold]\n(idle)")

        # 4. 反馈
        if result.get("ok"):
            chat.write(
                f"[green]✓ {result['n_steps_completed']}/{len(plan.steps)} steps done.[/green]"
            )
        else:
            chat.write(
                f"[red]✗ Stopped after {result['n_steps_completed']}/"
                f"{len(plan.steps)} steps.[/red]"
            )
        if result.get("warnings"):
            for w in result["warnings"][:5]:
                chat.write(f"  [yellow]warn:[/yellow] {w}")

        report = result.get("report_path")
        if report:
            chat.write(f"[bold]Report:[/bold] {report}")

        chat.write(f"[dim]Artifacts: {result['task_dir']}[/dim]")

        # 刷新右栏
        self.query_one("#recent_runs", Static).update(
            "[bold]Recent runs[/bold]\n" + self._scan_runs()
        )

    # ──────────────────────────────────────────────────────────────────
    # Side panel helpers
    # ──────────────────────────────────────────────────────────────────

    def _scan_runs(self) -> str:
        if not self._runs_dir.exists():
            return "(none)"
        items = sorted(
            (p for p in self._runs_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:5]
        if not items:
            return "(none)"
        return "\n".join(f"· {p.name}" for p in items)

    def _scan_engines(self) -> str:
        import shutil

        rows = []
        for label, exe in (("psi4", "psi4"), ("xtb", "xtb"),
                            ("orca", "orca"), ("multiwfn", "Multiwfn")):
            mark = "✓" if shutil.which(exe) else "·"
            rows.append(f"{mark} {label}")
        return "\n".join(rows)

    # ──────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────

    def action_clear_chat(self) -> None:
        self.query_one("#chat", RichLog).clear()


def run_tui(runs_dir: str | Path = "./runs") -> None:
    """``chemaster`` 默认入口。"""
    ChemMasterApp(runs_dir=runs_dir).run()


if __name__ == "__main__":
    run_tui()
