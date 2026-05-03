"""Context 管理器 —— 防止 LLM context 溢出。

参考 EvoMaster ContextManager，针对计算化学场景调整：
- 计算任务的工具输出可能很长（频率列表、几何坐标）
- 需要保留 system prompt + 最近几轮对话
- 截断策略：latest_half（保留前 1/4 + 后 3/4）

截断优先级（从低到高保留）：
1. 中间的 ToolMessage（最先截断）
2. 中间的 UserMessage / AssistantMessage
3. 最近 N 轮（preserve_recent_turns）
4. SystemMessage（永远保留）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from chemaster.agent.types import Dialog

logger = logging.getLogger(__name__)


class ContextConfig(BaseModel):
    """Context 管理配置。"""
    max_tokens: int = Field(default=100_000, description="触发截断的 token 上限")
    truncation_strategy: str = Field(
        default="latest_half",
        description="截断策略：latest_half | remove_middle_tools",
    )
    preserve_system_messages: bool = Field(default=True, description="始终保留 system 消息")
    preserve_recent_turns: int = Field(default=5, description="始终保留最近 N 对消息")
    # 每条工具输出超过此长度时单独截断
    max_tool_output_chars: int = Field(default=30_000, description="单条工具输出最大字符数")


class ContextManager:
    """管理 Dialog 的 token 用量，超限时执行截断。"""

    def __init__(self, config: ContextConfig | None = None) -> None:
        self.config = config or ContextConfig()
        self._last_prompt_tokens: int = 0

    def update_usage(self, usage: dict, msg_count: int = 0) -> None:  # noqa: ARG002
        """更新上次 LLM 调用的实际 token 用量。"""
        self._last_prompt_tokens = usage.get(
            "prompt_tokens",
            usage.get("input_tokens", 0),
        )

    def reset_prompt_tokens(self) -> None:
        self._last_prompt_tokens = 0

    def is_overflow(self, usage: dict) -> bool:
        """判断是否接近 token 上限（> 90%）。"""
        total = usage.get("total_tokens") or (
            usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        )
        return total > self.config.max_tokens * 0.9

    def prepare_for_query(self, dialog: "Dialog") -> tuple["Dialog", bool]:
        """准备发给 LLM 的 dialog；若需截断则截断并返回 (new_dialog, True)。"""
        # 简单估算：平均每字符 ~0.4 token（中英混合）
        estimated = self._estimate_tokens(dialog)
        if estimated < self.config.max_tokens * 0.8:
            return dialog, False

        logger.info(
            "Context 接近上限（估算 %d tokens），执行截断", estimated
        )
        truncated = self.truncate(dialog)
        return truncated, True

    def truncate(self, dialog: "Dialog") -> "Dialog":
        """执行截断，返回新的 Dialog。"""
        from chemaster.agent.types import Dialog, MessageRole, SystemMessage

        messages = dialog.messages
        if len(messages) <= 2:
            return dialog

        strategy = self.config.truncation_strategy
        if strategy == "latest_half":
            return self._truncate_latest_half(dialog)
        elif strategy == "remove_middle_tools":
            return self._remove_middle_tools(dialog)
        else:
            logger.warning("未知截断策略 '%s'，使用 latest_half", strategy)
            return self._truncate_latest_half(dialog)

    def _truncate_latest_half(self, dialog: "Dialog") -> "Dialog":
        """保留 system + 最后 75% 的消息。"""
        from chemaster.agent.types import Dialog, MessageRole

        messages = dialog.messages
        system_msgs = [m for m in messages if m.role == MessageRole.SYSTEM]
        non_system = [m for m in messages if m.role != MessageRole.SYSTEM]

        keep_n = max(
            self.config.preserve_recent_turns * 2,
            int(len(non_system) * 0.75),
        )
        kept = non_system[-keep_n:]

        new_msgs = system_msgs + kept
        logger.info(
            "截断: %d → %d 条消息（保留最近 %d 条非 system）",
            len(messages), len(new_msgs), keep_n,
        )
        return Dialog(messages=new_msgs, tools=dialog.tools)

    def _remove_middle_tools(self, dialog: "Dialog") -> "Dialog":
        """移除中间段的 ToolMessage，保留最近几轮。"""
        from chemaster.agent.types import Dialog, MessageRole

        messages = dialog.messages
        system_msgs = [m for m in messages if m.role == MessageRole.SYSTEM]
        non_system = [m for m in messages if m.role != MessageRole.SYSTEM]

        recent_n = self.config.preserve_recent_turns * 2
        recent = non_system[-recent_n:]
        middle = non_system[:-recent_n]

        # 移除中间段的 tool messages
        filtered_middle = [
            m for m in middle if m.role != MessageRole.TOOL
        ]

        new_msgs = system_msgs + filtered_middle + recent
        logger.info(
            "截断（remove_middle_tools）: %d → %d 条消息",
            len(messages), len(new_msgs),
        )
        return Dialog(messages=new_msgs, tools=dialog.tools)

    @staticmethod
    def _estimate_tokens(dialog: "Dialog") -> int:
        """粗估 dialog 的 token 数（0.4 token/char）。"""
        total_chars = sum(
            len(m.content or "") for m in dialog.messages
        )
        return int(total_chars * 0.4)
