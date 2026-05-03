"""LLM 抽象层 —— 统一不同 LLM 提供商的调用接口。

设计原则：
- BaseLLM 只暴露 query(dialog) → AssistantMessage
- 具体实现：AnthropicLLM（默认）、OpenAICompatLLM（DeepSeek/Qwen 等）
- 从 config.yaml 的 llm 配置块构建，不硬编码 key

Usage:
    from chemaster.agent.llm import build_llm
    llm = build_llm(config["llm"])
    msg = llm.query(dialog)
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    MessageRole,
    ToolCall,
    ToolCallFunction,
)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用失败。"""


class ContextOverflowError(LLMError):
    """Context 超限（prompt tokens 超过模型最大值）。"""


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------

class BaseLLM(ABC):
    """LLM 调用抽象基类。"""

    @abstractmethod
    def query(self, dialog: Dialog) -> AssistantMessage:
        """调用 LLM，返回 AssistantMessage。

        Args:
            dialog: 包含完整消息历史和工具规格的对话。

        Returns:
            LLM 的响应，可能含 tool_calls。

        Raises:
            ContextOverflowError: prompt tokens 超限。
            LLMError: 其他调用失败。
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前使用的模型名称。"""


# ---------------------------------------------------------------------------
# Anthropic 实现
# ---------------------------------------------------------------------------

