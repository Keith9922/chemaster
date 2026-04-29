"""Confirmation logging unit tests.

Whenever a destructive / long-running tool is invoked, the agent loop must:
1. Call confirm_callback with (tool_name, args, reason).
2. Record the result on trajectory.meta['confirmations'].
3. Append a JSONL row to runs/<task_id>/confirmations.jsonl.

These tests verify all three.
"""

from __future__ import annotations

import json
from pathlib import Path

from chemaster.agent.agent import AgentConfig, BaseAgent
from chemaster.agent.builtins import register_builtins
from chemaster.agent.llm_client import (
    MockLLM,
    stub_assistant_message,
    stub_tool_call,
)
from chemaster.agent.tool_registry import BaseTool, ToolRegistry, ToolResult
from chemaster.agent.types import TaskInstance


class _DangerTool(BaseTool):
    name = "danger_op"
    description = "destructive demo"
    input_schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    is_destructive = True

    def run(self, **kwargs) -> ToolResult:
        return ToolResult(ok=True, observation="ok", data=kwargs)


class _SlowTool(BaseTool):
    name = "slow_op"
    description = "long-running demo"
    input_schema = {"type": "object", "properties": {}}
    is_long_running = True

    def run(self, **kwargs) -> ToolResult:
        return ToolResult(ok=True, observation="ok")


def _build_agent(responses, tools, tmp_path, callback) -> BaseAgent:
    llm = MockLLM(responses=list(responses))
    reg = ToolRegistry()
    register_builtins(reg)
    for t in tools:
        reg.register(t)
    cfg = AgentConfig(max_turns=10, runs_dir=tmp_path, confirm_callback=callback)
    return BaseAgent(llm=llm, tools=reg, config=cfg)


def test_approval_logged_on_trajectory_meta(tmp_path: Path):
    finish = stub_tool_call("finish", {"summary": "ok"})
    danger = stub_tool_call("danger_op", {"x": "boom"})
    agent = _build_agent(
        [stub_assistant_message("call", [danger]), stub_assistant_message("done", [finish])],
        [_DangerTool()], tmp_path, lambda *_: True,
    )
    traj = agent.run(TaskInstance(description="t1", task_id="task-confirm-001"))
    confirmations = traj.meta["confirmations"]
    assert confirmations["approved"] == 1
    assert confirmations["declined"] == 0
    assert len(confirmations["log"]) == 1
    rec = confirmations["log"][0]
    assert rec["tool"] == "danger_op"
    assert rec["approved"] is True
    assert "destructive" in rec["reason"]


def test_decline_logged_on_trajectory_meta(tmp_path: Path):
    finish = stub_tool_call("finish", {"summary": "skipped"})
    danger = stub_tool_call("danger_op", {"x": "boom"})
    agent = _build_agent(
        [stub_assistant_message("attempt", [danger]),
         stub_assistant_message("ok then", [finish])],
        [_DangerTool()], tmp_path, lambda *_: False,
    )
    traj = agent.run(TaskInstance(description="t2", task_id="task-confirm-002"))
    confirmations = traj.meta["confirmations"]
    assert confirmations["approved"] == 0
    assert confirmations["declined"] == 1


def test_confirmations_persisted_to_jsonl(tmp_path: Path):
    finish = stub_tool_call("finish", {"summary": "ok"})
    danger = stub_tool_call("danger_op", {"x": "boom"})
    slow = stub_tool_call("slow_op", {})

    decisions = iter([True, False])     # first approved, second declined

    def cb(tool, args, reason):
        return next(decisions)

    agent = _build_agent(
        [
            stub_assistant_message("danger", [danger]),
            stub_assistant_message("slow", [slow]),
            stub_assistant_message("done", [finish]),
        ],
        [_DangerTool(), _SlowTool()], tmp_path, cb,
    )
    agent.run(TaskInstance(description="t3", task_id="task-confirm-003"))

    log_path = tmp_path / "task-confirm-003" / "confirmations.jsonl"
    assert log_path.exists()
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 2
    assert rows[0]["tool"] == "danger_op" and rows[0]["approved"] is True
    assert rows[1]["tool"] == "slow_op"   and rows[1]["approved"] is False


def test_read_only_tool_does_not_invoke_callback_or_log(tmp_path: Path):
    """Sanity: read-only tools never trigger confirm_callback."""
    finish = stub_tool_call("finish", {"summary": "ok"})
    think = stub_tool_call("think", {"thought": "noop"})

    invoked: list = []

    def cb(*args):
        invoked.append(args)
        return True

    agent = _build_agent(
        [stub_assistant_message("think first", [think]),
         stub_assistant_message("done", [finish])],
        [], tmp_path, cb,
    )
    traj = agent.run(TaskInstance(description="t4", task_id="task-confirm-004"))
    assert invoked == []
    assert "confirmations" not in traj.meta
    assert not (tmp_path / "task-confirm-004" / "confirmations.jsonl").exists()
