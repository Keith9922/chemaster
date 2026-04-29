"""LLM client abstraction.

Provides a vendor-neutral interface (`BaseLLM`) plus three implementations:

- `MockLLM`        — scriptable, used in unit tests; never makes a network call.
- `AnthropicLLM`   — real Claude via Anthropic SDK (lazy import; activated when
                     ANTHROPIC_API_KEY is available).
- `OpenAICompatLLM`— OpenAI-compatible endpoint (Qwen / DeepSeek / vLLM / etc.);
                     stub for now, ready for the BYO-LLM milestone.

The Agent loop only touches `BaseLLM.query(dialog) -> AssistantMessage`. All
vendor-specific protocol translation lives in subclasses.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    Role,
    ToolCall,
    ToolMessage,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Errors
# ══════════════════════════════════════════════════════════════════════════════


class LLMError(Exception):
    """Generic LLM error (transport, auth, schema validation, …)."""


class ContextOverflowError(LLMError):
    """Raised when the prompt exceeds the model's context window."""


# ══════════════════════════════════════════════════════════════════════════════
# Base
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class LLMConfig:
    provider: str = "mock"                 # mock | anthropic | openai_compat
    model: str = "claude-sonnet-4-6"
    temperature: float = 0.0
    max_tokens: int = 4096
    api_key: str | None = None
    base_url: str | None = None
    timeout_s: float = 120.0
    extra: dict[str, Any] = None  # type: ignore[assignment]


class BaseLLM(ABC):
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @abstractmethod
    def query(self, dialog: Dialog) -> AssistantMessage:
        """Send the dialog and return one assistant turn (possibly with tool calls)."""

    @property
    def model(self) -> str:
        return self.config.model


# ══════════════════════════════════════════════════════════════════════════════
# MockLLM (scripted; no network)
# ══════════════════════════════════════════════════════════════════════════════


class MockLLM(BaseLLM):
    """Returns pre-scripted assistant turns.

    Use cases:
    - Unit-test the Agent loop without any network.
    - Drive integration tests with deterministic tool-call sequences.

    Two ways to script:

    1. Fixed list (simplest):
        llm = MockLLM(responses=[
            AssistantMessage(content="", tool_calls=[ToolCall("c1", "finish", {})]),
        ])

    2. Callable (state-aware, can inspect the dialog):
        llm = MockLLM(responder=lambda dialog: AssistantMessage(...))
    """

    def __init__(
        self,
        responses: list[AssistantMessage] | None = None,
        responder=None,
        config: LLMConfig | None = None,
    ) -> None:
        super().__init__(config or LLMConfig(provider="mock"))
        self._responses = list(responses or [])
        self._responder = responder
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def query(self, dialog: Dialog) -> AssistantMessage:
        self._call_count += 1

        if self._responder is not None:
            msg = self._responder(dialog)
            if not isinstance(msg, AssistantMessage):
                raise LLMError(
                    f"MockLLM responder returned {type(msg).__name__}, expected AssistantMessage"
                )
            return msg

        if not self._responses:
            raise LLMError(
                f"MockLLM ran out of scripted responses after {self._call_count} calls. "
                "Either provide more responses or supply a responder callable."
            )
        return self._responses.pop(0)


# ══════════════════════════════════════════════════════════════════════════════
# AnthropicLLM (real Claude via Anthropic SDK)
# ══════════════════════════════════════════════════════════════════════════════


