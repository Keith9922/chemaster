"""Smoke tests for the ``chemaster doctor`` subcommand."""

from __future__ import annotations

from click.testing import CliRunner


class TestDoctor:
    def test_doctor_runs_without_crashing(self):
        from chemaster.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--quiet"])
        # On a CI machine the exit code is either 0 (all good) or 1 (no
        # chemistry engines + no API key). Either way it must not raise.
        assert result.exit_code in (0, 1), result.output
        # The Rich-rendered output should contain the section banners.
        assert "Runtime" in result.output
        assert "Chemistry engines" in result.output
        assert "Summary" in result.output

    def test_doctor_lists_psi4_when_present(self, monkeypatch):
        """If psi4 is reachable on PATH, the doctor must show the path."""
        import shutil
        if shutil.which("psi4"):
            from chemaster.cli import main
            runner = CliRunner()
            result = runner.invoke(main, ["doctor", "--quiet"])
            assert "psi4" in result.output

    def test_doctor_recognises_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-1234-mock")
        from chemaster.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--quiet"])
        assert "ANTHROPIC_API_KEY" in result.output
        # The key is masked, not echoed in full
        assert "sk-test-1234-mock" not in result.output

    def test_doctor_help_renders(self):
        from chemaster.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "environment audit" in result.output
        assert "chemistry engines" in result.output.lower()
