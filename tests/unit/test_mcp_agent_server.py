"""Unit tests for ``chemaster.mcp.agent.server`` — the agent-as-MCP-server.

These tests exercise the four exposed MCP tools directly (without going
through the stdio transport), to verify:

  1. ``chemaster_run`` rejects empty intents with a structured error
  2. ``chemaster_run`` with provider="mock" routes EN + ZH intents to the
     expected tools and finishes the loop cleanly
  3. ``chemaster_run`` returns a well-formed result envelope with all the
     fields downstream callers depend on
  4. ``chemaster_list_skills`` / ``chemaster_list_tools`` /
     ``chemaster_list_engines`` return the expected envelope shape
  5. Runs directory is cleaned up after each call (unless CHEMASTER_KEEP_MCP_RUNS)
  6. Mock router is bilingual (English + Chinese intents both work)

Stdio transport itself is exercised by the existing
``scripts/benchmarks/probe_mcp_protocol.py`` integration probe; here we
focus on the tool-level contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Shared lazy imports — load the module once per test session
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def srv():
    from chemaster.mcp.agent import server
    return server


# ──────────────────────────────────────────────────────────────────────────────
# chemaster_run — happy path + error envelope shape
# ──────────────────────────────────────────────────────────────────────────────


class TestChemasterRun:
    def test_empty_intent_returns_structured_error(self, srv):
        r = srv.chemaster_run("")
        assert r["ok"] is False
        assert r["error_code"] == "EMPTY_INTENT"
        assert "suggestion" in r

    def test_whitespace_intent_also_rejected(self, srv):
        r = srv.chemaster_run("   \n  ")
        assert r["ok"] is False
        assert r["error_code"] == "EMPTY_INTENT"

    def test_english_energy_intent_routes_to_psi4(self, srv):
        r = srv.chemaster_run("compute H2 energy with HF/sto-3g",
                              provider="mock", max_turns=5)
        assert r["ok"] is True, r
        names = [tc["name"] for tc in r["result"]["tool_calls"]]
        assert "calc_psi4_single_point" in names
        assert "finish" in names
        assert r["result"]["status"] == "completed"
        assert r["result"]["n_steps"] >= 2

    def test_chinese_constant_intent_routes_to_const_get(self, srv):
        r = srv.chemaster_run("查物理常数普朗克常数",
                              provider="mock", max_turns=5)
        assert r["ok"] is True
        names = [tc["name"] for tc in r["result"]["tool_calls"]]
        assert "const_get" in names
        assert "finish" in names

    def test_result_envelope_has_required_fields(self, srv):
        r = srv.chemaster_run("compute H2 energy", provider="mock", max_turns=5)
        assert r["ok"] is True
        result = r["result"]
        for key in ("task_id", "status", "n_steps", "tool_calls",
                    "finish_payload", "elapsed_s", "started_at", "finished_at"):
            assert key in result, f"missing {key!r}"
        meta = r["meta"]
        for key in ("engine", "provider", "n_tools_registered", "max_turns"):
            assert key in meta

    def test_finish_payload_captured_from_tool_args(self, srv):
        """The mock router emits finish(summary="Task completed.") — we
        must surface that payload at the top of the result."""
        r = srv.chemaster_run("compute H2 energy", provider="mock", max_turns=5)
        fp = r["result"]["finish_payload"]
        assert fp is not None
        assert fp.get("summary") == "Task completed."

    def test_max_turns_clamped(self, srv):
        # max_turns is clamped to [1, 60].  Falsy values (0, None) fall back
        # to the default of 20 via the `or 20` guard in the impl.
        r1 = srv.chemaster_run("compute H2 energy", provider="mock", max_turns=0)
        assert r1["meta"]["max_turns"] == 20  # falsy → default
        r2 = srv.chemaster_run("compute H2 energy", provider="mock", max_turns=999)
        assert r2["meta"]["max_turns"] == 60  # clamped down
        r3 = srv.chemaster_run("compute H2 energy", provider="mock", max_turns=-5)
        assert r3["meta"]["max_turns"] == 1   # clamped up to the lower bound

    def test_runs_dir_cleaned_up_by_default(self, srv, monkeypatch, tmp_path):
        """Without CHEMASTER_KEEP_MCP_RUNS, the temp runs dir is rm-rf'd."""
        monkeypatch.delenv("CHEMASTER_KEEP_MCP_RUNS", raising=False)
        # Spy on tempfile.mkdtemp to capture the path used. Filter by the
        # server's prefix: other layers (e.g. calc_psi4 log dirs) also call
        # mkdtemp during the run and have their own lifecycle.
        import tempfile as _tf
        captured = {}
        real_mkdtemp = _tf.mkdtemp
        def spy(*args, **kw):
            p = real_mkdtemp(*args, **kw)
            if "chemaster_mcp_runs_" in p:
                captured["path"] = p
            return p
        monkeypatch.setattr(srv.tempfile, "mkdtemp", spy)
        srv.chemaster_run("compute H2 energy", provider="mock", max_turns=5)
        assert "path" in captured
        assert not Path(captured["path"]).exists(), \
            f"Expected runs dir {captured['path']} to be cleaned up"

    def test_runs_dir_preserved_with_env_opt_in(self, srv, monkeypatch):
        """With CHEMASTER_KEEP_MCP_RUNS=1 the dir is kept for inspection."""
        monkeypatch.setenv("CHEMASTER_KEEP_MCP_RUNS", "1")
        import tempfile as _tf
        captured = {}
        real_mkdtemp = _tf.mkdtemp
        def spy(*args, **kw):
            p = real_mkdtemp(*args, **kw)
            if "chemaster_mcp_runs_" in p:
                captured["path"] = p
            return p
        monkeypatch.setattr(srv.tempfile, "mkdtemp", spy)
        try:
            srv.chemaster_run("compute H2 energy", provider="mock", max_turns=5)
            assert Path(captured["path"]).exists()
        finally:
            # Manual cleanup since we asked the server not to do it.
            import shutil
            shutil.rmtree(captured["path"], ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────────
# chemaster_list_* — envelope shape + delegation correctness
# ──────────────────────────────────────────────────────────────────────────────


class TestListTools:
    def test_list_skills_returns_envelope(self, srv):
        r = srv.chemaster_list_skills()
        assert r["ok"] is True
        assert "result" in r
        assert "skills" in r["result"]
        assert isinstance(r["result"]["skills"], list)

    def test_list_tools_includes_known_tools(self, srv):
        r = srv.chemaster_list_tools()
        assert r["ok"] is True
        names = {t["name"] for t in r["result"]["tools"]}
        # A few stable tool names that have shipped for many releases
        assert "kb_search" in names
        assert "const_get" in names
        assert "list_skills" in names
        # n_tools sanity bound (registry has > 20 tools at last count)
        assert r["result"]["n_tools"] >= 20

    def test_list_engines_reports_known_engines(self, srv):
        r = srv.chemaster_list_engines()
        assert r["ok"] is True
        result = r["result"]
        for engine in ("psi4", "xtb", "gaussian", "orca", "bdf", "momap"):
            assert engine in result
            assert "available" in result[engine]
            assert "path" in result[engine]
            assert isinstance(result[engine]["available"], bool)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — internal _summarize_trajectory + finish-payload extraction
# ──────────────────────────────────────────────────────────────────────────────


class TestSummarizeTrajectory:
    def test_pulls_finish_payload_from_step_tool_call(self, srv):
        """Build a minimal Trajectory by hand with a finish tool call, then
        verify the summarizer picks up the payload."""
        from chemaster.agent.types import (
            AssistantMessage,
            StepRecord,
            ToolCall,
            Trajectory,
        )
        traj = Trajectory()
        traj.add_step(StepRecord(
            step_id=1,
            assistant_message=AssistantMessage(
                content="",
                tool_calls=[ToolCall(
                    id="c1", name="finish",
                    arguments={"summary": "All done", "value": 42},
                )],
            ),
        ))
        traj.finish("completed")  # no payload passed — must come from steps

        summary = srv._summarize_trajectory(traj, agent=None)
        assert summary["finish_payload"]["summary"] == "All done"
        assert summary["finish_payload"]["value"] == 42
        assert summary["status"] == "completed"
        assert summary["n_steps"] == 1
        assert summary["tool_calls"] == [{"step": 1, "name": "finish"}]

    def test_agent_attr_takes_priority_over_trajectory(self, srv):
        """If the agent has _finish_payload set (the normal happy path),
        it should win over the trajectory's finish_payload."""
        from chemaster.agent.types import Trajectory
        traj = Trajectory()
        traj.finish("completed", {"from": "trajectory"})

        class FakeAgent:
            _finish_payload = {"from": "agent"}

        summary = srv._summarize_trajectory(traj, agent=FakeAgent())
        assert summary["finish_payload"] == {"from": "agent"}


# ──────────────────────────────────────────────────────────────────────────────
# MCP tool registration — verify FastMCP picked up the four tools
# ──────────────────────────────────────────────────────────────────────────────


class TestMCPRegistration:
    @pytest.mark.asyncio
    async def test_four_tools_registered(self, srv):
        """The FastMCP instance must expose exactly our four tools."""
        tools = await srv.mcp.list_tools()
        names = {t.name for t in tools}
        assert "chemaster_run" in names
        assert "chemaster_list_skills" in names
        assert "chemaster_list_tools" in names
        assert "chemaster_list_engines" in names
