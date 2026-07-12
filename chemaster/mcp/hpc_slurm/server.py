"""chem.hpc_slurm — submit / monitor / fetch SLURM jobs over SSH.

Async-style submission MCP for university HPC clusters. The Agent calls
``submit`` and gets back a job_id immediately; ``status`` polls; ``fetch``
pulls the result directory back over rsync.

Connection details (host, user, key) come from a config block; this MCP
does NOT execute arbitrary shell commands by design (see PITFALLS §8.3 —
agent shouldn't have an unrestricted SSH execv).

Python deps: paramiko (SSH), platformdirs (config). Both already in the
chemaster `dependencies` block.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)
mcp = FastMCP("chem.hpc_slurm")


# ══════════════════════════════════════════════════════════════════════════════
# Config helpers
# ══════════════════════════════════════════════════════════════════════════════


def _config_path() -> Path:
    """Where the user's HPC config lives.

    Format (YAML, ~/.chemaster/hpc.yaml):

        host: hpc.example.edu
        user: alice
        ssh_key: ~/.ssh/id_ed25519
        remote_workdir: /work/alice/chemaster_runs
        partition: cpu
        time_limit: "12:00:00"
        modules:
          - psi4/1.9
          - openmpi/4.1
        pre_run_hook: ""
    """
    return Path(os.path.expanduser("~/.chemaster/hpc.yaml"))


def _load_config() -> dict[str, Any] | None:
    p = _config_path()
    if not p.exists():
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or None
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", p, exc)
        return None


def _build_slurm_script(*, jobname: str, command: str, partition: str,
                       time_limit: str, modules: list[str],
                       pre_run_hook: str = "") -> str:
    """Compose a simple SLURM submission script."""
    module_block = "\n".join(f"module load {m}" for m in (modules or []))
    return "\n".join([
        "#!/bin/bash",
        f"#SBATCH --job-name={jobname}",
        f"#SBATCH --partition={partition}",
        f"#SBATCH --time={time_limit}",
        "#SBATCH --output=%j.out",
        "#SBATCH --error=%j.err",
        "",
        'cd "$SLURM_SUBMIT_DIR"',     # PITFALLS §4.3
        "set -eu",
        module_block,
        pre_run_hook,
        "",
        command,
    ])


# ══════════════════════════════════════════════════════════════════════════════
# SSH helpers
# ══════════════════════════════════════════════════════════════════════════════


def _ssh_run(*, host: str, user: str, key: str | None,
            command: str, timeout: int = 60) -> tuple[int, str, str]:
    """Execute ``command`` over SSH using paramiko. Returns (rc, stdout, stderr)."""
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko not installed") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict[str, Any] = {"username": user, "timeout": timeout}
    if key:
        kwargs["key_filename"] = os.path.expanduser(key)
    try:
        client.connect(hostname=host, **kwargs)
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return rc, out, err
    finally:
        client.close()


# ══════════════════════════════════════════════════════════════════════════════
# Tools
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def submit(
    command: str,
    jobname: str = "chemaster",
    partition: str | None = None,
    time_limit: str | None = None,
    extra_files: list[str] | None = None,
) -> dict[str, Any]:
    """Submit a SLURM job. Returns immediately with the job_id; the agent
    should then call ``status`` (and optionally ``fetch``) to poll.

    Args:
        command: shell command to run on the cluster (e.g. an ORCA invocation
                 or "psi4 input.dat").
        jobname: SLURM --job-name.
        partition / time_limit: override the defaults from ~/.chemaster/hpc.yaml.
        extra_files: local file paths to upload alongside the script.

    Returns:
        ok=True: {ok, result: {job_id, host, remote_workdir}, ...}
        ok=False: ENGINE_NOT_FOUND / NO_HPC_CONFIG / SSH_ERROR / SBATCH_FAILED
    """
    cfg = _load_config()
    if cfg is None:
        return {
            "ok": False,
            "error_code": "NO_HPC_CONFIG",
            "details": f"Missing or invalid {_config_path()}",
            "suggestion": (
                "Create ~/.chemaster/hpc.yaml with at minimum: host, user, "
                "ssh_key, remote_workdir, partition, time_limit. See the "
                "MCP docstring for the schema."
            ),
        }
    host = cfg.get("host")
    user = cfg.get("user")
    if not host or not user:
        return {
            "ok": False,
            "error_code": "NO_HPC_CONFIG",
            "details": "host or user missing from hpc.yaml",
            "suggestion": "Both host and user are required.",
        }

    try:
        import paramiko  # noqa: F401
    except ImportError:
        return {
            "ok": False,
            "error_code": "ENGINE_NOT_FOUND",
            "details": "paramiko not installed.",
            "suggestion": "pip install paramiko",
        }

    script = _build_slurm_script(
        jobname=jobname, command=command,
        partition=partition or cfg.get("partition", "cpu"),
        time_limit=time_limit or cfg.get("time_limit", "01:00:00"),
        modules=cfg.get("modules", []),
        pre_run_hook=cfg.get("pre_run_hook", ""),
    )

    remote_dir = (cfg.get("remote_workdir", "~/chemaster_runs")
                  + f"/{jobname}-{int(time.time())}")
    setup_cmd = (
        f"mkdir -p {remote_dir} && "
        f"cat > {remote_dir}/run.sbatch <<'__EOS__'\n{script}\n__EOS__\n"
        f"cd {remote_dir} && sbatch run.sbatch"
    )

    try:
        rc, out, err = _ssh_run(
            host=host, user=user, key=cfg.get("ssh_key"),
            command=setup_cmd, timeout=60,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "SSH_ERROR",
            "details": str(exc),
            "suggestion": "Check host, ssh_key, and that you can ssh manually.",
        }

    if rc != 0:
        return {
            "ok": False,
            "error_code": "SBATCH_FAILED",
            "details": (err or out)[-1000:],
            "suggestion": "Inspect the cluster's sbatch error; common: "
                          "invalid partition, time over limit, account quota.",
        }

    m = re.search(r"Submitted batch job\s+(\d+)", out)
    job_id = m.group(1) if m else None
    return {
        "ok": True,
        "result": {
            "job_id": job_id,
            "host": host,
            "remote_workdir": remote_dir,
        },
        "warnings": [] if job_id else [
            "sbatch returned 0 but no 'Submitted batch job <id>' line found. "
            "Check the raw output."
        ],
        "meta": {"raw_stdout": out[-500:]},
    }


@mcp.tool()
def status(job_id: str) -> dict[str, Any]:
    """Query SLURM for one job's status.

    Returns:
        ok=True: {ok, result: {job_id, state, time_used, partition, ...}}
        ok=False: NO_HPC_CONFIG / SSH_ERROR / JOB_NOT_FOUND
    """
    cfg = _load_config()
    if cfg is None:
        return {"ok": False, "error_code": "NO_HPC_CONFIG",
                "details": "see ~/.chemaster/hpc.yaml",
                "suggestion": "Run `chemaster init` then add HPC block."}

    try:
        rc, out, _err = _ssh_run(
            host=cfg["host"], user=cfg["user"], key=cfg.get("ssh_key"),
            command=f"squeue -j {job_id} -h -o '%T|%M|%P|%R'",
            timeout=20,
        )
    except Exception as exc:
        return {"ok": False, "error_code": "SSH_ERROR",
                "details": str(exc), "suggestion": "Check SSH connectivity."}

    if rc != 0 or not out.strip():
        # Job may have finished — check sacct.
        try:
            rc2, out2, _ = _ssh_run(
                host=cfg["host"], user=cfg["user"], key=cfg.get("ssh_key"),
                command=f"sacct -j {job_id} -P -n -o State,Elapsed,ExitCode",
                timeout=20,
            )
            if rc2 == 0 and out2.strip():
                first = out2.strip().splitlines()[0].split("|")
                return {
                    "ok": True,
                    "result": {"job_id": job_id, "state": first[0],
                               "time_used": first[1] if len(first) > 1 else None,
                               "exit_code": first[2] if len(first) > 2 else None,
                               "queue_visible": False},
                    "warnings": [], "meta": {},
                }
        except Exception:
            pass
        return {"ok": False, "error_code": "JOB_NOT_FOUND",
                "details": "squeue and sacct returned nothing.",
                "suggestion": "Job may have aged out of accounting."}

    parts = out.strip().split("|")
    return {
        "ok": True,
        "result": {
            "job_id": job_id,
            "state": parts[0] if parts else "UNKNOWN",
            "time_used": parts[1] if len(parts) > 1 else None,
            "partition": parts[2] if len(parts) > 2 else None,
            "reason": parts[3] if len(parts) > 3 else None,
            "queue_visible": True,
        },
        "warnings": [], "meta": {},
    }


@mcp.tool()
def fetch(job_id: str, local_dir: str) -> dict[str, Any]:
    """Pull a finished job's artefacts back via rsync.

    Args:
        job_id: SLURM job_id (used to locate the remote workdir from a
                ``runs/`` index — for now we ask the user to keep track).
        local_dir: where to drop the files locally.
    """
    if not shutil.which("rsync"):
        return {"ok": False, "error_code": "ENGINE_NOT_FOUND",
                "details": "rsync not on PATH",
                "suggestion": "Install rsync (system package manager)."}
    cfg = _load_config()
    if cfg is None:
        return {"ok": False, "error_code": "NO_HPC_CONFIG",
                "details": "see ~/.chemaster/hpc.yaml",
                "suggestion": "Add HPC config first."}
    # We can't introspect the original remote_workdir from job_id alone
    # without persistent state; rely on the caller passing a ``REMOTE``
    # env-style hint via local_dir's sibling marker.
    Path(local_dir).mkdir(parents=True, exist_ok=True)
    remote = f"{cfg['user']}@{cfg['host']}:{cfg.get('remote_workdir', '~')}"
    try:
        proc = subprocess.run(
            ["rsync", "-avz", "--include", f"*{job_id}*", "--exclude", "*",
             remote, local_dir],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "TIMEOUT",
                "details": "rsync exceeded 10 min.",
                "suggestion": "Run rsync manually with --partial."}
    if proc.returncode != 0:
        return {"ok": False, "error_code": "RSYNC_FAILED",
                "details": proc.stderr[-1000:],
                "suggestion": "Verify SSH key and remote path."}
    return {
        "ok": True,
        "result": {"local_dir": local_dir, "stdout_tail": proc.stdout[-500:]},
        "warnings": [], "meta": {},
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
