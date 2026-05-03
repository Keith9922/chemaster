"""Session 抽象层 —— 统一"在哪里执行计算"的接口。

参考 EvoMaster BaseSession/LocalSession，扩展 SlurmSession（Phase 3）。

Session 类型：
- LocalSession：直接在本机执行，适合 Phase 1/2
- SlurmSession：提交到 SLURM 超算，Phase 3 实现

Usage::

    from chemaster.agent.session import build_session
    session = build_session(config["session"])
    with session:
        result = session.exec_bash("xtb molecule.xyz --opt")
"""

from chemaster.agent.session.base import BaseSession, SessionConfig
from chemaster.agent.session.local import LocalSession, LocalSessionConfig
from chemaster.agent.session.slurm import SlurmSession, SlurmSessionConfig
from chemaster.agent.session.factory import build_session

__all__ = [
    "BaseSession",
    "SessionConfig",
    "LocalSession",
    "LocalSessionConfig",
    "SlurmSession",
    "SlurmSessionConfig",
    "build_session",
]