class AnthropicLLM(BaseLLM):
    """Real Claude via Anthropic SDK.

    Lazy-imports the SDK so unit tests don't require it. Translates between our
    internal Dialog / ToolCall / AssistantMessage and Anthropic's wire format.
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY not set. Pass config.api_key or export the env var."
            )
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise LLMError(
                "anthropic SDK not installed. Run: pip install anthropic"
            ) from exc

        from anthropic import Anthropic
        self._client = Anthropic(api_key=api_key, base_url=config.base_url)

    def query(self, dialog: Dialog) -> AssistantMessage:
        system, messages = self._translate_dialog(dialog)
        tools = [t.to_anthropic() for t in dialog.tools] if dialog.tools else None

        try:
            req: dict[str, Any] = {
                "model": self.config.model,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "messages": messages,
            }
            if system:
                req["system"] = system
            if tools:
                req["tools"] = tools
            response = self._client.messages.create(**req)
        except Exception as exc:
            # Surface context overflow as a typed error so the loop can compact.
            msg_str = str(exc).lower()
            if "context" in msg_str and ("length" in msg_str or "window" in msg_str):
                raise ContextOverflowError(str(exc)) from exc
            raise LLMError(str(exc)) from exc

        return self._translate_response(response)

    def _translate_dialog(self, dialog: Dialog) -> tuple[str, list[dict]]:
        """Split out the system prompt, build Anthropic-format messages."""
        system_parts: list[str] = []
        messages: list[dict] = []

        for msg in dialog.messages:
            if msg.role == Role.SYSTEM:
                system_parts.append(msg.content)
            elif msg.role == Role.USER:
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                blocks: list[dict] = []
                if msg.content:
                    blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                messages.append({"role": "assistant", "content": blocks})
            elif msg.role == Role.TOOL:
                # Anthropic expects tool_result inside a 'user' message.
                tool_msg: ToolMessage = msg  # type: ignore[assignment]
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_msg.tool_call_id,
                        "content": tool_msg.content,
                        "is_error": tool_msg.is_error,
                    }],
                })
        return "\n\n".join(system_parts), messages

    def _translate_response(self, response: Any) -> AssistantMessage:
        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_chunks.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=dict(block.input) if block.input else {},
                ))

        meta: dict[str, Any] = {
            "stop_reason": getattr(response, "stop_reason", None),
            "model": getattr(response, "model", self.config.model),
        }
        usage = getattr(response, "usage", None)
        if usage is not None:
            meta["usage"] = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            }
        return AssistantMessage(
            content="".join(text_chunks),
            tool_calls=tool_calls,
            meta=meta,
        )


# ══════════════════════════════════════════════════════════════════════════════
# MiniMax (Anthropic-compatible endpoint)
# ══════════════════════════════════════════════════════════════════════════════


class MiniMaxLLM(AnthropicLLM):
    """MiniMax LLM via its Anthropic-compatible endpoint.

    Reference: https://platform.minimaxi.com/docs/token-plan/quickstart

    The MiniMax token-plan endpoint at `https://api.minimaxi.com/anthropic`
    speaks the same wire protocol as Anthropic's `messages.create` (system
    prompt, messages with role/content blocks, tool_use / tool_result, etc.),
    so we just point AnthropicLLM at it.

    Auth: pass `config.api_key` or set the `MINIMAX_API_KEY` env var. If
    neither is set we fall back to `ANTHROPIC_API_KEY` (handy when the same
    key is reused).

    Default model: `MiniMax-M2.7` (the most capable model in their token-plan
    catalogue at the time of writing). Use `MiniMax-M2.7-highspeed` for a
    cheaper / faster variant.
    """

    DEFAULT_BASE_URL = "https://api.minimaxi.com/anthropic"
    DEFAULT_MODEL = "MiniMax-M2.7"

    def __init__(self, config: LLMConfig) -> None:
        # Normalize config so AnthropicLLM finds an api key + base url.
        api_key = (
            config.api_key
            or os.environ.get("MINIMAX_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )
        if not api_key:
            raise LLMError(
                "MINIMAX_API_KEY not set. Pass config.api_key or export the env var."
            )
        # Choose model: keep an explicit MiniMax model id, otherwise force the
        # default MiniMax model. The default LLMConfig.model is an Anthropic
        # id ("claude-sonnet-4-6"), so we swap it here unless the user really
        # supplied a MiniMax-prefixed id.
        model = config.model
        if not model or not model.startswith("MiniMax"):
            model = self.DEFAULT_MODEL
        cfg = LLMConfig(
            provider="minimax",
            model=model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            api_key=api_key,
            base_url=config.base_url or self.DEFAULT_BASE_URL,
            timeout_s=config.timeout_s,
            extra=config.extra,
        )
        super().__init__(cfg)


# ══════════════════════════════════════════════════════════════════════════════
# OpenAI-compatible (Qwen / DeepSeek / vLLM)
# ══════════════════════════════════════════════════════════════════════════════


class OpenAICompatLLM(BaseLLM):
    """OpenAI-compatible chat-completions endpoint.

    Stub for the BYO-LLM milestone (Qwen/DeepSeek/local vLLM). Not used in the
    MVP path; raises if instantiated until enabled.
    """

    def __init__(self, config: LLMConfig) -> None:  # pragma: no cover
        super().__init__(config)
        raise NotImplementedError(
            "OpenAICompatLLM not yet wired up. Use MockLLM for tests or "
            "AnthropicLLM with ANTHROPIC_API_KEY for real runs, or "
            "MiniMaxLLM with MINIMAX_API_KEY."
        )

    def query(self, dialog: Dialog) -> AssistantMessage:  # pragma: no cover
        raise NotImplementedError


# ══════════════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════════════


def create_llm(config: LLMConfig | None = None) -> BaseLLM:
    """Build an LLM client from config (or a MockLLM if config is None)."""
    cfg = config or LLMConfig(provider="mock")
    if cfg.provider == "mock":
        return MockLLM(config=cfg)
    if cfg.provider == "anthropic":
        return AnthropicLLM(cfg)
    if cfg.provider == "minimax":
        return MiniMaxLLM(cfg)
    if cfg.provider == "openai_compat":
        return OpenAICompatLLM(cfg)
    raise LLMError(f"Unknown LLM provider: {cfg.provider}")


# Export shortcut helpers for tests
def stub_assistant_message(
    text: str = "",
    tool_calls: list[ToolCall] | None = None,
) -> AssistantMessage:
    """Convenience builder used in unit tests."""
    return AssistantMessage(content=text, tool_calls=list(tool_calls or []))


def stub_tool_call(name: str, args: dict | None = None, call_id: str | None = None) -> ToolCall:
    cid = call_id or f"tc_{name}_{abs(hash(json.dumps(args or {}, sort_keys=True))) % 10_000}"
    return ToolCall(id=cid, name=name, arguments=dict(args or {}))
