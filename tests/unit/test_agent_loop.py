"""Agent loop unit tests using MockLLM.

These tests exercise the *control flow* of the BaseAgent / ChemAgent
loop without invoking any real chemistry engine or LLM. The MockLLM
returns scripted AssistantMessages, the test asserts the resulting
trajectory shape and the side-effects (tool registry calls, finish
payload, ask_user pause).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chemaster.agent.agent import AgentConfig, BaseAgent, ChemAgent
from chemaster.agent.builtins import register_builtins
from chemaster.agent.context import ContextConfig, TruncationStrategy
from chemaster.agent.llm_client import (
    MockLLM,
    stub_assistant_message,
    stub_tool_call,
)
from chemaster.agent.tool_registry import BaseTool, MCPToolAdapter, ToolRegistry, ToolResult
from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    Role,
    TaskInstance,
    ToolCall,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


class _RecorderTool(BaseTool):
    """A simple tool that echoes its args and records every call."""

    def __init__(
        self,
        name: str = "recorder",
        is_destructive: bool = False,
        is_long_running: bool = False,
        return_value: dict | None = None,
    ) -> None:
        self.name = name
        self.description = f"Recorder tool {name}."
        self.input_schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        self.is_destructive = is_destructive
        self.is_long_running = is_long_running
        self._return_value = return_value
        self.calls: list[dict] = []

    def run(self, **kwargs) -> ToolResult:
        self.calls.append(dict(kwargs))
        if self._return_value is not None:
            return ToolResult(
                ok=True,
                observation=str(self._return_value),
                data=self._return_value,
            )
        return ToolResult(
            ok=True,
            observation=f"[ok] {self.name}({kwargs})",
            data=kwargs,
        )


def _build_agent(
    responses: list[AssistantMessage] | None = None,
    extra_tools: list[BaseTool] | None = None,
    config: AgentConfig | None = None,
    tmp_path: Path | None = None,
) -> tuple[BaseAgent, MockLLM, ToolRegistry]:
    llm = MockLLM(responses=list(responses or []))
    registry = ToolRegistry()
    register_builtins(registry)
    for t in extra_tools or []:
        registry.register(t)
    cfg = config or AgentConfig(max_turns=10)
    if tmp_path is not None:
        cfg.runs_dir = tmp_path
    agent = BaseAgent(llm=llm, tools=registry, config=cfg)
    return agent, llm, registry


# ──────────────────────────────────────────────────────────────────────────
# 1. Single-step finish
# ──────────────────────────────────────────────────────────────────────────


def test_agent_finishes_on_explicit_finish_call(tmp_path):
    finish_call = stub_tool_call(
        "finish",
        {"summary": "All done.", "key_results": {"answer": 42}},
    )
    agent, llm, _ = _build_agent(
        responses=[stub_assistant_message("Wrapping up.", [finish_call])],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="trivial"))

    assert traj.status == "completed"
    assert llm.call_count == 1
    assert len(traj.steps) == 1
    assert agent.finish_payload == {"summary": "All done.", "key_results": {"answer": 42}}


def test_agent_persists_trajectory_to_runs_dir(tmp_path):
    finish_call = stub_tool_call("finish", {"summary": "ok"})
    agent, _, _ = _build_agent(
        responses=[stub_assistant_message("done", [finish_call])],
        tmp_path=tmp_path,
    )
    task = TaskInstance(description="trivial", task_id="task-trivial-001")
    agent.run(task)

    traj_path = tmp_path / "task-trivial-001" / "trajectory.json"
    assert traj_path.exists()
    payload = traj_path.read_text(encoding="utf-8")
    assert "task-trivial-001" in payload
    assert "completed" in payload


# ──────────────────────────────────────────────────────────────────────────
# 2. Multi-step tool dispatch
# ──────────────────────────────────────────────────────────────────────────


def test_agent_dispatches_intermediate_tool_calls(tmp_path):
    rec = _RecorderTool(name="recorder")
    rec_call = stub_tool_call("recorder", {"x": "hello"})
    finish_call = stub_tool_call("finish", {"summary": "done"})
    agent, _, registry = _build_agent(
        responses=[
            stub_assistant_message("calling tool", [rec_call]),
            stub_assistant_message("now finishing", [finish_call]),
        ],
        extra_tools=[rec],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="multi"))

    assert traj.status == "completed"
    assert len(traj.steps) == 2
    assert len(rec.calls) == 1
    assert rec.calls[0] == {"x": "hello"}


def test_agent_handles_unknown_tool_gracefully(tmp_path):
    bad_call = stub_tool_call("nonexistent_tool", {"foo": "bar"})
    finish_call = stub_tool_call("finish", {"summary": "recovered"})
    agent, _, _ = _build_agent(
        responses=[
            stub_assistant_message("trying bad tool", [bad_call]),
            stub_assistant_message("recovered", [finish_call]),
        ],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="bad-tool"))

    assert traj.status == "completed"
    # First step: bad tool was attempted, observation should mention "Unknown tool"
    first_step = traj.steps[0]
    assert any(
        "Unknown tool" in (tr.content or "")
        for tr in first_step.tool_responses
    )


# ──────────────────────────────────────────────────────────────────────────
# 3. ask_user pause
# ──────────────────────────────────────────────────────────────────────────


def test_agent_pauses_on_ask_user(tmp_path):
    ask_call = stub_tool_call(
        "ask_user",
        {"questions": ["Which molecule did you mean?"], "context": "ambiguous"},
    )
    agent, _, _ = _build_agent(
        responses=[stub_assistant_message("need clarification", [ask_call])],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="ambiguous"))

    assert traj.status == "waiting_for_input"
    assert traj.finish_payload is not None
    assert traj.finish_payload["questions"] == ["Which molecule did you mean?"]


def test_agent_continue_run_resumes_after_ask_user(tmp_path):
    ask_call = stub_tool_call("ask_user", {"questions": ["?"]})
    finish_call = stub_tool_call("finish", {"summary": "after-clarification"})
    agent, _, _ = _build_agent(
        responses=[
            stub_assistant_message("ask", [ask_call]),
            stub_assistant_message("done", [finish_call]),
        ],
        tmp_path=tmp_path,
    )
    agent.run(TaskInstance(description="multi-turn"))
    # Now user responds and we resume.
    traj = agent.continue_run("It's water.")
    assert traj.status == "completed"


# ──────────────────────────────────────────────────────────────────────────
# 4. think tool round-trip
# ──────────────────────────────────────────────────────────────────────────


def test_think_tool_records_thought_without_side_effect(tmp_path):
    think_call = stub_tool_call("think", {"thought": "I should plan first."})
    finish_call = stub_tool_call("finish", {"summary": "ok"})
    agent, _, _ = _build_agent(
        responses=[
            stub_assistant_message("", [think_call]),
            stub_assistant_message("", [finish_call]),
        ],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="plan first"))
    assert traj.status == "completed"
    # The first step's tool response is the think echo.
    assert traj.steps[0].tool_responses[0].name == "think"


# ──────────────────────────────────────────────────────────────────────────
# 5. max_turns enforcement
# ──────────────────────────────────────────────────────────────────────────


def test_agent_terminates_at_max_turns(tmp_path):
    """If LLM never calls finish, loop must terminate at max_turns."""
    looping = [
        stub_assistant_message("still thinking…", [
            stub_tool_call("think", {"thought": f"step {i}"}),
        ])
        for i in range(20)
    ]
    agent, _, _ = _build_agent(
        responses=looping,
        config=AgentConfig(max_turns=3, runs_dir=tmp_path),
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="loops"))
    assert traj.status == "failed"
    assert traj.finish_payload == {"reason": "max_turns_exceeded"}


# ──────────────────────────────────────────────────────────────────────────
# 6. No-tool-call nudging
# ──────────────────────────────────────────────────────────────────────────


def test_agent_nudges_when_assistant_returns_plain_text(tmp_path):
    """A plain-text reply (no tool calls) should not finish the task by
    default — we want the agent to either tool-call or `finish`. The loop
    should nudge once and continue until max_turns or finish."""
    finish_call = stub_tool_call("finish", {"summary": "now done"})
    agent, llm, _ = _build_agent(
        responses=[
            stub_assistant_message("Sure, let me think.", []),  # naked text
            stub_assistant_message("", [finish_call]),
        ],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="nudge"))
    assert traj.status == "completed"
    assert llm.call_count == 2


def test_finish_on_no_tool_calls_when_configured(tmp_path):
    """With finish_on_no_tool_calls=True, naked text completes the task."""
    agent, _, _ = _build_agent(
        responses=[stub_assistant_message("This is my answer.", [])],
        config=AgentConfig(max_turns=3, finish_on_no_tool_calls=True, runs_dir=tmp_path),
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="chat"))
    assert traj.status == "completed"


# ──────────────────────────────────────────────────────────────────────────
# 7. Confirmation gate (per-tool)
# ──────────────────────────────────────────────────────────────────────────


def test_destructive_tool_calls_confirm_callback(tmp_path):
    rec = _RecorderTool(name="dangerous_op", is_destructive=True)
    finish_call = stub_tool_call("finish", {"summary": "ok"})
    rec_call = stub_tool_call("dangerous_op", {"x": "fire"})

    seen: list[tuple] = []

    def confirm(tool_name, args, reason):
        seen.append((tool_name, args, reason))
        return True

    cfg = AgentConfig(max_turns=5, runs_dir=tmp_path, confirm_callback=confirm)
    agent, _, _ = _build_agent(
        responses=[
            stub_assistant_message("running danger", [rec_call]),
            stub_assistant_message("done", [finish_call]),
        ],
        extra_tools=[rec],
        config=cfg,
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="danger"))
    assert traj.status == "completed"
    assert len(seen) == 1
    assert seen[0][0] == "dangerous_op"
    assert "destructive" in seen[0][2]
    assert len(rec.calls) == 1


def test_destructive_tool_skipped_when_user_declines(tmp_path):
    rec = _RecorderTool(name="dangerous_op", is_destructive=True)
    finish_call = stub_tool_call("finish", {"summary": "skipped"})
    rec_call = stub_tool_call("dangerous_op", {"x": "fire"})
    cfg = AgentConfig(
        max_turns=5,
        runs_dir=tmp_path,
        confirm_callback=lambda *args: False,    # always decline
    )
    agent, _, _ = _build_agent(
        responses=[
            stub_assistant_message("attempt", [rec_call]),
            stub_assistant_message("ok skipping", [finish_call]),
        ],
        extra_tools=[rec],
        config=cfg,
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="declined"))
    assert traj.status == "completed"
    assert len(rec.calls) == 0
    # The first step's tool response should explain the decline.
    first_resp = traj.steps[0].tool_responses[0]
    assert "user_declined" in first_resp.content


def test_read_only_tool_does_not_invoke_callback(tmp_path):
    rec = _RecorderTool(name="safe_op")              # default: is_read_only=False, but not destructive/long
    finish_call = stub_tool_call("finish", {"summary": "ok"})
    rec_call = stub_tool_call("safe_op", {"x": "ok"})
    seen: list[tuple] = []

    def confirm(*args):
        seen.append(args)
        return True

    cfg = AgentConfig(max_turns=5, runs_dir=tmp_path, confirm_callback=confirm)
    agent, _, _ = _build_agent(
        responses=[
            stub_assistant_message("safe", [rec_call]),
            stub_assistant_message("done", [finish_call]),
        ],
        extra_tools=[rec],
        config=cfg,
        tmp_path=tmp_path,
    )
    agent.run(TaskInstance(description="safe"))
    assert seen == []                          # no confirmation prompted
    assert len(rec.calls) == 1


# ──────────────────────────────────────────────────────────────────────────
# 8. Tool exception is converted to error observation, not raise
# ──────────────────────────────────────────────────────────────────────────


class _RaisingTool(BaseTool):
    name = "raiser"
    description = "Always raises."
    input_schema = {"type": "object", "properties": {}}

    def run(self, **kwargs) -> ToolResult:
        raise RuntimeError("boom")


def test_tool_exception_becomes_error_observation(tmp_path):
    finish_call = stub_tool_call("finish", {"summary": "recovered"})
    raise_call = stub_tool_call("raiser", {})
    agent, _, _ = _build_agent(
        responses=[
            stub_assistant_message("call raiser", [raise_call]),
            stub_assistant_message("recovered", [finish_call]),
        ],
        extra_tools=[_RaisingTool()],
        tmp_path=tmp_path,
    )
    traj = agent.run(TaskInstance(description="raise"))
    assert traj.status == "completed"
    # Tool message should be flagged is_error and contain a useful msg.
    err_msg = traj.steps[0].tool_responses[0]
    assert err_msg.is_error or "error" in err_msg.content.lower() or "boom" in err_msg.content


# ──────────────────────────────────────────────────────────────────────────
# 9. ChemAgent loads the system prompt
# ──────────────────────────────────────────────────────────────────────────


def test_chem_agent_loads_chemistry_system_prompt(tmp_path):
    finish_call = stub_tool_call("finish", {"summary": "ok"})
    llm = MockLLM(responses=[stub_assistant_message("ok", [finish_call])])
    registry = ToolRegistry()
    register_builtins(registry)
    cfg = AgentConfig(max_turns=3, runs_dir=tmp_path)
    agent = ChemAgent(llm=llm, tools=registry, config=cfg)
    agent.run(TaskInstance(description="trivial"))

    # First message in the dialog must be the system prompt.
    assert agent.dialog is not None
    sys_msg = agent.dialog.messages[0]
    assert sys_msg.role == Role.SYSTEM
    # Spot-check chemistry-specific phrases.
    assert "ChemMaster" in sys_msg.content
    assert "tool" in sys_msg.content.lower()
    assert "psi4" in sys_msg.content.lower()


def test_chem_agent_user_prompt_includes_input_data(tmp_path):
    finish_call = stub_tool_call("finish", {"summary": "ok"})
    llm = MockLLM(responses=[stub_assistant_message("ok", [finish_call])])
    registry = ToolRegistry()
    register_builtins(registry)
    cfg = AgentConfig(max_turns=3, runs_dir=tmp_path)
    agent = ChemAgent(llm=llm, tools=registry, config=cfg)

    task = TaskInstance(
        description="optimize benzene",
        input_data="3\nbenzene\nC ...",
    )
    agent.run(task)
    user_msg = agent.dialog.messages[1]
    assert user_msg.role == Role.USER
    assert "optimize benzene" in user_msg.content
    assert "C ..." in user_msg.content


# ──────────────────────────────────────────────────────────────────────────
# 10. Tool registry specs
# ──────────────────────────────────────────────────────────────────────────


def test_registry_specs_round_trip():
    registry = ToolRegistry()
    register_builtins(registry)
    specs = registry.specs()
    names = {s.name for s in specs}
    assert {"finish", "ask_user", "think"}.issubset(names)
    for s in specs:
        assert s.input_schema["type"] == "object"


def test_registry_enabled_tools_filter():
    registry = ToolRegistry()
    register_builtins(registry)
    specs = registry.specs(enabled=["finish"])
    assert [s.name for s in specs] == ["finish"]


# ──────────────────────────────────────────────────────────────────────────
# 11. AgentConfig path coercion
# ──────────────────────────────────────────────────────────────────────────


def test_agent_config_coerces_string_runs_dir(tmp_path):
    """runs_dir passed as a str should be coerced to Path automatically."""
    from chemaster.agent.agent import AgentConfig
    cfg = AgentConfig(runs_dir=str(tmp_path))
    assert isinstance(cfg.runs_dir, Path)
    assert cfg.runs_dir == tmp_path


# ──────────────────────────────────────────────────────────────────────────
# 12. MiniMaxLLM provider wiring
# ──────────────────────────────────────────────────────────────────────────


def test_minimax_llm_uses_minimax_endpoint_and_model(monkeypatch):
    """MiniMaxLLM(LLMConfig(provider='minimax')) → MiniMax base URL + default model."""
    from chemaster.agent.llm_client import MiniMaxLLM, LLMConfig

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-real")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm = MiniMaxLLM(LLMConfig(provider="minimax"))
    assert llm.config.base_url == "https://api.minimaxi.com/anthropic"
    assert llm.config.model == "MiniMax-M2.7"


def test_minimax_llm_keeps_explicit_minimax_model(monkeypatch):
    """An explicit MiniMax-prefixed model id wins over the default."""
    from chemaster.agent.llm_client import MiniMaxLLM, LLMConfig
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-real")
    llm = MiniMaxLLM(LLMConfig(provider="minimax", model="MiniMax-M2.7-highspeed"))
    assert llm.config.model == "MiniMax-M2.7-highspeed"


def test_minimax_llm_overrides_anthropic_default_model(monkeypatch):
    """LLMConfig defaults to claude-sonnet-4-6; MiniMaxLLM should swap that
    out (otherwise the API call will be routed weirdly)."""
    from chemaster.agent.llm_client import MiniMaxLLM, LLMConfig
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-real")
    llm = MiniMaxLLM(LLMConfig(provider="minimax", model="claude-sonnet-4-6"))
    assert llm.config.model == "MiniMax-M2.7"


def test_minimax_llm_raises_without_api_key(monkeypatch):
    from chemaster.agent.llm_client import MiniMaxLLM, LLMConfig, LLMError
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="MINIMAX_API_KEY"):
        MiniMaxLLM(LLMConfig(provider="minimax"))


def test_create_llm_factory_routes_minimax(monkeypatch):
    from chemaster.agent.llm_client import create_llm, LLMConfig, MiniMaxLLM
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-real")
    llm = create_llm(LLMConfig(provider="minimax"))
    assert isinstance(llm, MiniMaxLLM)


# ──────────────────────────────────────────────────────────────────────────
# 13. MCPToolAdapter type coercion (LLMs send strings for ints/floats/bools)
# ──────────────────────────────────────────────────────────────────────────


def _make_adapter(fn):
    return MCPToolAdapter(
        fn=fn, name=fn.__name__, description=(fn.__doc__ or fn.__name__),
    )


def test_mcp_adapter_coerces_int_string_to_int():
    def add_charges(charge: int = 0, multiplicity: int = 1) -> dict:
        return {"ok": True, "result": {"sum": charge + multiplicity}}
    tool = _make_adapter(add_charges)
    res = tool.run(charge="2", multiplicity="3")
    assert res.ok
    assert res.data["result"]["sum"] == 5


def test_mcp_adapter_coerces_float_string_to_float():
    def scale(value: float = 1.0, factor: float = 2.0) -> dict:
        return {"ok": True, "result": {"x": value * factor}}
    tool = _make_adapter(scale)
    res = tool.run(value="1.5", factor="4.0")
    assert res.ok
    assert abs(res.data["result"]["x"] - 6.0) < 1e-9


def test_mcp_adapter_coerces_bool_strings():
    def toggle(flag: bool = False) -> dict:
        return {"ok": True, "result": {"flag": flag, "type": type(flag).__name__}}
    tool = _make_adapter(toggle)
    for s in ("true", "True", "TRUE", "1", "yes"):
        assert tool.run(flag=s).data["result"]["flag"] is True
    for s in ("false", "False", "0", "no", ""):
        assert tool.run(flag=s).data["result"]["flag"] is False


def test_mcp_adapter_does_not_coerce_unrelated_types():
    def echo(geometry_xyz: str = "") -> dict:
        return {"ok": True, "result": {"got": geometry_xyz}}
    tool = _make_adapter(echo)
    res = tool.run(geometry_xyz="3\nH 0 0 0\n")
    assert res.ok
    assert res.data["result"]["got"].startswith("3\n")


def test_mcp_adapter_passes_through_uncoercible_strings():
    def needs_int(charge: int = 0) -> dict:
        # Force a real type error by doing arithmetic.
        return {"ok": True, "result": {"x": charge - 0}}
    tool = _make_adapter(needs_int)
    # "abc" can't become int; we should pass through and let the function
    # complain (which is then caught and surfaced as INVALID_ARGS).
    res = tool.run(charge="abc")
    assert not res.ok
    assert res.data["error_code"] in ("INVALID_ARGS", "TOOL_EXCEPTION")
