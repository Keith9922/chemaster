"""协作式取消 + 引擎日志归档 + MCP 决策透传 的行为测试。

对应答辩后清单 §8.2 的"真的任务取消"（此前 Web 取消只是前端停止轮询，
后端线程跑满 max_turns）与 §5.6 复现承诺的引擎日志归档。
"""

from __future__ import annotations

import os

from chemaster.agent.agent import AgentConfig, BaseAgent
from chemaster.agent.llm_client import MockLLM, stub_assistant_message, stub_tool_call
from chemaster.agent.tool_registry import ToolRegistry
from chemaster.agent.types import TaskInstance, Trajectory


def _think():
    return stub_assistant_message("mulling", [stub_tool_call("think", {
        "thought": "still working",
    })])


def _finish():
    return stub_assistant_message("", [stub_tool_call("finish", {"summary": "ok"})])


# ── 协作式取消 ───────────────────────────────────────────────────────────────


def test_should_abort_cancels_cleanly(tmp_path):
    """第 2 轮开始前 should_abort 返回 True → 干净取消并持久化。"""
    polls = {"n": 0}

    def should_abort() -> bool:
        polls["n"] += 1
        return polls["n"] > 1     # 第一轮放行，第二轮取消

    llm = MockLLM(responses=[_think(), _think(), _think(), _finish()])
    agent = BaseAgent(
        llm=llm, tools=ToolRegistry(),
        config=AgentConfig(max_turns=6, runs_dir=tmp_path / "runs",
                           should_abort=should_abort),
    )
    traj = agent.run(TaskInstance(description="cancel me"))

    assert traj.status == "cancelled"
    assert traj.finish_payload == {"reason": "user_cancelled"}
    assert len(traj.steps) == 1            # 只跑了第一轮
    saved = tmp_path / "runs" / traj.task_id / "trajectory.json"
    assert saved.exists()                  # 取消也要落盘（可审计）


def test_no_abort_callback_runs_to_completion(tmp_path):
    llm = MockLLM(responses=[_finish()])
    agent = BaseAgent(
        llm=llm, tools=ToolRegistry(),
        config=AgentConfig(max_turns=3, runs_dir=tmp_path / "runs"),
    )
    traj = agent.run(TaskInstance(description="just finish"))
    assert traj.status == "completed"


# ── 引擎日志归档 env ─────────────────────────────────────────────────────────


def test_initialize_points_engine_logs_at_task_dir(tmp_path):
    llm = MockLLM(responses=[_finish()])
    agent = BaseAgent(
        llm=llm, tools=ToolRegistry(),
        config=AgentConfig(max_turns=2, runs_dir=tmp_path / "runs"),
    )
    traj = agent.run(TaskInstance(description="archive my logs"))
    expected = str(tmp_path / "runs" / traj.task_id / "engine_logs")
    assert os.environ.get("CHEMASTER_ENGINE_LOG_DIR") == expected


# ── MCP 决策透传 ─────────────────────────────────────────────────────────────


def test_mcp_summary_exposes_chemistry_decisions():
    from chemaster.mcp.agent import server as srv

    traj = Trajectory(task_id="task-x", meta={
        "recommendations": {
            "accepted": 1, "modified": 0, "cancelled": 0, "escalated": 0,
            "log": [{
                "tool": "recommend",
                "decision": "选择泛函",
                "recommendation": "B3LYP-D3(BJ)",
                "decision_class": "functional",
                "level": "L2",
                "status": "accept",
                "modified_value": "",
                "user_note": "(auto-accepted: no recommend_callback configured)",
            }],
        },
    })
    out = srv._summarize_trajectory(traj)
    cd = out["chemistry_decisions"]
    assert cd["accepted"] == 1
    assert cd["log"][0]["recommendation"] == "B3LYP-D3(BJ)"
    assert cd["log"][0]["level"] == "L2"
    assert "Relay them to your user" in cd["note"]


def test_mcp_summary_omits_block_when_no_decisions():
    from chemaster.mcp.agent import server as srv

    out = srv._summarize_trajectory(Trajectory(task_id="task-y"))
    assert "chemistry_decisions" not in out
