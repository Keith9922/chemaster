"""Textual TUI 主入口。

布局参考 docs/ARCHITECTURE.md §3.6：
  - 左：对话流（Chat）
  - 右：任务面板（ActiveTasks + RecentRuns + EngineStatus）
  - 底：命令行（斜杠命令）
  - 模态：Plan-Confirm 卡片

Phase 1 目标：可启动、能输入、能展示一个 Plan 卡片、按键 A/E/R/Q 决策。
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static


class ChemMasterApp(App):
    """ChemMaster 的 Textual App 主类。"""

    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #chat { width: 3fr; border: round $primary; }
    #side { width: 1fr; }
    #side > Static { border: round $secondary; padding: 0 1; }
    Input  { dock: bottom; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear chat"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, name="ChemMaster")
        with Horizontal(id="main"):
            yield RichLog(id="chat", highlight=True, markup=True)
            with Vertical(id="side"):
                yield Static("Active Tasks\n(none)", id="tasks")
                yield Static("Recent Runs\n(none)", id="runs")
                yield Static("Engines\n(use --check-engines)", id="engines")
        yield Input(placeholder="问点什么…  比如：算 H2O 的能量")
        yield Footer()

    def on_mount(self) -> None:
        chat = self.query_one("#chat", RichLog)
        chat.write(
            "[bold]ChemMaster[/bold] 已就绪。"
            "Phase 1 占位 TUI —— 还没接入 Agent。\n"
            "在底部输入框写自然语言意图，回车提交。\n"
        )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        chat = self.query_one("#chat", RichLog)
        text = event.value
        chat.write(f"[cyan]> {text}[/cyan]")
        chat.write("[yellow]TODO: connect Planner → ConfirmationLoop → Executor.[/yellow]")
        event.input.value = ""

    def action_clear_chat(self) -> None:
        self.query_one("#chat", RichLog).clear()


def run_tui() -> None:
    """``chemaster`` 默认入口。"""
    ChemMasterApp().run()


if __name__ == "__main__":
    run_tui()
