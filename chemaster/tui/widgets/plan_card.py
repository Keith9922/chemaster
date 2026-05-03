"""Plan-Confirm 模态卡片：显示 Plan，按 A/E/R/Q 决策。

Phase 1：A 调 ConfirmationLoop.approve()，其它三个键暂时只关 modal（E/R 后续接）。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from chemaster.agent.confirmation import ApprovedPlan, ConfirmationLoop
from chemaster.agent.plan import Plan


class PlanCard(ModalScreen[ApprovedPlan | None]):
    """渲染 Plan，让用户 A/E/R/Q。返回 ApprovedPlan 或 None。"""

    BINDINGS = [
        ("a", "accept", "Accept"),
        ("e", "edit", "Edit"),
        ("r", "replan", "Replan"),
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
    ]

    DEFAULT_CSS = """
    PlanCard {
        align: center middle;
    }
    #card {
        width: 80%;
        max-width: 100;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $panel;
        padding: 1 2;
    }
    #title { text-style: bold; color: $accent; }
    #steps { padding: 1 0; }
    #buttons { dock: bottom; height: 3; }
    Button { margin: 0 1; }
    """

    def __init__(self, plan: Plan, loop: ConfirmationLoop | None = None) -> None:
        super().__init__()
        self.plan = plan
        self.loop = loop or ConfirmationLoop()

    def compose(self) -> ComposeResult:
        sys_ = self.plan.target_system
        body = [
            f"[bold]Task:[/bold] {self.plan.task_id}",
            f"[bold]Intent:[/bold] {self.plan.user_intent}",
            f"[bold]Workflow:[/bold] {self.plan.inferred_workflow}",
            f"[bold]System:[/bold] {sys_.formula or '?'} "
            f"(charge={sys_.charge}, mult={sys_.multiplicity}, n={sys_.n_atoms or '?'})",
            "",
            "[bold]Steps:[/bold]",
        ]
        for i, s in enumerate(self.plan.steps, 1):
            wt = s.estimated_cost.wall_clock_s if s.estimated_cost else 0
            body.append(
                f"  {i}. {s.name}  (skill=[cyan]{s.skill or '-'}[/cyan], "
                f"~{wt:.0f}s)\n"
                f"     {s.rationale}"
            )
        body.append("")
        cost = self.plan.total_estimate
        body.append(f"[dim]Estimated total wall time: ~{cost.wall_clock_s:.0f}s[/dim]")
        body.append("")
        body.append("[bold]Cite:[/bold]")
        for c in self.plan.citations:
            body.append(f"  - {c.text}  [dim]({c.source})[/dim]")

        with Vertical(id="card"):
            yield Static("ChemMaster — Plan-Confirm", id="title")
            yield Static("\n".join(body), id="steps")
            with Vertical(id="buttons"):
                yield Static(
                    "[bold green]A[/bold green] Accept   "
                    "[bold yellow]E[/bold yellow] Edit (Phase 2)   "
                    "[bold yellow]R[/bold yellow] Replan (Phase 2)   "
                    "[bold red]Q[/bold red] Quit"
                )

    def action_accept(self) -> None:
        approved = self.loop.approve(self.plan)
        self.dismiss(approved)

    def action_edit(self) -> None:
        self.app.notify("Edit Plan 是 Phase 2，目前不支持。", severity="warning")

    def action_replan(self) -> None:
        self.app.notify("Replan 是 Phase 2，目前不支持。", severity="warning")

    def action_quit(self) -> None:
        self.loop.reject(self.plan)
        self.dismiss(None)
