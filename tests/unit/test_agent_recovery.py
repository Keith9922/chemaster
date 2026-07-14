"""Agent error-recovery unit tests.

When an MCP tool returns ok=False with a `suggestion`, the Agent loop should
surface that suggestion in the tool message back to the LLM so it can pick a
different action. These tests verify the round-trip:

    LLM calls bad-tool → adapter formats error with suggestion → ToolMessage
    has the suggestion text → LLM sees it on next turn → picks recovery path.
"""

from __future__ import annotations

from pathlib import Path

from chemaster.agent.agent import AgentConfig, BaseAgent
from chemaster.agent.builtins import register_builtins
from chemaster.agent.llm_client import (
    MockLLM,
    stub_assistant_message,
    stub_tool_call,
)
from chemaster.agent.tool_registry import (
    BaseTool,
    MCPToolAdapter,
    ToolRegistry,
    ToolResult,
)
from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    ToolMessage,
)


def _adapter_for(fn) -> MCPToolAdapter:
    return MCPToolAdapter(
        fn=fn,
        name=fn.__name__,
        description=fn.__doc__ or "",
        is_read_only=True,
    )


# ──────────────────────────────────────────────────────────────────────────
# 1. Error suggestion surfaces in observation
# ──────────────────────────────────────────────────────────────────────────


def test_mcp_error_suggestion_appears_in_observation():
    def flaky_tool(x: str) -> dict:
        return {
            "ok": False,
            "error_code": "SCF_NOT_CONVERGED",
            "details": "Max iter 200 reached, residual 1e-3",
            "suggestion": "Try guess=GWH or basis=def2-SVP first.",
        }
    tool = _adapter_for(flaky_tool)
    result = tool.run(x="ignored")
    assert not result.ok
    assert "SCF_NOT_CONVERGED" in result.observation
    assert "Try guess=GWH" in result.observation
    assert "Max iter 200" in result.observation


def test_mcp_warnings_surface_in_observation():
    def warn_tool() -> dict:
        return {
            "ok": True,
            "result": {"value": 1.0},
            "warnings": [
                {"code": "IMAGINARY_FREQUENCY", "message": "n=1, smallest=-150.0 cm^-1"},
                "Auto-adjusted memory_gb from 16 to 12",
            ],
        }
    tool = _adapter_for(warn_tool)
    result = tool.run()
    assert result.ok
    assert "Warnings:" in result.observation
    assert "IMAGINARY_FREQUENCY" in result.observation
    assert "memory_gb" in result.observation


# ──────────────────────────────────────────────────────────────────────────
# 2. Agent loop sees suggestion and picks an alternative on next turn
# ──────────────────────────────────────────────────────────────────────────


class _FlakySCFTool(BaseTool):
    """Returns SCF error on first call, succeeds when args change."""

    name = "calc_psi4_optimize"
    description = "Mocked SCF tool."
    input_schema = {"type": "object", "properties": {"guess": {"type": "string"}}}
    is_long_running = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs) -> ToolResult:
        self.calls.append(dict(kwargs))
        if kwargs.get("guess") != "GWH":
            return ToolResult(
                ok=False,
                observation=(
                    "[SCF_NOT_CONVERGED]\n"
                    "Details: residual 1e-3 at iter 200\n"
                    "Suggestion: Try guess=GWH or drop to def2-SVP first."
                ),
                data={
                    "ok": False,
                    "error_code": "SCF_NOT_CONVERGED",
                    "suggestion": "Try guess=GWH",
                },
                is_error=False,    # not a hard error; agent should retry
            )
        return ToolResult(
            ok=True,
            observation="[OK] calc_psi4_optimize\nfinal_energy=-76.42 Hartree",
            data={"ok": True, "result": {"final_energy": {"value": -76.42, "unit": "Hartree"}}},
        )


def test_agent_recovers_from_scf_failure_using_suggestion(tmp_path: Path) -> None:
    """End-to-end: agent calls tool → fails with suggestion → agent retries
    with the suggested arg → succeeds → finishes."""
    flaky = _FlakySCFTool()

    def respond(dialog: Dialog) -> AssistantMessage:
        # Inspect the dialog: was the last message an SCF failure?
        last_tool = next(
            (m for m in reversed(dialog.messages) if isinstance(m, ToolMessage)),
            None,
        )
        if last_tool is None:
            # Initial call: try without the GWH guess.
            return stub_assistant_message(
                "Optimizing.",
                [stub_tool_call("calc_psi4_optimize", {"guess": "SAD"})],
            )
        if "SCF_NOT_CONVERGED" in last_tool.content:
            # Recovery: switch to GWH.
            return stub_assistant_message(
                "SCF failed with SAD; retrying with GWH per the suggestion.",
                [stub_tool_call("calc_psi4_optimize", {"guess": "GWH"})],
            )
        # Success → finish.
        return stub_assistant_message(
            "Optimization succeeded; summarizing.",
            [stub_tool_call("finish", {
                "summary": "Optimized after SCF retry.",
                "key_results": {"final_energy": -76.42},
            })],
        )

    llm = MockLLM(responder=respond)
    registry = ToolRegistry()
    register_builtins(registry)
    registry.register(flaky)
    cfg = AgentConfig(max_turns=10, runs_dir=tmp_path, confirm_callback=lambda *_: True)
    agent = BaseAgent(llm=llm, tools=registry, config=cfg)
    traj = agent.run_task = None
    from chemaster.agent.types import TaskInstance
    traj = agent.run(TaskInstance(description="opt"))

    assert traj.status == "completed"
    assert len(flaky.calls) == 2
    assert flaky.calls[0]["guess"] == "SAD"
    assert flaky.calls[1]["guess"] == "GWH"


def test_agent_gives_up_after_max_retries(tmp_path: Path) -> None:
    """If recovery doesn't help, agent should eventually finish with a partial
    summary instead of looping forever (max_turns enforces this regardless of
    whether the agent itself caps retries)."""
    flaky = _FlakySCFTool()      # always fails unless guess=GWH

    def respond(dialog: Dialog) -> AssistantMessage:
        # Naive responder: always retries with SAD (no recovery).
        return stub_assistant_message(
            "trying again with SAD",
            [stub_tool_call("calc_psi4_optimize", {"guess": "SAD"})],
        )

    llm = MockLLM(responder=respond)
    registry = ToolRegistry()
    register_builtins(registry)
    registry.register(flaky)
    cfg = AgentConfig(max_turns=4, runs_dir=tmp_path, confirm_callback=lambda *_: True)
    agent = BaseAgent(llm=llm, tools=registry, config=cfg)
    from chemaster.agent.types import TaskInstance
    traj = agent.run(TaskInstance(description="give up"))

    assert traj.status == "failed"
    assert traj.finish_payload == {"reason": "max_turns_exceeded"}
    assert len(flaky.calls) == 4
