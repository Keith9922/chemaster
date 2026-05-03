"""Session 工厂函数 —— 从 config.yaml 构建 Session 实例。"""

from __future__ import annotations

from typing import Any

from chemaster.agent.session.base import BaseSession
from chemaster.agent.session.local import LocalSession, LocalSessionConfig
from chemaster.agent.session.slurm import SlurmSession, SlurmSessionConfig


def build_session(session_config: dict[str, Any]) -> BaseSession:
    """从 config.yaml 的 session 配置块构建 Session 实例。

    Args:
        session_config: config["session"] 字典。

    Returns:
        BaseSession 实例（未打开，需调用 open() 或用 with 语句）。

    Example config::

        session:
          type: local          # local | slurm
          local:
            workspace_path: ./workspace
            timeout: 300
            env_vars:
              OMP_NUM_THREADS: "4"
          slurm:               # Phase 3
            host: hpc.school.edu
            user: myname
            partition: cpu
    """
    session_type = session_config.get("type", "local")

    if session_type == "local":
        cfg_dict = session_config.get("local", {})
        cfg = LocalSessionConfig(**cfg_dict)
        return LocalSession(cfg)

    elif session_type == "slurm":
        cfg_dict = session_config.get("slurm", {})
        cfg = SlurmSessionConfig(**cfg_dict)
        return SlurmSession(cfg)

    else:
        raise ValueError(
            f"未知 session type: '{session_type}'。"
            f"支持: local, slurm（Phase 3）"
        )
