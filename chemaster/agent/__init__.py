"""Agent package — core tool-use loop and supporting modules.

V2 architecture (current):
- agent.py / agent_loop      ChemAgent / BaseAgent (the brain)
- types.py                   Message / Dialog / ToolCall / Trajectory / TaskInstance
- llm_client.py              BaseLLM / MockLLM / AnthropicLLM
- context.py                 ContextManager (truncation, compaction)
- tool_registry.py           BaseTool / ToolRegistry / MCPToolAdapter / ToolResult
- builtins.py                FinishTool / AskUserTool / ThinkTool
- tool_loader.py             build_default_registry() — wires every MCP tool
- system_prompt.md           Chemistry expert system prompt

Legacy (Phase-1 compatibility shims):
- plan.py                    Plan / PlanStep / Cost / System / Citation / McpCall
- planner.py                 Planner — hard-coded H2O Plan; superseded by ChemAgent
- confirmation.py            ConfirmationLoop / ApprovedPlan — kept for the
                             old e2e test which builds ApprovedPlan directly
- executor.py                Executor — kept for the old e2e test; new agent
                             uses BaseAgent._dispatch_tool instead
- iterator.py                BenchmarkIterator — Phase-4+ work, NotImplemented
- retriever.py               KnowledgeRetriever — superseded by chem.kb MCP

The legacy modules are still importable so the old H2O e2e test passes.
New code should always go through ChemAgent / build_default_chem_agent.
"""

from chemaster.agent.agent import (
    AgentConfig,
    BaseAgent,
    ChemAgent,
    ConfirmCallback,
    build_default_chem_agent,
)
from chemaster.agent.builtins import (
    AskUserTool,
    FinishTool,
    ThinkTool,
    register_builtins,
)
from chemaster.agent.confirmation import ApprovedPlan, ConfirmationLoop
from chemaster.agent.context import ContextConfig, ContextManager, TruncationStrategy
from chemaster.agent.executor import Executor
from chemaster.agent.iterator import BenchmarkIterator
from chemaster.agent.llm_client import (
    AnthropicLLM,
    BaseLLM,
    DeepSeekLLM,
    LLMConfig,
    LLMError,
    MiniMaxLLM,
    MockLLM,
    OpenAICompatLLM,
    QwenLLM,
    create_llm,
)
from chemaster.agent.plan import (
    Alternative,
    Citation,
    Cost,
    McpCall,
    Plan,
    PlanStep,
    System,
)
from chemaster.agent.planner import Planner
from chemaster.agent.retriever import KnowledgeRetriever
from chemaster.agent.tool_loader import build_default_registry
from chemaster.agent.tool_registry import (
    BaseTool,
    MCPToolAdapter,
    ToolRegistry,
    ToolResult,
)
from chemaster.agent.types import (
    AssistantMessage,
    Dialog,
    Role,
    StepRecord,
    SystemMessage,
    TaskInstance,
    ToolCall,
    ToolMessage,
    ToolSpec,
    Trajectory,
    UserMessage,
)

__all__ = [  # noqa: RUF022 — 按功能分组排列比字母序更易读
    # V2 agent
    "AgentConfig",
    "BaseAgent",
    "ChemAgent",
    "ConfirmCallback",
    "build_default_chem_agent",
    "build_default_registry",
    # Tools
    "BaseTool",
    "MCPToolAdapter",
    "ToolRegistry",
    "ToolResult",
    "AskUserTool",
    "FinishTool",
    "ThinkTool",
    "register_builtins",
    # LLM
    "AnthropicLLM",
    "BaseLLM",
    "DeepSeekLLM",
    "LLMConfig",
    "LLMError",
    "MiniMaxLLM",
    "MockLLM",
    "OpenAICompatLLM",
    "QwenLLM",
    "create_llm",
    # Context
    "ContextConfig",
    "ContextManager",
    "TruncationStrategy",
    # Types
    "AssistantMessage",
    "Dialog",
    "Role",
    "StepRecord",
    "SystemMessage",
    "TaskInstance",
    "ToolCall",
    "ToolMessage",
    "ToolSpec",
    "Trajectory",
    "UserMessage",
    # Legacy plan-shaped objects (still used by old tests)
    "Plan",
    "PlanStep",
    "System",
    "Cost",
    "McpCall",
    "Alternative",
    "Citation",
    "Planner",
    "ConfirmationLoop",
    "ApprovedPlan",
    "Executor",
    "BenchmarkIterator",
    "KnowledgeRetriever",
]
