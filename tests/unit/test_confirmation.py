"""ConfirmationLoop unit tests (legacy compat layer)."""

from __future__ import annotations

from chemaster.agent.confirmation import ApprovedPlan, ConfirmationLoop
from chemaster.agent.plan import Plan, System


def _trivial_plan() -> Plan:
    return Plan(
        user_intent="trivial",
        inferred_workflow="opt+freq",
        target_system=System(formula="H2O", n_atoms=3),
    )


def test_auto_approve_returns_approved_plan_with_token():
    plan = _trivial_plan()
    approved = ConfirmationLoop.auto_approve(plan)
    assert isinstance(approved, ApprovedPlan)
    assert approved.plan is plan
    assert approved.confirm_token            # non-empty
    assert approved.user_edits == []


def test_reject_marks_plan_with_reason():
    plan = _trivial_plan()
    approved = ConfirmationLoop.reject(plan, "user changed their mind")
    assert isinstance(approved, ApprovedPlan)
    assert approved.confirm_token == ""
    assert "user changed their mind" in approved.user_edits[0]


def test_reject_without_reason():
    plan = _trivial_plan()
    approved = ConfirmationLoop.reject(plan)
    assert approved.confirm_token == ""
    assert approved.user_edits == ["REJECTED"]


def test_run_via_custom_ui_short_circuit():
    """If the UI provides confirm_plan(), run() delegates to it."""
    plan = _trivial_plan()

    captured: list[Plan] = []

    class FakeUI:
        def confirm_plan(self, p):
            captured.append(p)
            return ConfirmationLoop.auto_approve(p)

    loop = ConfirmationLoop(ui=FakeUI())
    approved = loop.run(plan)
    assert captured == [plan]
    assert approved is not None
    assert approved.confirm_token


def test_token_uniqueness():
    """Different approvals get different tokens (sanity check)."""
    p1 = ConfirmationLoop.auto_approve(_trivial_plan())
    p2 = ConfirmationLoop.auto_approve(_trivial_plan())
    assert p1.confirm_token != p2.confirm_token
