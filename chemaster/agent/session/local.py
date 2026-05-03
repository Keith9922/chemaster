"""LocalSession —— 直接在本机执行命令，Phase 1/2 的默认 Session。

参考 EvoMaster LocalSession，添加计算化学专属：
- 自动创建 workspace_path
- 持久 shell 进程（支持环境变量继承）
- 输出截断防止 context 爆炸
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from pydantic import Field

from chemaster.agent.session.base import BaseSession, SessionConfig


class LocalSessionConfig(SessionConfig):
    """本地 Session 配置。"""
    workspace_path: str = Field(default="./workspace")
    timeout: int = Field(default=300)
    encoding: str = Field(default="utf-8")
    # 环境变量注入（如 OMP_NUM_THREADS、PSI4_SCRATCH 等）
    env_vars: dict[str, str] = Field(default_factory=dict)
    # 超长输出截断（字符数）
    max_output_chars: int = Field(default=50_000)


class LocalSession(BaseSession):
    """在本机直接执行命令的 Session。

    使用 subprocess 调用 bash，每次 exec_bash 都是独立进程
    （不维持持久 shell state，计算化学任务通常无需跨命令共享 state）。
    """

    def __init__(self, config: LocalSessionConfig | None = None) -> None:
        super().__init__(config)
        self.config: LocalSessionConfig = config or LocalSessionConfig()
        self._workspace = Path(self.config.workspace_path).resolve()
        self._env = {**os.environ, **self.config.env_vars}

    def open(self) -> None:
        if self._is_open:
            self.logger.warning("LocalSession 已打开")
            return
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._is_open = True
        self.logger.info("LocalSession 已打开，workspace=%s", self._workspace)

    def close(self) -> None:
        if not self._is_open:
            return
        self._is_open = False
        self.logger.info("LocalSession 已关闭")

    def exec_bash(
        self,
        command: str,
        timeout: int | None = None,
        is_input: bool = False,  # noqa: ARG002（本地不支持）
    ) -> dict[str, Any]:
        """在 workspace 目录执行 bash 命令。"""
        if not self._is_open:
            raise RuntimeError("Session 未打开，请先调用 open()")

        timeout = timeout or self.config.timeout
        command = command.strip()

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding=self.config.encoding,
                errors="replace",
                timeout=timeout,
                cwd=str(self._workspace),
                env=self._env,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            stdout = ""
            stderr = f"命令超时（>{timeout}s）: {command}"
            exit_code = -1
        except Exception as exc:
            stdout = ""
            stderr = f"执行异常: {exc}"
            exit_code = -1

        # 合并输出并截断
        output = stdout + ("\n" + stderr if stderr else "")
        max_chars = self.config.max_output_chars
        if len(output) > max_chars:
            half = max_chars // 2
            output = (
                output[:half]
                + f"\n\n... [输出过长，截断 {len(output) - max_chars} 字符] ...\n\n"
                + output[-half:]
            )

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "working_dir": str(self._workspace),
            "output": output,
        }

    def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """读取文件（支持绝对路径和相对 workspace 的路径）。"""
        p = Path(path)
        if not p.is_absolute():
            p = self._workspace / path
        return p.read_text(encoding=encoding)

    def write_file(self, path: str, content: str, encoding: str = "utf-8") -> None:
        """写文件（父目录不存在则自动创建）。"""
        p = Path(path)
        if not p.is_absolute():
            p = self._workspace / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)

    def path_exists(self, path: str) -> bool:
        p = Path(path)
        if not p.is_absolute():
            p = self._workspace / path
        return p.exists()

    def get_workspace_path(self) -> str:
        return str(self._workspace)