class AnthropicLLM(BaseLLM):
    """调用 Anthropic Claude API。

    配置示例（config.yaml）::

        llm:
          default: anthropic
          anthropic:
            provider: anthropic
            model: claude-sonnet-4-6
            api_key: ${ANTHROPIC_API_KEY}
            max_tokens: 8192
            temperature: 0.0
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        import os
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "请安装 anthropic：pip install anthropic"
            ) from exc

        api_key = cfg.get("api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
        base_url = cfg.get("base_url")

        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url

        self._client = anthropic.Anthropic(**kwargs)
        self._model = cfg.get("model", "claude-sonnet-4-6")
        self._max_tokens = cfg.get("max_tokens", 8192)
        self._temperature = cfg.get("temperature", 0.0)
        self._max_retries = cfg.get("max_retries", 3)

    @property
    def model_name(self) -> str:
        return self._model

    def query(self, dialog: Dialog) -> AssistantMessage:
        """调用 Anthropic Messages API。"""
        # 构建 messages 列表
        system_text = ""
        messages_payload: list[dict] = []

        for msg in dialog.messages:
            if msg.role == MessageRole.SYSTEM:
                system_text = msg.content
            elif msg.role == MessageRole.USER:
                messages_payload.append({"role": "user", "content": msg.content})
            elif msg.role == MessageRole.ASSISTANT:
                content: Any = msg.content
                # 如果有 tool_calls，构建 content blocks
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    blocks: list[dict] = []
                    if msg.content:
                        blocks.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        blocks.append({
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.function.name,
                            "input": json.loads(tc.function.arguments or "{}"),
                        })
                    content = blocks
                messages_payload.append({"role": "assistant", "content": content})
            elif msg.role == MessageRole.TOOL:
                # tool_result 块
                tool_msg = msg  # type: ignore[assignment]
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": getattr(tool_msg, "tool_call_id", ""),
                    "content": msg.content,
                }
                # Anthropic: tool_result 属于 user turn
                if messages_payload and messages_payload[-1]["role"] == "user":
                    prev = messages_payload[-1]["content"]
                    if isinstance(prev, list):
                        prev.append(tool_result_block)
                    else:
                        messages_payload[-1]["content"] = [
                            {"type": "text", "text": prev},
                            tool_result_block,
                        ]
                else:
                    messages_payload.append({
                        "role": "user",
                        "content": [tool_result_block],
                    })

        # 构建 tools 列表
        tools_payload: list[dict] = []
        for spec in (dialog.tools or []):
            tools_payload.append({
                "name": spec.function.name,
                "description": spec.function.description,
                "input_schema": spec.function.parameters,
            })

        # 调用 API
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": messages_payload,
        }
        if system_text:
            kwargs["system"] = system_text
        if tools_payload:
            kwargs["tools"] = tools_payload

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:
            err_str = str(exc).lower()
            if "context" in err_str or "token" in err_str or "length" in err_str:
                raise ContextOverflowError(f"Context 溢出: {exc}") from exc
            raise LLMError(f"Anthropic API 调用失败: {exc}") from exc

        # 解析响应
        text_content = ""
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    function=ToolCallFunction(
                        name=block.name,
                        arguments=json.dumps(block.input, ensure_ascii=False),
                    ),
                ))

        usage = {}
        if hasattr(response, "usage"):
            u = response.usage
            usage = {
                "prompt_tokens": getattr(u, "input_tokens", 0),
                "completion_tokens": getattr(u, "output_tokens", 0),
            }
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

        return AssistantMessage(
            content=text_content,
            tool_calls=tool_calls,
            meta={"usage": usage, "model": self._model, "stop_reason": response.stop_reason},
        )


# ---------------------------------------------------------------------------
# OpenAI 兼容实现（DeepSeek / Qwen / 本地 vLLM 等）
# ---------------------------------------------------------------------------

class OpenAICompatLLM(BaseLLM):
    """调用 OpenAI 兼容格式的 API。

    配置示例::

        llm:
          deepseek:
            provider: openai_compat
            model: deepseek-chat
            api_key: ${DEEPSEEK_API_KEY}
            base_url: https://api.deepseek.com/v1
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        import os
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("请安装 openai：pip install openai") from exc

        api_key = cfg.get("api_key", os.environ.get("OPENAI_API_KEY", "dummy"))
        base_url = cfg.get("base_url", "https://api.openai.com/v1")

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = cfg.get("model", "gpt-4o-mini")
        self._max_tokens = cfg.get("max_tokens", 8192)
        self._temperature = cfg.get("temperature", 0.0)

    @property
    def model_name(self) -> str:
        return self._model

    def query(self, dialog: Dialog) -> AssistantMessage:
        messages_payload: list[dict] = []

        for msg in dialog.messages:
            if msg.role in (MessageRole.SYSTEM, MessageRole.USER):
                messages_payload.append({
                    "role": msg.role.value,
                    "content": msg.content,
                })
            elif msg.role == MessageRole.ASSISTANT:
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or "",
                }
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                messages_payload.append(entry)
            elif msg.role == MessageRole.TOOL:
                tool_msg = msg  # type: ignore[assignment]
                messages_payload.append({
                    "role": "tool",
                    "tool_call_id": getattr(tool_msg, "tool_call_id", ""),
                    "content": msg.content,
                })

        tools_payload: list[dict] = [
            {
                "type": "function",
                "function": {
                    "name": s.function.name,
                    "description": s.function.description,
                    "parameters": s.function.parameters,
                },
            }
            for s in (dialog.tools or [])
        ]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": messages_payload,
        }
        if tools_payload:
            kwargs["tools"] = tools_payload
            kwargs["tool_choice"] = "auto"

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            err_str = str(exc).lower()
            if "context" in err_str or "token" in err_str:
                raise ContextOverflowError(str(exc)) from exc
            raise LLMError(str(exc)) from exc

        choice = response.choices[0]
        msg_out = choice.message
        text_content = msg_out.content or ""

        tool_calls: list[ToolCall] = []
        if msg_out.tool_calls:
            for tc in msg_out.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    function=ToolCallFunction(
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                    ),
                ))

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return AssistantMessage(
            content=text_content,
            tool_calls=tool_calls,
            meta={"usage": usage, "model": self._model},
        )


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def build_llm(llm_config: dict[str, Any], name: str | None = None) -> BaseLLM:
    """从 config.yaml 的 llm 配置块构建 LLM 实例。

    Args:
        llm_config: config["llm"] 字典。
        name: 使用哪个 LLM 配置（默认用 default 字段指定的）。

    Returns:
        BaseLLM 实例。

    Example config::

        llm:
          default: anthropic
          anthropic:
            provider: anthropic
            model: claude-sonnet-4-6
            api_key: sk-...
          deepseek:
            provider: openai_compat
            model: deepseek-chat
            api_key: sk-...
            base_url: https://api.deepseek.com/v1
    """
    target = name or llm_config.get("default", "anthropic")
    cfg = llm_config.get(target, {})
    provider = cfg.get("provider", target)

    if provider == "anthropic":
        return AnthropicLLM(cfg)
    elif provider in ("openai", "openai_compat", "deepseek", "qwen"):
        return OpenAICompatLLM(cfg)
    else:
        logger.warning("未知 LLM provider '%s'，尝试用 OpenAI 兼容模式", provider)
        return OpenAICompatLLM(cfg)
