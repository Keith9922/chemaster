"""ConfirmationLoop + Executor strict-token 强约束测试。

确保架构层的"必须经过 ConfirmationLoop 才能 Execute"是真的，
不是文档上的承诺。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from chemaster.agent import _token_registry as _tr
from chemaster.agent.confirmation import ApprovedPlan, ConfirmationLoop
from chemaster.agent.executor import Executor
from chemaster.agent.plan import McpCall, Plan, PlanStep, System


@pytest.fixture(autouse=True)
def _reset_token_registry():
    """每个测试前后清空白名单 + 重置 HMAC key。"""
    _tr._reset_for_tests()
    yield
    _tr._reset_for_tests()


@pytest.fixture
def sample_plan() -> Plan:
    return Plan(
        task_id="task-conf-test",
        user_intent="算 H2O",
        inferred_workflow="opt+freq",
        target_system=System(formula="H2O"),
        steps=[],
    )


# ────────────────────────────────────────────────────────────────────────
# token_registry 直测
# ────────────────────────────────────────────────────────────────────────

def test_issue_then_verify_ok():
    issued = _tr.issue("task-1")
    assert issued.task_id == "task-1"
    assert len(issued.token) > 16
    # 第一次 verify 通过；token 被消费
    _tr.verify("task-1", issued.token, signature=issued.signature)


def test_verify_consumes_token():
    """token 一次性：第二次 verify 应失败（重放保护）。"""
    issued = _tr.issue("task-2")
    _tr.verify("task-2", issued.token)
    with pytest.raises(_tr.TokenError):
        _tr.verify("task-2", issued.token)


def test_verify_unknown_task_id():
    with pytest.raises(_tr.TokenError, match="没有活跃 token"):
        _tr.verify("never-issued", "fake-token")


def test_verify_wrong_token():
    _tr.issue("task-3")
    with pytest.raises(_tr.TokenError, match="不匹配"):
        _tr.verify("task-3", "wrong-token")


def test_verify_wrong_signature():
    issued = _tr.issue("task-4")
    with pytest.raises(_tr.TokenError, match="signature"):
        _tr.verify("task-4", issued.token, signature="0" * 64)


def test_revoke():
    _tr.issue("task-5")
    assert _tr.revoke("task-5") is True
    assert _tr.revoke("task-5") is False
    with pytest.raises(_tr.TokenError):
        _tr.verify("task-5", "anything")


# ────────────────────────────────────────────────────────────────────────
# ConfirmationLoop 行为
# ────────────────────────────────────────────────────────────────────────

def test_approve_yields_valid_token(sample_plan):
    loop = ConfirmationLoop()
    approved = loop.approve(sample_plan)
    assert isinstance(approved, ApprovedPlan)
    assert approved.confirm_token != ""
    assert approved.signature != ""
    assert approved.plan is sample_plan
    # signature 真实 HMAC
    assert len(approved.signature) == 64  # hex sha256


def test_reject_revokes(sample_plan):
    loop = ConfirmationLoop()
    approved = loop.approve(sample_plan)
    loop.reject(sample_plan)
    # 由于 reject 之前已经颁过，再次 reject 是幂等的
    loop.reject(sample_plan)
    # 但 verify 也应该失败（reject 把白名单清了）
    with pytest.raises(_tr.TokenError):
        _tr.verify(sample_plan.task_id, approved.confirm_token)


# ────────────────────────────────────────────────────────────────────────
# Executor 强校验：伪造 token 不能过
# ────────────────────────────────────────────────────────────────────────

def _exec_with_mock_fns(tmp_path, plan, approved):
    """跳过真正的 _wire_mcps，注入空字典；只测 token gate。"""
    with patch.object(Executor, "_wire_mcps", lambda self: None):
        executor = Executor(runs_dir=tmp_path / "runs", strict_token=True)
        executor._mcp_funcs = {}
        return executor.run(approved)


def test_executor_rejects_fake_token(tmp_path, sample_plan):
    """伪造的 confirm_token 必须 raise PermissionError。"""
    fake = ApprovedPlan(plan=sample_plan, confirm_token="i-just-made-this-up")
    with pytest.raises(PermissionError, match="token 校验失败"):
        _exec_with_mock_fns(tmp_path, sample_plan, fake)


def test_executor_rejects_replayed_token(tmp_path, sample_plan):
    """同一个合法 token 第二次执行应失败（一次性消费）。"""
    loop = ConfirmationLoop()
    approved = loop.approve(sample_plan)
    # 第一次 OK
    _exec_with_mock_fns(tmp_path, sample_plan, approved)
    # 第二次伪造重放
    with pytest.raises(PermissionError):
        _exec_with_mock_fns(tmp_path, sample_plan, approved)


def test_executor_accepts_real_approved_plan(tmp_path, sample_plan):
    """正常路径：ConfirmationLoop.approve() → Executor.run() 通过。"""
    loop = ConfirmationLoop()
    approved = loop.approve(sample_plan, user_edits=["chosen B3LYP"])
    result = _exec_with_mock_fns(tmp_path, sample_plan, approved)
    assert result["ok"] is True
    assert result["n_steps_completed"] == 0  # 没有 step
    assert (tmp_path / "runs" / sample_plan.task_id / "plan.json").exists()


def test_executor_empty_token_raises_value_error(tmp_path, sample_plan):
    """空 token 直接 ValueError，不是 PermissionError。"""
    bad = ApprovedPlan(plan=sample_plan, confirm_token="")
    with pytest.raises(ValueError, match="confirm_token 为空"):
        _exec_with_mock_fns(tmp_path, sample_plan, bad)


def test_executor_strict_token_false_skips_check(tmp_path, sample_plan):
    """strict_token=False 仅供老 mock 测试；任意非空 token 通过。"""
    bad = ApprovedPlan(plan=sample_plan, confirm_token="anything-non-empty")
    with patch.object(Executor, "_wire_mcps", lambda self: None):
        executor = Executor(runs_dir=tmp_path / "runs", strict_token=False)
        executor._mcp_funcs = {}
        result = executor.run(bad)
    assert result["ok"] is True
