"""CLI unit tests via click.testing.CliRunner."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

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
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
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
    assert "MockLLM" in output or "ANTHROPIC_API_KEY" in output
