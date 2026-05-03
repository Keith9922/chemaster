"""SlurmSession —— 提交任务到 SLURM 超算（Phase 3 实现）。

Phase 1/2 只需要 LocalSession。本文件是 Phase 3 的扩展点，
提供接口定义和基本 stub，防止 import 报错。

Phase 3 实现路线：
1. exec_bash → sbatch → 返回 job_id
2. 轮询 sacct/squeue 等待完成
3. scp/rsync 拉回结果文件
4. 解析 stdout/stderr

参考：EvoMaster Session 接口 + SLURM 官方文档
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from chemaster.agent.session.base import BaseSession, SessionConfig


class SlurmSessionConfig(SessionConfig):
    """SLURM Session 配置。"""
    workspace_path: str = Field(default="./workspace")
    # 超算 SSH 连接信息
    host: str = Field(default="", description="超算登录节点 hostname")
    user: str = Field(default="", description="超算账号")
    ssh_key: str = Field(default="~/.ssh/id_rsa", description="SSH 私钥路径")
    # SLURM 作业默认参数
    partition: str = Field(default="cpu", description="SLURM 分区")
    nodes: int = Field(default=1)
    ntasks_per_node: int = Field(default=8)
    memory_gb: int = Field(default=32)
    walltime: str = Field(default="24:00:00")
    # 轮询间隔
    poll_interval_s: int = Field(default=30, description="等待作业完成的轮询间隔（秒）")


class SlurmSession(BaseSession):
    """SLURM 超算 Session —— Phase 3 实现。

    Phase 1/2 会直接抛出 NotImplementedError；在 Phase 3 开发前
    不应在生产代码中使用。
    """

    def __init__(self, config: SlurmSessionConfig | None = None) -> None:
        super().__init__(config)
        self.config: SlurmSessionConfig = config or SlurmSessionConfig()

    def open(self) -> None:
        raise NotImplementedError(
            "SlurmSession 是 Phase 3 功能。"
            "Phase 1/2 请使用 LocalSession。"
            "Phase 3 实现：SSH 连接超算，确认 SLURM 可用。"
        )

    def close(self) -> None:
        raise NotImplementedError("SlurmSession Phase 3")

    def exec_bash(
        self,
        command: str,
        timeout: int | None = None,
        is_input: bool = False,
    ) -> dict[str, Any]:
        """Phase 3：
        1. 将 command 包装成 SLURM job script
        2. sbatch 提交
        3. 轮询 sacct 等待完成
        4. 返回 stdout/stderr
        """
        raise NotImplementedError(
            "SlurmSession.exec_bash() Phase 3 功能未实现。\n"
            "实现路线：command → sbatch → poll sacct → scp 结果 → 返回 stdout/stderr"
        )

    def read_file(self, path: str, encoding: str = "utf-8") -> str:
        raise NotImplementedError("SlurmSession Phase 3")

    def write_file(self, path: str, content: str, encoding: str = "utf-8") -> None:
        raise NotImplementedError("SlurmSession Phase 3")

    # ------------------------------------------------------------------
    # Phase 3 预留钩子（供实现者填充）
    # ------------------------------------------------------------------

    def submit_job(self, script: str) -> str:
        """提交 SLURM 作业，返回 job_id。Phase 3 实现。"""
        raise NotImplementedError

    def wait_for_job(self, job_id: str) -> dict[str, Any]:
        """轮询等待 job 完成，返回状态信息。Phase 3 实现。"""
        raise NotImplementedError

    def fetch_output(self, job_id: str, remote_path: str, local_path: str) -> None:
        """将超算上的结果文件拉回本地。Phase 3 实现。"""
        raise NotImplementedError
