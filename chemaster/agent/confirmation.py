"""ConfirmationLoop —— Plan-Confirm 三段式中间态。

强制约束（架构层，不靠 prompt 引导）：Executor 没拿到本模块返回的
approved Plan + confirm_token，拒绝执行。这样 LLM 无法跳过用户确认。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from chemaster.agent.plan import Plan


@dataclass
class ApprovedPlan:
    plan: Plan
    confirm_token: str
    user_edits: list[str]   # 用户修改记录


class ConfirmationLoop:
    """渲染 Plan、收集用户决策、出 ApprovedPlan。"""

    def __init__(self, ui=None) -> None:
        self.ui = ui

    def run(self, plan: Plan) -> ApprovedPlan | None:  # noqa: ARG002
        """Phase 1 占位：自动 approve（用于无 UI 测试）。

        Phase 1 真实实现需要 TUI 卡片 + 键盘交互。
        Phase 2 加"建议+纠偏"：用户编辑后再次校验合理性。
        """
        raise NotImplementedError("Phase 1: implement TUI confirmation card.")

    @staticmethod
    def _generate_token() -> str:
        return secrets.token_urlsafe(16)
