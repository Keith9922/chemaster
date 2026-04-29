"""Confirmation primitives.

In V2 architecture confirmation is per-tool, not a central token gate. This
module retains a small surface for backwards compatibility:

- `ApprovedPlan` (legacy): wraps a Plan + an opaque token; still used by the
  Phase-1 H2O e2e test. New code should not construct these by hand —
  ChemAgent's loop calls a `confirm_callback` directly.
- `ConfirmationLoop` (legacy): now provides a working `auto_approve()` for
  programmatic flows and a simple `prompt_cli()` for terminal interaction.

For new code, prefer `AgentConfig.confirm_callback` (signature:
`(tool_name, args, reason) -> bool`).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from chemaster.agent.plan import Plan


@dataclass
class ApprovedPlan:
    """A Plan that has been approved by the user (legacy compat shim)."""
    plan: Plan
    confirm_token: str = ""
    user_edits: list[str] = field(default_factory=list)


class ConfirmationLoop:
    """Lightweight Plan rendering + approval helper.

    This is a *legacy* utility — V2 confirmation lives at the tool level.
    Useful when you have a Plan object (built by the old hard-coded Planner)
    and want to round-trip it through approval before handing it to the
    legacy Executor.
    """

    def __init__(self, ui=None) -> None:
        self.ui = ui

    # ------------------------------------------------------------------
    # Programmatic / scripted approval
    # ------------------------------------------------------------------

    @classmethod
    def auto_approve(cls, plan: Plan) -> ApprovedPlan:
        """Approve a Plan without user interaction (tests / batch mode)."""
        return ApprovedPlan(plan=plan, confirm_token=cls._generate_token())

    @classmethod
    def reject(cls, plan: Plan, reason: str = "") -> ApprovedPlan:
        """Mark a Plan as rejected (token stays empty)."""
        edits = [f"REJECTED: {reason}"] if reason else ["REJECTED"]
        return ApprovedPlan(plan=plan, confirm_token="", user_edits=edits)

    # ------------------------------------------------------------------
    # Interactive prompting (CLI fallback when no UI is supplied)
    # ------------------------------------------------------------------

    def run(self, plan: Plan) -> ApprovedPlan | None:
        """Show the plan and ask the user. Returns None if user quits.

        Default implementation is a simple terminal prompt. UI integrations
        (Textual TUI etc.) should call `auto_approve` after rendering their
        own card, or override this method.
        """
        if self.ui is not None and hasattr(self.ui, "confirm_plan"):
            return self.ui.confirm_plan(plan)
        return self._prompt_cli(plan)

    def _prompt_cli(self, plan: Plan) -> ApprovedPlan | None:
        print()
        print("─" * 60)
        print(f"Plan for: {plan.user_intent}")
        print(f"Workflow: {plan.inferred_workflow}")
        print(f"Steps: {len(plan.steps)}")
        for i, step in enumerate(plan.steps, 1):
            print(f"  {i}. {step.name}: {step.rationale}")
        print(f"Estimate: {plan.total_estimate.wall_clock_s:.0f}s wall, "
              f"{plan.total_estimate.memory_gb:.1f} GB")
        print("─" * 60)
        choice = input("[A]ccept / [R]eject / [Q]uit > ").strip().lower()
        if choice in {"a", ""}:
            return self.auto_approve(plan)
        if choice == "r":
            return self.reject(plan, "user rejected at confirmation prompt")
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_token() -> str:
        return secrets.token_urlsafe(16)
