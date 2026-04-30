"""hpc_slurm MCP tests — config loading, script generation, missing-config path.

A real SLURM cluster isn't available in CI; tests exercise the config
parsing, the SLURM-script builder, and the polite NO_HPC_CONFIG cold
path.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_no_hpc_config_when_yaml_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from chemaster.mcp.hpc_slurm.server import submit
    r = submit(command="echo hi", jobname="t1")
    assert not r["ok"]
    assert r["error_code"] == "NO_HPC_CONFIG"
    assert "hpc.yaml" in r["suggestion"]


def test_load_config_reads_yaml(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".chemaster"
    cfg_dir.mkdir()
    (cfg_dir / "hpc.yaml").write_text(
        "host: hpc.example.edu\n"
        "user: alice\n"
        "ssh_key: ~/.ssh/id_ed25519\n"
        "remote_workdir: /work/alice/runs\n"
        "partition: cpu\n"
        "time_limit: '12:00:00'\n"
        "modules:\n"
        "  - psi4/1.9\n"
    )
    from chemaster.mcp.hpc_slurm.server import _load_config
    cfg = _load_config()
    assert cfg["host"] == "hpc.example.edu"
    assert cfg["partition"] == "cpu"
    assert "psi4/1.9" in cfg["modules"]


def test_build_slurm_script_includes_essentials():
    from chemaster.mcp.hpc_slurm.server import _build_slurm_script
    s = _build_slurm_script(
        jobname="benzene-tddft", command="orca calc.inp",
        partition="gpu", time_limit="04:00:00",
        modules=["openmpi/4.1", "orca/5.0"],
    )
    assert "#!/bin/bash" in s
    assert "#SBATCH --job-name=benzene-tddft" in s
    assert "#SBATCH --partition=gpu" in s
    assert "#SBATCH --time=04:00:00" in s
    assert "module load openmpi/4.1" in s
    assert "module load orca/5.0" in s
    # PITFALLS §4.3: must cd into submit dir
    assert 'cd "$SLURM_SUBMIT_DIR"' in s
    assert "orca calc.inp" in s


def test_status_no_config(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from chemaster.mcp.hpc_slurm.server import status
    r = status("12345")
    assert not r["ok"]
    assert r["error_code"] == "NO_HPC_CONFIG"


def test_fetch_no_rsync(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import shutil as _shutil
    monkeypatch.setattr(_shutil, "which",
                        lambda x: None if x == "rsync" else "/bin/" + x)
    from chemaster.mcp.hpc_slurm.server import fetch
    r = fetch("12345", str(tmp_path / "out"))
    assert not r["ok"]
    assert r["error_code"] == "ENGINE_NOT_FOUND"


def test_hpc_tools_registered():
    from chemaster.agent.tool_loader import build_default_registry
    reg = build_default_registry()
    for name in ("hpc_submit", "hpc_status", "hpc_fetch"):
        assert reg.has(name), f"{name} not registered"
    # submit + fetch are destructive (cluster side-effect); status is read-only
    assert reg.get("hpc_submit").is_destructive
    assert reg.get("hpc_status").is_read_only
    assert reg.get("hpc_fetch").is_destructive
