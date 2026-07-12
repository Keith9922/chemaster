"""Unit tests for ChemAgent.run_streaming (the async generator path).

Covers:
  - Event order for the happy path (finish tool fires)
  - Confirmation: approved (tool runs) vs. declined (tool skipped)
  - ask_user → status="waiting_for_input"
  - max_turns_exceeded → status="failed" with reason
  - Unknown tool → ToolCompletedEvent with is_error=True
  - Async vs sync confirmation callback fallback
  - Backwards-compatibility: sync `run()` still works alongside `run_streaming()`

The sync `run()` regression coverage already lives in test_agent_loop.py;
this file specifically targets streaming semantics.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from chemaster.agent.agent import AgentConfig, ChemAgent
from chemaster.agent.builtins import register_builtins
from chemaster.agent.llm_client import MockLLM
from chemaster.agent.tool_registry import BaseTool, ToolRegistry, ToolResult
from chemaster.agent.types import (
    AssistantMessage,
    AssistantMessageEvent,
    ConfirmationRequiredEvent,
    RunCompletedEvent,
    StepCompletedEvent,
    StepStartedEvent,
    TaskInstance,
    ToolCall,
    ToolCompletedEvent,
    ToolStartedEvent,
)

# ──────────────────────────────────────────────────────────────────────────────
# Test fixtures: tools and helpers
# ──────────────────────────────────────────────────────────────────────────────


class _DangerousTool(BaseTool):
    """Tool flagged destructive — exercises the confirmation gate."""

    name = "delete_files"
    description = "Pretends to destroy something."
    input_schema = {"type": "object", "properties": {}}
    is_destructive = True

    def __init__(self) -> None:
        super().__init__()
        self.called = False

    def run(self, **kwargs):
        self.called = True
        return ToolResult(ok=True, observation="boom", data={"deleted": 42})


class _LongTool(BaseTool):
    """Tool flagged long-running — also requires confirmation."""

    name = "slow_calc"
    description = "Pretends to take ages."
    input_schema = {"type": "object", "properties": {}}
    is_long_running = True

    def run(self, **kwargs):
        return ToolResult(ok=True, observation="finished", data={"steps": 1})


def _make_agent(
    responses: list[AssistantMessage],
    *,
    tools_extra: list[BaseTool] | None = None,
    max_turns: int = 5,
    async_confirm=None,
    sync_confirm=None,
) -> tuple[ChemAgent, Path]:
    """Build a ChemAgent in a temp runs dir wired with MockLLM + builtins."""
    tools = ToolRegistry()
    register_builtins(tools)
    for t in tools_extra or []:
        tools.register(t)
    tmpdir = tempfile.mkdtemp(prefix="chemaster-streaming-")
    config = AgentConfig(
        runs_dir=Path(tmpdir),
        max_turns=max_turns,
        async_confirm_callback=async_confirm,
        confirm_callback=sync_confirm,
    )
    agent = ChemAgent(llm=MockLLM(responses=responses), tools=tools, config=config)
    return agent, Path(tmpdir)


def _drain(agent: ChemAgent, task: TaskInstance):
    async def _go():
        return [ev async for ev in agent.run_streaming(task)]
    return asyncio.run(_go())


# ──────────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────────


def test_streaming_emits_events_in_order_for_finish_path():
    agent, _ = _make_agent([
        AssistantMessage(content="thinking aloud", tool_calls=[
            ToolCall(id="t1", name="think", arguments={"reflection": "I will finish."})
        ]),
        AssistantMessage(content="all done", tool_calls=[
            ToolCall(id="f1", name="finish", arguments={"summary": "ok", "key_results": {"e": -76.0}})
        ]),
    ])
    events = _drain(agent, TaskInstance(description="hi"))

    types_in_order = [e.type for e in events]
    assert types_in_order == [
        # step 1 — think
        "step_started", "assistant_message", "tool_started", "tool_completed", "step_completed",
        # step 2 — finish
        "step_started", "assistant_message", "tool_completed", "step_completed",
        # terminal
        "run_completed",
    ]

    # The terminal event mirrors trajectory state.
    final = events[-1]
    assert isinstance(final, RunCompletedEvent)
    assert final.status == "completed"
    assert final.finish_payload == {"summary": "ok", "key_results": {"e": -76.0}}
    assert final.reason is None
    assert agent.trajectory.status == "completed"


def test_streaming_assistant_message_event_carries_tool_calls():
    agent, _ = _make_agent([
        AssistantMessage(content="hi", tool_calls=[
            ToolCall(id="f1", name="finish", arguments={"summary": "x"})
        ]),
    ])
    events = _drain(agent, TaskInstance(description=""))
    msg_event = next(e for e in events if isinstance(e, AssistantMessageEvent))
    assert msg_event.text == "hi"
    assert len(msg_event.tool_calls) == 1
    assert msg_event.tool_calls[0]["name"] == "finish"


# ──────────────────────────────────────────────────────────────────────────────
# Confirmation flow
# ──────────────────────────────────────────────────────────────────────────────


def test_streaming_confirmation_approved_runs_tool():
    danger = _DangerousTool()
    confirms: list[tuple[str, str]] = []

    async def acb(name, args, reason):
        confirms.append((name, reason))
        return True

    agent, _ = _make_agent(
        [
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="d1", name="delete_files", arguments={})
            ]),
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="f1", name="finish", arguments={"summary": "ok"})
            ]),
        ],
        tools_extra=[danger],
        async_confirm=acb,
    )
    events = _drain(agent, TaskInstance(description=""))
    assert len(confirms) == 1
    assert "destructive" in confirms[0][1]
    assert danger.called is True

    delete_events = [e for e in events if getattr(e, "tool_name", None) == "delete_files"]
    assert any(isinstance(e, ConfirmationRequiredEvent) for e in delete_events)
    assert any(isinstance(e, ToolStartedEvent) for e in delete_events)
    completed = next(e for e in delete_events if isinstance(e, ToolCompletedEvent))
    assert completed.ok is True
    assert completed.declined is False


def test_streaming_confirmation_declined_skips_tool():
    danger = _DangerousTool()

    async def acb(name, args, reason):
        return False  # decline

    agent, _ = _make_agent(
        [
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="d1", name="delete_files", arguments={})
            ]),
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="f1", name="finish", arguments={"summary": "alt path"})
            ]),
        ],
        tools_extra=[danger],
        async_confirm=acb,
    )
    events = _drain(agent, TaskInstance(description=""))

    assert danger.called is False, "Declined tool must not run"
    delete_events = [e for e in events if getattr(e, "tool_name", None) == "delete_files"]
    # Confirmation fired, but no ToolStarted should appear.
    assert any(isinstance(e, ConfirmationRequiredEvent) for e in delete_events)
    assert not any(isinstance(e, ToolStartedEvent) for e in delete_events)
    completed = next(e for e in delete_events if isinstance(e, ToolCompletedEvent))
    assert completed.declined is True
    assert completed.ok is False
    assert completed.is_error is False  # decline is not an error
    assert "user_declined" in completed.observation


def test_streaming_long_running_tool_also_triggers_confirmation():
    slow = _LongTool()
    seen_reasons = []

    async def acb(name, args, reason):
        seen_reasons.append(reason)
        return True

    agent, _ = _make_agent(
        [
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="s1", name="slow_calc", arguments={})
            ]),
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="f1", name="finish", arguments={"summary": "ok"})
            ]),
        ],
        tools_extra=[slow],
        async_confirm=acb,
    )
    _drain(agent, TaskInstance(description=""))
    assert len(seen_reasons) == 1
    assert "long-running" in seen_reasons[0]


def test_streaming_falls_back_to_sync_confirm_callback():
    danger = _DangerousTool()
    sync_calls: list[str] = []

    def sync_cb(name, args, reason):
        sync_calls.append(name)
        return True

    agent, _ = _make_agent(
        [
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="d1", name="delete_files", arguments={})
            ]),
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="f1", name="finish", arguments={"summary": "ok"})
            ]),
        ],
        tools_extra=[danger],
        sync_confirm=sync_cb,    # only sync provided
    )
    _drain(agent, TaskInstance(description=""))
    assert sync_calls == ["delete_files"]
    assert danger.called is True


def test_streaming_no_callback_auto_approves():
    """Legacy default: when no callback at all, destructive tools auto-approve."""
    danger = _DangerousTool()
    agent, _ = _make_agent(
        [
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="d1", name="delete_files", arguments={})
            ]),
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="f1", name="finish", arguments={"summary": "ok"})
            ]),
        ],
        tools_extra=[danger],
    )
    events = _drain(agent, TaskInstance(description=""))
    assert danger.called is True
    # Confirmation event should still fire so the UI can show what happened.
    assert any(isinstance(e, ConfirmationRequiredEvent) for e in events)


# ──────────────────────────────────────────────────────────────────────────────
# Termination paths
# ──────────────────────────────────────────────────────────────────────────────


def test_streaming_ask_user_yields_waiting_for_input():
    agent, _ = _make_agent([
        AssistantMessage(content="", tool_calls=[
            ToolCall(id="a1", name="ask_user", arguments={
                "questions": ["Which functional?"],
                "context": "We have B3LYP and PBE0.",
            })
        ]),
    ])
    events = _drain(agent, TaskInstance(description=""))
    final = events[-1]
    assert isinstance(final, RunCompletedEvent)
    assert final.status == "waiting_for_input"
    assert final.finish_payload == {
        "questions": ["Which functional?"],
        "context": "We have B3LYP and PBE0.",
    }


def test_streaming_max_turns_exceeded_yields_failed():
    # Each scripted assistant call has no tool calls → loop nudges, never finishes.
    agent, _ = _make_agent(
        [AssistantMessage(content="...", tool_calls=[]) for _ in range(10)],
        max_turns=3,
    )
    events = _drain(agent, TaskInstance(description=""))
    final = events[-1]
    assert isinstance(final, RunCompletedEvent)
    assert final.status == "failed"
    assert final.reason == "max_turns_exceeded"
    assert final.finish_payload is None


def test_streaming_unknown_tool_emits_error_completed():
    agent, _ = _make_agent([
        AssistantMessage(content="", tool_calls=[
            ToolCall(id="x1", name="not_a_real_tool", arguments={})
        ]),
        AssistantMessage(content="", tool_calls=[
            ToolCall(id="f1", name="finish", arguments={"summary": "fail recovery"})
        ]),
    ])
    events = _drain(agent, TaskInstance(description=""))
    unknown_completed = next(
        e for e in events
        if isinstance(e, ToolCompletedEvent) and e.tool_name == "not_a_real_tool"
    )
    assert unknown_completed.ok is False
    assert unknown_completed.is_error is True
    assert "Unknown tool" in unknown_completed.observation


def test_streaming_persists_trajectory_to_runs_dir():
    agent, runs_dir = _make_agent([
        AssistantMessage(content="", tool_calls=[
            ToolCall(id="f1", name="finish", arguments={"summary": "x"})
        ]),
    ])
    task = TaskInstance(description="persistence check")
    _drain(agent, task)
    expected = runs_dir / task.task_id / "trajectory.json"
    assert expected.exists(), f"trajectory.json must be written to {expected}"


# ──────────────────────────────────────────────────────────────────────────────
# Per-event invariants
# ──────────────────────────────────────────────────────────────────────────────


def test_streaming_every_step_has_started_and_completed_pair():
    agent, _ = _make_agent([
        AssistantMessage(content="", tool_calls=[
            ToolCall(id="t1", name="think", arguments={"reflection": "x"})
        ]),
        AssistantMessage(content="", tool_calls=[
            ToolCall(id="f1", name="finish", arguments={"summary": "x"})
        ]),
    ])
    events = _drain(agent, TaskInstance(description=""))
    step_started_ids = {e.step_id for e in events if isinstance(e, StepStartedEvent)}
    step_completed_ids = {e.step_id for e in events if isinstance(e, StepCompletedEvent)}
    assert step_started_ids == step_completed_ids == {1, 2}


def test_streaming_event_dicts_are_json_serializable():
    """Every event must round-trip through json.dumps for the WebSocket layer."""
    import json

    danger = _DangerousTool()
    async def acb(name, args, reason):
        return True
    agent, _ = _make_agent(
        [
            AssistantMessage(content="thinking", tool_calls=[
                ToolCall(id="d1", name="delete_files", arguments={"safe": False})
            ]),
            AssistantMessage(content="", tool_calls=[
                ToolCall(id="f1", name="finish", arguments={"summary": "ok"})
            ]),
        ],
        tools_extra=[danger],
        async_confirm=acb,
    )
    events = _drain(agent, TaskInstance(description=""))
    for e in events:
        payload = e.to_dict()
        # Must serialize without TypeError
        encoded = json.dumps(payload, ensure_ascii=False)
        # And round-trip preserves the discriminator
        decoded = json.loads(encoded)
        assert decoded["type"] == e.type
