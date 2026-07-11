"""Context management — keep dialog under the LLM's token budget.

Strategies:
- NONE             — never touch the dialog (useful for tests).
- LATEST_HALF      — keep system message + last N/2 messages.
- SLIDING_WINDOW   — keep system + most recent K messages by character count.

A *very* coarse token estimator is built in (chars / 3.5). Subclasses can
plug in a real tokenizer (tiktoken / Anthropic tokenizer) by overriding
`_count_tokens()`.

Reference: EvoMaster's evomaster/agent/context.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    SystemMessage,
    ToolMessage,
    UserMessage,
)

logger = logging.getLogger(__name__)


class TruncationStrategy(str, Enum):
    NONE = "none"
    LATEST_HALF = "latest_half"
    SLIDING_WINDOW = "sliding_window"


@dataclass
class ContextConfig:
    max_tokens: int = 180_000             # safe under Claude's 200k window
    soft_limit_ratio: float = 0.85        # compact when usage > soft_limit
    strategy: TruncationStrategy = TruncationStrategy.LATEST_HALF
    sliding_window_size: int = 30         # messages to keep when strategy=SLIDING
    keep_system: bool = True              # always preserve the first system message
    keep_first_user: bool = True          # preserve original task description


class ContextManager:
    """Owns truncation policy. Stateless w.r.t. the dialog itself."""

    def __init__(self, config: ContextConfig | None = None) -> None:
        self.config = config or ContextConfig()
        self._last_prompt_tokens = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare_for_query(self, dialog: Dialog) -> tuple[Dialog, bool]:
        """Return a dialog safe to send. Second value: True if the dialog
        was permanently compacted (caller should write back).
        """
        if self.config.strategy == TruncationStrategy.NONE:
            return dialog, False

        estimated = self._count_dialog_tokens(dialog)
        if estimated < self.config.max_tokens * self.config.soft_limit_ratio:
            return dialog, False

        compacted = self.truncate(dialog)
        new_estimate = self._count_dialog_tokens(compacted)
        logger.info(
            "Dialog compacted: %d → %d tokens (estimated)", estimated, new_estimate
        )
        return compacted, True

    def truncate(self, dialog: Dialog) -> Dialog:
        """Apply the configured truncation strategy."""
        if self.config.strategy == TruncationStrategy.LATEST_HALF:
            return self._truncate_latest_half(dialog)
        if self.config.strategy == TruncationStrategy.SLIDING_WINDOW:
            return self._truncate_sliding_window(dialog)
        return dialog

    def update_usage(self, usage: dict[str, Any], msg_count: int = 0) -> None:
        """Stash actual usage from the last LLM response; used for proactive compact."""
        self._last_prompt_tokens = (
            usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        )

    def is_overflow(self, usage: dict[str, Any]) -> bool:
        total = (
            usage.get("total_tokens")
            or (usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
            or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
        )
        return total > self.config.max_tokens * self.config.soft_limit_ratio

    def reset_prompt_tokens(self) -> None:
        self._last_prompt_tokens = 0

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def _truncate_latest_half(self, dialog: Dialog) -> Dialog:
        msgs = list(dialog.messages)
        if not msgs:
            return dialog

        anchors = self._collect_anchors(msgs)
        rest = [m for m in msgs if m not in anchors]
        keep = rest[len(rest) // 2:]

        # Drop orphan tool messages whose tool_use is no longer present.
        keep = self._drop_orphan_tool_messages(anchors, keep)

        return Dialog(messages=anchors + keep, tools=list(dialog.tools))

    def _truncate_sliding_window(self, dialog: Dialog) -> Dialog:
        msgs = list(dialog.messages)
        anchors = self._collect_anchors(msgs)
        rest = [m for m in msgs if m not in anchors]
        keep = rest[-self.config.sliding_window_size:]
        keep = self._drop_orphan_tool_messages(anchors, keep)
        return Dialog(messages=anchors + keep, tools=list(dialog.tools))

    def _collect_anchors(self, msgs: list) -> list:
        """Messages that must always survive truncation."""
        anchors: list = []
        if self.config.keep_system:
            for m in msgs:
                if isinstance(m, SystemMessage):
                    anchors.append(m)
                    break
        if self.config.keep_first_user:
            for m in msgs:
                if isinstance(m, UserMessage):
                    anchors.append(m)
                    break
        return anchors

    def _drop_orphan_tool_messages(self, anchors: list, kept: list) -> list:
        """A ToolMessage without its preceding tool_use is invalid for the LLM."""
        all_msgs = anchors + kept
        valid_call_ids: set[str] = set()
        for m in all_msgs:
            if isinstance(m, AssistantMessage):
                for tc in m.tool_calls:
                    valid_call_ids.add(tc.id)
        return [
            m for m in kept
            if not (isinstance(m, ToolMessage) and m.tool_call_id not in valid_call_ids)
        ]

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def _count_dialog_tokens(self, dialog: Dialog) -> int:
        total = 0
        for m in dialog.messages:
            total += self._count_tokens(self._extract_text(m))
        for t in dialog.tools:
            total += self._count_tokens(t.description)
            total += self._count_tokens(str(t.input_schema))
        return total

    def _count_tokens(self, text: str) -> int:
        """Coarse estimate: ~3.5 chars per token. Override for exact counts."""
        if not text:
            return 0
        return max(1, int(len(text) / 3.5))

    @staticmethod
    def _extract_text(msg) -> str:
        if isinstance(msg, (SystemMessage, UserMessage)):
            return msg.content
        if isinstance(msg, AssistantMessage):
            chunks = [msg.content or ""]
            for tc in msg.tool_calls:
                chunks.append(tc.name)
                chunks.append(str(tc.arguments))
            return " ".join(chunks)
        if isinstance(msg, ToolMessage):
            return msg.content
        return ""
