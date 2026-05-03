"""CLI 子命令测试 —— init / clean / skills list / mcps list / kb list / report。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from chemaster.cli import main


# ────────────────────────────────────────────────────────────────────────
# init
# ────────────────────────────────────────────────────────────────────────

def test_init_creates_config(tmp_path: Path):
    runner = CliRunner()
    cfg_dir = tmp_path / "cfg"
    result = runner.invoke(
        main, ["init", "--config-dir", str(cfg_dir)],
    )
    assert result.exit_code == 0, result.output
    assert (cfg_dir / "config.yaml").exists()


def test_init_refuses_overwrite(tmp_path: Path):
    runner = CliRunner()
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text("existing", encoding="utf-8")
    result = runner.invoke(
        main, ["init", "--config-dir", str(cfg_dir)],
    )
    assert result.exit_code == 2
    assert "already exists" in result.output.lower() or "已存在" in result.output


def test_init_force_overwrites(tmp_path: Path):
    runner = CliRunner()
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text("old content", encoding="utf-8")
    result = runner.invoke(
        main, ["init", "--config-dir", str(cfg_dir), "--force"],
    )
    assert result.exit_code == 0
    new_content = (cfg_dir / "config.yaml").read_text(encoding="utf-8")
    assert "old content" not in new_content


# ────────────────────────────────────────────────────────────────────────
# clean
# ────────────────────────────────────────────────────────────────────────

def test_clean_dry_run_lists_old_runs(tmp_path: Path):
    runs = tmp_path / "runs"
    runs.mkdir()
    old = runs / "task-old"
    old.mkdir()
    # 把 mtime 设到 100 天前
    old_ts = time.time() - 100 * 86400
    import os
    os.utime(old, (old_ts, old_ts))

    fresh = runs / "task-fresh"
    fresh.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        main, ["clean", "--runs-dir", str(runs), "--older-than", "30d", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "task-old" in result.output
    assert "task-fresh" not in result.output
    # dry-run 不删
    assert old.exists()


def test_clean_actually_removes(tmp_path: Path):
    runs = tmp_path / "runs"
    runs.mkdir()
    old = runs / "task-old"
    old.mkdir()
    (old / "result.json").write_text("{}", encoding="utf-8")
    import os
    old_ts = time.time() - 100 * 86400
    os.utime(old, (old_ts, old_ts))

    runner = CliRunner()
    result = runner.invoke(
        main, ["clean", "--runs-dir", str(runs), "--older-than", "30d"],
    )
    assert result.exit_code == 0
    assert not old.exists()


# ────────────────────────────────────────────────────────────────────────
# skills / mcps / kb listing
# ────────────────────────────────────────────────────────────────────────

def test_skills_list_nonempty():
    runner = CliRunner()
    result = runner.invoke(main, ["skills", "list"])
    assert result.exit_code == 0
    assert "opt-freq" in result.output


def test_kb_list_nonempty():
    runner = CliRunner()
    result = runner.invoke(main, ["kb", "list"])
    assert result.exit_code == 0
    assert "functionals.yaml" in result.output


# ────────────────────────────────────────────────────────────────────────
# report
# ────────────────────────────────────────────────────────────────────────

def test_report_subcommand(tmp_path: Path):
    """对一个最简任务目录跑 chemaster report。"""
    td = tmp_path / "task-rep-test"
    td.mkdir()
    (td / "plan.json").write_text(json.dumps({
        "task_id": "task-rep-test",
        "user_intent": "test",
        "inferred_workflow": "single_point",
        "target_system": {"formula": "X"},
        "steps": [], "citations": [], "total_estimate": {},
        "created_at": "x", "requires_confirmation": True,
    }), encoding="utf-8")
    (td / "meta.json").write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["report", str(td)])
    assert result.exit_code == 0
    assert (td / "report.md").exists()


# ────────────────────────────────────────────────────────────────────────
# version + check-engines（不抛错即可）
# ────────────────────────────────────────────────────────────────────────

def test_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "chemaster" in result.output


def test_check_engines_runs():
    runner = CliRunner()
    result = runner.invoke(main, ["--check-engines"])
    assert result.exit_code == 0
    assert "Python" in result.output
