"""CLI unit tests via click.testing.CliRunner."""

from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from chemaster.cli import main


def _runner() -> CliRunner:
    # click 8.2+ removed mix_stderr; fall back gracefully.
    try:
        return CliRunner(mix_stderr=False)        # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


# ──────────────────────────────────────────────────────────────────────────
# Top-level flags
# ──────────────────────────────────────────────────────────────────────────


def test_cli_version_prints_version():
    res = _runner().invoke(main, ["--version"])
    assert res.exit_code == 0
    assert "chemaster" in res.output


def test_cli_check_engines_runs_without_error():
    res = _runner().invoke(main, ["--check-engines"])
    assert res.exit_code == 0
    assert "ChemMaster" in res.output
    assert "Python" in res.output


# ──────────────────────────────────────────────────────────────────────────
# Sub-commands that don't need an LLM
# ──────────────────────────────────────────────────────────────────────────


def test_cli_skills_list():
    res = _runner().invoke(main, ["skills", "list"])
    assert res.exit_code == 0
    assert "opt-freq" in res.output
    assert "tadf-pipeline" in res.output


def test_cli_skills_show_known():
    res = _runner().invoke(main, ["skills", "show", "opt-freq"])
    assert res.exit_code == 0
    assert "opt-freq" in res.output.lower()


def test_cli_skills_show_unknown():
    res = _runner().invoke(main, ["skills", "show", "banana"])
    assert res.exit_code != 0


def test_cli_kb_search():
    res = _runner().invoke(main, ["kb", "search", "basis"])
    assert res.exit_code == 0
    assert "kb_search" in res.output or "basis" in res.output.lower()


def test_cli_kb_list():
    res = _runner().invoke(main, ["kb", "list"])
    assert res.exit_code == 0
    assert "yaml" in res.output


def test_cli_tools_list():
    res = _runner().invoke(main, ["tools", "list"])
    assert res.exit_code == 0
    # Should mention some core tools
    assert "calc_psi4_optimize" in res.output
    assert "finish" in res.output
    assert "kb_search" in res.output


def test_cli_mcps_list():
    res = _runner().invoke(main, ["mcps", "list"])
    assert res.exit_code == 0


# ──────────────────────────────────────────────────────────────────────────
# `chemaster run` — uses MockLLM when no API key
# ──────────────────────────────────────────────────────────────────────────


def test_cli_run_no_api_key_warns_and_exits_cleanly(tmp_path: Path):
    """With no ANTHROPIC_API_KEY, `run` should warn but not crash. The
    MockLLM has no scripted responses, so the loop will surface that."""
    runs_dir = tmp_path / "runs"
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY")}
    res = _runner().invoke(
        main,
        ["run", "Compute energy of H2O", "--runs-dir", str(runs_dir),
         "--max-turns", "2", "--no-confirm"],
        env=env,
    )
    # We tolerate either a graceful error exit or a successful "no responses" abort.
    # Exit code 3 = agent crash (expected when MockLLM exhausts).
    assert res.exit_code in {0, 3}
    output = (res.stderr or "") + res.output
    assert "MockLLM" in output or "API_KEY" in output


# ──────────────────────────────────────────────────────────────────────────
# `chemaster show` — task viewer
# ──────────────────────────────────────────────────────────────────────────


def _make_fake_trajectory(runs_dir: Path, task_id: str = "task-fake-001") -> Path:
    """Helper: drop a minimal trajectory.json for show/replay tests."""
    task_dir = runs_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id,
        "status": "completed",
        "started_at": "2026-04-30T00:00:00+00:00",
        "finished_at": "2026-04-30T00:00:30+00:00",
        "steps": [
            {
                "step_id": 1,
                "timestamp": "2026-04-30T00:00:01",
                "assistant_message": {
                    "role": "assistant",
                    "content": "ok",
                    "tool_calls": [
                        {"id": "tc-1", "name": "io_lookup_by_name",
                         "arguments": {"name": "water"}}
                    ],
                    "meta": {},
                },
                "tool_responses": [
                    {"role": "tool", "tool_call_id": "tc-1",
                     "name": "io_lookup_by_name",
                     "content": "[OK] io_lookup_by_name", "is_error": False, "meta": {}}
                ],
                "meta": {},
            },
            {
                "step_id": 2,
                "timestamp": "2026-04-30T00:00:02",
                "assistant_message": {
                    "role": "assistant",
                    "content": "done",
                    "tool_calls": [
                        {"id": "tc-2", "name": "finish",
                         "arguments": {"summary": "done", "key_results": {"e": 1.0}}}
                    ],
                    "meta": {},
                },
                "tool_responses": [],
                "meta": {},
            },
        ],
        "finish_payload": {"summary": "done", "key_results": {"e": 1.0}},
        "meta": {},
    }
    import json
    (task_dir / "trajectory.json").write_text(json.dumps(payload, indent=2))
    return task_dir


def test_cli_show_existing_task(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    _make_fake_trajectory(runs_dir, "task-fake-001")
    res = _runner().invoke(main, ["show", "task-fake-001",
                                  "--runs-dir", str(runs_dir)])
    assert res.exit_code == 0
    assert "task-fake-001" in res.output
    assert "completed" in res.output
    assert "io_lookup_by_name" in res.output


def test_cli_show_unknown_task(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    res = _runner().invoke(main, ["show", "nope",
                                  "--runs-dir", str(runs_dir)])
    assert res.exit_code != 0


def test_cli_init_writes_env_file(tmp_path: Path, monkeypatch):
    """Walk through the wizard non-interactively by feeding stdin."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Provider, api key, runs_dir
    res = _runner().invoke(
        main, ["init"],
        input="minimax\ntest-key\n/tmp/myruns\n",
    )
    assert res.exit_code == 0
    env_file = tmp_path / ".chemaster" / "env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "MINIMAX_API_KEY=test-key" in content
    assert "CHEMASTER_LLM_PROVIDER=minimax" in content
    assert "/tmp/myruns" in content


# ──────────────────────────────────────────────────────────────────────────
# `_write_markdown_report` writes a sensible report.md
# ──────────────────────────────────────────────────────────────────────────


def test_write_markdown_report_writes_well_formed_file(tmp_path: Path):
    from chemaster.agent.types import (
        AssistantMessage,
        StepRecord,
        ToolCall,
        Trajectory,
    )
    from chemaster.cli import _write_markdown_report

    traj = Trajectory(task_id="task-report-1", status="completed")
    traj.add_step(StepRecord(
        step_id=1,
        assistant_message=AssistantMessage(
            content="",
            tool_calls=[
                ToolCall(id="t1", name="finish",
                         arguments={"summary": "All done.",
                                    "key_results": {"final_energy_Hartree": -76.42}}),
            ],
        ),
    ))
    runs_dir = tmp_path / "runs"
    (runs_dir / traj.task_id).mkdir(parents=True)

    _write_markdown_report(traj, runs_dir)

    report = (runs_dir / traj.task_id / "report.md").read_text()
    assert "task-report-1" in report
    assert "All done." in report
    assert "final_energy_Hartree" in report
    assert "-76.42" in report
