"""Session 基类 —— 定义所有 Session 的统一接口。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    """Session 通用配置。"""
    workspace_path: str = Field(default="./workspace", description="工作目录路径")
    timeout: int = Field(default=300, description="命令超时（秒）")


class BaseSession(ABC):
    """所有 Session 的抽象基类。

    Session 封装"在哪里执行命令"，使 Agent/Executor 不需要知道
    任务跑在本机还是超算还是 Docker。

    所有子类必须实现：
    - open() / close()
    - exec_bash(command, timeout) → dict
    - read_file(path) → str
    - write_file(path, content)
    """

    def __init__(self, config: SessionConfig | None = None) -> None:
        self.config = config or SessionConfig()
        self._is_open = False
        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    @abstractmethod
    def open(self) -> None:
        """打开 Session（创建工作目录、建立连接等）。"""

    @abstractmethod
    def close(self) -> None:
        """关闭 Session（清理临时文件、断开连接等）。"""

    def __enter__(self) -> "BaseSession":
        self.open()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------

    @abstractmethod
    def exec_bash(
        self,
        command: str,
        timeout: int | None = None,
        is_input: bool = False,
    ) -> dict[str, Any]:
        """执行 bash 命令。

        Returns:
            {
              "stdout": str,
              "stderr": str,
              "exit_code": int,
              "working_dir": str,
              "output": str,   # stdout + stderr 合并
            }
        """

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------

    @abstractmethod
    def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """读取文件内容。"""

    @abstractmethod
    def write_file(self, path: str, content: str, encoding: str = "utf-8") -> None:
        """写文件内容。"""

    def path_exists(self, path: str) -> bool:
        """检查路径是否存在（默认实现：用 exec_bash test -e）。"""
        result = self.exec_bash(f"test -e {path} && echo EXISTS || echo NOT_EXISTS")
        return "EXISTS" in result.get("output", "")

    def get_workspace_path(self) -> str:
        """获取当前工作目录（绝对路径）。"""
        return str(Path(self.config.workspace_path).resolve())
