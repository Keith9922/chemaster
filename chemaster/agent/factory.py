"""Agent 组装工厂 — CLI / TUI / Web / REPL / agent-as-MCP 共用的唯一 wiring。

此前「provider 探测链 + 默认 model 映射 + registry/LLM/ChemAgent 组装」在
5 个入口各复制一份，并且已经互相漂移：REPL 不认 qwen/deepseek，agent-as-MCP
server 用的还是一批旧 model id。所有前端一律经由本模块组装 agent；改探测
顺序或默认模型时只改这里。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chemaster.agent.agent import AgentConfig, ChemAgent
from chemaster.agent.llm_client import LLMConfig, MockLLM, create_llm
from chemaster.agent.tool_loader import build_default_registry

# provider 探测顺序：先到先得。
PROVIDER_ENV_CHAIN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anthropic", ("ANTHROPIC_API_KEY",)),
    ("minimax", ("MINIMAX_API_KEY",)),
    ("qwen", ("DASHSCOPE_API_KEY", "QWEN_API_KEY")),
    ("deepseek", ("DEEPSEEK_API_KEY",)),
)

# 各 provider 的默认 model id。
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "minimax": "MiniMax-M2.7",
    "qwen": "qwen-max",
    "deepseek": "deepseek-chat",
    "mock": "mock",
}


def detect_provider() -> str:
    """按环境变量自动选 provider；一个 key 都没有 → ``"mock"``。"""
    for provider, env_keys in PROVIDER_ENV_CHAIN:
        if any(os.environ.get(k) for k in env_keys):
            return provider
    return "mock"


def default_model_for(provider: str) -> str | None:
    return DEFAULT_MODELS.get(provider)


def build_chem_agent(
    provider: str | None = None,
    model: str | None = None,
    *,
    runs_dir: str | Path = "./runs",
    max_turns: int = 30,
    confirm_callback: Callable[..., bool] | None = None,
    recommend_callback: Callable[[dict], dict] | None = None,
    async_confirm_callback: Callable[..., Any] | None = None,
    enabled_tools: list[str] | None = None,
    mock_responder: Callable[..., Any] | None = None,
) -> ChemAgent:
    """构造一个完整接线的 ChemAgent。

    Args:
        provider: LLM provider；None → :func:`detect_provider` 自动探测。
        model: 模型 id 覆盖；None → 该 provider 的默认模型。
        mock_responder: provider="mock" 时可注入确定性 responder
            （benchmark / agent-as-MCP 用）。
    """
    provider = provider or detect_provider()
    if provider == "mock" and mock_responder is not None:
        llm: Any = MockLLM(responder=mock_responder)
    else:
        llm = create_llm(LLMConfig(
            provider=provider,
            model=model or default_model_for(provider),
        ))
    config = AgentConfig(
        max_turns=max_turns,
        runs_dir=Path(runs_dir),
        confirm_callback=confirm_callback,
        recommend_callback=recommend_callback,
        async_confirm_callback=async_confirm_callback,
        enabled_tools=enabled_tools,
    )
    return ChemAgent(llm=llm, tools=build_default_registry(), config=config)


__all__ = [
    "DEFAULT_MODELS",
    "PROVIDER_ENV_CHAIN",
    "build_chem_agent",
    "default_model_for",
    "detect_provider",
]
